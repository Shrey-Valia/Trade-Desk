"""Pure functions that turn raw API payloads into ranked watchlist items.

Each builder returns a list of dicts ready to write into `watchlist_items`.
Keeping these pure (no I/O) means they're trivially unit-testable.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from zoneinfo import ZoneInfo

from services.alpaca_client import Quote
from services.finnhub_client import _EarningsRow, _NewsItem

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


class ItemDict(TypedDict):
    symbol: str
    rank: int
    price: float
    change_pct: float
    subtitle: str
    metadata_json: str


def _truncate(text: str, max_words: int = 5) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def build_hot_now(
    quotes: dict[str, Quote],
    news_by_symbol: dict[str, list[_NewsItem]],
    *,
    cap: int = 5,
) -> list[ItemDict]:
    """≥3 news items in last hour OR day-change >2% in absolute value.

    Sorted by news count desc, then absolute day-change desc.
    """
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    candidates: list[tuple[int, float, str, str]] = []
    for symbol, news in news_by_symbol.items():
        quote = quotes.get(symbol)
        if quote is None:
            continue
        recent = [
            n for n in news if datetime.fromtimestamp(n.datetime, tz=timezone.utc) >= one_hour_ago
        ]
        change = quote.change_pct
        triggered = len(recent) >= 3 or abs(change) >= 2.0
        if not triggered:
            continue
        latest_headline = recent[0].headline if recent else (news[0].headline if news else "")
        subtitle = _truncate(latest_headline) if latest_headline else f"{change:+.2f}% today"
        candidates.append((len(recent), abs(change), symbol, subtitle))

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)

    out: list[ItemDict] = []
    for rank, (news_count, _, symbol, subtitle) in enumerate(candidates[:cap]):
        quote = quotes[symbol]
        out.append(
            ItemDict(
                symbol=symbol,
                rank=rank,
                price=quote.price,
                change_pct=quote.change_pct,
                subtitle=subtitle,
                metadata_json=json.dumps({"news_count": news_count}),
            )
        )
    return out


def build_earnings(
    quotes: dict[str, Quote],
    earnings: Iterable[_EarningsRow],
    universe: Iterable[str],
    *,
    days_forward: int = 5,
    cap: int = 6,
) -> list[ItemDict]:
    """Companies in our universe reporting in the next `days_forward` days."""
    universe_set = set(universe)
    today = datetime.now(_ET).date()
    cutoff = today + timedelta(days=days_forward)

    earnings_list = list(earnings)
    in_window: list[tuple[str, _EarningsRow]] = []
    in_universe: list[tuple[str, _EarningsRow]] = []
    for row in earnings_list:
        try:
            event_date = datetime.fromisoformat(row.date).date()
        except ValueError:
            continue
        if today <= event_date <= cutoff:
            in_window.append((row.date, row))
            if row.symbol in universe_set:
                in_universe.append((row.date, row))

    rows = in_universe
    rows.sort(key=lambda r: r[0])

    log.info(
        "build_earnings: total=%d in_window=%d in_universe=%d window=%s..%s sample_window=%s",
        len(earnings_list),
        len(in_window),
        len(in_universe),
        today,
        cutoff,
        [(r[1].symbol, r[1].date) for r in in_window[:5]],
    )

    out: list[ItemDict] = []
    for rank, (_, row) in enumerate(rows[:cap]):
        quote = quotes.get(row.symbol)
        price = quote.price if quote else 0.0
        change = quote.change_pct if quote else 0.0
        when = _format_earnings_when(row)
        out.append(
            ItemDict(
                symbol=row.symbol,
                rank=rank,
                price=price,
                change_pct=change,
                subtitle=when,
                metadata_json=json.dumps({"earnings_date": row.date}),
            )
        )
    return out


def _format_earnings_when(row: _EarningsRow) -> str:
    try:
        d = datetime.fromisoformat(row.date).date()
    except ValueError:
        return row.date
    weekday = d.strftime("%a")
    hour = (row.hour or "").lower()
    suffix = {"bmo": "BMO", "amc": "AMC"}.get(hour, "")
    return f"{weekday} {suffix}".strip()


def build_unusual_options(
    quotes: dict[str, Quote],
    chain_volumes: dict[str, tuple[int, int]],
    *,
    cap: int = 4,
    min_total_volume: int = 1000,
) -> list[ItemDict]:
    """Today's call/put volume imbalance — directional positioning proxy.

    TODO: Phase 3 — replace with proper historical-baseline detection
    (today's volume ≥3× 20-day average) once we've collected enough
    daily chain snapshots to compute the baseline.
    """
    candidates: list[tuple[float, str, str, float]] = []
    for symbol, (call_vol, put_vol) in chain_volumes.items():
        if symbol not in quotes:
            continue
        if (call_vol + put_vol) < min_total_volume:
            continue
        if call_vol >= put_vol and put_vol > 0:
            ratio = call_vol / put_vol
            subtitle = f"Calls {ratio:.1f}× puts"
        elif put_vol > call_vol and call_vol > 0:
            ratio = put_vol / call_vol
            subtitle = f"Puts {ratio:.1f}× calls"
        else:
            continue
        if ratio < 1.5:
            continue
        candidates.append((ratio, symbol, subtitle, ratio))

    candidates.sort(key=lambda c: c[0], reverse=True)

    out: list[ItemDict] = []
    for rank, (_, symbol, subtitle, ratio) in enumerate(candidates[:cap]):
        quote = quotes[symbol]
        out.append(
            ItemDict(
                symbol=symbol,
                rank=rank,
                price=quote.price,
                change_pct=quote.change_pct,
                subtitle=subtitle,
                metadata_json=json.dumps({"options_volume_ratio": round(ratio, 2)}),
            )
        )
    return out


def build_sentiment(
    quotes: dict[str, Quote],
    sentiment_by_symbol: dict[str, float | None],
    *,
    direction: str,
    threshold: float = 0.2,
    cap: int = 3,
) -> list[ItemDict]:
    """direction == 'up' filters slope > +threshold; 'down' filters slope < -threshold."""
    rows: list[tuple[float, str]] = []
    for symbol, slope in sentiment_by_symbol.items():
        if slope is None or symbol not in quotes:
            continue
        if direction == "up" and slope > threshold:
            rows.append((slope, symbol))
        elif direction == "down" and slope < -threshold:
            rows.append((slope, symbol))

    rows.sort(key=lambda r: r[0], reverse=(direction == "up"))

    out: list[ItemDict] = []
    for rank, (slope, symbol) in enumerate(rows[:cap]):
        quote = quotes[symbol]
        out.append(
            ItemDict(
                symbol=symbol,
                rank=rank,
                price=quote.price,
                change_pct=quote.change_pct,
                subtitle=f"Sentiment {slope:+.2f}",
                metadata_json=json.dumps({"sentiment_score": round(slope, 3)}),
            )
        )
    return out
