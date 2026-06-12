"""Per-combine account math — the multi-user successor to the
single-AccountState read path.

Same computation pattern as before, now keyed by combine_id instead of
tier string: realized P&L from closed trades, balance via the frozen
compute_balance, HWM advanced monotonically (persisted on the combine
row), MLL via the frozen compute_mll, DLL from today's ET realized
losses. Used by both routers/account.py (active-combine snapshot) and
routers/combines.py (per-card snapshots) so the numbers can't drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.combine import Combine
from models.trade import Trade
from services.account_tiers import TIERS, compute_balance, compute_mll, update_hwm
from services.combine_objectives import objective_progress, profit_target

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class CombineSnapshot:
    combine: Combine
    starting_balance: float
    realized_pnl: float
    balance: float
    hwm: float
    mll: float
    dll_used: float
    dll_budget: float
    dll_breached: bool
    profit_target: float
    objective_progress: float


def realized_sum_for_combine(session: Session, combine_id: int) -> float:
    rows = session.execute(
        select(Trade.realized_pnl)
        .where(Trade.combine_id == combine_id)
        .where(Trade.status == "closed")
    ).all()
    return float(sum((r[0] or 0.0) for r in rows))


def dll_used_today_for_combine(session: Session, combine_id: int) -> float:
    """Today's realized loss on this combine (ET trading day), ≥0.
    Frontend folds open-position UPL in at display time."""
    rows = session.execute(
        select(Trade.exit_date, Trade.realized_pnl)
        .where(Trade.combine_id == combine_id)
        .where(Trade.status == "closed")
        .where(Trade.exit_date.is_not(None))
    ).all()
    today_et = datetime.now(_ET).date()
    today_realized = 0.0
    for exit_dt, pnl in rows:
        if exit_dt is None:
            continue
        if exit_dt.tzinfo is None:
            exit_dt = exit_dt.replace(tzinfo=timezone.utc)
        if exit_dt.astimezone(_ET).date() == today_et:
            today_realized += float(pnl or 0.0)
    return max(0.0, -today_realized)


def combine_snapshot(session: Session, combine: Combine) -> CombineSnapshot:
    """Full computed state for one combine. Advances the persisted HWM
    monotonically (realized-only, same conservative read as before)."""
    tier = TIERS[combine.tier]

    realized = realized_sum_for_combine(session, combine.id)
    balance = compute_balance(tier.starting_balance, realized, 0.0)

    new_hwm = update_hwm(combine.hwm, balance)
    if new_hwm != combine.hwm:
        combine.hwm = new_hwm
        session.add(combine)
        session.commit()

    dll_used = dll_used_today_for_combine(session, combine.id)
    return CombineSnapshot(
        combine=combine,
        starting_balance=tier.starting_balance,
        realized_pnl=realized,
        balance=balance,
        hwm=new_hwm,
        mll=compute_mll(combine.tier, new_hwm),  # type: ignore[arg-type]
        dll_used=dll_used,
        dll_budget=tier.dll_amount,
        dll_breached=dll_used > tier.dll_amount,
        profit_target=profit_target(combine.tier),
        objective_progress=objective_progress(combine.tier, realized),
    )
