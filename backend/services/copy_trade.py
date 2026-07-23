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
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from config import settings
from models.combine import Combine
from models.trade import Trade
from models.user import User
from schemas.journal import TradeLeg, compute_net_debit_credit
from services.account_tiers import TIERS, resolve_dll_budget
from services.combine_settlement import trading_day_start
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


def _follower_oco_group(lead_group: str, follower_id: int) -> str:
    """Fresh per-follower OCO group that PRESERVES the sibling pairing.
    Deterministic (uuid5 of lead group + follower id): the two legs of a lead
    bracket pair are mirrored in separate calls, so re-deriving the same value
    keeps the follower's copies paired with each other — while staying distinct
    from the lead's group so a follower-side fill can't cancel the lead's (or
    another follower's) resting sibling."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"copy:{lead_group}:{follower_id}"))


def _day_locked(
    session: Session,
    combine: Combine,
    now: datetime,
    owner: User | None = None,
) -> bool:
    # Gate copy trades on the SAME budget the direct open path enforces
    # (combine_state.combine_snapshot): the owner's clamped per-tier DLL
    # override, falling back to the tier default. Previously this used the
    # raw tier default, so a follower who tightened their DLL kept receiving
    # mirrored trades past their configured floor (and a loosened one locked
    # early).
    # Personal profit-target day-protect lock: a stamp within the current
    # 5pm-PT trading day blocks mirrored opens exactly like any day-lock
    # (mirrors combine_snapshot's profit_locked fold-in).
    if (
        combine.profit_locked_at is not None
        and combine.profit_locked_at >= trading_day_start(now)
    ):
        return True
    # DLL-off toggle: a disabled DLL never day-locks — mirror combine_snapshot
    # (`day_locked = (not dll_disabled) and used >= budget`) so a follower whose
    # DLL is switched OFF keeps receiving mirrored trades (the MLL still binds).
    if owner is not None and not owner.dll_enabled_for(combine.tier):
        return False
    used = dll_used_today_for_combine(session, combine.id, now, combine.eval_reset_at)
    # Mode-aware blocking budget, mirroring combine_snapshot: only a
    # "liquidate_block" override replaces the firm tier default as the
    # day-lock budget; "alert"/"liquidate" overrides never block mirrors
    # (they are monitor-side triggers).
    entry = owner.dll_override_entries.get(combine.tier) if owner else None
    override = (
        entry["amount"] if entry is not None and entry["mode"] == "liquidate_block" else None
    )
    budget = resolve_dll_budget(combine.tier, override)
    return used >= budget


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
        if _day_locked(session, f, now, owner=user):
            result.skipped.append((f.id, "daily loss limit hit"))
            continue

        mult = f.copy_multiplier or 1.0
        legs = copy.deepcopy(lead_legs)
        # Apply the follower's multiplier per leg (always ≥1 contract for an
        # enabled follower).
        scaled = [max(1, round(int(leg.get("contracts", 1)) * mult)) for leg in legs]
        if len(legs) == 1:
            # Single leg: no inter-leg ratio to distort — clamp to the cap and
            # mirror a smaller size, the intended proportional-copy behavior.
            scaled[0] = min(scaled[0], cap)
        elif any(s > cap for s in scaled):
            # MULTI-LEG: clamping only the larger leg of a ratio structure (e.g.
            # a 1-2-1 butterfly) silently turns it into a DIFFERENT position with
            # a different risk profile than the lead traded. Skip the whole mirror
            # (same skip-not-fail convention as the gates around it) rather than
            # distort the structure. (A structure that fits under the cap is
            # mirrored ratio-intact; one that overflows is caught here or by the
            # aggregate check below — neither path clamps an individual leg.)
            result.skipped.append((f.id, "structure exceeds contract allowance"))
            continue
        for leg, s in zip(legs, scaled):
            leg["contracts"] = s
        # AGGREGATE cap, same convention as the direct open path: the scaling
        # plan limits TOTAL contracts across all legs of all open+working
        # positions, not each leg in isolation (the per-leg clamp above lets a
        # 2-leg straddle mirror 2× the cap). Skip when the mirror doesn't fit.
        from routers.zerodte import _open_contracts_for_combine  # lazy — avoids import cycle

        mirrored_total = sum(int(leg.get("contracts", 1) or 1) for leg in legs)
        open_now = _open_contracts_for_combine(session, f.id)
        if open_now + mirrored_total > cap:
            result.skipped.append((f.id, "scaling cap exceeded"))
            continue

        # MARGIN — the follower's OWN buying power must hold the mirrored
        # structure (review wave 8, finding 2: followers previously received
        # positions with NO capital check while every direct open is gated —
        # a lead on a large tier could mirror a naked short into a small-tier
        # follower whose balance can't hold one contract of it). Same
        # skip-not-fail convention as the other follower gates; priced at the
        # lead's fill spot so the cascade adds no quote round-trip.
        if settings.margin_enforcement_enabled:
            from calculations.margin import structure_requirement
            from routers.zerodte import _book_margin_used  # lazy — avoids import cycle
            from services.combine_state import combine_snapshot

            spot_ref = float(lead_trade.entry_underlying_price or 0.0)
            req = structure_requirement(
                legs,
                spot_ref,
                naked_pct=settings.margin_naked_pct,
                naked_min_pct=settings.margin_naked_min_pct,
            )
            if req > 0:
                snap = combine_snapshot(session, f)
                used = _book_margin_used(
                    session,
                    f.id,
                    {lead_trade.symbol: spot_ref} if spot_ref > 0 else {},
                )
                if req > snap.balance - used:
                    result.skipped.append((f.id, "insufficient buying power"))
                    continue

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
            # stop_price verbatim: without it a mirrored buy stop-limit arms
            # instantly against 0.0 and a sell stop-limit never arms.
            stop_price=lead_trade.stop_price,
            # Fresh per-follower OCO group preserving the sibling pairing —
            # see _follower_oco_group.
            oco_group=(
                _follower_oco_group(lead_trade.oco_group, f.id)
                if lead_trade.oco_group
                else None
            ),
            time_in_force=lead_trade.time_in_force,
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
            # Premium-denominated TP/SL copied VERBATIM: each follower copy
            # carries the same multiples and self-closes via its own monitor
            # pass (same mechanism as the mirrored stop_loss/take_profit).
            tp_premium_mult=lead_trade.tp_premium_mult,
            sl_premium_mult=lead_trade.sl_premium_mult,
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
    final_slice_pnl: float | None = None,
) -> int:
    """Cascade a lead trade's close to its still-open follower copies.

    Linked via Trade.copied_from_trade_id. Two modes:

    * ``closed_qty is None`` (default) — FULL close. Each follower is settled
      by STATUS: an OPEN follower is closed through a conditional
      ``UPDATE ... WHERE status='open'`` that ACCUMULATES the lead's FINAL
      SLICE (``final_slice_pnl``, scaled by the follower/lead contract ratio)
      onto its existing realized — so a follower that was partially scaled out
      earlier keeps those slices instead of having them overwritten, and a
      concurrent monitor close is never double-booked (rowcount 0 → skip). A
      still-WORKING follower (its own limit never filled) is CANCELLED with no
      P&L — booking realized on an order that never executed would fabricate
      combine equity. ``final_slice_pnl`` defaults to the lead's realized (the
      whole P&L for a never-scaled position), so callers of a never-scaled
      close need not pass it.

    * ``closed_qty`` set — PROPORTIONAL PARTIAL close (the WS-A scale-out
      seam). The lead reduced its leg contracts by ``closed_qty`` and
      accumulated realized on that slice; each follower closes
      ``clamp(round(follower_contracts * closed_qty / lead_original), 1,
      follower_contracts)`` of its own contracts, reducing its legs and
      ACCUMULATING realized on the booked slice, and stays open until its
      contracts reach 0 (then closes). Mirrors WS-A's lead-side contract.

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
        _cascade_full_close(session, lead_trade, followers, final_slice_pnl)
    else:
        _cascade_partial_close(lead_trade, followers, closed_qty, slice_pnl)
        # The partial path mutates ORM objects in place; the full path owns its
        # writes via conditional UPDATE (below), so only add here.
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


