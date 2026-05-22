"""Tests for the journal P&L calendar bucketing."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from calculations.journal_calendar import build_month, parse_month


class FakeTrade:
    """Duck-typed Trade for the bucketing function — only the fields the
    bucketer reads. Mirrors the test pattern from test_journal_analytics."""

    def __init__(
        self,
        *,
        id: int = 1,
        status: str = "closed",
        realized_pnl: float | None = 0.0,
        exit_date: datetime | date | None = None,
    ):
        self.id = id
        self.status = status
        self.realized_pnl = realized_pnl
        self.exit_date = exit_date


def _exit(y: int, m: int, d: int, h: int = 16) -> datetime:
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Grid shape
# ---------------------------------------------------------------------------


def test_grid_always_six_weeks_seven_days():
    """Stable 6×7 grid regardless of where the month starts — the
    frontend depends on this so it doesn't reflow."""
    for month_start in [
        date(2026, 2, 1),
        date(2026, 5, 1),
        date(2026, 8, 1),
        date(2026, 12, 1),
    ]:
        grid = build_month([], month_start, today=date(2026, 5, 22))
        assert len(grid.weeks) == 6
        for w in grid.weeks:
            assert len(w.days) == 7


def test_grid_starts_on_sunday_and_includes_leading_days():
    """May 2026 begins on a Friday. The grid's first cell should be the
    Sunday before — Apr 26 — and labeled `in_month=False`."""
    grid = build_month([], date(2026, 5, 1), today=date(2026, 5, 22))
    first_cell = grid.weeks[0].days[0]
    assert first_cell.date == "2026-04-26"
    assert first_cell.in_month is False
    # First in-month cell sits at index 5 (Friday).
    fri = grid.weeks[0].days[5]
    assert fri.date == "2026-05-01"
    assert fri.in_month is True


def test_today_flagged_only_on_matching_date():
    grid = build_month([], date(2026, 5, 1), today=date(2026, 5, 22))
    flagged = [d for w in grid.weeks for d in w.days if d.is_today]
    assert len(flagged) == 1
    assert flagged[0].date == "2026-05-22"


# ---------------------------------------------------------------------------
# Bucketing semantics
# ---------------------------------------------------------------------------


def test_buckets_by_exit_date_not_entry():
    """The bucket key is exit_date. A trade entered last month but
    closed in May counts in May."""
    trades = [
        FakeTrade(id=1, exit_date=_exit(2026, 5, 5), realized_pnl=120),
        FakeTrade(id=2, exit_date=_exit(2026, 5, 5), realized_pnl=-40),
        FakeTrade(id=3, exit_date=_exit(2026, 5, 12), realized_pnl=300),
    ]
    grid = build_month(trades, date(2026, 5, 1), today=date(2026, 5, 22))
    by_date = {d.date: d for w in grid.weeks for d in w.days}
    may5 = by_date["2026-05-05"]
    assert may5.realized_pnl == 80      # 120 + -40 — same-day sum
    assert may5.trade_count == 2
    assert sorted(may5.trade_ids) == [1, 2]

    may12 = by_date["2026-05-12"]
    assert may12.realized_pnl == 300
    assert may12.trade_count == 1
    # A day with no trades is zero, not absent.
    assert by_date["2026-05-06"].realized_pnl == 0
    assert by_date["2026-05-06"].trade_count == 0


def test_open_trades_excluded_from_buckets():
    trades = [
        FakeTrade(id=1, exit_date=_exit(2026, 5, 5), realized_pnl=200, status="open"),
        FakeTrade(id=2, exit_date=None, realized_pnl=None, status="open"),
        FakeTrade(id=3, exit_date=_exit(2026, 5, 5), realized_pnl=50, status="closed"),
    ]
    grid = build_month(trades, date(2026, 5, 1), today=date(2026, 5, 22))
    may5 = next(d for w in grid.weeks for d in w.days if d.date == "2026-05-05")
    assert may5.trade_count == 1
    assert may5.realized_pnl == 50


