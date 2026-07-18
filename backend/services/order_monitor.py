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

  1. WORKING limit/stop orders → fill when the trigger is reached. With a
     live two-sided quote the trigger fires off the TOUCH (a buy limit when
     the ASK ≤ limit; stops on the adverse side) and the fill CROSSES THE
     SPREAD via services.fills (capped at the limit for limit orders); the
     mid-mark rule (limit fills AT the limit; stop at the current mark) is
     the fallback. Multi-leg NET-premium limits fill when the structure's
     per-1x net satisfies the signed limit. Stop-limit rests as a limit once
     the stop arms. Trailing stops track a favorable-mark high-water and
     recompute the trigger every tick. If the owning combine isn't tradeable
     (failed / day-locked), the order is cancelled instead of filled. Fills
     and closes commit via CONDITIONAL UPDATEs (status guards) so a user
     cancel/close landing in the pricing window is never overwritten.
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

import dataclasses
import logging
from datetime import date, datetime, time, timedelta, timezone
from math import gcd
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from config import settings
from models.trade import Trade
from schemas.journal import compute_net_debit_credit
from services import fills, platform_state

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


def _leg_model_price(rows, leg: dict, spot: float, now: datetime, rate: float) -> float:
    """Per-share MID price for ONE leg: the live option-chain quote mid for its
    exact strike/expiry/side when available (faithful — no model), else a
    Black-Scholes price at THE LEG'S OWN expiry (half-day aware) using the
    contract's live chain IV when present, else the DEFAULT_IV."""
    from calculations.intraday_analytics import bs_intraday
    from calculations.position_analytics import DEFAULT_IV

    strike = float(leg["strike"])
    side = leg["side"]
    row = _chain_row_for(rows, strike, side, _leg_expiry(leg))
    px = _chain_quote_mid(row)
    if px is None:
        iv = float(row.iv) if (row is not None and row.iv and row.iv > 0) else DEFAULT_IV
        px = bs_intraday(spot, strike, _leg_t_to_expiry(leg, now), rate, iv, side)
    return px


def _default_option_mark(trade: Trade, spot: float, now: datetime) -> float:
    """Signed, contracts-scaled per-share position mark (Σ sign·contracts·px)
    for working-order triggers and trailing stops.

    Prices each leg via `_leg_model_price` — the live chain mid when available,
    else a Black-Scholes fallback at the leg's own expiry. This replaces the
    old behaviour — a flat 30% IV at *today's* close for every leg — which
    fabricated stop fills and mispriced any future-expiry position as if it
    expired today."""
    rate = _rate()
    rows = _option_chain_rows(trade.symbol)
    total = 0.0
    for leg in trade.legs:
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        contracts = int(leg.get("contracts", 1) or 1)
        total += sign * contracts * _leg_model_price(rows, leg, spot, now, rate)
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


def _process_trailing_stop(
    session, trade: Trade, mark: float, spot: float, now: datetime, unrealized_for
) -> bool:
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

    if not _book_close(session, trade, spot, now, unrealized_for, "stop_loss"):
        return False  # closed concurrently — never double-book
    trade.notes = (trade.notes or "") + " · trailing stop hit"
    return True


# --- premium-denominated TP/SL (Tastytrade "manage winners") -----------------


def _has_premium_exit(trade: Trade) -> bool:
    return trade.tp_premium_mult is not None or trade.sl_premium_mult is not None


def _entry_net_premium(trade: Trade) -> float:
    """Signed, contracts-scaled NET entry premium (Σ sign·contracts·entry_price)
    — the same shape as `_default_option_mark`'s live value, so the premium
    TP/SL ratio test compares like with like (the contracts scale cancels in
    the ratio, making it equivalent to a per-contract comparison). Positive =
    net debit (long premium), negative = net credit (short premium)."""
    total = 0.0
    for leg in trade.legs:
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        contracts = int(leg.get("contracts", 1) or 1)
        total += sign * contracts * float(leg.get("entry_price", 0.0) or 0.0)
    return total


