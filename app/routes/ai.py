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


@router.post("/insights", response_model=InsightRead, status_code=201,
             summary="Generate and store a hybrid listening insight")
async def generate_insight(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await hybrid_svc.generate_hybrid_insight(db, user.id)


@router.post("/insights/{insight_id}/critique", response_model=InsightCritiqueResult,
             summary="Critique a generated insight for grounding and specificity")
async def critique_insight(
    insight_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await hybrid_svc.critique_insight(db, user.id, insight_id)


@router.post("/recommendations/explain", response_model=RecommendationExplainResult,
             summary="Return explainable hybrid recommendations grounded in your fingerprint")
async def recommendations_explain(
    body: RecommendationExplainRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await hybrid_svc.explain_recommendations(
        db, user.id, context=body.context,
        strategy=body.strategy, max_tracks=body.max_tracks,
    )


@router.post("/recommendations/what-if", response_model=RecommendationExplainResult,
             summary="Generate counterfactual recommendations for a scenario")
async def recommendations_what_if(
    body: WhatIfRecommendationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await hybrid_svc.what_if_recommendations(
        db, user.id, body.scenario, body.max_tracks
    )