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

Two responsibilities each tick:

  1. WORKING limit/stop orders → fill when the option mark crosses the
     trigger (limit fills AT the limit; stop fills at the current mark).
     If the owning combine isn't tradeable (failed / day-locked), the order
     is cancelled instead of filled.
  2. OPEN positions with brackets → close when the UNDERLYING crosses a set
     level. Trigger direction is derived from entry_underlying_price (a level
     above entry triggers on the way up, below triggers on the way down).
     Closing books realized P&L the same way the manual CLOSE button does
     (analytics unrealized − exit-side commission); OCO is implicit since the
     position is gone.
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
            # Skip open positions with no brackets — nothing to monitor.
            if trade.status == "open" and trade.stop_loss is None and trade.take_profit is None:
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
                    if _process_open(session, trade, spot, now, unrealized_for):
                        closed += 1
                session.commit()
            except Exception:  # noqa: BLE001 — isolate one bad trade from the rest
                session.rollback()
                log.exception("order_monitor: trade %s failed", trade.id)
        log.info(
            "order_monitor: filled=%d closed=%d cancelled=%d of %d candidates",
            filled, closed, cancelled, len(trades),
        )
        return {"filled": filled, "closed": closed, "cancelled": cancelled, "total": len(trades)}
    finally:
        session.close()


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
    trigger = float(trade.limit_price) if trade.limit_price is not None else 0.0
    mark = option_mark(trade, spot)
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
    return "filled"


def _process_open(session, trade: Trade, spot: float, now: datetime, unrealized_for) -> bool:
    """Close an open position if a bracket triggered. Returns True if closed."""
    entry_u = trade.entry_underlying_price
    reason: str | None = None
    if _bracket_triggered(entry_u, trade.stop_loss, spot):
        reason = "stop_loss"
    elif _bracket_triggered(entry_u, trade.take_profit, spot):
        reason = "take_profit"
    if reason is None:
        return False

    unrealized = unrealized_for(trade, spot)
    realized = unrealized - _commission_side(trade)
    trade.status = "closed"
    trade.close_reason = reason
    trade.exit_date = now
    trade.exit_underlying_price = spot
    trade.realized_pnl = round(realized, 2)
    return True