def _premium_exit_reason(trade: Trade, mark_net: float) -> tuple[str | None, str | None]:
    """Premium TP/SL trigger test. entry = |net entry premium|, mark = |net
    live premium| (both signed and contracts-scaled).

      NET-DEBIT (long premium):   TP when mark ≥ entry × tp_premium_mult,
                                  SL when mark ≤ entry × sl_premium_mult.
      NET-CREDIT (short premium): the semantics INVERT — tp_premium_mult is
        the FRACTION of the credit to buy back at (0.5 = close at 50% of max
        profit) → TP when mark ≤ entry × tp; sl_premium_mult is the cut
        multiple (2.0 = stop at 2× the credit) → SL when mark ≥ entry × sl.

    Returns (close_reason, note) or (None, None). The open endpoints validate
    the mults per direction, so TP and SL can never both be true on one tick."""
    entry_net = _entry_net_premium(trade)
    if entry_net == 0.0:
        return None, None  # zero-net-premium structure: no scale to multiply
    entry = abs(entry_net)
    mark = abs(mark_net)
    tp = trade.tp_premium_mult
    sl = trade.sl_premium_mult
    if entry_net > 0:  # net debit (long premium)
        if tp is not None and mark >= entry * tp:
            return "take_profit", f"premium target {tp:g}×"
        if sl is not None and mark <= entry * sl:
            return "stop_loss", f"premium stop {sl:g}×"
    else:  # net credit (short premium)
        if tp is not None and mark <= entry * tp:
            return "take_profit", f"premium target {tp:g}× credit"
        if sl is not None and mark >= entry * sl:
            return "stop_loss", f"premium stop {sl:g}×"
    return None, None


# --- resting close-limit (take-profit limit on the net premium) --------------


def _has_close_limit(trade: Trade) -> bool:
    return trade.close_limit_price is not None


def _structure_base(trade: Trade) -> int:
    """Base size of the structure = gcd of the leg quantities (contracts =
    ratio × base at placement) — the same reduction _process_working_multi
    uses, so close_limit_price and the entry net limit share one unit:
    signed net premium per 1× structure."""
    base = 0
    for leg in trade.legs:
        base = gcd(base, max(1, int(leg.get("contracts", 1) or 1)))
    return max(1, base)


def _close_limit_triggered(trade: Trade, mark_net: float) -> bool:
    """Uniform trigger for a resting close order: the live signed net per 1×
    has risen to the limit. A long structure (positive net) closes when its
    value reaches the target; a short structure (negative net) buys back when
    the premium has decayed so its negative net climbs to the limit
    (-0.30 = 'pay at most 0.30'). One rule covers both: net_1x ≥ limit —
    the mirror image of the entry limit's net_1x ≤ limit."""
    limit = trade.close_limit_price
    if limit is None:
        return False
    return (mark_net / _structure_base(trade)) >= float(limit)


def _process_close_limit(
    session, trade: Trade, spot: float, now: datetime, option_mark
) -> bool:
    """Fill a resting close-limit on an open position. Returns True if closed.

    Trigger: mid-based net mark (same machinery as the premium exits), with a
    TOUCH upgrade for single legs — a live two-sided quote must show the
    executable side at the limit (sell-to-close fills when the BID reaches it,
    buy-to-close when the ASK falls to it), mid fallback on a cold feed.

    Booking: exit value is EXACTLY the limit (a limit never fills worse than
    its price) with NO spread friction — the resting order is the passive side
    of the market, unlike every other exit path which crosses the spread.
    Commission is still charged both sides. The placement endpoint refuses a
    marketable limit, so booking at the limit can't shortchange a fill that
    should have gone off better."""
    limit = trade.close_limit_price
    if limit is None:
        return False
    mark_net = option_mark(trade, spot)
    if not _close_limit_triggered(trade, mark_net):
        return False

    legs = trade.legs
    if len(legs) == 1:
        # Touch check on the CLOSING side: closing a long is a sell (bid must
        # reach the limit), closing a short is a buy (ask must fall to it).
        closing_action = "sell" if legs[0].get("action") == "buy" else "buy"
        quotes = fills.live_leg_quotes(trade.symbol, legs)
        leg_q = fills.leg_quote(quotes, legs[0])
        touched = fills.entry_touch_triggered(
            "limit", closing_action, abs(float(limit)), leg_q
        )
        if touched is False:
            return False  # two-sided quote exists but the touch isn't there yet

    # Exit value pinned AT the limit: unrealized = (limit×base − entry_net)×100
    # minus the entry-side commission — the same folding _default_unrealized_for
    # applies — so _book_close's exit-side commission completes the round trip.
    base = _structure_base(trade)
    entry_net = _entry_net_premium(trade)
    pinned = (float(limit) * base - entry_net) * 100.0 - _commission_side(trade)
    if not _book_close(
        session, trade, spot, now, lambda _t, _s: pinned, "limit", friction=0.0
    ):
        return False  # closed concurrently — never double-book
    trade.notes = (trade.notes or "") + f" · close limit {float(limit):g} filled"
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


def _daily_close_for_date(symbol: str, day: date) -> float | None:
    """The official daily-bar CLOSE for `symbol` on `day` (ET), or None. Used to
    settle a STALE expired position at the right day's print rather than a
    drifted live spot. Best-effort — any feed failure returns None."""
    try:
        from services.alpaca_client import get_bars

        bars = get_bars(symbol, "1D")
    except Exception:  # noqa: BLE001 — degraded feed → caller falls back
        return None
    if not bars:
        return None
    for b in bars:
        ts = getattr(b, "timestamp", None)
        if ts is not None and ts.astimezone(_ET).date() == day:
            close = getattr(b, "close", None)
            if close and float(close) > 0:
                return float(close)
    return None


