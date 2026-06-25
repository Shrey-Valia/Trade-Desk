"""Order monitor — fills working limit/stop entries and auto-closes SL/TP
brackets (OCO). The simulated analog of an exchange's working-order book.

Runs on a clock (jobs/monitor_orders) every ~20s during market hours, but
all the decision logic lives here behind injectable callables so it's
unit-testable without any network or scheduler:

  - `spot_for(symbol)`       → live underlying price (None = unavailable)
  - `option_mark(trade,spot)`→ per-share option premium (working entry checks)
  - `unrealized_for(trade,spot)` → folded $ unrealized P&L (close booking)
  - `market_open()`          → bool gate
  - `now`                    → wall clock

Three responsibilities each tick:

  1. WORKING limit/stop orders → fill when the option mark crosses the
     trigger (limit fills AT the limit; stop fills at the current mark).
     Stop-limit rests as a limit once the stop arms. Trailing stops track a
     favorable-mark high-water and recompute the trigger every tick.
     If the owning combine isn't tradeable (failed / day-locked), the order
     is cancelled instead of filled.
  2. OPEN positions with brackets → close when the UNDERLYING crosses a set
     level. Trigger direction is derived from entry_underlying_price (a level
     above entry triggers on the way up, below triggers on the way down).
     Closing books realized P&L the same way the manual CLOSE button does
     (analytics unrealized − exit-side commission). When the closed leg
     belongs to an `oco_group`, its still-open siblings on the same combine
     are cancelled/closed so the bracket pair is one-cancels-the-other.
  3. AUTO-LIQUIDATION — per combine, the live balance (realized balance +
     open-position URPL) is tested against the MLL floor and the live DLL
     day-budget. A breach FORCE-CLOSES every open position on that combine
     (same booking path) and marks the combine `outcome = "failed"`. This is
     the hard-enforcement analog of a prop firm flattening you at the floor —
     fully deterministic, no randomness.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from config import settings
from models.trade import Trade
from schemas.journal import compute_net_debit_credit

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


# --- default (production) injectables ---------------------------------------


def _default_spot_for(symbol: str) -> float | None:
    from services.alpaca_client import get_quotes

    try:
        q = get_quotes([symbol]).get(symbol)
        return float(q.price) if q is not None else None
    except Exception:  # noqa: BLE001 — feed cold / rate-limited → skip this tick
        log.debug("order_monitor: quote fetch failed for %s", symbol)
        return None


def _rate() -> float:
    from services.fred_client import DEFAULT_RATE_FALLBACK, latest_dgs3mo_rate

    try:
        return latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        return DEFAULT_RATE_FALLBACK


def _t_to_close(now: datetime) -> float:
    from calculations.intraday_analytics import SECONDS_PER_YEAR

    now_et = now.astimezone(_ET)
    close = datetime.combine(now_et.date(), time(16, 0), tzinfo=_ET)
    secs = max((close - now_et).total_seconds(), 60.0)
    return secs / SECONDS_PER_YEAR


def _default_option_mark(trade: Trade, spot: float, now: datetime) -> float:
    """Per-share option premium for a (working) position. Uses a chain-default
    IV — approximate, but a working order only needs to know when the mark
    crosses the trigger, not an exact fill."""
    from calculations.intraday_analytics import bs_intraday
    from calculations.position_analytics import DEFAULT_IV

    t = _t_to_close(now)
    rate = _rate()
    total = 0.0
    for leg in trade.legs:
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        contracts = int(leg.get("contracts", 1) or 1)
        px = bs_intraday(spot, float(leg["strike"]), t, rate, DEFAULT_IV, leg["side"])
        total += sign * contracts * px
    return total


def _default_unrealized_for(trade: Trade, spot: float, now: datetime) -> float:
    """Folded $ unrealized P&L — identical math to the manual-close path so a
    monitor-driven close books the same realized number the user would see."""
    from routers.journal import _fold_commission, _intraday_analytics

    entry = trade.entry_date or now
    if entry.tzinfo is None:
        entry = entry.replace(tzinfo=timezone.utc)
    elapsed_hours = max(0.0, (now - entry).total_seconds() / 3600.0)
    resp = _intraday_analytics(trade=trade, spot=spot, rate=_rate(), elapsed_hours=elapsed_hours)
    contracts = max((int(leg.get("contracts", 1) or 1) for leg in trade.legs), default=1)
    resp = _fold_commission(resp, contracts * settings.commission_per_contract)
    return float(resp.unrealized_pnl)


def _commission_side(trade: Trade) -> float:
    contracts = max((int(leg.get("contracts", 1) or 1) for leg in trade.legs), default=1)
    return contracts * settings.commission_per_contract


# --- trigger logic ----------------------------------------------------------


def _entry_fill_triggered(order_type: str, action: str, mark: float, trigger: float) -> bool:
    """Working-order fill rule on the OPTION premium.
    limit-buy: mark ≤ limit · limit-sell: mark ≥ limit
    stop-buy:  mark ≥ stop  · stop-sell:  mark ≤ stop"""
    if order_type == "limit":
        return mark <= trigger if action == "buy" else mark >= trigger
    # stop
    return mark >= trigger if action == "buy" else mark <= trigger


def _bracket_triggered(entry_underlying: float, level: float | None, spot: float) -> bool:
    """A bracket fires when the underlying reaches the level from the side it
    was set on (derived from entry): level above entry → trigger on the way
    up; level below entry → trigger on the way down."""
    if level is None:
        return False
    if level >= entry_underlying:
        return spot >= level
    return spot <= level


def _has_trailing_stop(trade: Trade) -> bool:
    return (trade.trail_amount is not None and trade.trail_amount > 0) or (
        trade.trail_pct is not None and trade.trail_pct > 0
    )


def _trail_offset(hwm: float, trade: Trade) -> float:
    """Trail distance in PER-SHARE premium units — matching the per-share
    favorable value the trailing stop tracks. trail_amount is already a $/share
    offset (used directly); otherwise trail_pct × the favorable peak magnitude.
    trail_amount wins when both are set."""
    if trade.trail_amount is not None and trade.trail_amount > 0:
        return float(trade.trail_amount)
    return float(trade.trail_pct or 0.0) * abs(hwm)


def _process_trailing_stop(trade: Trade, mark: float, spot: float, now: datetime, unrealized_for) -> bool:
    """Advance a trailing stop's favorable high-water and close the position if
    the favorable value has retraced past the trail. Returns True if it closed.

    `mark` is the SIGNED, contracts-scaled position value (Σ sign·contracts·px
    from _default_option_mark). We reduce it to a PER-SHARE favorable value
    `fav = mark / contracts` in which HIGHER is always more favorable for BOTH
    long and short: a long gains as premium rises (fav rises); a short gains as
    premium decays (its negative fav rises toward 0). So one rule covers both —
    advance the max fav and stop when it retraces past the (per-share) trail.

    This normalization fixes two latent bugs that the unit tests masked (they
    inject positive per-share marks with contracts=1): using the signed mark
    directly INVERTED the trail for shorts (favorable moves triggered the stop),
    and comparing a $/share trail_amount against a contracts-scaled mark
    tightened the trail by a factor of `contracts`. Deterministic, idempotent."""
    total_contracts = max((int(leg.get("contracts", 1) or 1) for leg in trade.legs), default=1)
    fav = mark / max(1, total_contracts)

    hwm = trade.trail_hwm
    if hwm is None or fav > hwm:
        # Seed at — or advance to — the favorable high-water.
        hwm = fav
    trade.trail_hwm = round(float(hwm), 4)

    offset = _trail_offset(hwm, trade)
    if fav > hwm - offset:
        return False  # still within the trail of the favorable peak

    _book_close(trade, spot, now, unrealized_for, "stop_loss")
    trade.notes = (trade.notes or "") + " · trailing stop hit"
    return True


# --- the pass ---------------------------------------------------------------


def run_order_monitor(
    session_factory=None,
    *,
    now: datetime | None = None,
    spot_for=None,
    option_mark=None,
    unrealized_for=None,
    market_open=None,
) -> dict:
    """One monitor pass. Returns a summary dict for logging/tests."""
    now = now or datetime.now(timezone.utc)
    spot_for = spot_for or _default_spot_for
    option_mark = option_mark or (lambda t, s: _default_option_mark(t, s, now))
    unrealized_for = unrealized_for or (lambda t, s: _default_unrealized_for(t, s, now))
    if market_open is None:
        from services.market_calendar import is_market_open

        market_open = is_market_open
    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal

    if not market_open():
        return {"filled": 0, "closed": 0, "cancelled": 0, "skipped": "market_closed"}

    session = session_factory()
    filled = closed = cancelled = 0
    spot_cache: dict[str, float | None] = {}
    try:
        trades = (
            session.execute(
                select(Trade).where(Trade.status.in_(("working", "open")))
            )
            .scalars()
            .all()
        )
        for trade in trades:
            # A sibling may have been cancelled/closed earlier this pass (OCO,
            # or another in-session mutation) — skip anything no longer working
            # or open so we never re-process it.
            if trade.status not in ("working", "open"):
                continue
            # Skip open positions with nothing to monitor (no SL/TP bracket
            # AND no trailing stop). Auto-liquidation still scans them below.
            if (
                trade.status == "open"
                and trade.stop_loss is None
                and trade.take_profit is None
                and not _has_trailing_stop(trade)
            ):
                continue
            if trade.symbol not in spot_cache:
                spot_cache[trade.symbol] = spot_for(trade.symbol)
            spot = spot_cache[trade.symbol]
            if spot is None:
                continue
            try:
                if trade.status == "working":
                    outcome = _process_working(session, trade, spot, now, option_mark)
                    if outcome == "filled":
                        filled += 1
                    elif outcome == "cancelled":
                        cancelled += 1
                else:
                    if _process_open(session, trade, spot, now, unrealized_for, option_mark):
                        closed += 1
                session.commit()
            except Exception:  # noqa: BLE001 — isolate one bad trade from the rest
                session.rollback()
                log.exception("order_monitor: trade %s failed", trade.id)

        # HARD RISK ENFORCEMENT — auto-liquidate combines whose LIVE balance
        # (realized balance + open URPL) has fallen to/through the MLL floor,
        # or whose live DLL day-budget is exhausted, while positions are open.
        liquidated = _auto_liquidate(session, now, spot_for, unrealized_for, spot_cache)

        log.info(
            "order_monitor: filled=%d closed=%d cancelled=%d liquidated=%d of %d candidates",
            filled, closed, cancelled, liquidated, len(trades),
        )
        return {
            "filled": filled,
            "closed": closed,
            "cancelled": cancelled,
            "liquidated": liquidated,
            "total": len(trades),
        }
    finally:
        session.close()


def _auto_liquidate(
    session, now: datetime, spot_for, unrealized_for, spot_cache: dict[str, float | None]
) -> int:
    """Worst-first force-close on any combine that has breached its risk floor
    THIS tick: close the WORST-URPL positions one at a time, stopping the
    instant the LIVE balance (realized-after-cuts + the surviving open book)
    clears the floor — instead of always flattening everything.

    Breach test, per combine with ≥1 open position, against the combine's
    realized balance + the fixed-intraday floor:
      live_balance = realized + open_urpl  ≤  snap.mll   (MLL floor)
        OR
      live_dll_used = realized_day_loss + open_loss  ≥  snap.dll_budget  (DLL)

    where open_loss is the loss-only portion of the OPEN book's URPL (gains
    don't count against the DLL). When breached, positions are sorted WORST
    (most negative) URPL first and closed in order. A close REALIZES its loss,
    so after each cut we re-test against the moving realized base + the still-
    OPEN positions. The worst-first ordering means the largest open drawdowns
    leave the book first; we stop the instant the surviving book clears both
    floors (e.g. a marginal DLL breach where a net-winning remainder survives),
    keeping those positions open instead of flattening blindly.

    `outcome = "failed"` is set ONLY when, after the pass, the realized balance
    is still at/through the MLL floor (a permanent breach the cuts couldn't
    undo). A DLL-only breach that the cut cleared leaves the combine ACTIVE
    (a DLL never fails a combine — it day-locks, re-evaluated at settlement).

    Each force-close books realized P&L exactly like a bracket close
    (`unrealized − exit commission`) with close_reason "liquidation", then
    `mirror_close` cascades to any follower copies. Returns positions closed.
    """
    from models.combine import Combine
    from services.combine_state import combine_snapshot
    from services.copy_trade import mirror_close

    combine_ids = (
        session.execute(
            select(Trade.combine_id)
            .where(Trade.status == "open", Trade.combine_id.is_not(None))
            .distinct()
        )
        .scalars()
        .all()
    )
    if not combine_ids:
        return 0

    liquidated = 0
    for combine_id in combine_ids:
        combine = session.get(Combine, combine_id)
        if combine is None or combine.status == "archived":
            continue
        try:
            # Re-query open positions PER COMBINE so a prior combine's
            # mirror_close cascade (which may have already flattened a follower
            # copy here) is reflected — never double-book a closed trade.
            positions = (
                session.execute(
                    select(Trade).where(
                        Trade.combine_id == combine_id, Trade.status == "open"
                    )
                )
                .scalars()
                .all()
            )
            if not positions:
                continue

            # Resolve each position's live spot + unrealized once (cached).
            urpl = 0.0
            marks: dict[int, tuple[float, float]] = {}  # trade.id -> (spot, unreal)
            usable = True
            for t in positions:
                if t.symbol not in spot_cache:
                    spot_cache[t.symbol] = spot_for(t.symbol)
                spot = spot_cache[t.symbol]
                if spot is None:
                    usable = False
                    break
                unreal = unrealized_for(t, spot)
                marks[t.id] = (spot, unreal)
                urpl += unreal
            if not usable:
                # Can't price the book this tick — don't liquidate on partial info.
                continue

            snap = combine_snapshot(session, combine)
            # DLL branch active unless the owner disabled it (Step 3 toggle).
            dll_active = _combine_dll_enabled(session, combine)
            if not _breaches_floor(snap, snap.balance, urpl, dll_active):
                continue

            # The breach reason at pass start (MLL takes precedence — it's the
            # permanent floor). Tagged on every cut trade for a legible ledger.
            mll_breach = (snap.balance + urpl) <= snap.mll
            reason_note = (
                "MLL floor breached" if mll_breach else "daily loss limit exhausted"
            )

            # Sort WORST (most negative) URPL first — the largest open drawdowns
            # leave the book first. Tie-break on trade id for a deterministic,
            # stable order.
            ordered = sorted(positions, key=lambda t: (marks[t.id][1], t.id))

            # `realized_base` GROWS as each cut books its loss — the true live
            # MLL test (realized + still-open) is invariant, so an MLL breach
            # can't be traded out of: it flattens the book. The DLL test reduces
            # the still-OPEN loss against the pass-start realized day-loss, so
            # cutting the worst bleeder CAN bring open exposure back under the
            # daily budget while a net-winning remainder survives.
            realized_base = snap.balance
            remaining_urpl = urpl
            for t in ordered:
                spot, unreal = marks[t.id]
                _book_close(t, spot, now, unrealized_for, "liquidation")
                t.notes = (
                    (t.notes or "")
                    + f" · auto-liquidated worst-first ({reason_note})"
                )
                session.flush()
                mirror_close(session, t)
                liquidated += 1
                realized_base += t.realized_pnl or 0.0
                remaining_urpl -= unreal
                if not _breaches_floor(snap, realized_base, remaining_urpl, dll_active):
                    break

            from services.combine_state import record_event

            # FAILED only if STILL breached after the worst-first pass — the cuts
            # couldn't bring the book back inside the floor (a single
            # catastrophic position, or every position underwater). If the cut
            # CLEARED the breach (e.g. a DLL breach where a net-winning remainder
            # survives), the combine stays ACTIVE and keeps those positions open.
            still_breached = _breaches_floor(
                snap, realized_base, remaining_urpl, dll_active
            )
            if still_breached and combine.outcome == "active":
                survive_note = (
                    "MLL floor breached"
                    if (realized_base + remaining_urpl) <= snap.mll
                    else "daily loss limit exhausted"
                )
                combine.outcome = "failed"
                record_event(
                    session,
                    combine,
                    "failed",
                    f"Auto-liquidated — {survive_note}.",
                )
            elif not still_breached:
                # The worst-first cut cleared the breach — log it so the
                # liquidation is legible even though the combine survives.
                record_event(
                    session,
                    combine,
                    "liquidated",
                    f"Worst-first liquidation — cut {liquidated} position"
                    f"{'s' if liquidated != 1 else ''} to clear the "
                    f"{'MLL floor' if mll_breach else 'daily loss limit'}.",
                )
            session.commit()
        except Exception:  # noqa: BLE001 — isolate one combine from the rest
            session.rollback()
            log.exception("order_monitor: auto-liquidation for combine %s failed", combine_id)
    return liquidated


def _breaches_floor(
    snap, realized_base: float, open_urpl: float, dll_active: bool
) -> bool:
    """True when the combine breaches the MLL floor or (when the DLL is active)
    exhausts the daily loss budget, given a REALIZED base + the still-OPEN
    book's URPL.

      live_balance  = realized_base   + open_urpl            vs  snap.mll
      live_dll_used = snap.dll_used + max(0, -open_urpl)      vs  snap.dll_budget

    MLL uses `realized_base`, which GROWS as the worst-first pass books each
    cut — so realized_base + open_urpl is the true (invariant) live balance,
    and an MLL breach can't be cleared by closing (the loss is locked in).

    DLL uses the PASS-START realized day-loss (`snap.dll_used`) plus the
    loss-only portion of the STILL-OPEN book — so cutting the worst open loser
    reduces the open drawdown and can bring the DLL back under budget. The DLL
    is the daily *open-risk* hard-stop; the already-realized day-loss is fixed.
    Shared by the breach gate and the worst-first stop test so they can't
    drift."""
    if realized_base + open_urpl <= snap.mll:
        return True
    if dll_active and snap.dll_budget > 0:
        live_dll_used = snap.dll_used + max(0.0, -open_urpl)
        if live_dll_used >= snap.dll_budget:
            return True
    return False


def _combine_dll_enabled(session, combine) -> bool:
    """Whether the DLL branch is ACTIVE for this combine — i.e. the owner has
    not switched the daily loss limit OFF (the DLL-off toggle, matching real
    Topstep's 2024 drop of the DLL). Off → the auto-liquidation + soft-gate
    skip the DLL test entirely (MLL still binds). Defaults ON."""
    from models.user import User

    owner = session.get(User, combine.user_id)
    if owner is None:
        return True
    return owner.dll_enabled_for(combine.tier)


def _process_working(session, trade: Trade, spot: float, now: datetime, option_mark) -> str | None:
    """Fill or cancel a working limit/stop order. Returns 'filled'|'cancelled'|None."""
    from models.combine import Combine
    from services.combine_state import combine_snapshot

    # Don't fill into a non-tradeable combine — cancel the resting order.
    combine = session.get(Combine, trade.combine_id) if trade.combine_id else None
    if combine is not None:
        snap = combine_snapshot(session, combine)
        if snap.outcome == "failed" or snap.day_locked:
            trade.status = "cancelled"
            trade.close_reason = None
            trade.notes = (trade.notes or "") + " · cancelled (combine not tradeable)"
            return "cancelled"

    legs = trade.legs
    if not legs:
        return None
    action = legs[0].get("action", "buy")
    # option_mark returns the SIGNED, contracts-scaled position value
    # (Σ sign·contracts·px). Working-order triggers and the user's limit/stop
    # prices are PER-SHARE premium, so reduce to a positive per-share premium
    # before comparing. (Using the raw signed mark armed every SELL order on the
    # first tick — negative ≤ positive — and mis-scaled multi-contract orders.)
    total_contracts = max((int(leg.get("contracts", 1) or 1) for leg in legs), default=1)
    prem = abs(option_mark(trade, spot)) / max(1, total_contracts)

    # STOP-LIMIT — two phases. Phase 1: the order rests until the mark crosses
    # stop_price (stop semantics). Arming converts it into a plain LIMIT at
    # limit_price (persisted), so phase 2 (and every later tick) is a normal
    # limit fill. This deterministically reproduces "trigger at stop, then rest
    # as a limit": if the limit is already satisfied the same tick, it fills
    # immediately below; otherwise it waits as a limit.
    if trade.order_type == "stop_limit":
        stop_trigger = float(trade.stop_price) if trade.stop_price is not None else 0.0
        if not _entry_fill_triggered("stop", action, prem, stop_trigger):
            return None  # not yet armed
        trade.order_type = "limit"  # armed → now a resting limit at limit_price
        trade.notes = (trade.notes or "") + " · stop armed → limit"

    trigger = float(trade.limit_price) if trade.limit_price is not None else 0.0
    if not _entry_fill_triggered(trade.order_type, action, prem, trigger):
        return None

    # limit → fill AT the limit price; stop → fill at the current per-share mark.
    fill_px = trigger if trade.order_type == "limit" else max(0.01, prem)
    for leg in legs:
        leg["entry_price"] = round(float(fill_px), 4)
    trade.legs = legs
    from schemas.journal import TradeLeg

    trade.net_debit_credit = compute_net_debit_credit([TradeLeg(**leg) for leg in legs])
    trade.entry_underlying_price = spot
    trade.entry_date = now
    trade.status = "open"
    # OCO: filling this working order cancels its resting siblings.
    _cancel_oco_siblings(session, trade)
    return "filled"


def _cancel_oco_siblings(session, trade: Trade) -> int:
    """OCO: when `trade` fills (working entry) or closes (bracket), cancel the
    still-WORKING siblings sharing its oco_group. A sibling that is already OPEN
    or closed is left alone — only resting (unfilled) orders are pulled, which
    is the one-cancels-the-other guarantee for a bracket pair. Returns the
    number cancelled. Implicit no-op when oco_group is unset."""
    group = trade.oco_group
    if not group:
        return 0
    siblings = (
        session.execute(
            select(Trade).where(
                Trade.oco_group == group,
                Trade.id != trade.id,
                Trade.status == "working",
            )
        )
        .scalars()
        .all()
    )
    for s in siblings:
        s.status = "cancelled"
        s.close_reason = None
        s.notes = (s.notes or "") + " · OCO cancelled (sibling filled)"
    return len(siblings)


def _book_close(trade: Trade, spot: float, now: datetime, unrealized_for, reason: str) -> None:
    """Book a close on `trade` exactly the way the manual CLOSE button does:
    realized = analytics unrealized − exit-side commission. Mutates the trade
    in place; the caller owns the commit and any copy-trade cascade."""
    unrealized = unrealized_for(trade, spot)
    realized = unrealized - _commission_side(trade)
    trade.status = "closed"
    trade.close_reason = reason
    trade.exit_date = now
    trade.exit_underlying_price = spot
    trade.realized_pnl = round(realized, 2)


def _process_open(
    session, trade: Trade, spot: float, now: datetime, unrealized_for, option_mark=None
) -> bool:
    """Close an open position if a fixed bracket (SL/TP on the underlying) or a
    trailing stop (on the favorable option mark) triggered. Returns True if
    closed. The trailing stop is checked first so its high-water advances every
    tick even on a tick where the fixed brackets don't fire."""
    if _has_trailing_stop(trade) and option_mark is not None:
        mark = option_mark(trade, spot)
        if _process_trailing_stop(trade, mark, spot, now, unrealized_for):
            _cancel_oco_siblings(session, trade)
            return True

    entry_u = trade.entry_underlying_price
    reason: str | None = None
    if _bracket_triggered(entry_u, trade.stop_loss, spot):
        reason = "stop_loss"
    elif _bracket_triggered(entry_u, trade.take_profit, spot):
        reason = "take_profit"
    if reason is None:
        return False

    _book_close(trade, spot, now, unrealized_for, reason)
    # OCO: a bracket close cancels any resting siblings in the group.
    _cancel_oco_siblings(session, trade)
    return True
