"""Pure date arithmetic for the calendar strip — no I/O, fully unit-testable."""

from __future__ import annotations

from datetime import date, timedelta

import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")

_QUAD_WITCHING_MONTHS = {3, 6, 9, 12}


def third_friday(year: int, month: int) -> date:
    """Return the third Friday of the given month."""
    first = date(year, month, 1)
    # weekday(): Mon=0..Sun=6; Friday=4
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def is_monthly_opex(d: date) -> bool:
    return d == third_friday(d.year, d.month)


def is_quad_witching(d: date) -> bool:
    """Quad witching = third Friday of Mar/Jun/Sep/Dec.

    Check this before is_monthly_opex when labeling — quad days take the
    more specific (purple bold) styling per the §7.8 color table.
    """
    return d.month in _QUAD_WITCHING_MONTHS and is_monthly_opex(d)


def next_trading_days(start: date, n: int) -> list[date]:
    """Return the next `n` NYSE trading days starting from `start` (inclusive
    if `start` is itself a trading day, else from the next session).

    Uses pandas_market_calendars so weekends + NYSE holidays are skipped
    correctly. Looks ahead at most ~3 weeks of calendar days to find n
    trading days; that's enough for n ≤ 10 even around long holiday weeks.
    """
    end = start + timedelta(days=max(n * 3, 14))
    schedule = _NYSE.schedule(start_date=start, end_date=end)
    # `schedule.index` is a DatetimeIndex of trading days.
    sessions = [d.date() for d in schedule.index][:n]
    return sessions


def nth_trading_day_of_month(year: int, month: int, n: int) -> date | None:
    """Return the Nth NYSE trading day of (year, month), or None if not enough
    sessions exist (month has fewer than N open sessions — vanishingly rare).

    "Trading day" follows the NYSE calendar — both weekends and market
    holidays are skipped. So if Jan 1 is a Friday but the market is closed
    for New Year's, the 1st trading day is Mon Jan 4.
    """
    first = date(year, month, 1)
    # Calendar-month ranges: 31 days max → safe upper bound is end of month.
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    schedule = _NYSE.schedule(start_date=first, end_date=last)
    sessions = [d.date() for d in schedule.index]
    if len(sessions) < n:
        return None
    return sessions[n - 1]


def ism_manufacturing_date(year: int, month: int) -> date | None:
    """ISM Manufacturing PMI releases on the 1st business day of each month
    at 10:00 ET. ISM is private (not in FRED's release calendar) so we
    compute the date ourselves."""
    return nth_trading_day_of_month(year, month, 1)


def ism_services_date(year: int, month: int) -> date | None:
    """ISM Services PMI releases on the 3rd business day of each month
    at 10:00 ET."""
    return nth_trading_day_of_month(year, month, 3)
