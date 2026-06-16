"""Tests for the journal analytics aggregations.

The math here is what a trader will see in the analytics tab — every
metric definition is the standard journal convention. Tests pin down:

  - Win rate / profit factor / expectancy compute correctly across mixed
    win/loss baskets.
  - By-strategy grouping respects only closed trades for P&L but counts
    all trades in the total.
  - DTE bucketing uses the nearest leg's expiry.
  - Mistake-cost bucket sorts by most-costly first.
  - Equity curve cumulates in exit-date order and computes drawdown.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from calculations.journal_analytics import (
    compose,
    compute_by_day_of_week,
    compute_by_dte,
    compute_by_hold_duration,
    compute_by_mistake,
    compute_by_strategy,
    compute_by_symbol,
    compute_by_time_of_day,
    compute_equity_curve,
    compute_kpis,
    compute_risk,
    compute_streaks,
)

_ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hh: int, mm: int) -> datetime:
    """ET-aware datetime — used to pin time-of-day / weekday buckets."""
    return datetime(year, month, day, hh, mm, tzinfo=_ET)


# ---------------------------------------------------------------------------
# Test helpers — build lightweight Trade stand-ins. We don't need an ORM
# session here; the analytics functions accept anything with the right
# attributes.
# ---------------------------------------------------------------------------


class FakeTrade:
    """Minimal Trade duck for the aggregation functions. Mirrors the
    fields they read; ignores everything else."""

    def __init__(
        self,
        *,
        symbol: str = "X",
        strategy: str = "long_call",
        status: str = "closed",
        realized_pnl: float | None = None,
        is_paper: bool = True,
        legs: list[dict] | None = None,
        entry_date: datetime | None = None,
        exit_date: datetime | None = None,
        risk_amount: float | None = None,
        mistake_tags: list[str] | None = None,
    ):
        self.symbol = symbol
        self.strategy = strategy
        self.status = status
        self.realized_pnl = realized_pnl
        self.is_paper = is_paper
        self.legs = legs or []
        self.entry_date = entry_date
        self.exit_date = exit_date
        self.risk_amount = risk_amount
        self.mistake_tags = mistake_tags or []

    @property
    def r_multiple(self) -> float | None:
        if self.risk_amount is None or self.risk_amount <= 0:
            return None
        if self.realized_pnl is None:
            return None
        return self.realized_pnl / self.risk_amount


def _today():
    return datetime(2026, 5, 22, tzinfo=timezone.utc)


def _leg_with_expiry(days_out: int) -> dict:
    # Anchor to the test's _today() so the by_dte buckets are stable
    # regardless of the system wall-clock date. (Pre-fix this used
    # date.today() which drifted vs _today() on a calendar rollover.)
    return {"expiry": (_today().date() + timedelta(days=days_out)).isoformat()}


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


def test_kpis_basic_win_rate_and_pnl():
    trades = [
        FakeTrade(realized_pnl=100, exit_date=_today() - timedelta(days=3)),
        FakeTrade(realized_pnl=200, exit_date=_today() - timedelta(days=2)),
        FakeTrade(realized_pnl=-150, exit_date=_today() - timedelta(days=1)),
        FakeTrade(status="open", realized_pnl=None),
    ]
    k = compute_kpis(trades)
    assert k.total_trades == 4
    assert k.open_trades == 1
    assert k.closed_trades == 3
    assert k.win_rate == pytest.approx(2 / 3)
    assert k.net_pnl == 150
    # PF = 300 / 150 = 2.0
    assert k.profit_factor == pytest.approx(2.0)
    assert k.avg_winner == pytest.approx(150)        # (100+200)/2
    assert k.avg_loser == pytest.approx(-150)        # -150 / 1
    assert k.expectancy == pytest.approx(50)         # 150/3
    assert k.largest_winner == 200
    assert k.largest_loser == -150


def test_kpis_profit_factor_handles_no_losers():
    trades = [
        FakeTrade(realized_pnl=100, exit_date=_today()),
        FakeTrade(realized_pnl=50, exit_date=_today()),
    ]
    k = compute_kpis(trades)
    # API serializer coerces inf → None for JSON; the dataclass keeps inf.
    import math
    assert math.isinf(k.profit_factor)


def test_kpis_avg_r_uses_only_trades_with_risk():
    trades = [
        FakeTrade(realized_pnl=200, risk_amount=100, exit_date=_today()),  # +2R
        FakeTrade(realized_pnl=-50, risk_amount=100, exit_date=_today()),  # -0.5R
        FakeTrade(realized_pnl=300, risk_amount=None, exit_date=_today()), # no R
    ]
    k = compute_kpis(trades)
    # avg R = (2 + -0.5) / 2 = 0.75 — third trade excluded
    assert k.avg_r == pytest.approx(0.75)


def test_kpis_empty_basket():
    k = compute_kpis([])
    assert k.total_trades == 0
    assert k.closed_trades == 0
    assert k.win_rate is None
    assert k.profit_factor is None
    assert k.expectancy is None


# ---------------------------------------------------------------------------
# By-strategy
# ---------------------------------------------------------------------------


def test_by_strategy_groups_correctly():
    trades = [
        FakeTrade(strategy="long_straddle", realized_pnl=-100, exit_date=_today()),
        FakeTrade(strategy="long_straddle", realized_pnl=-200, exit_date=_today()),
        FakeTrade(strategy="iron_condor", realized_pnl=150, exit_date=_today()),
        FakeTrade(strategy="iron_condor", realized_pnl=200, exit_date=_today()),
        FakeTrade(strategy="iron_condor", status="open", realized_pnl=None),
    ]
    rows = compute_by_strategy(trades)
    by_name = {r.strategy: r for r in rows}
    ic = by_name["iron_condor"]
    ls = by_name["long_straddle"]
    # IC: 3 trades, 2 closed, 2 wins, $350 net
    assert ic.trades == 3
    assert ic.closed == 2
    assert ic.win_rate == 1.0
    assert ic.net_pnl == 350
    assert ic.avg_pnl == 175
    # LS: 2 trades both closed losers
    assert ls.closed == 2
    assert ls.win_rate == 0.0
    assert ls.net_pnl == -300
    # Sorted by net P&L descending → IC first
    assert rows[0].strategy == "iron_condor"


def test_by_strategy_ignores_open_only_groups():
    """A strategy with only open trades shows up with 0 closed and
    None metrics — useful for the table to render but not misleading."""
    trades = [FakeTrade(strategy="long_call", status="open", realized_pnl=None)]
    rows = compute_by_strategy(trades)
    assert len(rows) == 1
    r = rows[0]
    assert r.trades == 1
    assert r.closed == 0
    assert r.win_rate is None
    assert r.avg_pnl is None
    assert r.net_pnl == 0


# ---------------------------------------------------------------------------
# By-DTE
# ---------------------------------------------------------------------------


def test_by_dte_buckets_using_nearest_leg_expiry():
    entry = _today() - timedelta(days=2)
    trades = [
        FakeTrade(
            realized_pnl=100, exit_date=_today(),
            entry_date=entry,
            legs=[_leg_with_expiry(5)],   # 5 - (-2) accounting? Just nearest from `date.today()` minus entry...
        ),
        FakeTrade(
            realized_pnl=-50, exit_date=_today(),
            entry_date=entry,
            legs=[_leg_with_expiry(14)],
        ),
        FakeTrade(
            realized_pnl=200, exit_date=_today(),
            entry_date=entry,
            legs=[_leg_with_expiry(30)],
        ),
        FakeTrade(
            realized_pnl=300, exit_date=_today(),
            entry_date=entry,
            legs=[_leg_with_expiry(60)],
        ),
    ]
    rows = compute_by_dte(trades)
    by_label = {r.label: r for r in rows}
    # First leg: expiry 5d from today, entry today-2d → leg.expiry - entry_date = 7 days.
    # That lands in "0-7" bucket.
    assert by_label["0-7"].trades == 1
    assert by_label["8-21"].trades == 1
    assert by_label["22-45"].trades == 1
    assert by_label["45+"].trades == 1


def test_by_dte_emits_zero_rows_for_empty_buckets():
    """The chart needs every bucket present so it can render an axis;
    empty buckets get trades=0 / metrics=None."""
    rows = compute_by_dte([])
    labels = {r.label for r in rows}
    # All four canonical buckets + "expired" should be present.
    assert "0-7" in labels
    assert "8-21" in labels
    assert "22-45" in labels
    assert "45+" in labels
    for r in rows:
        assert r.trades == 0
        assert r.win_rate is None


# ---------------------------------------------------------------------------
# Hold-duration buckets
# ---------------------------------------------------------------------------


def test_by_hold_duration_buckets_by_entry_to_exit_minutes():
    entry = _et(2026, 5, 22, 10, 0)  # intraday entry (14:00 UTC, not midnight)
    trades = [
        FakeTrade(realized_pnl=50, entry_date=entry, exit_date=entry + timedelta(seconds=20)),   # <1m, win
        FakeTrade(realized_pnl=-20, entry_date=entry, exit_date=entry + timedelta(minutes=3)),    # 1-5m, loss
        FakeTrade(realized_pnl=100, entry_date=entry, exit_date=entry + timedelta(minutes=10)),   # 5-15m, win
        FakeTrade(realized_pnl=30, entry_date=entry, exit_date=entry + timedelta(minutes=45)),    # 15-60m, win
        FakeTrade(realized_pnl=-10, entry_date=entry, exit_date=entry + timedelta(minutes=90)),   # >60m, loss
    ]
    rows = compute_by_hold_duration(trades)
    # Canonical order, every bucket emitted (stable chart axis).
    assert [r.label for r in rows] == ["<1m", "1-5m", "5-15m", "15-60m", ">60m"]
    by = {r.label: r for r in rows}
    assert by["<1m"].trades == 1 and by["<1m"].win_rate == 1.0
    assert by["1-5m"].trades == 1 and by["1-5m"].net_pnl == -20
    assert by["5-15m"].trades == 1 and by["5-15m"].net_pnl == 100
    assert by["15-60m"].trades == 1
    assert by[">60m"].trades == 1 and by[">60m"].win_rate == 0.0


def test_by_hold_duration_excludes_date_only_entries():
    # A date-only entry serializes to 00:00 UTC → no intraday time → the
    # hold span is undefined, so the trade is excluded (all buckets zero).
    trades = [
        FakeTrade(
            realized_pnl=100,
            entry_date=datetime(2026, 5, 22, tzinfo=timezone.utc),
            exit_date=datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
        ),
    ]
    rows = compute_by_hold_duration(trades)
    assert [r.label for r in rows] == ["<1m", "1-5m", "5-15m", "15-60m", ">60m"]
    assert all(r.trades == 0 for r in rows)


# ---------------------------------------------------------------------------
# Mistake-cost
# ---------------------------------------------------------------------------


def test_by_mistake_sorts_most_costly_first():
    trades = [
        FakeTrade(realized_pnl=-200, exit_date=_today(),
                  mistake_tags=["chased IV crush"]),
        FakeTrade(realized_pnl=-50, exit_date=_today(),
                  mistake_tags=["rolled too soon"]),
        FakeTrade(realized_pnl=-150, exit_date=_today(),
                  mistake_tags=["chased IV crush", "no exit plan"]),
    ]
    rows = compute_by_mistake(trades)
    # chased IV crush: 2 trades, -350
    # no exit plan:    1 trade, -150
    # rolled too soon: 1 trade, -50
    # Sorted ascending net P&L (most negative first).
    assert rows[0].tag == "chased IV crush"
    assert rows[0].trades == 2
    assert rows[0].net_pnl == -350
    assert rows[1].tag == "no exit plan"
    assert rows[2].tag == "rolled too soon"


def test_by_mistake_excludes_open_trades():
    trades = [
        FakeTrade(status="open", realized_pnl=None, mistake_tags=["oversized"]),
    ]
    rows = compute_by_mistake(trades)
    assert rows == []


def test_by_mistake_one_trade_two_tags_double_counted():
    """A single trade carrying two mistake tags shows up in BOTH buckets
    — the trader was making two errors simultaneously."""
    trades = [
        FakeTrade(realized_pnl=-100, exit_date=_today(),
                  mistake_tags=["chased IV crush", "held too long"]),
    ]
    rows = compute_by_mistake(trades)
    by_tag = {r.tag: r for r in rows}
    assert by_tag["chased IV crush"].trades == 1
    assert by_tag["chased IV crush"].net_pnl == -100
    assert by_tag["held too long"].trades == 1
    assert by_tag["held too long"].net_pnl == -100


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------


def test_equity_curve_cumulates_in_exit_date_order():
    trades = [
        FakeTrade(realized_pnl=100, exit_date=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=-30, exit_date=datetime(2026, 5, 3, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=200, exit_date=datetime(2026, 5, 5, tzinfo=timezone.utc)),
    ]
    curve = compute_equity_curve(trades)
    assert [p.cumulative_pnl for p in curve.points] == [100, 70, 270]
    assert curve.final_pnl == 270
    assert curve.peak_pnl == 270
    # Max DD: peak was 100, dipped to 70 → DD=30; then back up to 270 (new peak).
    assert curve.max_drawdown == 30


def test_equity_curve_max_drawdown_when_underwater_at_end():
    trades = [
        FakeTrade(realized_pnl=200, exit_date=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=-300, exit_date=datetime(2026, 5, 2, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=50, exit_date=datetime(2026, 5, 3, tzinfo=timezone.utc)),
    ]
    curve = compute_equity_curve(trades)
    # Path: 200 → -100 → -50. Peak 200, trough -100 → DD 300.
    assert curve.peak_pnl == 200
    assert curve.max_drawdown == 300
    assert curve.final_pnl == -50


def test_equity_curve_empty_when_no_closed_trades():
    curve = compute_equity_curve([FakeTrade(status="open", realized_pnl=None)])
    assert curve.points == []
    assert curve.max_drawdown == 0
    assert curve.final_pnl == 0


# ---------------------------------------------------------------------------
# End-to-end composer
# ---------------------------------------------------------------------------


def test_compose_runs_all_four_aggregations():
    """Smoke test — ensures the public composer returns a populated
    payload for a mixed basket without raising."""
    trades = [
        FakeTrade(
            strategy="long_straddle", realized_pnl=-180,
            exit_date=_today() - timedelta(days=10),
            entry_date=_today() - timedelta(days=15),
            legs=[_leg_with_expiry(20)],
            risk_amount=200,
            mistake_tags=["chased IV crush"],
        ),
        FakeTrade(
            strategy="iron_condor", realized_pnl=120,
            exit_date=_today() - timedelta(days=5),
            entry_date=_today() - timedelta(days=20),
            legs=[_leg_with_expiry(30)],
            risk_amount=300,
        ),
    ]
    result = compose(trades)
    assert result.kpis.closed_trades == 2
    assert len(result.by_strategy) == 2
    assert any(r.trades > 0 for r in result.by_dte)
    assert len(result.by_mistake) == 1
    assert len(result.equity.points) == 2


# ---------------------------------------------------------------------------
# By-symbol
# ---------------------------------------------------------------------------


def test_by_symbol_groups_and_sorts_by_net():
    trades = [
        FakeTrade(symbol="SPY", realized_pnl=300, exit_date=_today()),
        FakeTrade(symbol="SPY", realized_pnl=-100, exit_date=_today()),
        FakeTrade(symbol="QQQ", realized_pnl=-250, exit_date=_today()),
        FakeTrade(symbol="QQQ", status="open", realized_pnl=None),
    ]
    rows = compute_by_symbol(trades)
    by_sym = {r.symbol: r for r in rows}
    assert by_sym["SPY"].trades == 2
    assert by_sym["SPY"].closed == 2
    assert by_sym["SPY"].net_pnl == 200
    assert by_sym["SPY"].win_rate == pytest.approx(0.5)
    # QQQ counts the open trade in `trades` but not in closed/P&L.
    assert by_sym["QQQ"].trades == 2
    assert by_sym["QQQ"].closed == 1
    assert by_sym["QQQ"].net_pnl == -250
    # Sorted by net P&L descending → SPY first.
    assert rows[0].symbol == "SPY"


# ---------------------------------------------------------------------------
# By time-of-day
# ---------------------------------------------------------------------------


def test_by_time_of_day_buckets_by_et_entry():
    trades = [
        FakeTrade(realized_pnl=100, entry_date=_et(2026, 5, 19, 9, 45),
                  exit_date=_et(2026, 5, 19, 10, 15)),   # Open
        FakeTrade(realized_pnl=-40, entry_date=_et(2026, 5, 19, 11, 30),
                  exit_date=_et(2026, 5, 19, 12, 0)),     # Midday
        FakeTrade(realized_pnl=60, entry_date=_et(2026, 5, 19, 14, 0),
                  exit_date=_et(2026, 5, 19, 15, 0)),      # Power hour
        FakeTrade(realized_pnl=20, entry_date=_et(2026, 5, 19, 10, 15),
                  exit_date=_et(2026, 5, 19, 10, 45)),     # Open (before 10:30)
    ]
    rows = compute_by_time_of_day(trades)
    by_label = {r.label: r for r in rows}
    assert by_label["Open"].trades == 2
    assert by_label["Midday"].trades == 1
    assert by_label["Power hour"].trades == 1
    # Net P&L on the Open bucket = 100 + 20.
    assert by_label["Open"].net_pnl == 120


def test_by_time_of_day_excludes_dateonly_entries():
    """Back-logged trades stored at UTC-midnight carry no real intraday
    time and must not pollute the buckets (they'd all read as 'Open')."""
    trades = [
        FakeTrade(realized_pnl=100,
                  entry_date=datetime(2026, 5, 19, tzinfo=timezone.utc),  # 00:00 UTC
                  exit_date=_today()),
    ]
    rows = compute_by_time_of_day(trades)
    # Every canonical bucket present, all empty.
    assert {r.label for r in rows} == {"Open", "Midday", "Power hour"}
    assert all(r.trades == 0 for r in rows)


# ---------------------------------------------------------------------------
# By day-of-week
# ---------------------------------------------------------------------------


def test_by_day_of_week_buckets_by_et_weekday():
    # May 18 2026 is a Monday; May 20 is a Wednesday.
    trades = [
        FakeTrade(realized_pnl=100, entry_date=_et(2026, 5, 18, 9, 45),
                  exit_date=_et(2026, 5, 18, 10, 0)),
        FakeTrade(realized_pnl=-50, entry_date=_et(2026, 5, 20, 9, 45),
                  exit_date=_et(2026, 5, 20, 10, 0)),
    ]
    rows = compute_by_day_of_week(trades)
    by_label = {r.label: r for r in rows}
    assert [r.label for r in rows] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert by_label["Mon"].trades == 1
    assert by_label["Wed"].trades == 1
    assert by_label["Tue"].trades == 0


# ---------------------------------------------------------------------------
# Streaks + hold
# ---------------------------------------------------------------------------


def test_streaks_best_worst_and_current():
    # Sequence by exit date: W W L L L W  → best 2, worst -3, current +1.
    seq = [100, 200, -50, -60, -70, 30]
    trades = [
        FakeTrade(realized_pnl=p, exit_date=_today() - timedelta(days=len(seq) - i))
        for i, p in enumerate(seq)
    ]
    s = compute_streaks(trades)
    assert s.best_win == 2
    assert s.worst_loss == -3
    assert s.current == 1


def test_streaks_avg_hold_split_by_outcome():
    trades = [
        # winner held 60m
        FakeTrade(realized_pnl=100, entry_date=_et(2026, 5, 19, 9, 30),
                  exit_date=_et(2026, 5, 19, 10, 30)),
        # loser held 30m
        FakeTrade(realized_pnl=-40, entry_date=_et(2026, 5, 20, 9, 30),
                  exit_date=_et(2026, 5, 20, 10, 0)),
    ]
    s = compute_streaks(trades)
    assert s.avg_hold_win_min == pytest.approx(60)
    assert s.avg_hold_loss_min == pytest.approx(30)


def test_kpis_avg_hold_excludes_dateonly_entries():
    trades = [
        FakeTrade(realized_pnl=100, entry_date=_et(2026, 5, 19, 9, 30),
                  exit_date=_et(2026, 5, 19, 10, 30)),          # 60m, counts
        FakeTrade(realized_pnl=50,
                  entry_date=datetime(2026, 5, 20, tzinfo=timezone.utc),  # date-only
                  exit_date=_today()),                          # excluded
    ]
    k = compute_kpis(trades)
    assert k.avg_hold_min == pytest.approx(60)


# ---------------------------------------------------------------------------
# Equity drawdown window
# ---------------------------------------------------------------------------


def test_equity_curve_reports_drawdown_window_dates():
    trades = [
        FakeTrade(realized_pnl=100, exit_date=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=200, exit_date=datetime(2026, 5, 2, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=-250, exit_date=datetime(2026, 5, 3, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=80, exit_date=datetime(2026, 5, 4, tzinfo=timezone.utc)),
    ]
    curve = compute_equity_curve(trades)
    # Peak 300 on May 2, trough 50 on May 3 → DD 250.
    assert curve.max_drawdown == 250
    assert curve.drawdown_peak_date == "2026-05-02"
    assert curve.drawdown_trough_date == "2026-05-03"


# ---------------------------------------------------------------------------
# Risk / discipline
# ---------------------------------------------------------------------------


def test_risk_worst_day_and_days_near_mll_with_trail():
    trades = [
        # Day 1: −1200 net (two losers same day)
        FakeTrade(realized_pnl=-800, exit_date=datetime(2026, 5, 1, 14, tzinfo=timezone.utc)),
        FakeTrade(realized_pnl=-400, exit_date=datetime(2026, 5, 1, 15, tzinfo=timezone.utc)),
        # Day 2: −300 net
        FakeTrade(realized_pnl=-300, exit_date=datetime(2026, 5, 2, 14, tzinfo=timezone.utc)),
        # Day 3: +500
        FakeTrade(realized_pnl=500, exit_date=datetime(2026, 5, 3, 14, tzinfo=timezone.utc)),
    ]
    # 50K trail = 2000; 50% = 1000. Day 1 loss (1200) exceeds it; Day 2 (300) does not.
    risk = compute_risk(trades, trail=2000)
    assert risk.worst_day_pnl == -1200
    assert risk.worst_day_date == "2026-05-01"
    assert risk.largest_loss == -800
    assert risk.days_near_mll == 1
    assert risk.trail == 2000


def test_risk_days_near_mll_none_without_trail():
    trades = [
        FakeTrade(realized_pnl=-1200, exit_date=datetime(2026, 5, 1, 14, tzinfo=timezone.utc)),
    ]
    risk = compute_risk(trades)  # no trail
    assert risk.days_near_mll is None
    assert risk.worst_day_pnl == -1200


def test_compose_includes_new_blocks():
    trades = [
        FakeTrade(symbol="SPY", realized_pnl=120,
                  entry_date=_et(2026, 5, 18, 9, 45),
                  exit_date=_et(2026, 5, 18, 10, 30)),
        FakeTrade(symbol="QQQ", realized_pnl=-60,
                  entry_date=_et(2026, 5, 20, 13, 30),
                  exit_date=_et(2026, 5, 20, 14, 0)),
    ]
    result = compose(trades, trail=2000)
    assert len(result.by_symbol) == 2
    assert len(result.by_time_of_day) == 3
    assert len(result.by_day_of_week) == 5
    assert result.streaks.best_win >= 1
    assert result.risk.trail == 2000