def _settlement_spot(trade, expiry: date, now: datetime, spot_cache, spot_for):
    """Underlying to settle an expired position against.

    SAME-DAY expiry (settled right after the bell): the live/last-good spot ≈
    the 4pm print — reliable and used as before. A PAST-DATED expiry means the
    app was down across that day's close, so today's spot would corrupt
    intrinsic — settle at the expiry date's official daily CLOSE instead,
    falling back to the live spot only if that bar is unavailable."""
    if expiry >= now.astimezone(_ET).date():
        return _liquidation_spot(trade.symbol, spot_for, now, spot_cache)
    close = _daily_close_for_date(trade.symbol, expiry)
    if close is not None:
        return close
    log.warning(
        "settlement: no daily close for %s on %s — falling back to live spot "
        "(intrinsic may drift from the true expiry print)",
        trade.symbol, expiry,
    )
    return _liquidation_spot(trade.symbol, spot_for, now, spot_cache)


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
                # Settle against the EXPIRY DATE's 4pm print: the live/last-good
                # spot for a same-day expiry (≈ the print right after the bell),
                # or the expiry date's official daily close for a stale position
                # (downtime spanned that close). No price ⇒ defer to a later tick
                # (never fabricate a settlement value).
                spot = _settlement_spot(trade, expiry, now, spot_cache, spot_for)
                if spot is None:
                    log.warning(
                        "settlement: no spot for %s (trade %s) — deferring",
                        trade.symbol, trade.id,
                    )
                    continue
                prior_realized = trade.realized_pnl or 0.0
                if not _book_close(
                    session, trade, spot, now, _settlement_unrealized_for, "expiry"
                ):
                    continue  # closed concurrently — never settle twice
                trade.notes = (trade.notes or "") + " · settled at expiry"
                session.commit()
                # Cascade to follower copies, threading only the slice THIS close
                # booked (delta) so a scaled-out lead's earlier slices aren't
                # re-booked onto followers.
                mirror_close(
                    session, trade,
                    final_slice_pnl=(trade.realized_pnl or 0.0) - prior_realized,
                )
                settled += 1
            except Exception:  # noqa: BLE001 — isolate one bad trade from the rest
                session.rollback()
                log.exception("settlement: trade %s failed", trade.id)
        return settled
    finally:
        session.close()


# --- expiration-day close-out (policy flatten before the bell) ---------------


