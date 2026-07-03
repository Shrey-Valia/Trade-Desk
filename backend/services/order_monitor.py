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
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from config import settings
from models.trade import Trade
from schemas.journal import compute_net_debit_credit

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# --- last-known-good spot fallback (auto-liquidation safety) -----------------
#
# Auto-liquidation FORCE-CLOSES a book when the live balance breaches the MLL
# floor / DLL budget. A single None spot (transient feed gap / rate-limit)
# previously SKIPPED the whole combine — meaning a breach could go un-flattened
# for one or more ticks, letting the loss overshoot the floor. To bound that
# overshoot we keep the last successfully-fetched spot per symbol and reuse it
# for a short TTL when the live fetch returns None.
#
# Keyed by symbol → (spot, observed_at). `observed_at` is the deterministic
# `now` threaded through the monitor — NEVER datetime.now() — so age is
# reproducible in tests and free of wall-clock surprises.
_LAST_GOOD_SPOT: dict[str, tuple[float, datetime]] = {}

# Max age a fallback spot may be and still be trusted for a liquidation price.
_SPOT_FALLBACK_TTL_SECONDS = 60.0


def _record_good_spot(symbol: str, spot: float, now: datetime) -> None:
    """Remember a freshly-fetched spot as the last-known-good for `symbol`,
    stamped with the deterministic monitor clock `now`."""
    _LAST_GOOD_SPOT[symbol] = (float(spot), now)


def _fallback_spot(symbol: str, now: datetime) -> tuple[float | None, float | None]:
    """Return (spot, age_seconds) from the last-known-good store if it is fresh
    (age ≤ TTL), else (None, age_or_None). Age is measured against the
    deterministic `now` so it never depends on wall-clock."""
    entry = _LAST_GOOD_SPOT.get(symbol)
    if entry is None:
        return None, None
    spot, observed_at = entry
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age = (now - observed_at).total_seconds()
    if 0.0 <= age <= _SPOT_FALLBACK_TTL_SECONDS:
        return spot, age
    return None, age


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


def _session_close_for_date(d: date) -> datetime:
    """Regular-session close instant (tz-aware ET) for date `d`, half-day aware
    via the NYSE schedule, with a flat 16:00 ET fallback when `d` isn't a
    listed trading day (defensive — a stored expiry that got shifted)."""
    from services.market_calendar import session_close_et

    close = session_close_et(d.isoformat())
    if close is not None:
        return close
    return datetime.combine(d, time(16, 0), tzinfo=_ET)


def _t_to_close(now: datetime) -> float:
    from calculations.intraday_analytics import SECONDS_PER_YEAR

    now_et = now.astimezone(_ET)
    # Half-day aware: the NYSE schedule knows the 1:00pm ET early closes, so a
    # 0DTE isn't priced with ~3 extra hours of fictitious time value on those
    # ~9 sessions/year.
    close = _session_close_for_date(now_et.date())
    secs = max((close - now_et).total_seconds(), 60.0)
    return secs / SECONDS_PER_YEAR


