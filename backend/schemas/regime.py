from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RegimeSignal(BaseModel):
    name: str
    value: float
    rule: str
    satisfied: bool


class RegimeResponse(BaseModel):
    regime: Literal["crisis", "vol_spike", "defensive", "risk_on", "mean_reverting_chop"]
    confidence: float
    contributing_signals: list[RegimeSignal] = Field(default_factory=list)
    updated_at: datetime
