from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, CheckConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Match(Base):
    __tablename__ = "matches"

    __table_args__ = (
        CheckConstraint("home_score >= 0", name="chk_home_score_nonnegative"),
        CheckConstraint("away_score >= 0", name="chk_away_score_nonnegative"),
        CheckConstraint("home_team_id != away_team_id", name="chk_home_away_different"),
    )

    id = Column(Integer, primary_key=True, index=True)

    home_team_id = Column(Integer, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False, index=True)
    away_team_id = Column(Integer, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False, index=True)

    home_score = Column(Integer, nullable=False, default=0)
    away_score = Column(Integer, nullable=False, default=0)

    match_date = Column(Date, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