def test_trade_outside_grid_is_excluded():
    """A trade closing far outside the visible 6-week window (e.g. last
    January when we're rendering May) doesn't accidentally leak into
    any cell."""
    trades = [
        FakeTrade(id=1, exit_date=_exit(2026, 1, 15), realized_pnl=500),
    ]
    grid = build_month(trades, date(2026, 5, 1), today=date(2026, 5, 22))
    assert grid.trade_count == 0
    assert grid.realized_pnl == 0
    # And it didn't sneak into any cell.
    all_ids = [tid for w in grid.weeks for d in w.days for tid in d.trade_ids]
    assert 1 not in all_ids


# ---------------------------------------------------------------------------
# Month boundary
# ---------------------------------------------------------------------------


def test_leading_days_count_toward_week_total_but_not_month_total():
    """A trade closing on April 28 shows in the May grid's leading-day
    cell (Tue Apr 28 is in the first week row). It contributes to that
    WEEK's total but NOT to the MAY MONTH total — leading cells are
    `in_month=False`."""
    trades = [
        FakeTrade(id=1, exit_date=_exit(2026, 4, 28), realized_pnl=100),
        FakeTrade(id=2, exit_date=_exit(2026, 5, 1), realized_pnl=200),  # in-month
    ]
    grid = build_month(trades, date(2026, 5, 1), today=date(2026, 5, 22))
    # First week's total = 100 (Apr 28) + 200 (May 1) = 300
    week1 = grid.weeks[0]
    assert week1.realized_pnl == 300
    assert week1.trade_count == 2
    # Month total includes only in-month cells → just the May 1 trade.
    assert grid.realized_pnl == 200
    assert grid.trade_count == 1


def test_trailing_days_excluded_from_month_total():
    """Mirror of the leading-days test for the back end of the grid.
    May 2026 ends on Sunday May 31 — no trailing days in the last in-
    month week, so let's use February which DOES have trailing days."""
    # Feb 2026 ends Sat Feb 28; March 1 is the next day. With a Sun-
    # start grid, Feb 28 lands in the last in-month row. We need a
    # month that overflows — try Aug 2026 (Aug 31 = Mon → trailing
    # Tue Sep 1 .. Sat Sep 5 in the last row).
    trades = [
        FakeTrade(id=1, exit_date=_exit(2026, 8, 31), realized_pnl=100),
        FakeTrade(id=2, exit_date=_exit(2026, 9, 2), realized_pnl=200),
    ]
    grid = build_month(trades, date(2026, 8, 1), today=date(2026, 8, 15))
    # Month total includes only the Aug 31 trade.
    assert grid.realized_pnl == 100
    assert grid.trade_count == 1
    # Sep 2 still appears in the last-row trailing cells.
    sep2 = next(d for w in grid.weeks for d in w.days if d.date == "2026-09-02")
    assert sep2.in_month is False
    assert sep2.realized_pnl == 200


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def test_month_total_matches_sum_of_in_month_days():
    trades = [
        FakeTrade(id=1, exit_date=_exit(2026, 5, 5), realized_pnl=100),
        FakeTrade(id=2, exit_date=_exit(2026, 5, 12), realized_pnl=-200),
        FakeTrade(id=3, exit_date=_exit(2026, 5, 20), realized_pnl=300),
    ]
    grid = build_month(trades, date(2026, 5, 1), today=date(2026, 5, 22))
    assert grid.realized_pnl == 200
    assert grid.trade_count == 3
    # Cross-check: sum of every in_month cell equals month total.
    in_month_sum = sum(
        d.realized_pnl for w in grid.weeks for d in w.days if d.in_month
    )
    assert in_month_sum == pytest.approx(grid.realized_pnl)


def test_label_is_human_readable():
    g = build_month([], date(2026, 5, 1), today=date(2026, 5, 22))
    assert g.label == "May 2026"
    assert g.month == "2026-05"


# ---------------------------------------------------------------------------
# parse_month helper
# ---------------------------------------------------------------------------


def test_parse_month_happy_path():
    assert parse_month("2026-05") == date(2026, 5, 1)
    assert parse_month("2026-12") == date(2026, 12, 1)


def test_parse_month_falls_back_to_fallback_on_garbage():
    fb = date(2026, 5, 22)
    assert parse_month(None, fallback=fb) == date(2026, 5, 1)
    assert parse_month("not-a-month", fallback=fb) == date(2026, 5, 1)
    assert parse_month("", fallback=fb) == date(2026, 5, 1)
