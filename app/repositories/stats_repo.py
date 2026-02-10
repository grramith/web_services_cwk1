from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.player_stats import PlayerStats
from app.schemas.player_stats import PlayerStatsCreate, PlayerStatsUpdate

def create_stats(db: Session, payload: PlayerStatsCreate) -> PlayerStats:
    s = PlayerStats(
        player_id=payload.player_id,
        match_id=payload.match_id,
        points=payload.points,
        assists=payload.assists,
        errors=payload.errors,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

def get_stats(db: Session, stats_id: int) -> PlayerStats | None:
    return db.get(PlayerStats, stats_id)

def get_stats_by_player_match(db: Session, player_id: int, match_id: int) -> PlayerStats | None:
    stmt = select(PlayerStats).where(
        PlayerStats.player_id == player_id,
        PlayerStats.match_id == match_id
    )
    return db.execute(stmt).scalars().first()

def list_stats(db: Session, match_id: int | None, player_id: int | None) -> list[PlayerStats]:
    stmt = select(PlayerStats)
    if match_id is not None:
        stmt = stmt.where(PlayerStats.match_id == match_id)
    if player_id is not None:
        stmt = stmt.where(PlayerStats.player_id == player_id)
    stmt = stmt.order_by(PlayerStats.id)
    return db.execute(stmt).scalars().all()

def update_stats(db: Session, stats: PlayerStats, payload: PlayerStatsUpdate) -> PlayerStats:
    if payload.points is not None:
        stats.points = payload.points
    if payload.assists is not None:
        stats.assists = payload.assists
    if payload.errors is not None:
        stats.errors = payload.errors

    db.commit()
    db.refresh(stats)
    return stats

def delete_stats(db: Session, stats: PlayerStats) -> None:
    db.delete(stats)
    db.commit()