def expiry_closeout(session, now: datetime, spot_for, unrealized_for, spot_cache) -> int:
    """Force-flatten open positions inside the last `expiry_closeout_minutes`
    of their dying session, and pull working orders resting on those contracts.

    This is the prop-firm answer to assignment/pin risk on physically-settled
    ETF options: rather than model OCC auto-exercise (share delivery this sim
    can't hold), the desk closes 0DTE books ~10 minutes before the bell —
    matching how funded-account firms actually handle expiry. Half-day aware
    via the NYSE schedule. Every row (lead AND copy-follower) is processed
    independently — the conditional UPDATE in _book_close keeps that
    idempotent, and each follower books its own honest exit mark.

    Returns positions closed (cancelled working orders are counted by the
    caller through the row status, not the return value). 0 disables via
    config. Runs only in-session — past the close, expiry settlement owns
    the book."""
    minutes = float(settings.expiry_closeout_minutes)
    if minutes <= 0:
        return 0
    closed = 0
    now_et = now.astimezone(_ET)
    trades = (
        session.execute(select(Trade).where(Trade.status.in_(("working", "open"))))
        .scalars()
        .all()
    )
    for trade in trades:
        expiry = _latest_leg_expiry(trade)
        if expiry is None:
            continue
        close_et = _session_close_for_date(expiry)
        if now_et < close_et - timedelta(minutes=minutes) or now_et >= close_et:
            continue  # outside the close-out window (settlement owns post-close)
        try:
            if trade.status == "working":
                # A resting order on a dying contract can only fill into a book
                # this policy immediately flattens — pull it instead.
                claimed = session.execute(
                    update(Trade)
                    .where(Trade.id == trade.id, Trade.status == "working")
                    .values(status="cancelled")
                    .execution_options(synchronize_session=False)
                ).rowcount
                if claimed:
                    trade.status = "cancelled"
                    trade.close_reason = None
                    trade.notes = (trade.notes or "") + " · expiry close-out (order pulled)"
                session.commit()
                continue
            if trade.symbol not in spot_cache:
                fetched = spot_for(trade.symbol)
                if fetched is not None:
                    _record_good_spot(trade.symbol, fetched, now)
                spot_cache[trade.symbol] = fetched
            spot = spot_cache[trade.symbol]
            if spot is None:
                continue  # cold feed — retry next tick inside the window
            if _book_close(session, trade, spot, now, unrealized_for, "expiry_closeout"):
                trade.notes = (trade.notes or "") + " · expiry close-out (policy)"
                _cancel_oco_siblings(session, trade)
                closed += 1
            session.commit()
        except Exception:  # noqa: BLE001 — isolate one bad trade from the rest
            session.rollback()
            log.exception("expiry_closeout: trade %s failed", trade.id)
    return closed


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
        # EXPIRATION-DAY CLOSE-OUT runs FIRST: inside the policy window the
        # book is being flattened and dying-contract orders pulled, so the
        # fill/bracket pass below sees their final status and skips them.
        closeouts = expiry_closeout(session, now, spot_for, unrealized_for, spot_cache)
        closed += closeouts
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
            # Skip open positions with nothing to monitor (no SL/TP bracket,
            # no trailing stop, no premium-denominated TP/SL AND no resting
            # close-limit). Auto-liquidation still scans them below.
            if (
                trade.status == "open"
                and trade.stop_loss is None
                and trade.take_profit is None
                and not _has_trailing_stop(trade)
                and not _has_premium_exit(trade)
                and not _has_close_limit(trade)
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


def _flatten_book(
    session,
    positions,
    marks: dict[int, tuple[float, float]],
    now: datetime,
    unrealized_for,
    note: str,
    start_balance: float,
) -> float:
    """Force-close every position in `positions` at its cached mark — the
    day-lock flatten path: each close books through `_book_close`
    (close_reason "liquidation"), gets `note` appended, and cascades to
    follower copies via mirror_close. Returns the realized balance after all
    cuts (start_balance plus each close's booked slice) so the caller can run
    the MLL fail test. Caller owns the commit."""
    from services.copy_trade import mirror_close

    realized_base = start_balance
    for t in positions:
        spot, _unreal = marks[t.id]
        prior_realized = t.realized_pnl or 0.0
        if not _book_close(session, t, spot, now, unrealized_for, "liquidation"):
            continue  # closed concurrently — never double-book
        t.notes = (t.notes or "") + note
        session.flush()
        # Cascade threading only the slice THIS close booked (delta) so a
        # scaled-out lead's earlier slices aren't re-booked onto followers.
        mirror_close(session, t, final_slice_pnl=(t.realized_pnl or 0.0) - prior_realized)
        # Add the FULL post-close realized, not just this close's delta. A
        # position scaled out of earlier holds its booked slice(s) in
        # realized_pnl while still OPEN — so that slice is in neither
        # start_balance (closed-trades only) nor the delta. Adding the delta
        # dropped it, floating the flatten's realized balance above the true
        # figure and letting an MLL breach escape the fail test. Mirrors the
        # worst-first loop's `realized_base += t.realized_pnl`.
        realized_base += t.realized_pnl or 0.0
    return realized_base


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

            # SCALE-OUT REALIZED on the STILL-OPEN book. A partial close books
            # its slice onto trade.realized_pnl while the row stays status=open,
            # so that P&L is in neither snap.balance (closed-trades only) nor
            # `urpl` (which prices only the REMAINING contracts). Left out, a
            # trader could scale 99% out of a deep loser and the locked-in loss
            # would be invisible to this gate until the final close. Fold it in:
            #   - MLL floor tests against snap.balance + open_realized
            #   - the loss portion counts toward the day's DLL like any realized
            #     loss (gains don't reduce it — the loss-only DLL convention).
            open_realized = sum(float(t.realized_pnl or 0.0) for t in positions)
            balance_base = snap.balance + open_realized
            gate_snap = dataclasses.replace(
                snap, dll_used=snap.dll_used + max(0.0, -open_realized)
            )

            # DLL DAY-LOCK / PROFIT-LOCK FLATTEN (Topstep semantics: lock
            # engaged → flatten). Once the REALIZED day-loss alone exhausts
            # the blocking budget the combine is day-locked and
            # `_breaches_floor`'s DLL branch goes dead for the rest of the
            # day (it only fires while realized is under budget) — leaving
            # the open book to bleed down to the MLL. Flatten everything the
            # moment the lock engages instead. snap.day_locked also folds in
            # the personal profit-target lock (snap.profit_locked), which
            # flattens even with the DLL disabled.
            if (dll_active and snap.day_locked) or snap.profit_locked:
                from services.combine_state import record_event

                if snap.profit_locked:
                    note = " · auto-liquidated (profit target reached — day protected)"
                    lock_reason = "profit target reached"
                else:
                    note = " · auto-liquidated (daily loss limit hit — day-locked)"
                    lock_reason = "daily loss limit hit"
                realized_base = _flatten_book(
                    session, positions, marks, now, unrealized_for, note, snap.balance
                )
                liquidated += len(positions)
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
                        f"Day-lock flatten — {lock_reason}; closed "
                        f"{len(positions)} open position"
                        f"{'s' if len(positions) != 1 else ''}.",
                    )
                session.commit()
                continue

            if not _breaches_floor(gate_snap, balance_base, urpl, dll_active):
                # No FIRM floor breach this tick — evaluate the PERSONAL
                # (junior) triggers instead: the daily profit target and the
                # alert / liquidate DLL override modes. The firm tier-default
                # DLL and the MLL stay senior — when they fire (above/below),
                # personal triggers don't run.
                liquidated += _personal_triggers(
                    session, combine, snap, positions, marks, urpl,
                    dll_active, now, unrealized_for,
                )
                continue

            # The breach reason at pass start (MLL takes precedence — it's the
            # permanent floor). Tagged on every cut trade for a legible ledger.
            mll_breach = (balance_base + urpl) <= snap.mll
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
            #
            # It starts at balance_base (= snap.balance + the open book's already-
            # booked scale-out realized). Because that prior realized is already
            # in the base, each close adds only its DELTA — the realized booked by
            # THIS close of the remaining contracts — so a scale-out slice is
            # never double-counted.
            realized_base = balance_base
            remaining_urpl = urpl
            for t in ordered:
                spot, unreal = marks[t.id]
                prior_realized = float(t.realized_pnl or 0.0)
                if not _book_close(session, t, spot, now, unrealized_for, "liquidation"):
                    # Closed concurrently — its URPL already left the open book;
                    # the concurrent booking isn't ours to count.
                    remaining_urpl -= unreal
                    continue
                t.notes = (
                    (t.notes or "")
                    + f" · auto-liquidated worst-first ({reason_note})"
                )
                session.flush()
                mirror_close(session, t, final_slice_pnl=(t.realized_pnl or 0.0) - prior_realized)
                liquidated += 1
                realized_base += float(t.realized_pnl or 0.0) - prior_realized
                remaining_urpl -= unreal
                if not _breaches_floor(gate_snap, realized_base, remaining_urpl, dll_active):
                    break

            from services.combine_state import record_event

            # FAILED only if STILL breached after the worst-first pass — the cuts
            # couldn't bring the book back inside the floor (a single
            # catastrophic position, or every position underwater). If the cut
            # CLEARED the breach (e.g. a DLL breach where a net-winning remainder
            # survives), the combine stays ACTIVE and keeps those positions open.
            still_breached = _breaches_floor(
                gate_snap, realized_base, remaining_urpl, dll_active
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


def _personal_triggers(
    session,
    combine,
    snap,
    positions,
    marks: dict[int, tuple[float, float]],
    urpl: float,
    dll_active: bool,
    now: datetime,
    unrealized_for,
) -> int:
    """PERSONAL (junior) risk triggers for one combine — run only on a tick
    where no FIRM floor fired (the tier-default DLL day-lock, the live DLL
    budget, and the MLL are senior and handled in `_auto_liquidate`).

    1) Personal daily PROFIT target ("protect the green day"), on the same
       day-P&L basis as the live DLL test (today's realized + open URPL):
       lock=True → flatten + day-lock (combine.profit_locked_at stamped;
       lifts at the 5pm-PT boundary); lock=False → one event per trading day.
    2) Personal DLL override in "alert" / "liquidate" mode, on the live
       day-loss basis (realized day-loss + the loss-only open book):
       "alert" → one event per trading day, no flatten, no lock;
       "liquidate" → flatten (same close path as the day-lock flatten,
       cascading to followers) but NO day-lock — re-opens stay allowed.
       ("liquidate_block" is not handled here: it IS the blocking dll_budget,
       enforced by the day-lock flatten.)

    Returns the number of positions force-closed. Commits its own writes,
    mirroring _auto_liquidate's per-combine commit discipline."""
    from services.combine_state import event_recorded_today, record_event

    closed = 0

    # 1) Personal daily profit target.
    if snap.profit_target_amount is not None and not snap.profit_locked:
        day_pnl = snap.today_realized + urpl
        if day_pnl >= snap.profit_target_amount:
            if snap.profit_target_lock:
                _flatten_book(
                    session, positions, marks, now, unrealized_for,
                    " · auto-liquidated (profit target reached — day protected)",
                    snap.balance,
                )
                closed += len(positions)
                combine.profit_locked_at = now
                record_event(
                    session, combine, "profit_target",
                    "Profit target reached — day protected.",
                )
                session.commit()
                return closed
            if not event_recorded_today(session, combine.id, "profit_target", now):
                record_event(session, combine, "profit_target", "Profit target reached.")
                session.commit()
            # lock=False: nothing else happens — and a green day can't also
            # be at the personal loss limit, so falling through is safe.

    # 2) Personal DLL — alert / liquidate modes.
    if (
        dll_active
        and snap.personal_dll_amount is not None
        and snap.personal_dll_mode in ("alert", "liquidate")
    ):
        live_day_loss = snap.dll_used + max(0.0, -urpl)
        if live_day_loss >= snap.personal_dll_amount:
            if snap.personal_dll_mode == "alert":
                if not event_recorded_today(session, combine.id, "personal_dll", now):
                    record_event(
                        session, combine, "personal_dll",
                        "Personal daily loss limit hit — alert only.",
                    )
                    session.commit()
            else:  # "liquidate": flatten, but do NOT day-lock
                realized_base = _flatten_book(
                    session, positions, marks, now, unrealized_for,
                    " · auto-liquidated (personal daily loss limit hit — no day-lock)",
                    snap.balance,
                )
                closed += len(positions)
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
                        f"Personal daily loss limit hit — flattened {len(positions)}"
                        f" open position{'s' if len(positions) != 1 else ''};"
                        " trading stays open.",
                    )
                session.commit()
    return closed


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
    from models.user import User
    from services.combine_state import combine_snapshot
    from services.copy_trade import mirror_cancel

    # OPERATOR KILL SWITCH (risk controls, B5) — a working ENTRY filling is new
    # exposure, which both "halted" and "close_only" bar. SKIP the order rather
    # than cancel it: a temporary platform halt shouldn't destroy the user's
    # resting orders — they become fill-eligible again the moment the mode
    # clears. Exits (brackets, trailing/premium stops), liquidations and expiry
    # settlement never come through here, so they run in EVERY mode.
    if platform_state.get_trading_mode(session) != "normal":
        return None

    combine = session.get(Combine, trade.combine_id) if trade.combine_id else None

    # A SUSPENDED owner's resting entries likewise sit tight — the monitor-side
    # analog of the open endpoints' account_suspended 403 (skip, don't cancel:
    # an unsuspension restores them untouched).
    if combine is not None:
        owner = session.get(User, combine.user_id)
        if owner is not None and owner.suspended_at is not None:
            return None

    # Don't fill into a non-tradeable combine — cancel the resting order.
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

    # Multi-leg NET-premium limit order (/open-multi order_type="limit") —
    # triggered on the structure's signed per-1x net, not a per-share premium.
    if len(legs) > 1:
        return _process_working_multi(session, trade, spot, now, option_mark)

    action = legs[0].get("action", "buy")
    # option_mark returns the SIGNED, contracts-scaled position value
    # (Σ sign·contracts·px). Working-order triggers and the user's limit/stop
    # prices are PER-SHARE premium, so reduce to a positive per-share premium
    # before comparing. (Using the raw signed mark armed every SELL order on the
    # first tick — negative ≤ positive — and mis-scaled multi-contract orders.)
    total_contracts = max((int(leg.get("contracts", 1) or 1) for leg in legs), default=1)
    prem = abs(option_mark(trade, spot)) / max(1, total_contracts)

    # Live two-sided quote for the leg (best-effort — {} on any failure).
    # Triggers fire off the TOUCH when it exists: a resting order is executable
    # when the EXECUTABLE side reaches it, not when the mid does (the mid can
    # cross a buy limit while the offer never trades down to it). The mid rule
    # stays as the fallback so a cold feed never strands a working order.
    quotes = fills.live_leg_quotes(trade.symbol, legs)
    leg_q = fills.leg_quote(quotes, legs[0])

    # STOP-LIMIT — two phases. Phase 1: the order rests until the mark crosses
    # stop_price (stop semantics). Arming converts it into a plain LIMIT at
    # limit_price (persisted), so phase 2 (and every later tick) is a normal
    # limit fill. This deterministically reproduces "trigger at stop, then rest
    # as a limit": if the limit is already satisfied the same tick, it fills
    # immediately below; otherwise it waits as a limit.
    if trade.order_type == "stop_limit":
        stop_trigger = float(trade.stop_price) if trade.stop_price is not None else 0.0
        touched = fills.entry_touch_triggered("stop", action, stop_trigger, leg_q)
        armed = (
            touched
            if touched is not None
            else _entry_fill_triggered("stop", action, prem, stop_trigger)
        )
        if not armed:
            return None  # not yet armed
        # Arming mutates a WORKING order — claim it conditionally so a user
        # cancel landing in the pricing window above isn't overwritten.
        claimed = session.execute(
            update(Trade)
            .where(Trade.id == trade.id, Trade.status == "working")
            .values(order_type="limit")
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed == 0:
            session.expire(trade)
            return None  # cancelled during the pricing window
        trade.order_type = "limit"  # armed → now a resting limit at limit_price
        trade.notes = (trade.notes or "") + " · stop armed → limit"

    trigger = float(trade.limit_price) if trade.limit_price is not None else 0.0
    touched = fills.entry_touch_triggered(trade.order_type, action, trigger, leg_q)
    hit = (
        touched
        if touched is not None
        else _entry_fill_triggered(trade.order_type, action, prem, trigger)
    )
    if not hit:
        return None

    fill_px = _entry_fill_price(
        trade.order_type, action, trigger, prem, leg_q, total_contracts
    )
    return _commit_fill(session, trade, [fill_px], spot, now)


def _entry_fill_price(
    order_type: str, action: str, trigger: float, prem: float, leg_q, contracts: int
) -> float:
    """Fill price for a triggered working entry. With a live quote the fill
    CROSSES THE SPREAD (same machinery as the user-facing market opens) —
    capped at the limit for a limit order (a limit never fills worse than its
    price). Mid fallback keeps the legacy behavior: limit fills AT the limit,
    stop fills at the current per-share mark."""
    crossed = fills.pick_fill_price(leg_q, action, contracts) if leg_q is not None else 0.0
    if crossed > 0:
        if order_type == "limit":
            crossed = min(crossed, trigger) if action == "buy" else max(crossed, trigger)
        return max(0.01, round(crossed, 4))
    return trigger if order_type == "limit" else max(0.01, prem)


def _process_working_multi(
    session, trade: Trade, spot: float, now: datetime, option_mark
) -> str | None:
    """Fill a WORKING multi-leg NET-premium limit order.

    Trigger: the structure's live signed net per 1x (option_mark — the same
    leg-mark machinery the premium exits use — divided by the base size, i.e.
    the common factor of the leg quantities) must satisfy the SIGNED
    limit_price: net debit ≤ limit for a debit structure (limit > 0), net
    credit ≥ |limit| for a credit structure (limit < 0). Both reduce to
    `net_1x ≤ limit` with the debit-positive/credit-negative convention.

    Fill: each leg through the spread-crossing helper against its live quote;
    a leg without a quote fills at its mid mark (never strand the order on a
    partial feed)."""
    if trade.order_type != "limit" or trade.limit_price is None:
        return None
    legs = trade.legs
    # base size = the common factor of the leg quantities (contracts = ratio ×
    # base at placement), so mark/base is the per-1x-structure net premium.
    base = 0
    for leg in legs:
        base = gcd(base, max(1, int(leg.get("contracts", 1) or 1)))
    base = max(1, base)
    limit = float(trade.limit_price)
    net_1x = option_mark(trade, spot) / base
    if net_1x > limit:
        return None  # debit still too rich / credit still too thin

    quotes = fills.live_leg_quotes(trade.symbol, legs)
    # Resolve the chain + rate up front — needed for each leg's MID (the
    # frictionless model/chain mark, the same _leg_model_price option_mark uses
    # for the trigger) so we can cap the booked net at the limit.
    rows = _option_chain_rows(trade.symbol)
    rate = _rate()
    mids: list[float] = []       # frictionless per-leg mid (per share)
    crossed: list[float] = []    # spread-crossed per-leg fill (per share)
    sign_contracts: list[tuple[float, int]] = []
    for leg in legs:
        contracts = int(leg.get("contracts", 1) or 1)
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        mid = max(0.01, float(_leg_model_price(rows, leg, spot, now, rate)))
        leg_q = fills.leg_quote(quotes, leg)
        cx = (
            fills.pick_fill_price(leg_q, leg.get("action", "buy"), contracts)
            if leg_q is not None
            else 0.0
        )
        cx = mid if cx <= 0 else float(cx)   # no live quote → fill at the mid
        mids.append(mid)
        crossed.append(max(0.01, cx))
        sign_contracts.append((sign, contracts))

    # CAP THE BOOKED NET AT THE LIMIT. Crossing the spread pushes each leg
    # adversely (buys up, sells down), so the crossed net is always ≥ the mid
    # net that triggered — and can exceed the limit, filling the trader THROUGH
    # their own limit (a debit paid above limit / a credit collected below it).
    # The single-leg path caps at min(crossed, trigger); the multi-leg analog is
    # to land the booked net AT the limit: scale every leg's slippage back
    # toward its mid by one factor k so Σ sign·contracts·price / base == limit.
    def _net_1x(pl: list[float]) -> float:
        return sum(s * c * p for (s, c), p in zip(sign_contracts, pl)) / base

    crossed_net = _net_1x(crossed)
    if crossed_net > limit:
        mid_net = _net_1x(mids)          # ≤ limit (the trigger condition)
        denom = crossed_net - mid_net
        k = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, (limit - mid_net) / denom))
        prices = [max(0.01, round(m + k * (c - m), 4)) for m, c in zip(mids, crossed)]
    else:
        prices = [max(0.01, round(c, 4)) for c in crossed]
    return _commit_fill(session, trade, prices, spot, now)


