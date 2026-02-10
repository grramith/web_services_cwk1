from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class PlayerStats(Base):
    __tablename__ = "player_stats"

    __table_args__ = (
        UniqueConstraint("player_id", "match_id", name="uq_player_match_stats"),
        CheckConstraint("points >= 0", name="chk_points_nonnegative"),
        CheckConstraint("assists >= 0", name="chk_assists_nonnegative"),
        CheckConstraint("errors >= 0", name="chk_errors_nonnegative"),
    )

    id = Column(Integer, primary_key=True, index=True)

    player_id = Column(Integer, ForeignKey("players.id", ondelete="RESTRICT"), nullable=False, index=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="RESTRICT"), nullable=False, index=True)

    points = Column(Integer, nullable=False, default=0)
    assists = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    player = relationship("Player")
    match = relationship("Match")
