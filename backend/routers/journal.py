"""Trade Desk journal CRUD.

POST /api/journal/trades       — create
GET  /api/journal/trades       — list, filter by status / is_paper / symbol
GET  /api/journal/trades/{id}  — single
PATCH /api/journal/trades/{id} — update (typically: close)
DELETE /api/journal/trades/{id}

Validation is mostly handled by Pydantic at the schema layer; the router
enforces only the cross-field rules (expiry-in-future on open trades is
a warning header, strategy-leg-count mismatch is a warning header).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculations.journal_calendar import build_month, parse_month
from calculations.intraday_analytics import (
    SECONDS_PER_YEAR,
    bs_intraday,
    greeks_intraday,
    iv_intraday,
)
from calculations.position_analytics import (
    CONTRACT_MULTIPLIER,
    DEFAULT_IV,
    build_legs_from_journal,
    compute_analytics,
)
from database import get_session
from models.account_state import AccountState
from models.trade import Trade
from schemas.calendar_journal import (
    CalendarDayOut,
    CalendarMonthOut,
    CalendarWeekOut,
)
from schemas.journal import (
    AnalyticsGreeks,
    EXPECTED_LEG_COUNT,
    MISTAKE_TAG_VOCABULARY,
    TradeAnalyticsOut,
    TradeIn,
    TradeOut,
    TradeUpdate,
    TradesResponse,
    compute_net_debit_credit,
)
from services.alpaca_client import get_quotes
from services.cache import cache
from services.fred_client import latest_dgs3mo_rate

router = APIRouter(prefix="/api/journal", tags=["journal"])
log = logging.getLogger(__name__)


@router.post("/trades", response_model=TradeOut, status_code=201)
def create_trade(
    payload: TradeIn,
    response: Response,
    session: Session = Depends(get_session),
) -> TradeOut:
    warnings = _validate_soft(payload)
    if warnings:
        response.headers["X-Journal-Warnings"] = " | ".join(warnings)

    net = (
        payload.net_debit_credit
        if payload.net_debit_credit is not None
        else compute_net_debit_credit(payload.legs)
    )

    state = session.get(AccountState, 1)
    active_tier = state.active_tier if state else "50K"
    trade = Trade(
        symbol=payload.symbol,
        strategy=payload.strategy,
        entry_date=_as_utc(payload.entry_date),
        entry_underlying_price=payload.entry_underlying_price,
        net_debit_credit=net,
        status="open",
        is_paper=payload.is_paper,
        notes=payload.notes,
        confidence=payload.confidence,
        thesis=payload.thesis,
        planned_exit=payload.planned_exit,
        risk_amount=payload.risk_amount,
        screenshot_url=payload.screenshot_url,
        tier=active_tier,
    )
    trade.legs = [leg.model_dump(mode="json") for leg in payload.legs]
    trade.tags = list(payload.tags)
    trade.mistake_tags = []         # captured at close time, not entry
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return _to_out(trade)


@router.get("/trades", response_model=TradesResponse)
def list_trades(
    status: Literal["open", "closed"] | None = None,
    is_paper: bool | None = None,
    symbol: str | None = None,
    session: Session = Depends(get_session),
) -> TradesResponse:
    stmt = select(Trade).order_by(Trade.entry_date.desc(), Trade.id.desc())
    if status is not None:
        stmt = stmt.where(Trade.status == status)
    if is_paper is not None:
        stmt = stmt.where(Trade.is_paper == is_paper)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol.upper())
    rows = session.execute(stmt).scalars().all()
    return TradesResponse(trades=[_to_out(t) for t in rows])


@router.get("/trades/{trade_id}", response_model=TradeOut)
def get_trade(trade_id: int, session: Session = Depends(get_session)) -> TradeOut:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")
    return _to_out(trade)


@router.patch("/trades/{trade_id}", response_model=TradeOut)
def update_trade(
    trade_id: int,
    payload: TradeUpdate,
    session: Session = Depends(get_session),
) -> TradeOut:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")

    if payload.status is not None:
        trade.status = payload.status
    if payload.exit_date is not None:
        trade.exit_date = _as_utc(payload.exit_date)
    if payload.exit_underlying_price is not None:
        trade.exit_underlying_price = payload.exit_underlying_price
    if payload.realized_pnl is not None:
        trade.realized_pnl = payload.realized_pnl
    if payload.notes is not None:
        trade.notes = payload.notes
    if payload.mistake_tags is not None:
        trade.mistake_tags = list(payload.mistake_tags)
    if payload.review_note is not None:
        trade.review_note = payload.review_note

    session.commit()
    session.refresh(trade)
    return _to_out(trade)


@router.get("/calendar", response_model=CalendarMonthOut)
def get_calendar(
    month: str | None = None,
    is_paper: bool | None = None,
    session: Session = Depends(get_session),
) -> CalendarMonthOut:
    """Monthly P&L calendar grid. Buckets closed trades by exit_date.

    `month` is "YYYY-MM"; malformed or omitted falls back to today's
    month. `is_paper` mirrors the trade-list filter so the journal page
    can flip paper/live without re-rendering the trade list separately.
    """
    target = parse_month(month)

    stmt = select(Trade).where(Trade.status == "closed")
    if is_paper is not None:
        stmt = stmt.where(Trade.is_paper == is_paper)
    trades = session.execute(stmt).scalars().all()

    grid = build_month(trades, target)
    return CalendarMonthOut(
        month=grid.month,
        label=grid.label,
        weeks=[
            CalendarWeekOut(
                week_of_month=w.week_of_month,
                days=[
                    CalendarDayOut(
                        date=d.date,
                        in_month=d.in_month,
                        realized_pnl=d.realized_pnl,
                        trade_count=d.trade_count,
                        trade_ids=d.trade_ids,
                        is_today=d.is_today,
                    )
                    for d in w.days
                ],
                realized_pnl=w.realized_pnl,
                trade_count=w.trade_count,
            )
            for w in grid.weeks
        ],
        realized_pnl=grid.realized_pnl,
        trade_count=grid.trade_count,
    )


@router.get("/vocab/mistakes")
def mistake_vocab() -> dict[str, list[str]]:
    """Suggestion set for the close-position mistake-tag picker.

    Frontend treats this as autocomplete suggestions, not a closed set —
    custom mistake-tag strings can still be saved against a trade."""
    return {"tags": list(MISTAKE_TAG_VOCABULARY)}


@router.get("/trades/{trade_id}/analytics", response_model=TradeAnalyticsOut)
def get_trade_analytics(
    trade_id: int,
    dte_override: int | None = Query(default=None, ge=0, le=3650),
    elapsed_hours: float | None = Query(default=None, ge=0, le=48),
    session: Session = Depends(get_session),
) -> TradeAnalyticsOut:
    """Position analytics at current state (or at a scrubbed point in time).

    Two scrubber paths:
      * `dte_override` — integer days remaining; the multi-day path.
      * `elapsed_hours` — fractional hours since entry; only honored for
        0DTE positions (nearest-leg expiry == today). Walks BS at sub-day
        T via the intraday helpers.

    Cached per (trade_id, dte_override, elapsed_hours bucket) for a short
    TTL. The intraday branch uses a 1-second bucket so live polling stays
    responsive; the day branch keeps its 15s TTL."""
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")

    # Determine which branch to use BEFORE fetching live data so the
    # cache key reflects it. 0DTE positions ALWAYS use the intraday
    # path; when no elapsed_hours is passed, the branch computes elapsed
    # from wall clock so a freshly-opened position picks up live theta.
    is_intraday = _trade_is_zerodte(trade)
    elapsed_bucket = (
        round(elapsed_hours, 2) if elapsed_hours is not None and is_intraday else None
    )
    # Include the trade's updated_at (microsecond precision) AND the
    # entry_date in the cache key. SQLite reuses primary keys after
    # DELETE, so the same `trade_id` may legitimately point at a new
    # row — without this disambiguation the previous trade's analytics
    # would be served. Microsecond precision avoids collisions when a
    # delete + recreate happens within the same wall-clock second.
    updated_us = (
        trade.updated_at.timestamp() if trade.updated_at else 0.0
    )
    entry_stamp = (
        trade.entry_date.timestamp() if trade.entry_date else 0.0
    )
    cache_key = (
        f"trade_analytics:{trade_id}:{updated_us}:{entry_stamp}:"
        f"{dte_override}:{'INT' if is_intraday else 'DAY'}:{elapsed_bucket}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Current underlying spot — prefer live quote, fall back to entry
    # price so analytics still render when the market data feed is cold
    # (e.g. nights / weekends in the demo).
    quote = None
    try:
        quote = get_quotes([trade.symbol]).get(trade.symbol)
    except Exception:  # noqa: BLE001
        log.exception("analytics: quote fetch failed for %s", trade.symbol)
    spot = quote.price if quote is not None else trade.entry_underlying_price

    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = 0.045  # ~3M T-bill rate; safe fallback for the demo

    if is_intraday:
        # If no override is provided, derive elapsed from wall clock so
        # freshly-opened positions show live theta from the first tick.
        effective_elapsed = elapsed_hours
        if effective_elapsed is None:
            entry_dt = trade.entry_date if trade.entry_date else datetime.now(timezone.utc)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            wall = (datetime.now(timezone.utc) - entry_dt).total_seconds()
            effective_elapsed = max(0.0, wall / 3600.0)
        response = _intraday_analytics(
            trade=trade, spot=spot, rate=rate, elapsed_hours=effective_elapsed
        )
        # Short TTL for live polling — the chart hits this every 5s.
        cache.set(cache_key, response, ttl_seconds=3)
        return response

    today = datetime.now(timezone.utc).date()
    entry_date = trade.entry_date.date() if trade.entry_date else today

    legs_now, iv_used, iv_source = build_legs_from_journal(
        trade.legs,
        today=today,
        rate=rate,
        spot_at_entry=trade.entry_underlying_price,
        entry_date=entry_date,
    )
    if not legs_now:
        raise HTTPException(500, f"trade {trade_id} has no usable legs")

    result = compute_analytics(
        legs_now,
        spot=spot,
        rate=rate,
        scrubber_dte_days=dte_override,
        iv_used=iv_used,
        iv_source=iv_source,
    )

    response = TradeAnalyticsOut(
        trade_id=trade_id,
        symbol=trade.symbol,
        spot=spot,
        rate=rate,
        current_dte_days=result.current_dte_days,
        scrubber_dte_days=result.scrubber_dte_days,
        iv_used=result.iv_used,
        iv_source=result.iv_source,  # type: ignore[arg-type]
        prices=result.prices,
        payoff_expiration=result.payoff_expiration,
        payoff_today=result.payoff_today,
        breakevens_expiration=result.breakevens_expiration,
        breakevens_today=result.breakevens_today,
        entry_underlying_price=trade.entry_underlying_price,
        entry_date=trade.entry_date,
        cost_basis=result.cost_basis,
        current_value=result.current_value,
        unrealized_pnl=result.unrealized_pnl,
        max_profit=result.max_profit,
        max_loss=result.max_loss,
        unlimited_gain=result.unlimited_gain,
        unlimited_loss=result.unlimited_loss,
        greeks=AnalyticsGreeks(**result.greeks),
    )
    cache.set(cache_key, response, ttl_seconds=15)
    return response


@router.delete("/trades/{trade_id}", status_code=204)
def delete_trade(trade_id: int, session: Session = Depends(get_session)) -> None:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")
    session.delete(trade)
    session.commit()


# -- internals --------------------------------------------------------------


def _validate_soft(payload: TradeIn) -> list[str]:
    """Return non-blocking warnings — surfaced via X-Journal-Warnings."""
    warnings: list[str] = []
    expected = EXPECTED_LEG_COUNT.get(payload.strategy)
    if expected is not None and len(payload.legs) != expected:
        warnings.append(
            f"{payload.strategy} usually has {expected} legs; received {len(payload.legs)}"
        )
    today = datetime.now(timezone.utc).date()
    past = [leg for leg in payload.legs if leg.expiry < today]
    if past:
        warnings.append(f"{len(past)} leg(s) have past expiry")
    return warnings


def _as_utc(dt: datetime) -> datetime:
    """Ensure tz-aware UTC. Naive datetimes from the client get assumed-UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_ET = ZoneInfo("America/New_York")
