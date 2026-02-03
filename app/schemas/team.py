from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    league: Optional[str] = Field(default=None, max_length=120)

class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    league: Optional[str] = Field(default=None, max_length=120)

class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    league: Optional[str] = None
