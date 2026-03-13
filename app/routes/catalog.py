"""Catalog browsing routes.

GET /catalog            — search and filter the imported catalog
GET /catalog/{track_id} — retrieve a single catalog track by ID
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import CatalogTrack, User
from app.schemas import CatalogSearchResult, CatalogTrackRead

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("", response_model=CatalogSearchResult, summary="Search and filter the discovery catalog")
def search_catalog(
    q: Optional[str] = Query(None, description="Search by track name or artist (case-insensitive)"),
    genre: Optional[str] = Query(None, description="Filter by genre (e.g. pop, rock, hip hop)"),
    min_energy: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum energy value"),
    max_energy: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum energy value"),
    min_valence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum valence (positivity)"),
    max_valence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum valence (positivity)"),
    min_danceability: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum danceability"),
    max_danceability: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum danceability"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CatalogTrack)

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            CatalogTrack.name.ilike(pattern) | CatalogTrack.artist.ilike(pattern)
        )
    if genre:
        query = query.filter(CatalogTrack.genre.ilike(f"%{genre}%"))
    if min_energy is not None:
        query = query.filter(CatalogTrack.energy >= min_energy)
    if max_energy is not None:
        query = query.filter(CatalogTrack.energy <= max_energy)
    if min_valence is not None:
        query = query.filter(CatalogTrack.valence >= min_valence)
    if max_valence is not None:
        query = query.filter(CatalogTrack.valence <= max_valence)
    if min_danceability is not None:
        query = query.filter(CatalogTrack.danceability >= min_danceability)
    if max_danceability is not None:
        query = query.filter(CatalogTrack.danceability <= max_danceability)

    total = query.count()
    items = query.order_by(CatalogTrack.name).offset(offset).limit(limit).all()

    return CatalogSearchResult(total=total, limit=limit, offset=offset, items=items)


@router.get("/{track_id}", response_model=CatalogTrackRead, summary="Get a single catalog track by ID")
def get_catalog_track(
    track_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Catalog track not found")
    return track


@router.get(
    "/{track_id}/similar",
    summary="Find catalog tracks similar to a given track using cosine similarity",
    description=(
        "Computes cosine similarity across 8 audio features (energy, valence, danceability, "
        "tempo, acousticness, instrumentalness, speechiness, liveness) to find the closest "
        "matches to the seed track in the catalog."
    ),
)
def get_similar_tracks(
    track_id: int,
    limit: int = Query(10, ge=1, le=50, description="Number of similar tracks to return"),
    same_genre: bool = Query(False, description="Restrict results to the same genre"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import math
    from app.schemas import SimilarTrackItem, SimilarTracksResult

    seed = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if not seed:
        raise HTTPException(status_code=404, detail="Catalog track not found")

    # Audio feature vector definition — order matters for cosine similarity
    FEATURES = ["energy", "valence", "danceability", "acousticness",
                "instrumentalness", "speechiness", "liveness"]
    # Tempo lives on a different scale (0-250 BPM) so normalise it to 0-1
    TEMPO_MAX = 250.0

    def to_vector(track: CatalogTrack) -> list[float]:
        vec = [getattr(track, f) or 0.0 for f in FEATURES]
        vec.append((track.tempo or 0.0) / TEMPO_MAX)
        return vec

    def cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return round(dot / (mag_a * mag_b), 4)

    def feature_breakdown(seed_vec: list[float], candidate_vec: list[float]) -> dict:
        all_features = FEATURES + ["tempo_norm"]
        return {
            f: round(1.0 - abs(seed_vec[i] - candidate_vec[i]), 4)
            for i, f in enumerate(all_features)
        }

    seed_vec = to_vector(seed)

    query = db.query(CatalogTrack).filter(CatalogTrack.id != seed.id)
    if same_genre and seed.genre:
        query = query.filter(CatalogTrack.genre.ilike(f"%{seed.genre}%"))

    candidates = query.all()

    scored = []
    for track in candidates:
        candidate_vec = to_vector(track)
        score = cosine_similarity(seed_vec, candidate_vec)
        scored.append((track, score, candidate_vec))

    scored.sort(key=lambda x: -x[1])

    results = [
        SimilarTrackItem(
            id=track.id,
            name=track.name,
            artist=track.artist,
            genre=track.genre,
            energy=track.energy,
            valence=track.valence,
            danceability=track.danceability,
            tempo=track.tempo,
            similarity_score=score,
            feature_breakdown=feature_breakdown(seed_vec, vec),
        )
        for track, score, vec in scored[:limit]
    ]

    return SimilarTracksResult(
        seed_track_id=seed.id,
        seed_name=seed.name,
        seed_artist=seed.artist,
        algorithm="cosine-similarity-8d-audio-features",
        results=results,
    )