"""NYSE session state.

Authoritative source: Alpaca's /v2/clock (`is_open` field). Alpaca handles
the full holiday + half-day schedule on their side, so we don't maintain
a local list. We fall back to pandas_market_calendars only when the
Alpaca call fails (network blip, credentials misconfigured) — better to
serve a probably-correct local answer than crash open/closed gates.

The `now` parameter is preserved for the fallback path and for testing.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

log = logging.getLogger(__name__)

_NYSE = mcal.get_calendar("NYSE")
_ET = ZoneInfo("America/New_York")


def is_market_open(now: datetime | None = None) -> bool:
    """True iff the regular NYSE session is open right now.

    If `now` is explicitly supplied, we always use the local
    pandas-market-calendars path so callers can ask hypotheticals
    (e.g. "was the market open at 10:30 ET on this date?"). For the
    common no-arg "right now" question we prefer Alpaca's clock."""
    if now is None:
        # Avoid a circular import — alpaca_client imports services.cache
        # which is fine, but services.market_calendar is imported by the
        # job layer; keep the alpaca dep lazy.
        from services.alpaca_client import get_market_clock

        clock = get_market_clock()
        if clock is not None:
            return clock.is_open
        log.warning("alpaca clock unavailable; falling back to local calendar")
        now = datetime.now(tz=_ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    schedule = _NYSE.schedule(start_date=now.date(), end_date=now.date())
    if schedule.empty:
        return False
    open_ts = schedule.iloc[0]["market_open"].to_pydatetime()
    close_ts = schedule.iloc[0]["market_close"].to_pydatetime()
    return open_ts <= now <= close_ts
