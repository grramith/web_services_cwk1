import datetime as dt
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator

class MatchCreate(BaseModel):
    home_team_id: int = Field(ge=1)
    away_team_id: int = Field(ge=1)
    home_score: int = Field(ge=0, le=1000)
    away_score: int = Field(ge=0, le=1000)
    match_date: dt.date

    @model_validator(mode="after")
    def validate_teams(self):
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must be different")
        return self

class MatchUpdate(BaseModel):
    home_team_id: Optional[int] = Field(default=None, ge=1)
    away_team_id: Optional[int] = Field(default=None, ge=1)
    home_score: Optional[int] = Field(default=None, ge=0, le=1000)
    away_score: Optional[int] = Field(default=None, ge=0, le=1000)
    match_date: Optional[dt.date] = None

    @model_validator(mode="after")
    def validate_teams(self):
        if self.home_team_id is not None and self.away_team_id is not None:
            if self.home_team_id == self.away_team_id:
                raise ValueError("home_team_id and away_team_id must be different")
        return self

class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    match_date: dt.date
