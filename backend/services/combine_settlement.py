"""Combine settlement engine — the enforcement layer over the frozen
floor math in services/account_tiers.py and the display-only objectives
in services/combine_objectives.py.

This is where a combine actually settles, passes, and fails — the piece
the display-only shell deliberately left out. Pure time/threshold logic
only; the per-combine orchestration (reading trades, persisting state)
lives in services/combine_state.py so this module stays trivially
testable and free of DB concerns.

Model:
  * The combine "trading day" boundary / daily settlement is 5:00 PM
    Pacific. At that boundary the DLL window resets and each combine's
    SETTLED high-water mark re-baselines UP to the highest END-OF-DAY
    balance among completed trading days — the advertised Topstep
    convention: an intraday spike given back by the close moves the
    floor $0; only profit KEPT at 5pm PT advances it. The MLL floor is
    computed from the SETTLED HWM, so it is FIXED intraday and only
    ever steps up — never trails down mid-session. The running
    (day-high) HWM is intraday DISPLAY only and re-seeds to the balance
    at each settlement.
  * PASS rules (Topstep-aligned): realized profit ≥ the 6% target, a
    minimum number of distinct trading days with a closed trade, and a
    consistency rule (no single day's realized profit may exceed 50% of
    total realized profit).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# 5pm-PT trading-day boundary. America/Los_Angeles handles PST/PDT.
_PT = ZoneInfo("America/Los_Angeles")
SETTLEMENT_HOUR_PT = 17  # 5pm PT

# Locked combine PASS rules:
#   - PROFIT TARGET: 6% of starting balance (lives in combine_objectives).
#   - MIN TRADING DAYS: ≥2 distinct 5pm-PT trading days with a closed trade.
#   - CONSISTENCY: no single trading day's realized profit may exceed 50%
#     of total realized profit (checked at the moment of passing).
MIN_TRADING_DAYS: int = 2
CONSISTENCY_MAX_DAY_FRACTION: float = 0.50


def trading_day_start(now_utc: datetime) -> datetime:
    """The most recent 5pm-PT settlement boundary at or before `now`,
    returned as a UTC-aware datetime. The current trading day runs
    [trading_day_start, next 5pm PT)."""
    now_pt = now_utc.astimezone(_PT)
    boundary_today = now_pt.replace(
        hour=SETTLEMENT_HOUR_PT, minute=0, second=0, microsecond=0
    )
    start_pt = (
        boundary_today if now_pt >= boundary_today else boundary_today - timedelta(days=1)
    )
    return start_pt.astimezone(timezone.utc)


def needs_settlement(last_settled_at: datetime | None, now_utc: datetime) -> bool:
    """True when a 5pm-PT boundary has passed since the last settlement
    (or the combine has never settled) — i.e. we've entered a new trading
    day and should re-baseline the settled HWM up and reset the DLL day."""
    if last_settled_at is None:
        return True
    return last_settled_at < trading_day_start(now_utc)


def settle_hwm(settled_hwm: float, eod_balance: float) -> float:
    """Settlement re-baseline: the settled HWM advances UP to the
    end-of-day balance basis, never down."""
    return max(settled_hwm, eod_balance)


def peak_eod_balance(
    starting_balance: float,
    realized_by_day: dict[datetime, float],
    current_day_start: datetime,
) -> float:
    """Highest END-OF-DAY balance across COMPLETED trading days — the basis
    the settled HWM re-baselines to. Walks the per-day realized buckets in
    day order accumulating the balance at each 5pm-PT close; buckets at or
    after `current_day_start` are still in flight and excluded. Settlement
    is lazy and may skip several boundaries between reads, so trailing the
    PEAK across the gap (not just the latest boundary's balance) keeps the
    floor independent of read timing."""
    peak = balance = starting_balance
    for day, pnl in sorted(realized_by_day.items()):
        if day >= current_day_start:
            break
        balance += pnl
        peak = max(peak, balance)
    return peak


def consistency_ok(largest_day_profit: float, total_realized: float) -> bool:
    """No single day's realized profit may exceed 50% of total realized
    profit. Vacuously true until there is realized profit (you can't pass
    without profit anyway)."""
    if total_realized <= 0:
        return True
    return largest_day_profit <= CONSISTENCY_MAX_DAY_FRACTION * total_realized
