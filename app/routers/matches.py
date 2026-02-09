import datetime as dt
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import not_found
from app.schemas.common import ApiResponse
from app.schemas.match import MatchCreate, MatchOut, MatchUpdate
from app.repositories import match_repo, team_repo

router = APIRouter()

@router.post("", response_model=ApiResponse[MatchOut], status_code=status.HTTP_201_CREATED)
def create_match(payload: MatchCreate, db: Session = Depends(get_db)):
    # Ensure teams exist (nice viva answer + better errors than DB constraint failures)
    if not team_repo.get_team(db, payload.home_team_id):
        raise not_found("Home team")
    if not team_repo.get_team(db, payload.away_team_id):
        raise not_found("Away team")

    try:
        match = match_repo.create_match(db, payload)
        return ApiResponse(data=match)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "Invalid match data"}
        )


@router.get("", response_model=ApiResponse[list[MatchOut]])
def list_matches(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    team_id: int | None = Query(default=None, ge=1),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    matches = match_repo.list_matches(db, page, limit, team_id, date_from, date_to)
    meta = {"page": page, "limit": limit, "count": len(matches), "team_id": team_id, "date_from": date_from, "date_to": date_to}
    return ApiResponse(data=matches, meta=meta)

@router.get("/{match_id}", response_model=ApiResponse[MatchOut])
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = match_repo.get_match(db, match_id)
    if not match:
        raise not_found("Match")
    return ApiResponse(data=match)

@router.put("/{match_id}", response_model=ApiResponse[MatchOut])
def update_match(match_id: int, payload: MatchUpdate, db: Session = Depends(get_db)):
    match = match_repo.get_match(db, match_id)
    if not match:
        raise not_found("Match")

    # If updating teams, validate existence
    if payload.home_team_id is not None and not team_repo.get_team(db, payload.home_team_id):
        raise not_found("Home team")
    if payload.away_team_id is not None and not team_repo.get_team(db, payload.away_team_id):
        raise not_found("Away team")

    try:
        updated = match_repo.update_match(db, match, payload)
        return ApiResponse(data=updated)
    except IntegrityError:
        db.rollback()
        # constraint violations
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Invalid match update"})

@router.delete("/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_match(match_id: int, db: Session = Depends(get_db)):
    match = match_repo.get_match(db, match_id)
    if not match:
        raise not_found("Match")
    match_repo.delete_match(db, match)
    return None
