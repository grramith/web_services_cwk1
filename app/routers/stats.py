from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import not_found, conflict
from app.schemas.common import ApiResponse
from app.schemas.player_stats import PlayerStatsCreate, PlayerStatsOut, PlayerStatsUpdate
from app.repositories import stats_repo, player_repo, match_repo

router = APIRouter()

@router.post("", response_model=ApiResponse[PlayerStatsOut], status_code=status.HTTP_201_CREATED)
def create_stats(payload: PlayerStatsCreate, db: Session = Depends(get_db)):
    # Validate FK existence with clean 404s
    if not player_repo.get_player(db, payload.player_id):
        raise not_found("Player")
    if not match_repo.get_match(db, payload.match_id):
        raise not_found("Match")

    # Nice 409 before DB uniqueness triggers
    existing = stats_repo.get_stats_by_player_match(db, payload.player_id, payload.match_id)
    if existing:
        raise conflict("Stats already exist for this player in this match")

    try:
        created = stats_repo.create_stats(db, payload)
        return ApiResponse(data=created)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": "Stats already exist for this player in this match"},
        )

@router.get("", response_model=ApiResponse[list[PlayerStatsOut]])
def list_stats(
    match_id: int | None = Query(default=None, ge=1),
    player_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    stats = stats_repo.list_stats(db, match_id, player_id)
    meta = {"count": len(stats), "match_id": match_id, "player_id": player_id}
    return ApiResponse(data=stats, meta=meta)

@router.get("/{stats_id}", response_model=ApiResponse[PlayerStatsOut])
def get_stats(stats_id: int, db: Session = Depends(get_db)):
    stats = stats_repo.get_stats(db, stats_id)
    if not stats:
        raise not_found("Stats")
    return ApiResponse(data=stats)

@router.put("/{stats_id}", response_model=ApiResponse[PlayerStatsOut])
def update_stats(stats_id: int, payload: PlayerStatsUpdate, db: Session = Depends(get_db)):
    stats = stats_repo.get_stats(db, stats_id)
    if not stats:
        raise not_found("Stats")

    updated = stats_repo.update_stats(db, stats, payload)
    return ApiResponse(data=updated)

@router.delete("/{stats_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stats(stats_id: int, db: Session = Depends(get_db)):
    stats = stats_repo.get_stats(db, stats_id)
    if not stats:
        raise not_found("Stats")

    stats_repo.delete_stats(db, stats)
    return None
