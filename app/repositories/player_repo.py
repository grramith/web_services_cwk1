from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.player import Player
from app.schemas.player import PlayerCreate, PlayerUpdate

def create_player(db: Session, payload: PlayerCreate) -> Player:
    p = Player(name=payload.name, position=payload.position, team_id=payload.team_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

def get_player(db: Session, player_id: int) -> Player | None:
    return db.get(Player, player_id)

def list_players(db: Session, page: int, limit: int, team_id: int | None) -> list[Player]:
    stmt = select(Player)

    if team_id is not None:
        stmt = stmt.where(Player.team_id == team_id)

    offset = (page - 1) * limit
    stmt = stmt.order_by(Player.id).offset(offset).limit(limit)
    return db.execute(stmt).scalars().all()

def update_player(db: Session, player: Player, payload: PlayerUpdate) -> Player:
    if payload.name is not None:
        player.name = payload.name
    if payload.position is not None:
        player.position = payload.position
    if payload.team_id is not None:
        player.team_id = payload.team_id

    db.commit()
    db.refresh(player)
    return player

def delete_player(db: Session, player: Player) -> None:
    db.delete(player)
    db.commit()