def _commit_fill(
    session, trade: Trade, leg_prices: list[float], spot: float, now: datetime
) -> str | None:
    """Commit a working→open fill. The transition is a CONDITIONAL UPDATE
    (WHERE status='working') — the pricing above straddles a network window,
    and a user cancel that landed in it must WIN, not be silently overwritten
    by the fill. rowcount 0 → the order is no longer working; skip."""
    claimed = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, Trade.status == "working")
        .values(status="open")
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.expire(trade)
        return None  # cancelled (or otherwise decided) during the window
    legs = trade.legs
    for leg, px in zip(legs, leg_prices):
        leg["entry_price"] = round(float(px), 4)
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


def _book_close(
    session,
    trade: Trade,
    spot: float,
    now: datetime,
    unrealized_for,
    reason: str,
    *,
    friction: float | None = None,
) -> bool:
    """Book a close on `trade` exactly the way the manual CLOSE button does:
    realized = analytics unrealized − exit-side commission − spread-crossing
    exit friction (see fills.close_friction; liquidations stress the size
    term — a forced flatten is the most slippage-heavy fill there is; expiry
    settlement is cash-settled at intrinsic, so it pays no spread).

    The open→closed transition is a CONDITIONAL UPDATE (WHERE status='open'):
    the unrealized/friction resolution above straddles a network window, and a
    concurrent manual close / bracket / liquidation must not be double-booked
    (+= applied twice) or overwritten. Returns False when the claim is lost —
    the caller must skip its notes/cascade; True when this call booked the
    close. Mutates the trade in place on success; the caller owns the commit
    and any copy-trade cascade."""
    unrealized = unrealized_for(trade, spot)
    if friction is None:
        friction = (
            0.0
            if reason == "expiry"
            else fills.close_friction(
                trade.symbol, trade.legs, stressed=(reason == "liquidation")
            )
        )
    realized = unrealized - _commission_side(trade) - friction
    claimed = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, Trade.status == "open")
        .values(status="closed")
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.expire(trade)
        return False
    trade.status = "closed"
    trade.close_reason = reason
    trade.exit_date = now
    trade.exit_underlying_price = spot
    # ACCUMULATE onto any realized already booked by prior scale-outs (a partial
    # close reduces the legs and adds its slice to realized_pnl). The recompute
    # above covers only the REMAINING contracts, so a bare assignment would
    # discard every booked scale-out slice. None/0 for a never-scaled position.
    trade.realized_pnl = round((trade.realized_pnl or 0.0) + realized, 2)
    return True


