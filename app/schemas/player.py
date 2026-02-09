from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class PlayerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    position: Optional[str] = Field(default=None, max_length=60)
    team_id: int = Field(ge=1)

class PlayerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    position: Optional[str] = Field(default=None, max_length=60)
    team_id: Optional[int] = Field(default=None, ge=1)

class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    position: Optional[str] = None
    team_id: int
