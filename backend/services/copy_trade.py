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

        mirrored = Trade(
            symbol=lead_trade.symbol,
            strategy=lead_trade.strategy,
            entry_date=now,
            entry_underlying_price=lead_trade.entry_underlying_price,
            net_debit_credit=net,
            status=lead_trade.status,
            order_type=lead_trade.order_type,
            limit_price=lead_trade.limit_price,
            stop_loss=lead_trade.stop_loss,
            take_profit=lead_trade.take_profit,
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


def _leg_contracts(trade: Trade) -> int:
    legs = trade.legs or []
    return int(legs[0].get("contracts", 0)) if legs else 0


def _set_leg_contracts(trade: Trade, contracts: int) -> None:
    """Reduce every leg's contract count to `contracts`, preserving the rest
    of each leg dict. Mirrors the per-leg scaling done at mirror time."""
    legs = trade.legs or []
    for leg in legs:
        leg["contracts"] = contracts
    trade.legs = legs


def mirror_close(
    session: Session,
    lead_trade: Trade,
    *,
    closed_qty: int | None = None,
    slice_pnl: float | None = None,
) -> int:
    """Cascade a lead trade's close to its still-open follower copies.

    Linked via Trade.copied_from_trade_id. Two modes:

    * ``closed_qty is None`` (default) — FULL close. Each follower copy is
      closed outright; its realized P&L is the lead's scaled by the contract
      ratio (followers may hold fewer contracts after the multiplier + cap
      clamp). This is the historical behaviour other callers
      (zerodte.py / order_monitor.py / journal full-close) rely on.

    * ``closed_qty`` set — PROPORTIONAL PARTIAL close (the scale-out seam).
      The lead reduced its leg contracts by ``closed_qty`` and accumulated
      realized on that slice; each follower closes
      ``clamp(round(follower_contracts * closed_qty / lead_original), 1,
      follower_contracts)`` of its own contracts, reducing its legs and
      ACCUMULATING realized on the booked slice, and stays open until its
      contracts reach 0 (then closes). Mirrors the lead-side scale-out
      contract.

    ``slice_pnl`` is the realized booked on the lead's JUST-CLOSED slice
    (threaded in by the scale-out caller). The lead's own realized_pnl is a
    RUNNING ACCUMULATED total, so reading it would re-book the lead's whole
    history onto followers on the 2nd+ scale-out — pass the slice explicitly.

    Returns how many follower copies were touched."""
    followers = session.execute(
        select(Trade).where(
            Trade.copied_from_trade_id == lead_trade.id,
            Trade.status.in_(("open", "working")),
        )
    ).scalars().all()
    if not followers:
        return 0

    if closed_qty is None:
        _cascade_full_close(lead_trade, followers)
    else:
        _cascade_partial_close(lead_trade, followers, closed_qty, slice_pnl)

    for f in followers:
        session.add(f)
    session.commit()
    log.info(
        "copy-trade: lead trade %s cascaded close (closed_qty=%s) to %d follower copies",
        lead_trade.id,
        closed_qty,
        len(followers),
    )
    return len(followers)


def _cascade_full_close(lead_trade: Trade, followers: list[Trade]) -> None:
    lead_contracts = _leg_contracts(lead_trade)
    for f in followers:
        ratio = (_leg_contracts(f) / lead_contracts) if lead_contracts else 1.0
        f.status = "closed"
        f.exit_date = lead_trade.exit_date
        f.exit_underlying_price = lead_trade.exit_underlying_price
        if lead_trade.realized_pnl is not None:
            f.realized_pnl = round(lead_trade.realized_pnl * ratio, 2)
        f.close_reason = "copy"


def _cascade_partial_close(
    lead_trade: Trade,
    followers: list[Trade],
    closed_qty: int,
    slice_pnl: float | None = None,
) -> None:
    closed_qty = max(0, int(closed_qty))
    if closed_qty <= 0:
        return
    # The lead's legs were already reduced by closed_qty before calling us, so
    # the ORIGINAL lead size is the current (reduced) size plus what just closed.
    lead_original = _leg_contracts(lead_trade) + closed_qty
    if lead_original <= 0:
        return
    # Realized booked on the lead's JUST-CLOSED slice. The caller threads this
    # in explicitly (lead_trade.realized_pnl is a RUNNING ACCUMULATED total, so
    # reading it would re-book the lead's whole history onto followers on the
    # 2nd+ scale-out); the fallback is correct only for a single scale-out.
    lead_slice_pnl = slice_pnl if slice_pnl is not None else lead_trade.realized_pnl

    for f in followers:
        f_contracts = _leg_contracts(f)
        if f_contracts <= 0:
            continue
        # Proportional follower slice, at least 1 contract, never more than it
        # currently holds.
        f_close = min(
            f_contracts,
            max(1, round(f_contracts * closed_qty / lead_original)),
        )
        remaining = f_contracts - f_close

        # Accumulate realized on the follower's closed slice. Scale the lead's
        # just-closed-slice P&L by the follower/lead closed-contract ratio so
        # the per-contract realized stays consistent across the cascade.
        if lead_slice_pnl is not None:
            f_slice = round(lead_slice_pnl * (f_close / closed_qty), 2)
            f.realized_pnl = round((f.realized_pnl or 0.0) + f_slice, 2)

        if remaining <= 0:
            # Fully unwound — close the follower copy.
            _set_leg_contracts(f, 0)
            f.status = "closed"
            f.exit_date = lead_trade.exit_date
            f.exit_underlying_price = lead_trade.exit_underlying_price
            f.close_reason = "copy"
        else:
            # Still open with fewer contracts; keep status, record the level.
            _set_leg_contracts(f, remaining)
            f.exit_underlying_price = lead_trade.exit_underlying_price


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
