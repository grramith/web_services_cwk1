from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import conflict, not_found
from app.schemas.common import ApiResponse, ApiError
from app.schemas.team import TeamCreate, TeamOut, TeamUpdate
from app.repositories import team_repo

router = APIRouter()

@router.post("", response_model=ApiResponse[TeamOut], status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, db: Session = Depends(get_db)):
    # Pre-check for cleaner 409 message (still keep DB unique as source of truth)
    existing = team_repo.get_team_by_name(db, payload.name)
    if existing:
        raise conflict("Team name already exists")

    try:
        team = team_repo.create_team(db, payload)
        return ApiResponse(data=team)
    except IntegrityError:
        db.rollback()
        raise conflict("Team name already exists")

@router.get("", response_model=ApiResponse[list[TeamOut]])
def list_teams(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    teams = team_repo.list_teams(db, page, limit)
    meta = {"page": page, "limit": limit, "count": len(teams)}
    return ApiResponse(data=teams, meta=meta)

@router.get("/{team_id}", response_model=ApiResponse[TeamOut])
def get_team(team_id: int, db: Session = Depends(get_db)):
    team = team_repo.get_team(db, team_id)
    if not team:
        raise not_found("Team")
    return ApiResponse(data=team)

@router.put("/{team_id}", response_model=ApiResponse[TeamOut])
def update_team(team_id: int, payload: TeamUpdate, db: Session = Depends(get_db)):
    team = team_repo.get_team(db, team_id)
    if not team:
        raise not_found("Team")

    # Optional: if renaming, check conflicts
    if payload.name is not None:
        existing = team_repo.get_team_by_name(db, payload.name)
        if existing and existing.id != team_id:
            raise conflict("Team name already exists")

    try:
        updated = team_repo.update_team(db, team, payload)
        return ApiResponse(data=updated)
    except IntegrityError:
        db.rollback()
        raise conflict("Team name already exists")

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int, db: Session = Depends(get_db)):
    team = team_repo.get_team(db, team_id)
    if not team:
        raise not_found("Team")
    team_repo.delete_team(db, team)
    return None
