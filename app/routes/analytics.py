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


