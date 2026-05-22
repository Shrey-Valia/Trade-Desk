from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "earnings", "fomc", "fomc_minutes", "fed_speak", "economic", "opex", "quad_witching"
]
Importance = Literal["low", "medium", "high"]


class CalendarEvent(BaseModel):
    type: EventType
    title: str
    ticker: str | None = None
    time: str | None = None
    importance: Importance = "medium"


class CalendarDay(BaseModel):
    date: str  # ISO YYYY-MM-DD
    is_today: bool
    events: list[CalendarEvent] = Field(default_factory=list)


class CalendarResponse(BaseModel):
    days: list[CalendarDay]
    # Per-section placeholder text. Surfaced in the UI as italic gray notes
    # — used today to flag the empty Fed-speakers list, like the watchlist's
    # "Sentiment unavailable" pattern.
    notes: dict[str, str] = Field(default_factory=dict)
