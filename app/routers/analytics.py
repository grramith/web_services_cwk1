from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import not_found
from app.schemas.common import ApiResponse
from app.schemas.analytics import TeamFormOut, LeagueTableRowOut, PlayerTrendOut
from app.repositories import team_repo, player_repo
from app.services.analytics_service import get_team_form, get_league_table, get_player_trend

router = APIRouter()

@router.get("/team/{team_id}/form", response_model=ApiResponse[TeamFormOut])
def team_form(
    team_id: int,
    last_n: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    if not team_repo.get_team(db, team_id):
        raise not_found("Team")

    data = get_team_form(db, team_id, last_n)
    return ApiResponse(data=data)

@router.get("/league/table", response_model=ApiResponse[list[LeagueTableRowOut]])
def league_table(db: Session = Depends(get_db)):
    data = get_league_table(db)
    meta = {"count": len(data), "scoring": {"win": 3, "draw": 1, "loss": 0}}
    return ApiResponse(data=data, meta=meta)

@router.get("/player/{player_id}/trend", response_model=ApiResponse[PlayerTrendOut])
def player_trend(player_id: int, db: Session = Depends(get_db)):
    if not player_repo.get_player(db, player_id):
        raise not_found("Player")

    data = get_player_trend(db, player_id)
    return ApiResponse(data=data)
