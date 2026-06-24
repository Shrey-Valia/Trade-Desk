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


def _trail_offset(mark: float, trade: Trade) -> float:
    """Absolute $/share trail distance from the high-water mark. trail_amount
    wins when both are set; otherwise trail_pct × the high-water price."""
    if trade.trail_amount is not None and trade.trail_amount > 0:
        return float(trade.trail_amount)
    return float(trade.trail_pct or 0.0) * mark


def _process_trailing_stop(trade: Trade, mark: float, spot: float, now: datetime, unrealized_for) -> bool:
    """Advance a trailing stop's favorable-mark high-water and close the
    position if the mark has retraced past the trail. Long (net buy) favors a
    RISING mark and trails below the peak; short (net sell) favors a FALLING
    mark and trails above the trough. Returns True if it closed the position.

    Deterministic: the trigger is recomputed from the persisted high-water and
    the trail offset each tick — no randomness, idempotent once closed."""
    legs = trade.legs
    is_long = (legs[0].get("action", "buy") == "buy") if legs else True

    hwm = trade.trail_hwm
    if hwm is None:
        # Seed the high-water at the current mark on the first tick.
        hwm = mark
    elif is_long:
        hwm = max(hwm, mark)
    else:
        hwm = min(hwm, mark)
    trade.trail_hwm = round(float(hwm), 4)

    offset = _trail_offset(hwm, trade)
    if is_long:
        trigger = hwm - offset
        hit = mark <= trigger
    else:
        trigger = hwm + offset
        hit = mark >= trigger
    if not hit:
        return False

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
    """Force-close every open position on any combine that has breached its
    risk floor THIS tick, then mark the combine `outcome = "failed"`.

    Breach test, per combine with ≥1 open position:
      live_balance = snap.balance + URPL  ≤  snap.mll   (MLL floor)
        OR
      live_dll_used = snap.dll_used + open-loss  ≥  snap.dll_budget   (DLL exhausted)

    where URPL is the summed unrealized P&L of the combine's open positions and
    open-loss is the loss-only portion of that URPL (gains don't count against
    the DLL). snap.balance is the realized live balance (start + realized) and
    snap.mll the fixed-intraday floor — both from the same combine engine the
    rest of the app reads. Fully deterministic.

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
            live_balance = snap.balance + urpl
            open_loss = max(0.0, -urpl)
            live_dll_used = snap.dll_used + open_loss

            mll_breach = live_balance <= snap.mll
            dll_breach = snap.dll_budget > 0 and live_dll_used >= snap.dll_budget
            if not (mll_breach or dll_breach):
                continue

            reason_note = (
                "MLL floor breached" if mll_breach else "daily loss limit exhausted"
            )
            for t in positions:
                spot, _unreal = marks[t.id]
                _book_close(t, spot, now, unrealized_for, "liquidation")
                t.notes = (t.notes or "") + f" · auto-liquidated ({reason_note})"
                session.flush()
                mirror_close(session, t)
                liquidated += 1

            # Mark the combine FAILED (terminal). The combine engine also
            # fails on a realized-only MLL breach; doing it here makes the
            # auto-flatten and the fail atomic in the same tick.
            if combine.outcome == "active":
                combine.outcome = "failed"
                from services.combine_state import record_event

                record_event(
                    session,
                    combine,
                    "failed",
                    f"Auto-liquidated — {reason_note}.",
                )
            session.commit()
        except Exception:  # noqa: BLE001 — isolate one combine from the rest
            session.rollback()
            log.exception("order_monitor: auto-liquidation for combine %s failed", combine_id)
    return liquidated


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
    mark = option_mark(trade, spot)

    # STOP-LIMIT — two phases. Phase 1: the order rests until the mark crosses
    # stop_price (stop semantics). Arming converts it into a plain LIMIT at
    # limit_price (persisted), so phase 2 (and every later tick) is a normal
    # limit fill. This deterministically reproduces "trigger at stop, then rest
    # as a limit": if the limit is already satisfied the same tick, it fills
    # immediately below; otherwise it waits as a limit.
    if trade.order_type == "stop_limit":
        stop_trigger = float(trade.stop_price) if trade.stop_price is not None else 0.0
        if not _entry_fill_triggered("stop", action, mark, stop_trigger):
            return None  # not yet armed
        trade.order_type = "limit"  # armed → now a resting limit at limit_price
        trade.notes = (trade.notes or "") + " · stop armed → limit"

    trigger = float(trade.limit_price) if trade.limit_price is not None else 0.0
    if not _entry_fill_triggered(trade.order_type, action, mark, trigger):
        return None

    # limit → fill AT the limit price; stop → fill at the current mark.
    fill_px = trigger if trade.order_type == "limit" else max(0.01, mark)
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
