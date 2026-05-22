"""NYSE calendar awareness — handles holidays + half-days, not just weekday/time."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")
_ET = ZoneInfo("America/New_York")


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(tz=_ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    schedule = _NYSE.schedule(start_date=now.date(), end_date=now.date())
    if schedule.empty:
        return False
    open_ts = schedule.iloc[0]["market_open"].to_pydatetime()
    close_ts = schedule.iloc[0]["market_close"].to_pydatetime()
    return open_ts <= now <= close_ts