# 4:00pm ET equity-options close — matches the convention used by
# routers/zerodte.py for the session clock.
_CLOSE_HHMM = (16, 0)


def _trade_is_zerodte(trade: Trade) -> bool:
    """True when the trade's nearest-leg expiry is today (ET). 0DTE
    positions use the intraday-T analytics branch rather than the
    integer-day path."""
    if not trade.legs:
        return False
    today_et = datetime.now(_ET).date()
    for leg in trade.legs:
        expiry_raw = leg.get("expiry")
        try:
            expiry = date.fromisoformat(str(expiry_raw))
        except (TypeError, ValueError):
            continue
        if expiry == today_et:
            return True
    return False


def _intraday_analytics(
    *, trade: Trade, spot: float, rate: float, elapsed_hours: float
) -> TradeAnalyticsOut:
    """Build a TradeAnalyticsOut for a 0DTE position at `elapsed_hours`
    after entry. Mirrors the shape that compute_analytics() returns but
    uses the sub-day-floored Black-Scholes from intraday_analytics."""
    legs = list(trade.legs or [])
    if not legs:
        raise HTTPException(500, f"trade {trade.id} has no usable legs")

    # Times: entry → expiry (today's 4pm ET).
    entry_dt = trade.entry_date if trade.entry_date else datetime.now(timezone.utc)
    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
    entry_et = entry_dt.astimezone(_ET)

    # All legs share the same expiry on a 0DTE straddle. Take the first.
    expiry_raw = legs[0].get("expiry")
    try:
        expiry_d = date.fromisoformat(str(expiry_raw))
    except (TypeError, ValueError):
        expiry_d = datetime.now(_ET).date()
    expiry_dt = datetime.combine(expiry_d, time(*_CLOSE_HHMM), tzinfo=_ET)

    total_seconds = max(60.0, (expiry_dt - entry_et).total_seconds())
    t_at_entry = total_seconds / SECONDS_PER_YEAR
    elapsed_seconds = max(0.0, elapsed_hours * 3600)
    remaining_seconds = max(60.0, total_seconds - elapsed_seconds)
    t_now = remaining_seconds / SECONDS_PER_YEAR

    # Back-solve IV from each leg's entry price; median is robust to one
    # noisy leg. Same defensive pattern as build_legs_from_journal.
    iv_candidates: list[float] = []
    for leg in legs:
        side = str(leg.get("side", "")).lower()
        if side not in ("call", "put"):
            continue
        entry_price = float(leg.get("entry_price", 0.0))
        strike = float(leg.get("strike", 0.0))
        if entry_price <= 0 or strike <= 0:
            continue
        iv = iv_intraday(
            entry_price,
            float(trade.entry_underlying_price),
            strike,
            t_at_entry,
            rate,
            side,
        )
        if iv is not None:
            iv_candidates.append(iv)
    if iv_candidates:
        iv_used = float(np.median(iv_candidates))
        iv_source: Literal["implied_from_entry", "fallback", "default"] = (
            "implied_from_entry"
        )
    else:
        iv_used = DEFAULT_IV
        iv_source = "default"

    # Per-share aggregator across legs: sign × contracts × bs_intraday.
    def _portfolio_value(s: float, t_years: float) -> float:
        total = 0.0
        for leg in legs:
            side = str(leg.get("side", "")).lower()
            action = str(leg.get("action", "buy")).lower()
            if side not in ("call", "put"):
                continue
            strike = float(leg.get("strike", 0.0))
            contracts = int(leg.get("contracts", 1))
            sign = 1 if action == "buy" else -1
            total += sign * contracts * bs_intraday(
                s, strike, t_years, rate, iv_used, side
            )
        return total

    def _portfolio_intrinsic(s: float) -> float:
        total = 0.0
        for leg in legs:
            side = str(leg.get("side", "")).lower()
            action = str(leg.get("action", "buy")).lower()
            if side not in ("call", "put"):
                continue
            strike = float(leg.get("strike", 0.0))
            contracts = int(leg.get("contracts", 1))
            sign = 1 if action == "buy" else -1
            intrinsic = max(s - strike, 0.0) if side == "call" else max(strike - s, 0.0)
            total += sign * contracts * intrinsic
        return total

    # Cost basis per share (signed: + for net debit, − for net credit).
    cb_per_share = 0.0
    for leg in legs:
        action = str(leg.get("action", "buy")).lower()
        sign = 1 if action == "buy" else -1
        cb_per_share += sign * int(leg.get("contracts", 1)) * float(
            leg.get("entry_price", 0.0)
        )
    cb_total = cb_per_share * CONTRACT_MULTIPLIER

    # Price grid: ±25% around spot, GRID_POINTS=81 — same convention as
    # position_analytics so the front-end payoff curves render at the
    # same resolution multi-day trades use.
    prices_np = np.linspace(spot * 0.75, spot * 1.25, 81)
    today_pnl_ps = np.array(
        [_portfolio_value(float(s), t_now) for s in prices_np]
    )
    today_pnl_ps -= cb_per_share
    exp_pnl_ps = np.array([_portfolio_intrinsic(float(s)) for s in prices_np])
    exp_pnl_ps -= cb_per_share

    today_pnl = today_pnl_ps * CONTRACT_MULTIPLIER
    exp_pnl = exp_pnl_ps * CONTRACT_MULTIPLIER

    # Breakevens — linear-interpolated zero crossings.
    def _zero_crossings(xs: np.ndarray, ys: np.ndarray) -> list[float]:
        out: list[float] = []
        for i in range(len(ys) - 1):
            a, b = float(ys[i]), float(ys[i + 1])
            if a == 0:
                out.append(float(xs[i]))
            elif a * b < 0:
                t = a / (a - b)
                out.append(float(xs[i] + t * (xs[i + 1] - xs[i])))
        return out

    be_today = _zero_crossings(prices_np, today_pnl_ps)
    be_expiration = _zero_crossings(prices_np, exp_pnl_ps)

    cv_per_share = _portfolio_value(spot, t_now)
    cv_total = cv_per_share * CONTRACT_MULTIPLIER
    unrealized = cv_total - cb_total

    # Long straddle (and most net-long premium structures) has unbounded
    # gain on at least one side. We compute these flags structurally so
    # an iron-condor 0DTE (future use) would still report bounded loss.
    net_calls = sum(
        (1 if str(l.get("action", "buy")).lower() == "buy" else -1)
        * int(l.get("contracts", 1))
        for l in legs
        if str(l.get("side", "")).lower() == "call"
    )
    unlimited_gain = net_calls > 0
    unlimited_loss = net_calls < 0
    max_profit = None if unlimited_gain else float(np.max(exp_pnl))
    max_loss = None if unlimited_loss else float(np.min(exp_pnl))

    # Portfolio greeks at the scrubbed (spot, T_now) point — sum of per-
    # leg greeks weighted by sign × contracts. Same per-share convention
    # as compute_analytics(); scaled to position dollars below.
    g_total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        side = str(leg.get("side", "")).lower()
        action = str(leg.get("action", "buy")).lower()
        if side not in ("call", "put"):
            continue
        strike = float(leg.get("strike", 0.0))
        contracts = int(leg.get("contracts", 1))
        sign = 1 if action == "buy" else -1
        leg_g = greeks_intraday(spot, strike, t_now, rate, iv_used, side)
        for k in g_total:
            g_total[k] += sign * contracts * leg_g[k]
    # Scale to position dollars (CONTRACT_MULTIPLIER = 100 shares/contract).
    greeks = AnalyticsGreeks(
        delta=float(g_total["delta"] * CONTRACT_MULTIPLIER),
        gamma=float(g_total["gamma"] * CONTRACT_MULTIPLIER),
        theta=float(g_total["theta"] * CONTRACT_MULTIPLIER),
        vega=float(g_total["vega"] * CONTRACT_MULTIPLIER),
    )

    return TradeAnalyticsOut(
        trade_id=trade.id,
        symbol=trade.symbol,
        spot=float(spot),
        rate=float(rate),
        current_dte_days=0,
        scrubber_dte_days=0,
        iv_used=iv_used,
        iv_source=iv_source,
        prices=[float(p) for p in prices_np],
        payoff_expiration=[float(v) for v in exp_pnl],
        payoff_today=[float(v) for v in today_pnl],
        breakevens_expiration=be_expiration,
        breakevens_today=be_today,
        entry_underlying_price=float(trade.entry_underlying_price),
        entry_date=trade.entry_date,
        cost_basis=float(cb_total),
        current_value=float(cv_total),
        unrealized_pnl=float(unrealized),
        max_profit=max_profit,
        max_loss=max_loss,
        unlimited_gain=unlimited_gain,
        unlimited_loss=unlimited_loss,
        greeks=greeks,
    )


def _to_out(trade: Trade) -> TradeOut:
    return TradeOut(
        id=trade.id,
        symbol=trade.symbol,
        strategy=trade.strategy,
        legs=trade.legs,
        entry_date=trade.entry_date,
        entry_underlying_price=trade.entry_underlying_price,
        net_debit_credit=trade.net_debit_credit,
        status=trade.status,  # type: ignore[arg-type]
        exit_date=trade.exit_date,
        exit_underlying_price=trade.exit_underlying_price,
        realized_pnl=trade.realized_pnl,
        is_paper=trade.is_paper,
        notes=trade.notes,
        tier=trade.tier,
        tags=trade.tags,
        mistake_tags=trade.mistake_tags,
        confidence=trade.confidence,
        thesis=trade.thesis,
        planned_exit=trade.planned_exit,
        risk_amount=trade.risk_amount,
        screenshot_url=trade.screenshot_url,
        review_note=trade.review_note,
        r_multiple=trade.r_multiple,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )
