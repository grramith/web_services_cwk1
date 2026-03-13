from app.services.catalog_import import import_catalog_tracks
"""
Import pipeline routes.

POST /imports/spotify      — start import job
GET  /imports/jobs/{job_id} — check status
GET  /imports/jobs         — list recent jobs

This coursework version runs synchronously for simplicity, but models the
workflow as a tracked import job with counts, audit fields, and clean error
handling. One request can now fan out to multiple Spotify sources:
- top tracks (single range or all three ranges)
- recently played
- saved tracks (paginated)
- audio feature enrichment
"""

import logging
import random
import time
from datetime import datetime, timedelta, timezone

import requests as http_requests
from requests import RequestException
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import ImportJob, JobStatus, ListeningEvent, Track, User
from app.schemas import ImportJobRead, ImportStartRequest, CatalogImportRequest, CatalogImportResult

router = APIRouter(prefix="/imports", tags=["Ingestion"])
logger = logging.getLogger(__name__)

SPOTIFY = "https://api.spotify.com/v1"
TOP_TRACK_WINDOWS = ["long_term", "medium_term", "short_term"]


def _sp_get(endpoint: str, token: str):
    """Helper for Spotify API calls with basic retry / auth handling."""
    if not token or token.strip().lower() == "invalid":
        return None

    url = f"{SPOTIFY}/{endpoint}"
    try:
        response = http_requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except RequestException as exc:
        logger.warning("Spotify request failed for %s: %s", endpoint, exc)
        raise HTTPException(status_code=503, detail="Spotify service unavailable") from exc

    if response.status_code == 429:
        wait = int(response.headers.get("Retry-After", 3))
        time.sleep(wait)
        return _sp_get(endpoint, token)
    if response.status_code == 401:
        return None
    if response.status_code >= 500:
        raise HTTPException(status_code=503, detail="Spotify service unavailable")
    if response.status_code == 403:
        return {"spotify_error": "forbidden", "status_code": 403}
    return response.json() if response.status_code == 200 else None


def _iter_saved_tracks(token: str, max_pages: int):
    for page in range(max_pages):
        offset = page * 50
        data = _sp_get(f"me/tracks?limit=50&offset={offset}", token)
        if data is None:
            return None
        if isinstance(data, dict) and data.get("spotify_error") == "forbidden":
            return data
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break
        yield items


@router.post("/spotify", response_model=ImportJobRead, status_code=202,
             summary="Start a Spotify import job")
def start_import(body: ImportStartRequest,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """
    Runs a richer Spotify ingestion pipeline.

    One request can fetch:
    - top tracks for one window or all three Spotify windows
    - recently played history
    - saved-library tracks using pagination
    - audio features for all unique imported tracks

    Recently played items become real listening events. Top-track and saved-track
    imports can additionally synthesise plausible historical listening events so
    analytics endpoints remain useful even when Spotify only exposes affinity data.
    """
    job = ImportJob(
        user_id=user.id,
        status=JobStatus.RUNNING,
        source="spotify",
        time_range=body.time_range,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    errors: list[str] = []
    all_sp_tracks: dict[str, dict] = {}
    recent_plays: dict[str, list[str | None]] = {}

    try:
        requested_ranges = TOP_TRACK_WINDOWS if body.time_range == "all" else [body.time_range]

        # 1) Top tracks across one or all windows
        for tr in requested_ranges:
            data = _sp_get(f"me/top/tracks?time_range={tr}&limit=50", body.spotify_token)
            if data is None:
                errors.append(f"Auth failed for top tracks ({tr})")
                job.status = JobStatus.FAILED
                job.errors = errors
                db.commit()
                raise HTTPException(status_code=401, detail="Spotify token invalid or expired")
            if isinstance(data, dict) and data.get("items"):
                for track in data["items"]:
                    sid = track.get("id")
                    if not sid:
                        continue
                    entry = all_sp_tracks.setdefault(sid, {"track": track, "sources": set()})
                    entry["track"] = track
                    entry["sources"].add(f"top:{tr}")

        # 2) Recently played
        if body.include_recently_played:
            recent = _sp_get("me/player/recently-played?limit=50", body.spotify_token)
            if recent is None:
                errors.append("Auth failed for recently played")
                job.status = JobStatus.FAILED
                job.errors = errors
                db.commit()
                raise HTTPException(status_code=401, detail="Spotify token invalid or expired")
            if isinstance(recent, dict) and recent.get("items"):
                for item in recent["items"]:
                    track = item.get("track", {})
                    sid = track.get("id")
                    if not sid:
                        continue
                    entry = all_sp_tracks.setdefault(sid, {"track": track, "sources": set()})
                    entry["track"] = track
                    entry["sources"].add("recent")
                    recent_plays.setdefault(sid, []).append(item.get("played_at"))

        # 3) Saved tracks with pagination
        if body.include_saved_tracks:
            saved_pages = _iter_saved_tracks(body.spotify_token, body.saved_tracks_max_pages)
            if saved_pages is None:
                errors.append("Auth failed for saved tracks")
                job.status = JobStatus.FAILED
                job.errors = errors
                db.commit()
                raise HTTPException(status_code=401, detail="Spotify token invalid or expired")
            else:
                for page_items in saved_pages:
                    if isinstance(page_items, dict):
                        if page_items.get("spotify_error") == "forbidden":
                            errors.append(
                                "Saved tracks skipped: token missing user-library-read scope"
                            )
                            break
                    for item in page_items:
                        track = item.get("track", {})
                        sid = track.get("id")
                        if not sid:
                            continue
                        entry = all_sp_tracks.setdefault(sid, {"track": track, "sources": set()})
                        entry["track"] = track
                        entry["sources"].add("saved")

        if not all_sp_tracks:
            errors.append("No Spotify tracks returned for this token/request")
            job.status = JobStatus.FAILED
            job.errors = errors
            db.commit()
            raise HTTPException(status_code=400, detail="Spotify returned no importable tracks")

        job.tracks_found = len(all_sp_tracks)

        # 4) Audio features in batches of 100
        ids = list(all_sp_tracks.keys())
        features: dict[str, dict] = {}
        for i in range(0, len(ids), 100):
            batch = ids[i:i + 100]
            af_data = _sp_get(f"audio-features?ids={','.join(batch)}", body.spotify_token)
            if af_data and isinstance(af_data, dict) and af_data.get("audio_features"):
                for af in af_data["audio_features"]:
                    if af and af.get("id"):
                        features[af["id"]] = af
            else:
                errors.append(f"Audio features failed for batch starting {i}")

        # 5) Artist genres in batches of 50
        artist_ids: list[str] = []
        seen_artist_ids: set[str] = set()
        for entry in all_sp_tracks.values():
            for artist in entry["track"].get("artists", []):
                aid = artist.get("id")
                if aid and aid not in seen_artist_ids:
                    seen_artist_ids.add(aid)
                    artist_ids.append(aid)

        genres: dict[str, str] = {}
        for i in range(0, len(artist_ids), 50):
            data = _sp_get(f"artists?ids={','.join(artist_ids[i:i+50])}", body.spotify_token)
            if data and isinstance(data, dict) and data.get("artists"):
                for artist in data["artists"]:
                    if artist and artist.get("id") and artist.get("genres"):
                        genres[artist["id"]] = artist["genres"][0]

        # 6) Upsert tracks
        imported = 0
        sp_to_db: dict[str, int] = {}
        for sid, entry in all_sp_tracks.items():
            existing = db.query(Track).filter(Track.spotify_id == sid).first()
            if existing:
                # update empty fields if new data is richer
                track_data = entry["track"]
                af = features.get(sid, {})
                if not existing.album:
                    existing.album = track_data.get("album", {}).get("name")
                if existing.duration_ms is None:
                    existing.duration_ms = track_data.get("duration_ms")
                if not existing.genre:
                    first_artist_id = track_data.get("artists", [{}])[0].get("id") if track_data.get("artists") else None
                    existing.genre = genres.get(first_artist_id) if first_artist_id else existing.genre
                for feature_name in [
                    "danceability", "energy", "valence", "acousticness",
                    "instrumentalness", "speechiness", "liveness",
                    "loudness", "tempo",
                ]:
                    if getattr(existing, feature_name) is None and af.get(feature_name) is not None:
                        setattr(existing, feature_name, af.get(feature_name))
                sp_to_db[sid] = existing.id
                continue

            track_data = entry["track"]
            af = features.get(sid, {})
            artists_str = ", ".join(a["name"] for a in track_data.get("artists", []))
            first_artist_id = track_data.get("artists", [{}])[0].get("id") if track_data.get("artists") else None
            release_year = None
            release_date = track_data.get("album", {}).get("release_date", "")
            if release_date:
                try:
                    release_year = int(release_date[:4])
                except ValueError:
                    pass

            track = Track(
                spotify_id=sid,
                title=track_data.get("name", "Unknown"),
                artist=artists_str or "Unknown Artist",
                album=track_data.get("album", {}).get("name"),
                genre=genres.get(first_artist_id) if first_artist_id else None,
                release_year=release_year,
                duration_ms=track_data.get("duration_ms"),
                **{feature_name: af.get(feature_name) for feature_name in [
                    "danceability", "energy", "valence", "acousticness",
                    "instrumentalness", "speechiness", "liveness",
                    "loudness", "tempo",
                ]},
            )
            db.add(track)
            db.flush()
            sp_to_db[sid] = track.id
            imported += 1

        job.tracks_imported = imported

        # 7) Listening events: real recent plays + optional synthetic history
        hours = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
        weights = [1, 2, 3, 3, 2, 3, 2, 2, 2, 3, 4, 5, 6, 7, 8, 7, 5]
        events_created = 0

        for sid, entry in all_sp_tracks.items():
            track_id = sp_to_db.get(sid)
            if not track_id:
                continue
            duration_ms = entry["track"].get("duration_ms")

            if sid in recent_plays:
                for ts_str in recent_plays[sid]:
                    listened_at = datetime.now(timezone.utc)
                    if ts_str:
                        try:
                            listened_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    db.add(ListeningEvent(
                        user_id=user.id,
                        track_id=track_id,
                        listened_at=listened_at,
                        duration_listened_ms=duration_ms,
                        source="spotify-recent",
                    ))
                    events_created += 1
                continue

            if not body.synthesise_history:
                continue

            sources = entry.get("sources", set())
            if any(source.startswith("top:long_term") for source in sources):
                n = random.randint(8, 20)
                min_days, max_days = 30, 365
                source_label = "spotify-top-long"
            elif any(source.startswith("top:medium_term") for source in sources):
                n = random.randint(4, 12)
                min_days, max_days = 7, 180
                source_label = "spotify-top-medium"
            elif any(source.startswith("top:short_term") for source in sources):
                n = random.randint(2, 6)
                min_days, max_days = 1, 30
                source_label = "spotify-top-short"
            elif "saved" in sources:
                n = random.randint(1, 4)
                min_days, max_days = 14, 365
                source_label = "spotify-saved"
            else:
                n = random.randint(1, 3)
                min_days, max_days = 1, 21
                source_label = "spotify-import"

            for _ in range(n):
                days_ago = random.randint(min_days, max_days)
                hour = random.choices(hours, weights=weights, k=1)[0]
                listened_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(
                    hour=hour,
                    minute=random.randint(0, 59),
                    second=random.randint(0, 59),
                    microsecond=0,
                )
                pct = random.choices([0.3, 0.5, 0.75, 1.0], weights=[5, 10, 25, 60], k=1)[0]
                db.add(ListeningEvent(
                    user_id=user.id,
                    track_id=track_id,
                    listened_at=listened_at,
                    duration_listened_ms=int(duration_ms * pct) if duration_ms else None,
                    source=source_label,
                ))
                events_created += 1

        job.events_created = events_created
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.errors = errors

    except HTTPException:
        raise
    except Exception as exc:
        errors.append(str(exc))
        job.status = JobStatus.FAILED
        job.errors = errors
        logger.exception("Import failed")

    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=ImportJobRead,
            summary="Check import job status")
def get_job(job_id: str,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    job = db.query(ImportJob).filter(
        ImportJob.id == job_id,
        ImportJob.user_id == user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs", response_model=list[ImportJobRead],
            summary="List your recent import jobs")
def list_jobs(user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return (
        db.query(ImportJob)
        .filter(ImportJob.user_id == user.id)
        .order_by(ImportJob.started_at.desc())
        .limit(20)
        .all()
    )


@router.post(
    "/catalog",
    response_model=CatalogImportResult,
    status_code=201,
    summary="Import the public discovery catalog dataset",
)
def import_catalog(
    body: CatalogImportRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = body or CatalogImportRequest()

    try:
        result = import_catalog_tracks(db, body.dataset_slug, body.file_path)
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="kagglehub is not installed on the server.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Catalog import failed: {str(exc)}",
        ) from exc

    return CatalogImportResult(
        status="completed",
        dataset=body.dataset_slug,
        imported_by=user.username,
        **result,
    )