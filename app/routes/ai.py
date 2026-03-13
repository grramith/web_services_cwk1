"""Focused hybrid AI routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    InsightCritiqueResult,
    InsightRead,
    RecommendationExplainRequest,
    RecommendationExplainResult,
    WhatIfRecommendationRequest,
)
from app.services import hybrid as hybrid_svc

router = APIRouter(prefix="/ai", tags=["AI"])


@router.post(
    "/recommendations/explain",
    response_model=RecommendationExplainResult,
    summary="Return explainable hybrid recommendations grounded in your fingerprint",
)
def recommendations_explain(
    body: RecommendationExplainRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return hybrid_svc.explain_recommendations(
        db,
        user.id,
        context=body.context,
        strategy=body.strategy,
        max_tracks=body.max_tracks,
    )


@router.post(
    "/recommendations/what-if",
    response_model=RecommendationExplainResult,
    summary="Generate counterfactual recommendations for a scenario",
)
def recommendations_what_if(
    body: WhatIfRecommendationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return hybrid_svc.what_if_recommendations(db, user.id, body.scenario, body.max_tracks)


@router.post(
    "/insights",
    response_model=InsightRead,
    status_code=201,
    summary="Generate a grounded hybrid insight",
)
def create_insight(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return hybrid_svc.generate_hybrid_insight(db, user.id)


@router.post(
    "/insights/{insight_id}/critique",
    response_model=InsightCritiqueResult,
    summary="Critique a generated insight for grounding and specificity",
)
def critique_insight(insight_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return hybrid_svc.critique_insight(db, user.id, insight_id)


@router.get(
    "/insights",
    response_model=list[InsightRead],
    summary="List your saved insights",
)
def list_insights(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models import Insight
    return (
        db.query(Insight)
        .filter(Insight.user_id == user.id)
        .order_by(Insight.created_at.desc())
        .all()
    )