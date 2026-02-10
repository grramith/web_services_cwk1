from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class PlayerStatsCreate(BaseModel):
    player_id: int = Field(ge=1)
    match_id: int = Field(ge=1)
    points: int = Field(ge=0, le=1000)
    assists: int = Field(ge=0, le=1000)
    errors: int = Field(ge=0, le=1000)

class PlayerStatsUpdate(BaseModel):
    points: Optional[int] = Field(default=None, ge=0, le=1000)
    assists: Optional[int] = Field(default=None, ge=0, le=1000)
    errors: Optional[int] = Field(default=None, ge=0, le=1000)

class PlayerStatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    player_id: int
    match_id: int
    points: int
    assists: int
    errors: int