def _cascade_full_close(
    session: Session,
    lead_trade: Trade,
    followers: list[Trade],
    final_slice_pnl: float | None = None,
) -> None:
    """Settle each follower of a FULL lead close by status, via race-guarded
    conditional UPDATEs (never a bare ORM assignment that would clobber a
    concurrent monitor close or overwrite accumulated scale-out slices)."""
    lead_contracts = _leg_contracts(lead_trade)
    # Default to the lead's full realized — correct for a never-scaled position
    # (its whole realized IS the final slice). Callers that full-close AFTER a
    # scale-out thread the just-booked slice so earlier slices aren't re-booked.
    lead_final = (
        final_slice_pnl if final_slice_pnl is not None else lead_trade.realized_pnl
    )
    for f in followers:
        if f.status == "working":
            # Never filled → cancel with NO P&L (mirror_cancel semantics). The
            # status guard leaves a copy the monitor filled mid-cascade alone.
            session.execute(
                update(Trade)
                .where(Trade.id == f.id, Trade.status == "working")
                .values(status="cancelled")
                .execution_options(synchronize_session=False)
            )
            session.expire(f)
            continue
        # OPEN follower → close, ACCUMULATING the scaled final slice. rowcount 0
        # means a concurrent monitor close already booked it — skip.
        ratio = (_leg_contracts(f) / lead_contracts) if lead_contracts else 1.0
        values: dict = {
            "status": "closed",
            "close_reason": "copy",
            "exit_date": lead_trade.exit_date,
            "exit_underlying_price": lead_trade.exit_underlying_price,
        }
        if lead_final is not None:
            slice_amt = round(lead_final * ratio, 2)
            values["realized_pnl"] = func.coalesce(Trade.realized_pnl, 0.0) + slice_amt
        session.execute(
            update(Trade)
            .where(Trade.id == f.id, Trade.status == "open")
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        session.expire(f)


def _cascade_partial_close(
    lead_trade: Trade,
    followers: list[Trade],
    closed_qty: int,
    slice_pnl: float | None = None,
) -> None:
    closed_qty = max(0, int(closed_qty))
    if closed_qty <= 0:
        return
    # WS-A reduced the lead's legs by closed_qty before calling us, so the
    # ORIGINAL lead size is the current (reduced) size plus what just closed.
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
            slice_pnl = round(lead_slice_pnl * (f_close / closed_qty), 2)
            f.realized_pnl = round((f.realized_pnl or 0.0) + slice_pnl, 2)

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


def order_modification_values(
    trade: Trade,
    *,
    limit_price: float | None = None,
    stop_price: float | None = None,
    time_in_force: str | None = None,
) -> dict:
    """Column values for a cancel/replace on a WORKING order — shared by the
    journal modify endpoint and `mirror_modify` so lead and follower semantics
    can't drift. Callers apply them via ONE conditional UPDATE (a
    status='working' guard), so a concurrent monitor fill can't be
    half-overwritten by the modification.

    * limit_price also refreshes the single-leg display placeholder
      (entry_price) + net_debit_credit, exactly like placement. Multi-leg
      net-limit orders keep their per-leg mid placeholders.
    * stop_price only applies while the order still RESTS as a stop_limit;
      silently dropped otherwise (an armed copy is already a plain limit).
    """
    values: dict = {}
    if limit_price is not None:
        values["limit_price"] = float(limit_price)
        legs = trade.legs
        if len(legs) == 1:
            legs[0]["entry_price"] = round(float(limit_price), 4)
            values["legs_json"] = json.dumps(legs)
            values["net_debit_credit"] = compute_net_debit_credit(
                [TradeLeg(**leg) for leg in legs]
            )
    if stop_price is not None and trade.order_type == "stop_limit":
        values["stop_price"] = float(stop_price)
    if time_in_force is not None:
        values["time_in_force"] = str(time_in_force)
    return values


def mirror_modify(
    session: Session,
    lead_trade: Trade,
    *,
    limit_price: float | None = None,
    stop_price: float | None = None,
    time_in_force: str | None = None,
) -> int:
    """Cascade a lead order MODIFICATION (cancel/replace) to its still-WORKING
    follower copies — resolved via copied_from_trade_id exactly like
    mirror_cancel. Each follower is written through the same conditional
    status='working' guard the lead used, so a copy the monitor filled
    mid-cascade is left alone. Returns how many copies were modified."""
    followers = session.execute(
        select(Trade).where(
            Trade.copied_from_trade_id == lead_trade.id,
            Trade.status == "working",
        )
    ).scalars().all()
    if not followers:
        return 0
    modified = 0
    for f in followers:
        values = order_modification_values(
            f,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
        )
        if not values:
            continue
        modified += session.execute(
            update(Trade)
            .where(Trade.id == f.id, Trade.status == "working")
            .values(**values)
            .execution_options(synchronize_session=False)
        ).rowcount
        session.expire(f)
    session.commit()
    if modified:
        log.info(
            "copy-trade: lead trade %s modified %d follower copies",
            lead_trade.id,
            modified,
        )
    return modified


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
    # Conditional UPDATE guarded on status='working' (like mirror_modify): a
    # copy the monitor FILLED between the read above and here (working→open)
    # must NOT be overwritten to cancelled — its rowcount is 0 and it's skipped.
    cancelled = 0
    for f in followers:
        cancelled += session.execute(
            update(Trade)
            .where(Trade.id == f.id, Trade.status == "working")
            .values(status="cancelled")
            .execution_options(synchronize_session=False)
        ).rowcount
        session.expire(f)
    session.commit()
    log.info("copy-trade: lead trade %s cancelled %d follower copies", lead_trade.id, cancelled)
    return cancelled