def _et_date(dt: datetime):
    """ET calendar date of an instant — used to expire DAY working orders that
    survive unfilled into a later trading session."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET).date()


def _option_chain_rows(symbol: str):
    """Cached live option chain for the monitor's mark, or None when the feed
    is cold / the circuit breaker is open. Best-effort — never raises into the
    loop. `with_volume=False` skips the expensive per-contract bars fetch."""
    try:
        from services.alpaca_client import get_chain_snapshot

        return get_chain_snapshot(symbol, with_volume=False)
    except Exception:  # noqa: BLE001 — cold feed / breaker open → model fallback
        return None


def _chain_row_for(rows, strike: float, side: str, expiry):
    if not rows or expiry is None:
        return None
    for r in rows:
        if r.type == side and r.expiry == expiry and abs(r.strike - strike) < 1e-6:
            return r
    return None


def _chain_quote_mid(row) -> float | None:
    """Per-share mid from a live chain row: (bid+ask)/2 when two-sided, else a
    positive last. None when the contract has no usable quote (→ model fallback)."""
    if row is None:
        return None
    if row.bid is not None and row.ask is not None and row.bid > 0 and row.ask > 0:
        return (row.bid + row.ask) / 2.0
    if row.last is not None and row.last > 0:
        return float(row.last)
    return None


def _leg_t_to_expiry(leg: dict, now: datetime) -> float:
    """Years to THIS leg's own expiry close (ET, half-day aware), floored at 60s
    — NOT today's close. A position on a future expiry must price with its real
    remaining life, not as if it expired today."""
    from calculations.intraday_analytics import SECONDS_PER_YEAR

    exp = _leg_expiry(leg)
    now_et = now.astimezone(_ET)
    close = _session_close_for_date(exp if exp is not None else now_et.date())
    secs = max((close - now_et).total_seconds(), 60.0)
    return secs / SECONDS_PER_YEAR


def _default_option_mark(trade: Trade, spot: float, now: datetime) -> float:
    """Signed, contracts-scaled per-share position mark (Σ sign·contracts·px)
    for working-order triggers and trailing stops.

    Prices each leg from the LIVE option-chain quote MID for its exact
    strike/expiry/side when available (faithful — no model). Only when the
    contract isn't quoted does it fall back to a Black-Scholes price at THE
    LEG'S OWN expiry (half-day aware), using the contract's live chain IV when
    present, else the DEFAULT_IV. This replaces the old behaviour — a flat 30%
    IV at *today's* close for every leg — which fabricated stop fills and
    mispriced any future-expiry position as if it expired today."""
    from calculations.intraday_analytics import bs_intraday
    from calculations.position_analytics import DEFAULT_IV

    rate = _rate()
    rows = _option_chain_rows(trade.symbol)
    total = 0.0
    for leg in trade.legs:
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        contracts = int(leg.get("contracts", 1) or 1)
        strike = float(leg["strike"])
        side = leg["side"]
        row = _chain_row_for(rows, strike, side, _leg_expiry(leg))
        px = _chain_quote_mid(row)
        if px is None:
            iv = float(row.iv) if (row is not None and row.iv and row.iv > 0) else DEFAULT_IV
            px = bs_intraday(spot, strike, _leg_t_to_expiry(leg, now), rate, iv, side)
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
    resp = _fold_commission(resp, _commission_side(trade))
    return float(resp.unrealized_pnl)


def _commission_side(trade: Trade) -> float:
    # TOTAL contracts across all legs (per contract per leg) — matches
    # journal._position_commission_side. A 4-leg condor at 1 contract = 4×fee.
    # per_contract_fee = commission + regulatory/exchange fee, per side.
    contracts = sum(int(leg.get("contracts", 1) or 1) for leg in trade.legs)
    return contracts * settings.per_contract_fee


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


# Short-volatility, delta-neutral structures lose on a big move in EITHER
# direction, so a single underlying stop level must protect BOTH sides.
_SHORT_VOL_STRATEGIES = {
    "short_straddle", "short_strangle", "iron_condor", "iron_butterfly",
}


def _bracket_band_triggered(entry_underlying: float, level: float | None, spot: float) -> bool:
    """Two-sided (distance-band) stop for a short-vol structure: fire when the
    underlying has moved AT LEAST |level − entry| away from entry in EITHER
    direction. A directional level on a short straddle/strangle/condor silently
    ignored an equally large adverse move the other way."""
    if level is None:
        return False
    return abs(spot - entry_underlying) >= abs(level - entry_underlying)


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


# --- expiry settlement ------------------------------------------------------


def _leg_expiry(leg: dict) -> date | None:
    raw = leg.get("expiry")
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _latest_leg_expiry(trade: Trade) -> date | None:
    """The LAST expiry across all legs. Settlement waits for this so a
    multi-expiry structure (calendar/diagonal) isn't force-closed while a
    longer-dated leg is still live."""
    expiries = [e for e in (_leg_expiry(leg) for leg in trade.legs) if e is not None]
    return max(expiries) if expiries else None


def _working_contract_expired(trade: Trade, now: datetime) -> bool:
    """True when every leg of a working order is past its expiry's session
    close — the contract no longer exists, so the resting order can never
    legitimately fill. In a 0DTE product a GTC order (the ticket default)
    otherwise outlives its contract: it can 'fill' next session at the model's
    60s-floor price of a dead contract and permanently eat the scaling cap
    (working orders count against the open-contracts aggregate)."""
    expiry = _latest_leg_expiry(trade)
    if expiry is None:
        return False
    return now.astimezone(_ET) >= _session_close_for_date(expiry)


def cancel_expired_working_orders(session_factory=None, *, now: datetime) -> int:
    """Cancel every WORKING order whose contract has expired (see
    `_working_contract_expired`), regardless of time-in-force. Runs in the
    market-CLOSED branch of the monitor alongside expiry settlement; the
    in-session pass applies the same test per order. Idempotent — a cancelled
    order drops out of the working query. Returns the number cancelled."""
    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    session = session_factory()
    cancelled = 0
    try:
        orders = (
            session.execute(select(Trade).where(Trade.status == "working"))
            .scalars()
            .all()
        )
        for trade in orders:
            try:
                if not _working_contract_expired(trade, now):
                    continue
                trade.status = "cancelled"
                trade.close_reason = None
                trade.notes = (trade.notes or "") + " · expired contract"
                session.commit()
                cancelled += 1
            except Exception:  # noqa: BLE001 — isolate one bad order from the rest
                session.rollback()
                log.exception("order_monitor: expired-contract cancel %s failed", trade.id)
        return cancelled
    finally:
        session.close()


def _settlement_unrealized_for(trade: Trade, settle_spot: float) -> float:
    """Folded unrealized P&L at EXPIRY INTRINSIC — same convention as
    `_default_unrealized_for` (entry-side commission folded in), so `_book_close`
    books the same shape of number it does for a manual / bracket close.

    At expiry every option is worth exactly its intrinsic value: max(S-K,0) for
    a call, max(K-S,0) for a put. P&L is intrinsic vs the entry premium, ×100,
    summed signed across legs (long +, short −), less the entry commission."""
    gross = 0.0
    for leg in trade.legs:
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        contracts = int(leg.get("contracts", 1) or 1)
        strike = float(leg["strike"])
        entry = float(leg.get("entry_price", 0.0) or 0.0)
        if leg.get("side") == "call":
            intrinsic = max(settle_spot - strike, 0.0)
        else:
            intrinsic = max(strike - settle_spot, 0.0)
        gross += sign * contracts * (intrinsic - entry) * 100.0
    return gross - _commission_side(trade)


def settle_expired_positions(
    session_factory=None, *, now: datetime, spot_for=None
) -> int:
    """Book every OPEN position whose options have ALL expired to their
    settlement INTRINSIC value at the 4pm ET close (or the half-day close),
    exactly once. This is the simulated analog of cash settlement /
    exercise-assignment: an expired option ceases to exist, so its win/loss
    must be REALIZED — not left marking as a phantom live position forever
    (which silently corrupts combine balance, the MLL/DLL floors, and the
    scaling-cap budget).

    Invoked from the market-CLOSED branch of `run_order_monitor` (the bell has
    rung; the fill/bracket pass is dormant), and independently re-checks
    `now_et >= session_close(latest_leg_expiry)` so a not-yet-expired multi-day
    position is never touched. Idempotent — a settled trade becomes
    status='closed' and drops out of the open query on the next tick. The
    settlement spot is recorded as exit_underlying_price so a later view can't
    re-mark the (now closed) position at a drifted live price. Returns the
    number of positions settled."""
    spot_for = spot_for or _default_spot_for
    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    from services.copy_trade import mirror_close

    now_et = now.astimezone(_ET)
    session = session_factory()
    settled = 0
    spot_cache: dict[str, float | None] = {}
    try:
        trades = (
            session.execute(select(Trade).where(Trade.status == "open"))
            .scalars()
            .all()
        )
        for trade in trades:
            try:
                expiry = _latest_leg_expiry(trade)
                if expiry is None or now_et < _session_close_for_date(expiry):
                    continue  # no expiry data, or the last leg hasn't expired
                # Settle against the 4pm print: the live spot if the feed is
                # warm, else the last-known-good fallback. No price ⇒ defer to a
                # later tick (never fabricate a settlement value).
                spot = _liquidation_spot(trade.symbol, spot_for, now, spot_cache)
                if spot is None:
                    log.warning(
                        "settlement: no spot for %s (trade %s) — deferring",
                        trade.symbol, trade.id,
                    )
                    continue
                _book_close(trade, spot, now, _settlement_unrealized_for, "expiry")
                trade.notes = (trade.notes or "") + " · settled at expiry"
                session.commit()
                mirror_close(session, trade)  # cascade to follower copies
                settled += 1
            except Exception:  # noqa: BLE001 — isolate one bad trade from the rest
                session.rollback()
                log.exception("settlement: trade %s failed", trade.id)
        return settled
    finally:
        session.close()


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
        # The fill/bracket pass is dormant out of session, but expiration is a
        # wall-clock event — settle anything that expired at/after the bell and
        # cancel working orders resting on now-dead contracts (GTC zombies).
        settled = settle_expired_positions(session_factory, now=now, spot_for=spot_for)
        expired = cancel_expired_working_orders(session_factory, now=now)
        return {
            "filled": 0,
            "closed": 0,
            "cancelled": expired,
            "settled": settled,
            "skipped": "market_closed",
        }

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
            # A working order on a dead contract is a zombie — cancel it before
            # any fill logic can price the corpse (no spot needed, so this runs
            # ahead of the spot fetch and survives a cold feed).
            if trade.status == "working" and _working_contract_expired(trade, now):
                trade.status = "cancelled"
                trade.close_reason = None
                trade.notes = (trade.notes or "") + " · expired contract"
                cancelled += 1
                session.commit()
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
                fetched = spot_for(trade.symbol)
                if fetched is not None:
                    # Warm the last-known-good store so a later auto-liquidation
                    # tick can fall back to this price across a brief feed gap.
                    _record_good_spot(trade.symbol, fetched, now)
                spot_cache[trade.symbol] = fetched
            spot = spot_cache[trade.symbol]
            if spot is None:
                continue
            try:
                if trade.status == "working":
                    # DAY time-in-force: a working order that survived unfilled
                    # into a later ET session is expired (the simulated analog of
                    # an exchange cancelling DAY orders at the close).
                    if (
                        trade.time_in_force == "day"
                        and trade.created_at is not None
                        and _et_date(trade.created_at) < _et_date(now)
                    ):
                        trade.status = "cancelled"
                        trade.close_reason = None
                        trade.notes = (trade.notes or "") + " · DAY order expired (unfilled)"
                        cancelled += 1
                        session.commit()
                        continue
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
            "settled": 0,  # in-session: nothing is past its expiry close
            "total": len(trades),
        }
    finally:
        session.close()


def _liquidation_spot(
    symbol: str, spot_for, now: datetime, spot_cache: dict[str, float | None]
) -> float | None:
    """Resolve the spot to PRICE a liquidation, preferring the live feed and
    falling back to the last-known-good price across a brief feed gap.

    Order of preference:
      1. A live spot already cached this tick (the main loop or an earlier
         position resolved it) — used as-is and recorded as last-known-good.
      2. A fresh live fetch — recorded as last-known-good.
      3. The last-known-good fallback IF it is fresh (age ≤ TTL) — logged with
         `liquidation_spot_age_seconds` so a stale-but-used price is visible.

    Returns None only when there is no live price AND no fresh fallback, in
    which case the caller SKIPS the combine (no liquidation on partial info)."""
    cached = spot_cache.get(symbol)
    if cached is not None:
        _record_good_spot(symbol, cached, now)
        return cached

    fetched = spot_for(symbol)
    if fetched is not None:
        _record_good_spot(symbol, fetched, now)
        spot_cache[symbol] = fetched
        return fetched

    # Live feed is cold for this symbol — try the last-known-good fallback.
    fallback, age = _fallback_spot(symbol, now)
    if fallback is not None:
        log.warning(
            "order_monitor: liquidation using last-known-good spot for %s "
            "(liquidation_spot_age_seconds=%.1f, spot=%.4f)",
            symbol,
            age if age is not None else -1.0,
            fallback,
        )
        spot_cache[symbol] = fallback
        return fallback

    if age is not None:
        # A fallback existed but was too stale to trust — log why we skip.
        log.warning(
            "order_monitor: liquidation fallback for %s is stale "
            "(liquidation_spot_age_seconds=%.1f > %.1f) — skipping",
            symbol,
            age,
            _SPOT_FALLBACK_TTL_SECONDS,
        )
    spot_cache[symbol] = None
    return None


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
                spot = _liquidation_spot(t.symbol, spot_for, now, spot_cache)
                if spot is None:
                    # No live price AND no fresh fallback — can't price the book
                    # this tick. Don't liquidate on partial info (overshoot is
                    # bounded by the fallback when one exists; here it doesn't).
                    usable = False
                    break
                unreal = unrealized_for(t, spot)
                marks[t.id] = (spot, unreal)
                urpl += unreal
            if not usable:
                continue

            snap = combine_snapshot(session, combine)
            # DLL branch active unless the owner disabled it (Step 3 toggle).
            dll_active = _combine_dll_enabled(session, combine)

            # DLL DAY-LOCK FLATTEN (Topstep semantics: DLL hit → flatten +
            # lock). Once the REALIZED day-loss alone exhausts the budget the
            # combine is day-locked and `_breaches_floor`'s DLL branch goes
            # dead for the rest of the day (it only fires while realized is
            # under budget) — leaving the open book to bleed down to the MLL.
            # Flatten everything the moment the lock engages instead.
            if dll_active and snap.day_locked:
                from services.combine_state import record_event

                realized_base = snap.balance
                for t in positions:
                    spot, _unreal = marks[t.id]
                    prior_realized = t.realized_pnl or 0.0
                    _book_close(t, spot, now, unrealized_for, "liquidation")
                    t.notes = (
                        (t.notes or "")
                        + " · auto-liquidated (daily loss limit hit — day-locked)"
                    )
                    session.flush()
                    mirror_close(session, t)
                    liquidated += 1
                    realized_base += (t.realized_pnl or 0.0) - prior_realized
                if realized_base <= snap.mll and combine.outcome in ("active", "passed"):
                    # The flatten locked in losses through the permanent floor.
                    combine.outcome = "failed"
                    record_event(
                        session, combine, "failed", "Auto-liquidated — MLL floor breached."
                    )
                else:
                    record_event(
                        session,
                        combine,
                        "liquidated",
                        f"Day-lock flatten — daily loss limit hit; closed "
                        f"{len(positions)} open position"
                        f"{'s' if len(positions) != 1 else ''}.",
                    )
                session.commit()
                continue

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
            # passed → failed is a legal terminal transition: a FUNDED account
            # that liquidates through its floor is terminated, not immortal.
            if still_breached and combine.outcome in ("active", "passed"):
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
        # Only the OPEN book's loss should TRIGGER a DLL liquidation. If the
        # already-REALIZED day-loss (snap.dll_used, fixed for the pass) alone
        # meets the budget, the combine is day-LOCKED — the soft-gate blocks new
        # opens, but force-closing the existing open book (which may be WINNERS,
        # and whose closure can't reduce the realized day-loss) is wrong. So the
        # DLL only fires while the realized portion is still under budget and the
        # open loss pushes it over.
        live_dll_used = snap.dll_used + max(0.0, -open_urpl)
        if snap.dll_used < snap.dll_budget and live_dll_used >= snap.dll_budget:
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
    from services.copy_trade import mirror_cancel

    # Don't fill into a non-tradeable combine — cancel the resting order.
    combine = session.get(Combine, trade.combine_id) if trade.combine_id else None
    if combine is not None:
        snap = combine_snapshot(session, combine)
        if snap.outcome == "failed" or snap.day_locked:
            trade.status = "cancelled"
            trade.close_reason = None
            trade.notes = (trade.notes or "") + " · cancelled (combine not tradeable)"
            # Cascade to follower copies — same as the manual /cancel endpoint.
            mirror_cancel(session, trade)
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
    from services.copy_trade import mirror_cancel

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
        # Cascade to follower copies — a lead OCO cancel must pull the
        # mirrored siblings too (the manual /cancel endpoint already does).
        mirror_cancel(session, s)
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
    # ACCUMULATE onto any realized already booked by prior scale-outs (a partial
    # close reduces the legs and adds its slice to realized_pnl). The recompute
    # above covers only the REMAINING contracts, so a bare assignment would
    # discard every booked scale-out slice. None/0 for a never-scaled position.
    trade.realized_pnl = round((trade.realized_pnl or 0.0) + realized, 2)


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
    # A short-vol structure's stop is two-sided (a big move EITHER way is the
    # loss); every other strategy keeps the directional level.
    short_vol = (trade.strategy or "") in _SHORT_VOL_STRATEGIES
    sl_triggered = (
        _bracket_band_triggered(entry_u, trade.stop_loss, spot)
        if short_vol
        else _bracket_triggered(entry_u, trade.stop_loss, spot)
    )
    reason: str | None = None
    if sl_triggered:
        reason = "stop_loss"
    elif _bracket_triggered(entry_u, trade.take_profit, spot):
        reason = "take_profit"
    if reason is None:
        return False

    _book_close(trade, spot, now, unrealized_for, reason)
    # OCO: a bracket close cancels any resting siblings in the group.
    _cancel_oco_siblings(session, trade)
    return True
