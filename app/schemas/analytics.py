from typing import List, Optional
from pydantic import BaseModel, Field

class TeamFormOut(BaseModel):
    team_id: int
    last_n: int
    played: int
    wins: int
    losses: int
    draws: int
    points_for: int
    points_against: int
    win_percentage: float = Field(ge=0.0, le=1.0)
    recent_results: List[str]  # ["W","L","D",...]

class LeagueTableRowOut(BaseModel):
    team_id: int
    team_name: str
    played: int
    wins: int
    losses: int
    draws: int
    points_for: int
    points_against: int
    points_diff: int
    points: int  # e.g., 3 for win, 1 for draw

class PlayerTrendOut(BaseModel):
    player_id: int
    matches_played: int
    avg_points: float
    avg_assists: float
    avg_errors: float
    best_match_id: Optional[int] = None
    best_match_points: Optional[int] = None
    trend: str  # "improving" | "declining" | "stable"
