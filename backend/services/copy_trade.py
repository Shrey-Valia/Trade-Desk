"""Copy trading — mirror a lead combine's trades to follower combines.

When a user opens a trade on their configured LEAD combine
(user.copy_lead_combine_id), it is replicated to every follower combine
(combine.copy_follow=True) the user holds. v1 model (owner-chosen):

  * Sizing: SAME contract count, CLAMPED to each follower's scaling-plan
    contract cap. A follower with no allowance (cap < 1) is skipped.
  * Execution: SYNCHRONOUS best-effort — mirrored inside the lead's request,
    skipping any follower that can't take the trade (archived / failed eval /
    daily-loss-locked) and logging why. Never raises into the lead's request.

Closes/brackets and per-follower multipliers are future phases; this covers
the open path (market + working orders).
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.combine import Combine
from models.trade import Trade
from models.user import User
from schemas.journal import TradeLeg, compute_net_debit_credit
from services.account_tiers import TIERS
from services.combine_state import dll_used_today_for_combine
from services.scaling_plan import max_contracts as scaling_max_contracts

log = logging.getLogger(__name__)


@dataclass
class MirrorResult:
    mirrored: list[int] = field(default_factory=list)  # follower combine ids
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (id, reason)


def _follower_cap(combine: Combine) -> int:
    """Follower's max-contracts allowance (scaling-plan cap by built equity)."""
    settled_profit = max(0.0, combine.settled_hwm - TIERS[combine.tier].starting_balance)
    return scaling_max_contracts(combine.tier, settled_profit)


def _day_locked(session: Session, combine: Combine, now: datetime) -> bool:
    used = dll_used_today_for_combine(session, combine.id, now, combine.eval_reset_at)
    return used >= TIERS[combine.tier].dll_amount


def mirror_open(session: Session, lead_combine: Combine, lead_trade: Trade) -> MirrorResult:
    """Replicate a freshly-opened `lead_trade` to the lead's followers.

    No-op unless `lead_combine` is the user's configured copy lead. Best-effort:
    eligible followers get a clamped copy; ineligible ones are recorded in the
    result (and logged). Commits its own writes; never raises into the caller.
    """
    result = MirrorResult()
    user = session.get(User, lead_combine.user_id)
    if user is None or user.copy_lead_combine_id != lead_combine.id:
        return result  # copy trading off, or this combine isn't the lead

    followers = session.execute(
        select(Combine).where(
            Combine.user_id == lead_combine.user_id,
            Combine.copy_follow.is_(True),
            Combine.id != lead_combine.id,
            Combine.status != "archived",
        )
    ).scalars().all()
    if not followers:
        return result

    now = datetime.now(timezone.utc)
    lead_legs = lead_trade.legs or []

    for f in followers:
        if f.outcome == "failed":
            result.skipped.append((f.id, "failed eval"))
            continue
        cap = _follower_cap(f)
        if cap < 1:
            result.skipped.append((f.id, "no contract allowance"))
            continue
        if _day_locked(session, f, now):
            result.skipped.append((f.id, "daily loss limit hit"))
            continue

        mult = f.copy_multiplier or 1.0
        legs = copy.deepcopy(lead_legs)
        for leg in legs:
            # Apply the follower's multiplier, then clamp to its cap. Always
            # at least 1 contract for an enabled follower.
            scaled = max(1, round(int(leg.get("contracts", 1)) * mult))
            leg["contracts"] = min(scaled, cap)
        net = compute_net_debit_credit([TradeLeg(**leg) for leg in legs])

        # Per-follower bracket overrides win; fall back to the lead's levels
        # when the follower hasn't set its own.
        stop_loss = f.copy_stop_loss if f.copy_stop_loss is not None else lead_trade.stop_loss
        take_profit = (
            f.copy_take_profit if f.copy_take_profit is not None else lead_trade.take_profit
        )

        mirrored = Trade(
            symbol=lead_trade.symbol,
            strategy=lead_trade.strategy,
            entry_date=now,
            entry_underlying_price=lead_trade.entry_underlying_price,
            net_debit_credit=net,
            status=lead_trade.status,
            order_type=lead_trade.order_type,
            limit_price=lead_trade.limit_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            # Copy the trailing-stop CONFIG (offset) so followers trail too,
            # but NOT trail_hwm: each follower's monitor must seed its own
            # high-water from its own marks. Copying the lead's trail_hwm
            # would make followers trail off the LEAD's peak — closing them on
            # the lead's pullback regardless of their own price action.
            trail_amount=lead_trade.trail_amount,
            trail_pct=lead_trade.trail_pct,
            trail_hwm=None,
            is_paper=True,
            notes=f"{lead_trade.notes or ''} · copied from {lead_combine.name}".strip(" ·"),
            tier=f.tier,
            combine_id=f.id,
            copied_from_trade_id=lead_trade.id,
        )
        mirrored.legs = legs
        mirrored.tags = list(dict.fromkeys((lead_trade.tags or []) + ["copy"]))
        mirrored.mistake_tags = []
        session.add(mirrored)
        result.mirrored.append(f.id)

    if result.mirrored or result.skipped:
        session.commit()
    if result.skipped:
        log.info(
            "copy-trade: lead combine %s mirrored to %d, skipped %s",
            lead_combine.id,
            len(result.mirrored),
            result.skipped,
        )
    return result


def mirror_close(session: Session, lead_trade: Trade) -> int:
    """Cascade a lead trade's close to its still-open follower copies.

    Linked via Trade.copied_from_trade_id. Each follower's realized P&L is the
    lead's scaled by the contract ratio (followers may hold fewer contracts
    after the multiplier + cap clamp). Returns how many were closed."""
    followers = session.execute(
        select(Trade).where(
            Trade.copied_from_trade_id == lead_trade.id,
            Trade.status.in_(("open", "working")),
        )
    ).scalars().all()
    if not followers:
        return 0

    lead_legs = lead_trade.legs or []
    lead_contracts = int(lead_legs[0].get("contracts", 0)) if lead_legs else 0

    for f in followers:
        f_legs = f.legs or []
        f_contracts = int(f_legs[0].get("contracts", 0)) if f_legs else 0
        ratio = (f_contracts / lead_contracts) if lead_contracts else 1.0
        f.status = "closed"
        f.exit_date = lead_trade.exit_date
        f.exit_underlying_price = lead_trade.exit_underlying_price
        if lead_trade.realized_pnl is not None:
            f.realized_pnl = round(lead_trade.realized_pnl * ratio, 2)
        f.close_reason = "copy"
        session.add(f)

    session.commit()
    log.info("copy-trade: lead trade %s closed %d follower copies", lead_trade.id, len(followers))
    return len(followers)


def mirror_cancel(session: Session, lead_trade: Trade) -> int:
    """Cascade a lead WORKING-order cancel to its still-working follower
    copies (linked via copied_from_trade_id). Returns how many were
    cancelled."""
    followers = session.execute(
        select(Trade).where(
            Trade.copied_from_trade_id == lead_trade.id,
            Trade.status == "working",
        )
    ).scalars().all()
    if not followers:
        return 0
    for f in followers:
        f.status = "cancelled"
        session.add(f)
    session.commit()
    log.info("copy-trade: lead trade %s cancelled %d follower copies", lead_trade.id, len(followers))
    return len(followers)
