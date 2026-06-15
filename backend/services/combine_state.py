"""Per-combine account math — the multi-user successor to the
single-AccountState read path, now with the settlement engine folded in.

Same computation pattern as before, keyed by combine_id: realized P&L
from closed trades, balance via the frozen compute_balance, a RUNNING
HWM advanced monotonically intraday, and DLL from realized losses. On
top of that this module now drives the combine settlement engine
(services/combine_settlement): a lazy 5pm-PT settlement re-baselines the
SETTLED HWM up, the MLL floor is computed from that settled HWM (so it
is fixed intraday), the DLL window is the current 5pm-PT trading day,
and the realized-based PASS/FAIL outcome is persisted on the combine.

Used by both routers/account.py (active-combine snapshot) and
routers/combines.py (per-card snapshots) so the numbers can't drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.combine import Combine
from models.trade import Trade
from services.account_tiers import TIERS, compute_balance, compute_mll, update_hwm
from services.combine_objectives import objective_progress, profit_target
from services.combine_settlement import (
    MIN_TRADING_DAYS,
    consistency_ok,
    needs_settlement,
    settle_hwm,
    trading_day_start,
)


@dataclass(frozen=True)
class CombineSnapshot:
    combine: Combine
    starting_balance: float
    realized_pnl: float
    balance: float
    hwm: float
    settled_hwm: float
    mll: float
    dll_used: float
    dll_budget: float
    dll_breached: bool
    day_locked: bool
    profit_target: float
    objective_progress: float
    # --- settlement engine: PASS / FAIL ---
    outcome: str  # "active" | "passed" | "failed"
    days_traded: int
    min_trading_days: int
    largest_day_profit: float
    consistency_ok: bool


def realized_sum_for_combine(session: Session, combine_id: int) -> float:
    rows = session.execute(
        select(Trade.realized_pnl)
        .where(Trade.combine_id == combine_id)
        .where(Trade.status == "closed")
    ).all()
    return float(sum((r[0] or 0.0) for r in rows))


def _closed_exits(session: Session, combine_id: int) -> list[tuple[datetime, float]]:
    """(exit_date, realized_pnl) for this combine's closed trades, exit
    coerced to UTC-aware. Shared by the DLL window and the per-day buckets
    so both read the same source."""
    rows = session.execute(
        select(Trade.exit_date, Trade.realized_pnl)
        .where(Trade.combine_id == combine_id)
        .where(Trade.status == "closed")
        .where(Trade.exit_date.is_not(None))
    ).all()
    out: list[tuple[datetime, float]] = []
    for exit_dt, pnl in rows:
        if exit_dt is None:
            continue
        if exit_dt.tzinfo is None:
            exit_dt = exit_dt.replace(tzinfo=timezone.utc)
        out.append((exit_dt, float(pnl or 0.0)))
    return out


def dll_used_today_for_combine(
    session: Session, combine_id: int, now: datetime
) -> float:
    """Today's realized loss on this combine within the current 5pm-PT
    trading-day window [trading_day_start, now], clamped to ≥0. Frontend
    folds open-position URPL in at display time for the live DLL test."""
    day_start = trading_day_start(now)
    today_realized = 0.0
    for exit_dt, pnl in _closed_exits(session, combine_id):
        if exit_dt >= day_start:
            today_realized += pnl
    return max(0.0, -today_realized)


def realized_by_trading_day(
    session: Session, combine_id: int
) -> dict[datetime, float]:
    """Realized P&L on this combine bucketed by 5pm-PT trading day (keyed
    by the day's start instant). Drives the min-trading-days count and the
    consistency rule — both realized-based, like fail/settlement."""
    by_day: dict[datetime, float] = {}
    for exit_dt, pnl in _closed_exits(session, combine_id):
        day = trading_day_start(exit_dt)
        by_day[day] = by_day.get(day, 0.0) + pnl
    return by_day


def combine_snapshot(session: Session, combine: Combine) -> CombineSnapshot:
    """Full computed state for one combine. Advances the persisted RUNNING
    HWM monotonically (realized-only), runs the lazy 5pm-PT settlement,
    computes the fixed-intraday MLL floor, and persists a realized-based
    PASS/FAIL outcome. All persisted decisions are realized-based; the
    frontend folds live URPL in for display only."""
    tier = TIERS[combine.tier]
    now = datetime.now(timezone.utc)

    realized = realized_sum_for_combine(session, combine.id)
    balance = compute_balance(tier.starting_balance, realized, 0.0)
    dirty = False

    # RUNNING HWM — monotonic, updated intraday from realized balance.
    new_hwm = update_hwm(combine.hwm, balance)
    if new_hwm != combine.hwm:
        combine.hwm = new_hwm
        dirty = True

    # Lazy 5pm-PT settlement: once a boundary has passed, the settled HWM
    # re-baselines UP to the running HWM (never down) and we stamp the time
    # so we settle once per trading day. The DLL day resets implicitly —
    # it derives from the 5pm-PT window below, not a persisted flag.
    if needs_settlement(combine.last_settled_at, now):
        combine.settled_hwm = settle_hwm(combine.settled_hwm, new_hwm)
        combine.last_settled_at = now
        dirty = True

    # MLL floor — FIXED intraday, from the SETTLED HWM. Only settlement
    # moves it (always up).
    mll = compute_mll(combine.tier, combine.settled_hwm)  # type: ignore[arg-type]

    # DLL — today's realized loss within the current 5pm-PT trading day.
    dll_used = dll_used_today_for_combine(session, combine.id, now)
    dll_budget = tier.dll_amount
    day_locked = dll_used >= dll_budget

    # PASS progress (realized-based), bucketed per 5pm-PT trading day.
    by_day = realized_by_trading_day(session, combine.id)
    days_traded = len(by_day)
    total_realized = sum(by_day.values()) if by_day else 0.0
    largest_day_profit = max(by_day.values()) if by_day else 0.0
    consistency = consistency_ok(largest_day_profit, total_realized)
    target = profit_target(combine.tier)
    target_met = target > 0 and realized >= target
    min_days_met = days_traded >= MIN_TRADING_DAYS

    # Outcome precedence: FAILED is terminal (MLL breach) and wins; PASSED
    # is permanent. We only transition an ACTIVE, non-archived combine —
    # an already-decided or archived combine keeps its recorded outcome.
    outcome = combine.outcome
    if outcome == "active" and combine.status != "archived":
        if balance <= mll:
            outcome = "failed"
        elif target_met and min_days_met and consistency:
            outcome = "passed"
        if outcome != combine.outcome:
            combine.outcome = outcome
            dirty = True

    if dirty:
        session.add(combine)
        session.commit()

    return CombineSnapshot(
        combine=combine,
        starting_balance=tier.starting_balance,
        realized_pnl=realized,
        balance=balance,
        hwm=new_hwm,
        settled_hwm=combine.settled_hwm,
        mll=mll,
        dll_used=dll_used,
        dll_budget=dll_budget,
        dll_breached=dll_used > dll_budget,
        day_locked=day_locked,
        profit_target=target,
        objective_progress=objective_progress(combine.tier, realized),
        outcome=outcome,
        days_traded=days_traded,
        min_trading_days=MIN_TRADING_DAYS,
        largest_day_profit=largest_day_profit,
        consistency_ok=consistency,
    )
