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
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculations.position_analytics import (
    build_legs_from_journal,
    compute_analytics,
)
from database import get_session
from models.trade import Trade
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
    session: Session = Depends(get_session),
) -> TradeAnalyticsOut:
    """Position analytics at current state (or at a scrubbed DTE).

    Cached per (trade_id, dte_override) for a short TTL — the scrubber
    can fire many requests, and the underlying inputs (spot, IV) move
    on minute scale at fastest. 15s TTL keeps the demo responsive
    without re-running BS for every keystroke."""
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")

    cache_key = f"trade_analytics:{trade_id}:{dte_override}"
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
