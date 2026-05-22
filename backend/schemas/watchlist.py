from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WatchlistMetadata(BaseModel):
    """Per-category extras. All optional — populated only when relevant."""

    model_config = ConfigDict(extra="ignore")

    news_count: int | None = None
    earnings_date: str | None = None
    iv30_percentile: float | None = None
    options_volume_ratio: float | None = None
    sentiment_score: float | None = None


class WatchlistItemOut(BaseModel):
    symbol: str
    price: float
    change_pct: float
    subtitle: str
    metadata: WatchlistMetadata = Field(default_factory=WatchlistMetadata)


class WatchlistResponse(BaseModel):
    hot_now: list[WatchlistItemOut]
    earnings: list[WatchlistItemOut]
    unusual_options: list[WatchlistItemOut]
    sentiment_up: list[WatchlistItemOut]
    sentiment_down: list[WatchlistItemOut]
    # Optional per-category placeholder text. Surfaces things like
    # "Sentiment unavailable on free tier" instead of the generic empty state.
    notes: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime
