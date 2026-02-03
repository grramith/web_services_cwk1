from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.team import Team
from app.schemas.team import TeamCreate, TeamUpdate

def create_team(db: Session, payload: TeamCreate) -> Team:
    team = Team(name=payload.name, league=payload.league)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team

def get_team(db: Session, team_id: int) -> Team | None:
    return db.get(Team, team_id)

def get_team_by_name(db: Session, name: str) -> Team | None:
    stmt = select(Team).where(Team.name == name)
    return db.execute(stmt).scalars().first()

def list_teams(db: Session, page: int, limit: int) -> list[Team]:
    offset = (page - 1) * limit
    stmt = select(Team).order_by(Team.id).offset(offset).limit(limit)
    return db.execute(stmt).scalars().all()

def update_team(db: Session, team: Team, payload: TeamUpdate) -> Team:
    if payload.name is not None:
        team.name = payload.name
    if payload.league is not None:
        team.league = payload.league
    db.commit()
    db.refresh(team)
    return team

def delete_team(db: Session, team: Team) -> None:
    db.delete(team)
    db.commit()
