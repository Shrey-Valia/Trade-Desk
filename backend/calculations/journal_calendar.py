"""Bucket closed trades by exit_date into a monthly calendar grid.

Drives the Topstep-style P&L calendar on the /journal page. Pure
function over a list of Trade-like rows — no DB or HTTP here.

Semantics:
  - Realized P&L lands on the day the trade CLOSES (exit_date in UTC).
  - Open trades contribute nothing (no realized_pnl).
  - The grid expands to whole weeks: leading days from the prior
    month and trailing days from the next month are included as
    cells with `in_month=False` so the frontend renders them dimmed
    without recomputing the layout.
  - Monthly total sums in-month days only — leading/trailing cells
    don't double-count into adjacent months.
  - Weekly total sums ALL 7 cells in the row (Sun-Sat) the way Topstep
    presents it, since the week as a whole is what the trader scans.
"""

from __future__ import annotations

import calendar as _stdcal
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable


# Sunday-start US convention. The frontend renders columns left-to-right.
WEEKDAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


@dataclass
class CalendarDay:
    date: str               # ISO date "YYYY-MM-DD"
    in_month: bool
    realized_pnl: float
    trade_count: int
    trade_ids: list[int] = field(default_factory=list)
    is_today: bool = False


@dataclass
class CalendarWeek:
    week_of_month: int      # 1-indexed
    days: list[CalendarDay]
    realized_pnl: float
    trade_count: int


@dataclass
class CalendarMonth:
    month: str              # ISO "YYYY-MM"
    label: str              # human "May 2026"
    weeks: list[CalendarWeek]
    realized_pnl: float
    trade_count: int


def parse_month(month_str: str | None, *, fallback: date | None = None) -> date:
    """Parse 'YYYY-MM' into the first-of-month date. Falls back to today's
    month when the input is missing or malformed — keeps the endpoint
    robust to bad query strings without 400ing."""
    if month_str:
        try:
            y, m = month_str.split("-")
            return date(int(y), int(m), 1)
        except (ValueError, AttributeError):
            pass
    today = fallback or datetime.now(timezone.utc).date()
    return date(today.year, today.month, 1)


def _grid_bounds(first_of_month: date) -> tuple[date, date]:
    """Return (grid_start, grid_end) inclusive — Sunday before first of
    month through Saturday after last of month. Always 6 weeks × 7 days
    so the frontend gets a stable row count and doesn't reflow."""
    # Sunday before the 1st of the month. weekday(): Mon=0..Sun=6
    weekday = first_of_month.weekday()
    # Days back from `first_of_month` to land on the prior Sunday.
    # Sunday is weekday=6, so we go back (weekday+1) days, but wrap
    # via modulo so when first-of-month IS a Sunday we go back 0.
    days_back = (weekday + 1) % 7
    grid_start = first_of_month - timedelta(days=days_back)
    grid_end = grid_start + timedelta(days=6 * 7 - 1)
    return grid_start, grid_end


def _exit_date(trade) -> date | None:
    raw = getattr(trade, "exit_date", None)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc).date() if raw.tzinfo else raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def build_month(
    trades: Iterable[object],
    month: date,
    *,
    today: date | None = None,
) -> CalendarMonth:
    """Bucket closed trades into a 6-row × 7-col calendar grid.

    `trades` can be any iterable of Trade-likes with `status`,
    `exit_date`, `realized_pnl`, and `id` attributes — the function
    duck-types so the same code path serves both ORM rows and the
    test stand-ins.
    """
    today = today or datetime.now(timezone.utc).date()
    first_of_month = date(month.year, month.month, 1)
    grid_start, grid_end = _grid_bounds(first_of_month)

    # Bucket only closed trades with a usable exit date inside the grid.
    by_day: dict[date, list[object]] = defaultdict(list)
    for t in trades:
        if getattr(t, "status", None) != "closed":
            continue
        if getattr(t, "realized_pnl", None) is None:
            continue
        ed = _exit_date(t)
        if ed is None or ed < grid_start or ed > grid_end:
            continue
        by_day[ed].append(t)

    weeks: list[CalendarWeek] = []
    month_pnl = 0.0
    month_count = 0
    cursor = grid_start
    for week_idx in range(6):
        week_days: list[CalendarDay] = []
        week_pnl = 0.0
        week_count = 0
        for _ in range(7):
            in_month = (
                cursor.year == first_of_month.year
                and cursor.month == first_of_month.month
            )
            bucket = by_day.get(cursor, [])
            day_pnl = sum(float(getattr(t, "realized_pnl", 0) or 0) for t in bucket)
            day_ids = [int(getattr(t, "id", 0)) for t in bucket if getattr(t, "id", None) is not None]
            cell = CalendarDay(
                date=cursor.isoformat(),
                in_month=in_month,
                realized_pnl=round(day_pnl, 2),
                trade_count=len(bucket),
                trade_ids=day_ids,
                is_today=(cursor == today),
            )
            week_days.append(cell)
            # Weekly total covers ALL seven cells, mirroring Topstep —
            # the trader scans the row, not just in-month days.
            week_pnl += day_pnl
            week_count += len(bucket)
            if in_month:
                month_pnl += day_pnl
                month_count += len(bucket)
            cursor = cursor + timedelta(days=1)
        weeks.append(CalendarWeek(
            week_of_month=week_idx + 1,
            days=week_days,
            realized_pnl=round(week_pnl, 2),
            trade_count=week_count,
        ))

    return CalendarMonth(
        month=f"{first_of_month.year:04d}-{first_of_month.month:02d}",
        label=f"{_stdcal.month_name[first_of_month.month]} {first_of_month.year}",
        weeks=weeks,
        realized_pnl=round(month_pnl, 2),
        trade_count=month_count,
    )


__all__ = [
    "CalendarDay",
    "CalendarMonth",
    "CalendarWeek",
    "WEEKDAY_LABELS",
    "build_month",
    "parse_month",
]
