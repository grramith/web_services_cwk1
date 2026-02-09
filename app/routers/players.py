from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import not_found
from app.schemas.common import ApiResponse
from app.schemas.player import PlayerCreate, PlayerOut, PlayerUpdate
from app.repositories import player_repo, team_repo

router = APIRouter()

@router.post("", response_model=ApiResponse[PlayerOut], status_code=status.HTTP_201_CREATED)
def create_player(payload: PlayerCreate, db: Session = Depends(get_db)):
    # Ensure team exists
    if not team_repo.get_team(db, payload.team_id):
        raise not_found("Team")

    player = player_repo.create_player(db, payload)
    return ApiResponse(data=player)

@router.get("", response_model=ApiResponse[list[PlayerOut]])
def list_players(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    team_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    players = player_repo.list_players(db, page, limit, team_id)
    meta = {"page": page, "limit": limit, "count": len(players), "team_id": team_id}
    return ApiResponse(data=players, meta=meta)

@router.get("/{player_id}", response_model=ApiResponse[PlayerOut])
def get_player(player_id: int, db: Session = Depends(get_db)):
    player = player_repo.get_player(db, player_id)
    if not player:
        raise not_found("Player")
    return ApiResponse(data=player)

@router.put("/{player_id}", response_model=ApiResponse[PlayerOut])
def update_player(player_id: int, payload: PlayerUpdate, db: Session = Depends(get_db)):
    player = player_repo.get_player(db, player_id)
    if not player:
        raise not_found("Player")

    # If team_id is being changed, ensure new team exists
    if payload.team_id is not None and not team_repo.get_team(db, payload.team_id):
        raise not_found("Team")

    updated = player_repo.update_player(db, player, payload)
    return ApiResponse(data=updated)

@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_player(player_id: int, db: Session = Depends(get_db)):
    player = player_repo.get_player(db, player_id)
    if not player:
        raise not_found("Player")

    player_repo.delete_player(db, player)
    return None