def _process_open(
    session, trade: Trade, spot: float, now: datetime, unrealized_for, option_mark=None
) -> bool:
    """Close an open position if a fixed bracket (SL/TP on the underlying) or a
    trailing stop (on the favorable option mark) triggered. Returns True if
    closed. The trailing stop is checked first so its high-water advances every
    tick even on a tick where the fixed brackets don't fire."""
    if _has_trailing_stop(trade) and option_mark is not None:
        mark = option_mark(trade, spot)
        if _process_trailing_stop(session, trade, mark, spot, now, unrealized_for):
            _cancel_oco_siblings(session, trade)
            return True

    # Resting close-limit (take-profit at a price the trader named) — checked
    # ahead of the premium/bracket exits: when both a limit target and a
    # market-order exit would fire the same tick, the trader's named price wins.
    if _has_close_limit(trade) and option_mark is not None:
        if _process_close_limit(session, trade, spot, now, option_mark):
            _cancel_oco_siblings(session, trade)
            return True

    # Premium-denominated TP/SL (Tastytrade "manage winners") — tested on the
    # same live option mark the trailing stop uses. Coexists with the
    # underlying-price brackets below: whichever exit triggers first wins (the
    # trade is closed, the other becomes moot).
    if _has_premium_exit(trade) and option_mark is not None:
        reason, note = _premium_exit_reason(trade, option_mark(trade, spot))
        if reason is not None:
            if not _book_close(session, trade, spot, now, unrealized_for, reason):
                return False  # closed concurrently — never double-book
            trade.notes = (trade.notes or "") + f" · {note}"
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

    if not _book_close(session, trade, spot, now, unrealized_for, reason):
        return False  # closed concurrently — never double-book
    # OCO: a bracket close cancels any resting siblings in the group.
    _cancel_oco_siblings(session, trade)
    return True
