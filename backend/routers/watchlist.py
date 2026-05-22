import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.watchlist_item import WatchlistItem
from schemas.watchlist import WatchlistItemOut, WatchlistMetadata, WatchlistResponse
from services.finnhub_client import SENTIMENT_AVAILABLE, SENTIMENT_NOTE

router = APIRouter(prefix="/api", tags=["watchlist"])

CATEGORIES = ("hot_now", "earnings", "unusual_options", "sentiment_up", "sentiment_down")


@router.get("/watchlist", response_model=WatchlistResponse)
def get_watchlist(session: Session = Depends(get_session)) -> WatchlistResponse:
    rows = session.execute(
        select(WatchlistItem).order_by(WatchlistItem.category, WatchlistItem.rank)
    ).scalars().all()

    buckets: dict[str, list[WatchlistItemOut]] = {c: [] for c in CATEGORIES}
    latest_update = datetime.now(timezone.utc)

    for row in rows:
        if row.category not in buckets:
            continue
        try:
            metadata = WatchlistMetadata.model_validate(json.loads(row.metadata_json or "{}"))
        except (ValueError, TypeError):
            metadata = WatchlistMetadata()
        buckets[row.category].append(
            WatchlistItemOut(
                symbol=row.symbol,
                price=row.price,
                change_pct=row.change_pct,
                subtitle=row.subtitle,
                metadata=metadata,
            )
        )
        if row.created_at and row.created_at < latest_update:
            latest_update = row.created_at

    notes: dict[str, str] = {}
    if not SENTIMENT_AVAILABLE:
        notes["sentiment_up"] = SENTIMENT_NOTE
        notes["sentiment_down"] = SENTIMENT_NOTE

    return WatchlistResponse(
        hot_now=buckets["hot_now"],
        earnings=buckets["earnings"],
        unusual_options=buckets["unusual_options"],
        sentiment_up=buckets["sentiment_up"],
        sentiment_down=buckets["sentiment_down"],
        notes=notes,
        updated_at=latest_update,
    )
