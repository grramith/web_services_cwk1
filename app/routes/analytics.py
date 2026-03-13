"""Focused analytics routes for Sonic Insights Hybrid."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import FingerprintResult, HighlightResult, OverviewResult, RecentChangesResult
from app.services import hybrid as hybrid_svc

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overview", response_model=OverviewResult, summary="High-level hybrid listening summary")
def get_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return hybrid_svc.overview(db, user.id)


@router.get("/fingerprint", response_model=FingerprintResult, summary="Build your listening fingerprint")
def get_fingerprint(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return hybrid_svc.fingerprint_result(db, user.id)


@router.get("/changes/recent", response_model=RecentChangesResult, summary="Explain recent taste drift")
def get_recent_changes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return hybrid_svc.recent_changes(db, user.id)


@router.get("/highlights", response_model=HighlightResult, summary="Compact analytics highlights")
def get_highlights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return hybrid_svc.highlights(db, user.id)


@router.get("/genres", summary="Genre breakdown of the imported catalog")
def get_genre_breakdown(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from collections import defaultdict
    import statistics
    from app.models import CatalogTrack
    from app.schemas import GenreBreakdownResult, GenreStat

    tracks = db.query(CatalogTrack).filter(CatalogTrack.genre.isnot(None)).all()

    buckets: dict = defaultdict(lambda: {"energy": [], "valence": [], "danceability": [], "tempo": []})
    for t in tracks:
        g = t.genre.strip().lower()
        if t.energy is not None:
            buckets[g]["energy"].append(t.energy)
        if t.valence is not None:
            buckets[g]["valence"].append(t.valence)
        if t.danceability is not None:
            buckets[g]["danceability"].append(t.danceability)
        if t.tempo is not None:
            buckets[g]["tempo"].append(t.tempo)

    def safe_mean(vals):
        return round(statistics.mean(vals), 4) if vals else None

    genres = sorted(
        [
            GenreStat(
                genre=genre,
                track_count=len(data["energy"]) or len(data["valence"]) or 1,
                avg_energy=safe_mean(data["energy"]),
                avg_valence=safe_mean(data["valence"]),
                avg_danceability=safe_mean(data["danceability"]),
                avg_tempo=safe_mean(data["tempo"]),
            )
            for genre, data in buckets.items()
        ],
        key=lambda x: -x.track_count,
    )

    return GenreBreakdownResult(total_genres=len(genres), genres=genres)