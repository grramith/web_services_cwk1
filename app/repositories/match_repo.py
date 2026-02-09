import datetime as dt
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.models.match import Match
from app.schemas.match import MatchCreate, MatchUpdate

def create_match(db: Session, payload: MatchCreate) -> Match:
    m = Match(
        home_team_id=payload.home_team_id,
        away_team_id=payload.away_team_id,
        home_score=payload.home_score,
        away_score=payload.away_score,
        match_date=payload.match_date,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m

def get_match(db: Session, match_id: int) -> Match | None:
    return db.get(Match, match_id)

def list_matches(
    db: Session,
    page: int,
    limit: int,
    team_id: int | None,
    date_from: dt.date | None,
    date_to: dt.date | None,
) -> list[Match]:
    stmt = select(Match)

    if team_id is not None:
        stmt = stmt.where(or_(Match.home_team_id == team_id, Match.away_team_id == team_id))

    if date_from is not None:
        stmt = stmt.where(Match.match_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Match.match_date <= date_to)

    offset = (page - 1) * limit
    stmt = stmt.order_by(Match.match_date.desc(), Match.id.desc()).offset(offset).limit(limit)

    return db.execute(stmt).scalars().all()

def update_match(db: Session, match: Match, payload: MatchUpdate) -> Match:
    if payload.home_team_id is not None:
        match.home_team_id = payload.home_team_id
    if payload.away_team_id is not None:
        match.away_team_id = payload.away_team_id
    if payload.home_score is not None:
        match.home_score = payload.home_score
    if payload.away_score is not None:
        match.away_score = payload.away_score
    if payload.match_date is not None:
        match.match_date = payload.match_date

    db.commit()
    db.refresh(match)
    return match

def delete_match(db: Session, match: Match) -> None:
    db.delete(match)
    db.commit()
