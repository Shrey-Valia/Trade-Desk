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

import json
import logging
from datetime import date, datetime, time, timezone
from math import gcd
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
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
from config import settings
from database import get_session
from models.combine import Combine
from models.trade import Trade
from models.user import User
from schemas.calendar_journal import (
    CalendarDayOut,
    CalendarMonthOut,
    CalendarWeekOut,
)
from schemas.journal import (
    AnalyticsGreeks,
    BracketsUpdate,
    EXPECTED_LEG_COUNT,
    MISTAKE_TAG_VOCABULARY,
    PortfolioGreeksOut,
    ScaleOutRequest,
    TradeAnalyticsOut,
    TradeIn,
    TradeOut,
    TradeUpdate,
    TradesResponse,
    compute_net_debit_credit,
)
from services.alpaca_client import get_quotes
from services.auth import get_active_combine, get_current_user
from services.cache import cache
from services.copy_trade import (
    mirror_cancel,
    mirror_close,
    mirror_modify,
    order_modification_values,
)
from services.fills import close_friction
from services.fred_client import DEFAULT_RATE_FALLBACK, latest_dgs3mo_rate

router = APIRouter(prefix="/api/journal", tags=["journal"])
log = logging.getLogger(__name__)


def _user_combine_ids(user: User):
    """Subquery of combine ids owned by this user — the journal's
    ownership boundary (trade → combine → user)."""
    return select(Combine.id).where(Combine.user_id == user.id)


def _owned_trade(session: Session, user: User, trade_id: int) -> Trade:
    trade = session.get(Trade, trade_id)
    if trade is None or trade.combine_id is None:
        raise HTTPException(404, f"trade {trade_id} not found")
    owned = session.execute(
        select(Combine.id).where(
            Combine.id == trade.combine_id, Combine.user_id == user.id
        )
    ).scalar_one_or_none()
    if owned is None:
        # Foreign trade — indistinguishable from nonexistent.
        raise HTTPException(404, f"trade {trade_id} not found")
    return trade


def _position_commission_side(trade: Trade) -> float:
    """Per-side commission for a full position: TOTAL contracts across all legs
    × the configured per-contract rate. A real broker charges per contract PER
    LEG, so a 4-leg iron condor at 1 contract is 4 fills (4×rate), a 2-leg
    straddle is 2×. Same convention the order monitor's `_commission_side`
    uses; `_fold_commission` folds this into both entry and exit."""
    position_contracts = sum(
        int(leg.get("contracts", 1) or 1) for leg in (trade.legs or [])
    )
    return position_contracts * settings.per_contract_fee


def _recompute_unrealized(trade: Trade) -> float:
    """Server-side unrealized P&L for `trade` from the LIVE mark — the
    integrity backbone of the close / scale-out recompute. Mirrors EXACTLY
    the pattern the order monitor's `_default_unrealized_for` uses and the
    `get_trade_analytics` endpoint serves, so a manual close books the same
    number the user sees on screen and the monitor would book on a bracket:

      * spot  = live quote for the symbol, falling back to entry price when
                the feed is cold (nights / weekends / rate-limit);
      * branch = `_trade_is_zerodte` → `_intraday_analytics` (0DTE) else
                `compute_analytics` (multi-day);
      * value = the branch's folded `unrealized_pnl` (entry commission folded
                in by `_fold_commission`, the same as the analytics endpoint).

    The caller subtracts the EXIT-side commission to get realized. The client
    never supplies the number — it is recomputed here from the mark."""
    # Live spot — prefer the quote, fall back to entry so a cold feed still
    # books a deterministic number instead of failing the close.
    spot = float(trade.entry_underlying_price)
    try:
        quote = get_quotes([trade.symbol]).get(trade.symbol)
        if quote is not None:
            spot = float(quote.price)
    except Exception:  # noqa: BLE001 — feed cold → entry price is the fallback
        log.debug("close recompute: quote fetch failed for %s", trade.symbol)

    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK

    commission_side = _position_commission_side(trade)

    if _trade_is_zerodte(trade):
        # Elapsed since entry, in hours — drives sub-day theta (same as the
        # analytics endpoint's wall-clock default for a freshly-opened 0DTE).
        entry_dt = trade.entry_date or datetime.now(timezone.utc)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        elapsed_hours = max(
            0.0, (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600.0
        )
        resp = _intraday_analytics(
            trade=trade, spot=spot, rate=rate, elapsed_hours=elapsed_hours
        )
        resp = _fold_commission(resp, commission_side)
        return float(resp.unrealized_pnl)

    # Multi-day branch — identical to the analytics endpoint's day path. DTE is
    # an ET-calendar quantity (US equity options), so anchor "today" and the
    # entry date to ET — NOT UTC, which rolls a day ahead every evening and
    # would mark a 1DTE position as already-expired (intrinsic only) all night.
    today = datetime.now(_ET).date()
    entry_date = trade.entry_date.astimezone(_ET).date() if trade.entry_date else today
    legs_now, iv_used, iv_source = build_legs_from_journal(
        trade.legs,
        today=today,
        rate=rate,
        spot_at_entry=trade.entry_underlying_price,
        entry_date=entry_date,
    )
    if not legs_now:
        raise HTTPException(
            422,
            f"trade {trade.id} has no usable legs — its stored legs data is "
            "missing or malformed",
        )
    result = compute_analytics(
        legs_now,
        spot=spot,
        rate=rate,
        scrubber_dte_days=None,
        iv_used=iv_used,
        iv_source=iv_source,
    )
    # Fold entry commission the same way `_fold_commission` does on the full
    # TradeAnalyticsOut (unrealized = current_value − cost_basis, less entry side).
    return float(result.unrealized_pnl - commission_side)


@router.post("/trades", response_model=TradeOut, status_code=201)
def create_trade(
    payload: TradeIn,
    response: Response,
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> TradeOut:
    warnings = _validate_soft(payload)
    if warnings:
        response.headers["X-Journal-Warnings"] = " | ".join(warnings)

    # INTEGRITY: this endpoint hand-keys a trade from client-supplied
    # entry_price / entry_date / size that can't be server-verified, so every
    # row it writes is tagged origin='manual' — RECORD-KEEPING that never moves
    # combine equity, the DLL/MLL windows, the scaling cap, the profit target
    # or payout eligibility (all of which sum over origin='execution' only).
    # That closes the manual-journal P&L fabrication channel at the source, so
    # no scaling-cap / risk gate is needed here — a manual row bears no combine
    # risk. Real combine positions are opened through the server-priced
    # /api/zerodte/open* path, which enforces the cap and risk gates.
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
        tier=combine.tier,
        combine_id=combine.id,
        origin="manual",          # record-keeping — never moves combine equity
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
    status: Literal["working", "open", "closed", "cancelled"] | None = None,
    is_paper: bool | None = None,
    symbol: str | None = None,
    combine_id: int | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradesResponse:
    stmt = (
        select(Trade)
        .where(Trade.combine_id.in_(_user_combine_ids(user)))
        .order_by(Trade.entry_date.desc(), Trade.id.desc())
    )
    if combine_id is not None:
        stmt = stmt.where(Trade.combine_id == combine_id)
    if status is not None:
        stmt = stmt.where(Trade.status == status)
    if is_paper is not None:
        stmt = stmt.where(Trade.is_paper == is_paper)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol.upper())
    rows = session.execute(stmt).scalars().all()
    return TradesResponse(trades=[_to_out(t) for t in rows])


@router.get("/trades/{trade_id}", response_model=TradeOut)
def get_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    return _to_out(_owned_trade(session, user, trade_id))


@router.patch("/trades/{trade_id}", response_model=TradeOut)
def update_trade(
    trade_id: int,
    payload: TradeUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    trade = _owned_trade(session, user, trade_id)

    # STATUS WHITELIST: open → closed is the ONLY transition this endpoint
    # performs (a same-status no-op is tolerated for idempotent clients).
    # Everything else rewrites the combine ledger: closed → open/cancelled
    # erases a booked loss from the DLL/MLL window, working → open self-fills
    # at the placeholder entry_price, working → closed books P&L on an order
    # that never filled. Working orders are pulled via the dedicated /cancel
    # endpoint (which cascades to follower copies); fills belong to the order
    # monitor; a decided trade (closed/cancelled) accepts metadata-only edits.
    closing_now = payload.status == "closed" and trade.status == "open"
    if (
        payload.status is not None
        and payload.status != trade.status
        and not closing_now
    ):
        if trade.status == "working" and payload.status == "cancelled":
            raise HTTPException(
                409,
                "working orders are cancelled via POST /api/journal/trades/{id}/cancel",
            )
        raise HTTPException(
            409,
            f"illegal status transition {trade.status} → {payload.status} — "
            "this endpoint only closes an open position",
        )

    # INTEGRITY: `payload.realized_pnl` is DEPRECATED + IGNORED. On a close we
    # RECOMPUTE realized server-side from the live mark (recompute unrealized,
    # subtract the exit-side commission AND the spread-crossing exit friction)
    # — the exact `_book_close` / `_default_unrealized_for` path the order
    # monitor uses. The client can no longer book an arbitrary number.
    if closing_now:
        # Resolve the numbers BEFORE the claim — this is the network window a
        # concurrent bracket/liquidation close can land in.
        unrealized = _recompute_unrealized(trade)
        realized = (
            unrealized
            - _position_commission_side(trade)
            - close_friction(trade.symbol, trade.legs)
        )
        # RACE GUARD: claim the open→closed transition with a conditional
        # UPDATE. rowcount 0 → the monitor (bracket/liquidation) already booked
        # this close during the recompute window — a second booking would
        # double-count the realized (+= applied twice). 409 instead.
        claimed = session.execute(
            update(Trade)
            .where(Trade.id == trade.id, Trade.status == "open")
            .values(status="closed")
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed == 0:
            session.rollback()
            raise HTTPException(
                409,
                "trade is no longer open — it was closed concurrently"
                " (bracket / liquidation); refresh to see the booked close",
            )
        trade.status = "closed"
        # Exit fields are part of the CLOSE transition only — a decided trade's
        # settlement record can't be rewritten after the fact.
        #
        # INTEGRITY: for an execution trade the exit timestamp is stamped from
        # the SERVER clock, never the client. A client-chosen exit_date would
        # let a trader move a loss into a different 5pm-PT trading day and dodge
        # the DLL day-lock, forge distinct winning days for the payout gate, or
        # satisfy the min-trading-days count in one sitting. Manual (record-
        # keeping) rows don't touch combine accounting, so a logged exit_date is
        # honored there.
        if trade.origin == "execution":
            trade.exit_date = datetime.now(timezone.utc)
        elif payload.exit_date is not None:
            trade.exit_date = _as_utc(payload.exit_date)
        if payload.exit_underlying_price is not None:
            trade.exit_underlying_price = payload.exit_underlying_price
        # ACCUMULATE onto any realized already booked by prior scale-outs. After
        # a scale-out the legs hold only the REMAINING contracts, so this
        # recompute covers just that final slice — a bare assignment would wipe
        # every booked scale-out slice (e.g. +$800 on 2/3 then +$100 on the last
        # would show $100, not $900). None/0 for a never-scaled close → no-op.
        trade.realized_pnl = round((trade.realized_pnl or 0.0) + realized, 2)
    elif payload.status is not None:
        # Whitelisted above: only a same-status no-op reaches here.
        trade.status = payload.status
    if payload.notes is not None:
        trade.notes = payload.notes
    if payload.tags is not None:
        trade.tags = list(payload.tags)
    if payload.mistake_tags is not None:
        trade.mistake_tags = list(payload.mistake_tags)
    if payload.review_note is not None:
        trade.review_note = payload.review_note

    session.commit()
    session.refresh(trade)
    # Copy trading: a lead close cascades to its follower copies (best-effort).
    # Only on the actual transition — a metadata edit to an already-closed
    # trade must not re-run the cascade.
    if closing_now:
        # Thread the FINAL SLICE just booked (this close covers only the
        # remaining contracts after any prior scale-outs) so followers
        # accumulate that slice instead of re-booking the lead's running total.
        mirror_close(session, trade, final_slice_pnl=realized)
    return _to_out(trade)


@router.post("/trades/{trade_id}/scale-out", response_model=TradeOut)
def scale_out_trade(
    trade_id: int,
    payload: ScaleOutRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Partial close (scale-out): book `qty` contracts of an OPEN position and
    leave the rest open. Reduces each leg's contracts by qty, ACCUMULATES the
    booked realized P&L for the slice, records a scale-out note, and cascades
    proportionally to any follower copies. Scale-out is strictly PARTIAL
    (qty < held); closing the final contracts uses the normal PATCH close.

    INTEGRITY: `payload.realized_pnl` is DEPRECATED + IGNORED. The slice's
    realized is RECOMPUTED server-side: recompute the WHOLE position's
    unrealized from the live mark, take the slice = `unrealized × qty / held`,
    and subtract a proportional exit commission (qty × per-contract rate)."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status != "open":
        raise HTTPException(status_code=409, detail="can only scale out an OPEN position")
    legs = trade.legs
    # Guard on the SMALLEST leg so reducing every leg by qty can't drive any leg
    # negative (imbalanced multi-leg positions are representable). For the common
    # balanced case (straddle / single leg) min == max, so this is unchanged.
    held = min((int(leg.get("contracts", 1) or 1) for leg in legs), default=1)
    if payload.qty >= held:
        raise HTTPException(
            status_code=400,
            detail=f"scale-out qty {payload.qty} must be fewer than the {held} held — use close for the rest",
        )

    # RECOMPUTE the slice server-side from the live mark. `_recompute_unrealized`
    # returns the WHOLE position's folded unrealized (entry commission already
    # folded); the slice is the held-fraction of it. The exit commission is
    # PROPORTIONAL to the closed contracts (qty × rate), not the whole position.
    position_unrealized = _recompute_unrealized(trade)
    slice_fraction = payload.qty / held
    slice_unrealized = position_unrealized * slice_fraction
    # Closing `qty` reduces EVERY leg by qty, so the slice's exit commission is
    # qty × number-of-legs × rate (per contract per leg) — not a single leg's.
    num_legs = len(legs) or 1
    exit_commission = payload.qty * num_legs * settings.per_contract_fee
    # Spread-crossing exit friction on the CLOSED slice (qty of each leg) —
    # same machinery as a full close; 0 where no two-sided quote exists.
    friction = close_friction(
        trade.symbol, [{**leg, "contracts": payload.qty} for leg in legs]
    )
    slice_realized = round(slice_unrealized - exit_commission - friction, 2)

    # Reduce every leg by qty (all legs scale together — a straddle closes qty
    # of each side).
    for leg in legs:
        leg["contracts"] = int(leg.get("contracts", 1) or 1) - payload.qty
    px = f"${payload.exit_underlying_price:.2f}" if payload.exit_underlying_price else "—"
    new_notes = (trade.notes or "") + f" · scaled out {payload.qty} @ {px}"

    # RACE GUARD: write the slice through ONE conditional UPDATE claimed on
    # status='open'. The recompute above spans a network window (live mark,
    # option quotes, FRED); a bracket / liquidation full-close landing there
    # would flip status to 'closed', and without this guard the scale-out would
    # commit reduced legs + a doubled realized onto a CLOSED row (and cascade a
    # phantom partial to followers). rowcount 0 → the position closed
    # concurrently → 409. The realized ACCUMULATE is done in SQL (coalesce + …)
    # so it's atomic against the concurrent booking rather than a stale
    # read-modify-write.
    values: dict = {
        "legs_json": json.dumps(legs),
        "realized_pnl": func.coalesce(Trade.realized_pnl, 0.0) + slice_realized,
        "notes": new_notes,
    }
    if payload.exit_underlying_price is not None:
        values["exit_underlying_price"] = payload.exit_underlying_price
    claimed = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, Trade.status == "open")
        .values(**values)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.rollback()
        raise HTTPException(
            409,
            "position is no longer open — it was closed concurrently"
            " (bracket / liquidation); refresh to see the booked close",
        )
    session.commit()
    session.refresh(trade)
    # Copy-trade: cascade the partial close proportionally to follower copies.
    # The lead's legs are ALREADY reduced here — mirror_close derives the lead's
    # original size as (post-reduction contracts + closed_qty). Pass the per-slice
    # P&L explicitly (trade.realized_pnl is the running accumulated total, which
    # would over-book followers on the 2nd+ scale-out).
    mirror_close(session, trade, closed_qty=payload.qty, slice_pnl=slice_realized)
    return _to_out(trade)


class CloseLegRequest(BaseModel):
    """POST body for closing ONE leg of a multi-leg position. `qty` = None
    closes the whole leg; a smaller qty reduces it (per-leg scale-out)."""

    leg_index: int = Field(ge=0)
    qty: int | None = Field(default=None, gt=0)


def _single_leg_strategy(leg: dict) -> str:
    side = str(leg.get("side", "call")).lower()
    action = str(leg.get("action", "buy")).lower()
    return f"{'long' if action == 'buy' else 'short'}_{side}"


@router.post("/trades/{trade_id}/close-leg", response_model=TradeOut)
def close_leg(
    trade_id: int,
    payload: CloseLegRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Close ONE leg of an open multi-leg position at the live mark — buy back
    the tested short of a condor and let the far side ride. The leg's slice
    books like any close: (mark − entry) × sign × qty × 100 minus round-trip
    commission on the closed contracts minus its spread-crossing friction.

    The surviving structure keeps riding: legs shrink, the entry net is
    recomputed over the remainder, and the strategy label degrades honestly
    ("custom", or the single-leg name when one leg remains). Blocked while
    copy-trade followers mirror this trade (the cascade machinery is
    whole-position; a silent lead/follower divergence would be worse than
    the 409). Single-leg positions use CLOSE / scale-out instead."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status != "open":
        raise HTTPException(409, "can only close a leg of an OPEN position")
    legs = trade.legs
    if len(legs) < 2:
        raise HTTPException(
            409, "single-leg position — use close or scale-out instead"
        )
    if payload.leg_index >= len(legs):
        raise HTTPException(422, f"leg_index {payload.leg_index} out of range")
    followers = session.execute(
        select(func.count()).select_from(Trade).where(
            Trade.copied_from_trade_id == trade.id,
            Trade.status.in_(("open", "working")),
        )
    ).scalar_one()
    if followers:
        raise HTTPException(
            409,
            "this position is copy-mirrored — per-leg closes don't cascade to "
            "followers yet; use scale-out or a full close",
        )

    old_json = trade.legs_json
    leg = dict(legs[payload.leg_index])
    held = int(leg.get("contracts", 1) or 1)
    qty = payload.qty if payload.qty is not None else held
    if qty > held:
        raise HTTPException(400, f"qty {qty} exceeds the {held} held on this leg")

    # Price the leg at the live mark (chain mid, BS fallback) — the same
    # per-leg pricer every monitor exit uses.
    from services.order_monitor import (
        _leg_model_price,
        _option_chain_rows,
        _rate,
    )

    try:
        q = get_quotes([trade.symbol]).get(trade.symbol)
    except Exception:  # noqa: BLE001
        q = None
    if q is None:
        raise HTTPException(503, f"{trade.symbol} quote unavailable — can't price the leg")
    spot = float(q.price)
    now = datetime.now(timezone.utc)
    px = float(_leg_model_price(_option_chain_rows(trade.symbol), leg, spot, now, _rate()))

    sign = 1.0 if str(leg.get("action", "buy")).lower() == "buy" else -1.0
    entry_px = float(leg.get("entry_price", 0.0) or 0.0)
    leg_unrealized = sign * qty * (px - entry_px) * CONTRACT_MULTIPLIER
    # Round-trip commission on the closed contracts (entry side was folded at
    # the position level; the leg slice carries its own share) + the leg's
    # spread-crossing exit friction.
    commission = 2 * qty * settings.per_contract_fee
    friction = close_friction(trade.symbol, [{**leg, "contracts": qty}])
    slice_realized = round(leg_unrealized - commission - friction, 2)

    new_legs = [dict(l_) for l_ in legs]
    if qty == held:
        new_legs.pop(payload.leg_index)
    else:
        new_legs[payload.leg_index]["contracts"] = held - qty
    from schemas.journal import TradeLeg

    new_net = compute_net_debit_credit([TradeLeg(**l_) for l_ in new_legs])
    new_strategy = (
        _single_leg_strategy(new_legs[0]) if len(new_legs) == 1 else "custom"
    )
    leg_desc = (
        f"{leg.get('action')} {leg.get('strike'):g}"
        f"{'C' if leg.get('side') == 'call' else 'P'}"
    )
    new_notes = (
        (trade.notes or "")
        + f" · closed leg {leg_desc} ×{qty} @ ~{px:.2f}"
    )

    # RACE GUARD — compare-and-swap on the EXACT legs blob (stricter than
    # scale-out's status guard): a concurrent monitor close flips status, and
    # a concurrent scale-out / other leg close rewrites legs_json; either way
    # rowcount 0 → nothing was booked twice.
    claimed = session.execute(
        update(Trade)
        .where(
            Trade.id == trade.id,
            Trade.status == "open",
            Trade.legs_json == old_json,
        )
        .values(
            legs_json=json.dumps(new_legs),
            strategy=new_strategy,
            net_debit_credit=new_net,
            realized_pnl=func.coalesce(Trade.realized_pnl, 0.0) + slice_realized,
            notes=new_notes,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.rollback()
        raise HTTPException(
            409,
            "position changed concurrently (close / scale-out / another leg"
            " close) — refresh and retry",
        )
    session.commit()
    session.refresh(trade)
    return _to_out(trade)


# Min distance an SL/TP bracket must sit from the underlying — mirrors the
# placement guard in routers/zerodte (0.1% of spot) so a bracket can't be
# dragged on top of spot and insta-trigger.
_MIN_BRACKET_FRAC = 0.001


@router.put("/trades/{trade_id}/brackets", response_model=TradeOut)
def set_brackets(
    trade_id: int,
    payload: BracketsUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Set/clear the SL/TP underlying-price brackets on a working or open
    trade (the draggable chart lines write here). PUT semantics: both sides
    are replaced; a null side clears that bracket. The order monitor closes
    the position when the underlying crosses a set level (OCO)."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status not in ("working", "open"):
        raise HTTPException(409, "brackets can only be set on a working or open trade")

    # Validate min distance from the live underlying (fall back to entry).
    spot = trade.entry_underlying_price
    try:
        q = get_quotes([trade.symbol]).get(trade.symbol)
        if q is not None:
            spot = float(q.price)
    except Exception:  # noqa: BLE001 — feed cold → use entry as reference
        log.debug("brackets: quote fetch failed for %s", trade.symbol)
    min_dist = max(spot * _MIN_BRACKET_FRAC, 0.01)
    for label, level in (("stop_loss", payload.stop_loss), ("take_profit", payload.take_profit)):
        if level is not None and abs(level - spot) < min_dist:
            raise HTTPException(
                422,
                f"{label} {level:.2f} is too close to the underlying "
                f"{spot:.2f} (min {min_dist:.2f} away).",
            )

    trade.stop_loss = payload.stop_loss
    trade.take_profit = payload.take_profit
    session.commit()
    session.refresh(trade)
    return _to_out(trade)


@router.get("/portfolio/greeks", response_model=PortfolioGreeksOut)
def portfolio_greeks(
    user: User = Depends(get_current_user),
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> PortfolioGreeksOut:
    """Net Greek exposure across every OPEN execution position on the active
    combine, plus the SPY-beta-weighted delta — the top-line book numbers a
    multi-position options trader steers by. Live-priced per request off the
    same intraday analytics engine the per-position panel uses; manual journal
    rows are excluded (they carry no combine risk)."""
    from calculations.portfolio_greeks import aggregate_portfolio_greeks

    trades = (
        session.execute(
            select(Trade).where(
                Trade.combine_id == combine.id,
                Trade.status == "open",
                Trade.origin == "execution",
            )
        )
        .scalars()
        .all()
    )
    empty = PortfolioGreeksOut(
        positions=0,
        net=AnalyticsGreeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0),
    )
    if not trades:
        return empty

    symbols = sorted({t.symbol for t in trades} | {"SPY"})
    try:
        quotes = get_quotes(symbols)
    except Exception as exc:  # noqa: BLE001 — feed cold → typed degrade
        raise HTTPException(
            503, "market data unavailable — portfolio greeks need live quotes"
        ) from exc
    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK

    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for t in trades:
        q = quotes.get(t.symbol)
        if q is None:
            continue  # cold symbol — skip rather than fabricate exposure
        entry = t.entry_date or now
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=timezone.utc)
        elapsed_hours = max(0.0, (now - entry).total_seconds() / 3600.0)
        try:
            resp = _intraday_analytics(
                trade=t, spot=float(q.price), rate=rate, elapsed_hours=elapsed_hours
            )
        except HTTPException:
            continue  # malformed stored legs — never poison the whole book
        rows.append(
            {
                "symbol": t.symbol,
                "spot": float(q.price),
                "delta": resp.greeks.delta,
                "gamma": resp.greeks.gamma,
                "theta": resp.greeks.theta,
                "vega": resp.greeks.vega,
            }
        )
    if not rows:
        return empty

    spy_q = quotes.get("SPY")
    agg = aggregate_portfolio_greeks(rows, float(spy_q.price) if spy_q else None)
    return PortfolioGreeksOut(**agg)


class CloseOrderRequest(BaseModel):
    """POST body for placing/replacing a resting CLOSE-LIMIT on an open
    position. `limit_price` is the SIGNED net premium per 1× structure —
    the same convention as the multi-leg entry limit (debit positive /
    credit negative): a long structure names the value to sell at (> 0);
    a short structure names the buy-back cost as a negative (-0.30 =
    'pay at most 0.30'). Sign/direction is validated in the handler."""

    limit_price: float


def _entry_net_1x(trade: Trade) -> tuple[float, int]:
    """(signed net ENTRY premium per 1× structure, base size). Base = gcd of
    the leg quantities — the same reduction the order monitor uses, so the
    limit and the live trigger share one unit."""
    base = 0
    net = 0.0
    for leg in trade.legs:
        contracts = max(1, int(leg.get("contracts", 1) or 1))
        base = gcd(base, contracts)
        sign = 1.0 if leg.get("action") == "buy" else -1.0
        net += sign * contracts * float(leg.get("entry_price", 0.0) or 0.0)
    base = max(1, base)
    return net / base, base


@router.post("/trades/{trade_id}/close-order", response_model=TradeOut)
def set_close_order(
    trade_id: int,
    payload: CloseOrderRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Place (or replace) a resting close-limit on an OPEN position. The order
    monitor fills it AT the limit — no spread friction, commission both sides —
    when the live net mark reaches it (net_1x ≥ limit). The limit must be
    NON-marketable at placement: an immediately-fillable close belongs to the
    market CLOSE button, and booking a marketable limit at its own price would
    fill the trader worse than the market they could have hit."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status != "open":
        raise HTTPException(409, "a close order can only rest on an open position")

    limit = float(payload.limit_price)
    entry_net_1x, _base = _entry_net_1x(trade)
    if entry_net_1x == 0.0:
        raise HTTPException(422, "zero-net-premium structure: no close-limit scale")
    if entry_net_1x > 0 and limit <= 0:
        raise HTTPException(
            422,
            "this position was opened for a net debit — the close limit is the "
            "value to sell it at and must be positive",
        )
    if entry_net_1x < 0 and limit >= 0:
        raise HTTPException(
            422,
            "this position was opened for a net credit — the close limit is the "
            "buy-back cost as a NEGATIVE net (e.g. -0.30 = pay at most 0.30)",
        )

    # Marketability guard on the live mid-based net (best-effort: a cold feed
    # skips the check rather than blocking the placement).
    try:
        from services.order_monitor import _default_option_mark

        q = get_quotes([trade.symbol]).get(trade.symbol)
        if q is not None:
            now = datetime.now(timezone.utc)
            net_1x = _default_option_mark(trade, float(q.price), now) / _base
            if net_1x >= limit:
                raise HTTPException(
                    422,
                    f"close limit {limit:g} is already marketable (net mark "
                    f"{net_1x:.2f}) — use the market close, or set the limit "
                    "beyond the current mark",
                )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — feed cold → accept without the guard
        log.debug("close-order: marketability check skipped for %s", trade.symbol)

    trade.close_limit_price = round(limit, 4)
    session.commit()
    session.refresh(trade)
    return _to_out(trade)


@router.delete("/trades/{trade_id}/close-order", response_model=TradeOut)
def clear_close_order(
    trade_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Pull the resting close-limit off an open position. No-op-safe on a
    position without one (the field is simply already NULL); 409 once the
    position is no longer open (nothing is resting anymore)."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status != "open":
        raise HTTPException(409, "no resting close order — the position is not open")
    # RACE GUARD: clear only while still open, so a monitor fill that already
    # booked the close (and its P&L at the limit) isn't half-unwound.
    claimed = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, Trade.status == "open")
        .values(close_limit_price=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.rollback()
        raise HTTPException(409, "position closed concurrently — nothing to pull")
    trade.close_limit_price = None
    session.commit()
    session.refresh(trade)
    return _to_out(trade)


class OcoLinkRequest(BaseModel):
    """Link 2–4 WORKING orders as an OCO group (one fill cancels the rest).
    The monitor already honors oco_group on fills and bracket closes — this
    endpoint is the missing user-facing way to create the pairing."""

    trade_ids: list[int] = Field(min_length=2, max_length=4)


@router.post("/orders/oco-link", response_model=TradesResponse)
def oco_link(
    payload: OcoLinkRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradesResponse:
    """Group the given WORKING orders under one fresh oco_group. 409 when any
    is no longer working (a filled/cancelled order can't be a sibling); an
    order already in a group is re-homed to the new one (last link wins)."""
    if len(set(payload.trade_ids)) != len(payload.trade_ids):
        raise HTTPException(422, "duplicate trade ids in the OCO link")
    trades = [_owned_trade(session, user, tid) for tid in payload.trade_ids]
    not_working = [t.id for t in trades if t.status != "working"]
    if not_working:
        raise HTTPException(
            409,
            f"only working orders can be OCO-linked — trade(s) {not_working} "
            "are no longer working",
        )
    group = str(uuid4())
    for t in trades:
        t.oco_group = group
        t.notes = (t.notes or "") + " · OCO linked"
    session.commit()
    for t in trades:
        session.refresh(t)
    return TradesResponse(trades=[_to_out(t) for t in trades])


@router.post("/orders/oco-unlink", response_model=TradesResponse)
def oco_unlink(
    payload: OcoLinkRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradesResponse:
    """Dissolve the OCO pairing on the given orders (clears oco_group).
    Tolerant of already-filled/cancelled members — unlinking is cleanup,
    not risk-bearing."""
    trades = [_owned_trade(session, user, tid) for tid in payload.trade_ids]
    for t in trades:
        t.oco_group = None
    session.commit()
    for t in trades:
        session.refresh(t)
    return TradesResponse(trades=[_to_out(t) for t in trades])


@router.post("/trades/{trade_id}/cancel", response_model=TradeOut)
def cancel_order(
    trade_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Cancel a WORKING (unfilled limit/stop) order. No-op-safe: a trade
    that isn't working returns 409 (only unfilled orders can be pulled)."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status != "working":
        raise HTTPException(409, "only a working (unfilled) order can be cancelled")
    # RACE GUARD: the working→cancelled transition is a conditional UPDATE so
    # a monitor fill that lands between the read above and this write wins the
    # row (rowcount 0) instead of being silently overwritten by the cancel.
    claimed = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, Trade.status == "working")
        .values(status="cancelled")
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.rollback()
        raise HTTPException(
            409, "order is no longer working — it was filled or cancelled concurrently"
        )
    trade.status = "cancelled"
    session.commit()
    session.refresh(trade)
    # Copy trading: cancelling the lead's working order pulls its copies too.
    mirror_cancel(session, trade)
    return _to_out(trade)


class OrderModify(BaseModel):
    """PATCH body for modifying a WORKING order (cancel/replace). Every field
    optional, but at least one must be provided. `limit_price` is validated in
    the handler, NOT here: a single-leg premium limit is positive, but a
    multi-leg NET-premium limit is signed (debit positive / credit negative),
    so a fixed `gt=0` bound both blocked tightening a credit order and let a
    positive value silently flip a credit order to a debit → instant mis-fill.
    stop_price only applies while the order rests as a stop_limit."""

    limit_price: float | None = None
    stop_price: float | None = Field(default=None, gt=0)
    time_in_force: Literal["day", "gtc"] | None = None


@router.patch("/trades/{trade_id}/order", response_model=TradeOut)
def modify_order(
    trade_id: int,
    payload: OrderModify,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Modify a WORKING (unfilled) order in place — the cancel/replace path.

    Allowed ONLY while status='working' (409 otherwise: a filled/closed/
    cancelled order has nothing to replace). All modified columns are written
    in ONE conditional UPDATE guarded on status='working', so a monitor fill
    landing concurrently wins the row (409) instead of having its fill prices
    overwritten. Cascades to still-working copy-trade follower copies via
    mirror_modify."""
    trade = _owned_trade(session, user, trade_id)
    if trade.status != "working":
        raise HTTPException(409, "only a working (unfilled) order can be modified")
    if (
        payload.limit_price is None
        and payload.stop_price is None
        and payload.time_in_force is None
    ):
        raise HTTPException(
            400, "nothing to modify — provide limit_price, stop_price, or time_in_force"
        )
    if payload.stop_price is not None and trade.order_type != "stop_limit":
        raise HTTPException(
            400,
            "stop_price only applies to a stop_limit order — this order is"
            f" a {trade.order_type}",
        )

    # limit_price sign/positivity, validated like placement:
    #   * single-leg premium limit → strictly positive;
    #   * multi-leg NET limit → signed (debit +, credit −), non-zero, and the
    #     sign must MATCH the resting order's direction — a modify retightens a
    #     credit/debit limit but can never flip the structure (which would fill
    #     it at any price on the next tick, the exact thing a limit prevents).
    if payload.limit_price is not None:
        is_multi_net = len(trade.legs or []) > 1
        if payload.limit_price == 0:
            raise HTTPException(400, "limit_price must be non-zero")
        if not is_multi_net and payload.limit_price < 0:
            raise HTTPException(
                400, "limit_price must be > 0 for a single-leg order"
            )
        if (
            is_multi_net
            and trade.limit_price is not None
            and (payload.limit_price > 0) != (trade.limit_price > 0)
        ):
            raise HTTPException(
                400,
                "net limit sign must match the order's direction "
                "(debit positive / credit negative) — a modify can't flip a "
                "credit structure to a debit",
            )

    values = order_modification_values(
        trade,
        limit_price=payload.limit_price,
        stop_price=payload.stop_price,
        time_in_force=payload.time_in_force,
    )
    claimed = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, Trade.status == "working")
        .values(**values)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed == 0:
        session.rollback()
        raise HTTPException(
            409, "order is no longer working — it was filled or cancelled concurrently"
        )
    session.commit()
    session.expire(trade)
    # Copy trading: cascade the replace to still-working follower copies.
    mirror_modify(
        session,
        trade,
        limit_price=payload.limit_price,
        stop_price=payload.stop_price,
        time_in_force=payload.time_in_force,
    )
    session.refresh(trade)
    return _to_out(trade)


@router.get("/calendar", response_model=CalendarMonthOut)
def get_calendar(
    month: str | None = None,
    is_paper: bool | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CalendarMonthOut:
    """Monthly P&L calendar grid. Buckets closed trades by exit_date.

    `month` is "YYYY-MM"; malformed or omitted falls back to today's
    month. `is_paper` mirrors the trade-list filter so the journal page
    can flip paper/live without re-rendering the trade list separately.
    """
    target = parse_month(month)

    stmt = (
        select(Trade)
        .where(Trade.status == "closed")
        .where(Trade.combine_id.in_(_user_combine_ids(user)))
    )
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
    user: User = Depends(get_current_user),
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
    trade = _owned_trade(session, user, trade_id)

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

    # Simulated commission for THIS position, $ per side — TOTAL contracts
    # across all legs × the configured rate (per contract per leg). Folded into
    # cost basis + unrealized below (entry side); realized P&L on close
    # subtracts the exit side too. Display-only — does not touch MLL/tier.
    commission_side = _position_commission_side(trade)

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
        rate = DEFAULT_RATE_FALLBACK

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
        response = _fold_commission(response, commission_side)
        # Short TTL for live polling — the chart hits this every 5s.
        cache.set(cache_key, response, ttl_seconds=3)
        return response

    # ET-calendar DTE (see _recompute_unrealized) — UTC would lose a day of
    # value every evening on the multi-day path.
    today = datetime.now(_ET).date()
    entry_date = trade.entry_date.astimezone(_ET).date() if trade.entry_date else today

    try:
        legs_now, iv_used, iv_source = build_legs_from_journal(
            trade.legs,
            today=today,
            rate=rate,
            spot_at_entry=trade.entry_underlying_price,
            entry_date=entry_date,
        )
    except (KeyError, TypeError, ValueError) as exc:
        # A leg dict that parses as JSON but is missing/garbling fields
        # (hand-edited DB, partial write). Same class of problem as the
        # empty case below — stored-data fault, not a server bug.
        raise HTTPException(
            422,
            f"trade {trade_id} has malformed legs data ({exc!r})",
        ) from exc
    if not legs_now:
        # Stored row problem (empty or malformed legs_json), not a server
        # fault — 422 so the client can show a real message instead of a
        # generic 500.
        raise HTTPException(
            422,
            f"trade {trade_id} has no usable legs — its stored legs data is "
            "missing or malformed",
        )

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
    response = _fold_commission(response, commission_side)
    cache.set(cache_key, response, ttl_seconds=15)
    return response


def _fold_commission(
    response: TradeAnalyticsOut, commission_side: float
) -> TradeAnalyticsOut:
    """Fold the ENTRY-side commission into a computed analytics payload —
    the single place both the day and 0DTE branches funnel through. Cost
    basis rises by the entry commission and unrealized P&L falls by it
    (unrealized = current_value − cost_basis), so the header and panel UP&L
    (which both read unrealized) reflect it identically. `commission`
    carries the per-side amount so the close can subtract the exit side."""
    return response.model_copy(
        update={
            "cost_basis": response.cost_basis + commission_side,
            "unrealized_pnl": response.unrealized_pnl - commission_side,
            "commission": commission_side,
        }
    )


@router.delete("/trades/{trade_id}", status_code=204)
def delete_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    trade = _owned_trade(session, user, trade_id)
    # INTEGRITY: an execution trade that is OPEN or CLOSED is part of the
    # combine ledger — its realized_pnl is summed into balance / DLL / MLL /
    # payout eligibility. Deleting it would silently erase a booked loss (heal
    # a day-lock, un-fail an account, inflate a payout) or drop a live losing
    # position out of risk. This is the same ledger the PATCH whitelist
    # protects against un-closing; DELETE must honor it too. Working orders
    # (never filled) and cancelled rows carry no P&L, and manual record-keeping
    # rows never touch the combine — those stay freely deletable.
    if trade.origin == "execution" and trade.status in ("open", "closed"):
        raise HTTPException(
            409,
            "execution trades that are open or closed are permanent combine "
            "ledger entries and cannot be deleted — they can only be closed. "
            "Cancel a working order instead, or delete a manual journal entry.",
        )
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
    today = datetime.now(_ET).date()  # ET-calendar expiry check (US options)
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
        # See the multi-day path: stored-data problem → 422, not 500.
        raise HTTPException(
            422,
            f"trade {trade.id} has no usable legs — its stored legs data is "
            "missing or malformed",
        )

    # Times: entry → expiry, PER LEG (each leg uses its own expiry close).
    entry_dt = trade.entry_date if trade.entry_date else datetime.now(timezone.utc)
    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
    entry_et = entry_dt.astimezone(_ET)
    elapsed_seconds = max(0.0, elapsed_hours * 3600)

    # Per-leg time-to-expiry. Each leg prices off its OWN expiry close (half-day
    # aware), so a calendar/diagonal with mixed expiries is priced correctly
    # instead of forcing every leg onto leg[0]'s expiry. For the common
    # single-expiry 0DTE structure every leg shares one expiry, so this reduces
    # to identical numbers. Past the close → T=0 (settled intrinsic); otherwise
    # floored at 60s so BS never sees T<=0 intraday.
    from services.market_calendar import session_close_et as _sched_close

    def _leg_close_dt(leg: dict) -> datetime:
        try:
            d = date.fromisoformat(str(leg.get("expiry")))
        except (TypeError, ValueError):
            d = datetime.now(_ET).date()
        return _sched_close(d.isoformat()) or datetime.combine(
            d, time(*_CLOSE_HHMM), tzinfo=_ET
        )

    def _leg_t(leg: dict) -> tuple[float, float]:
        """(t_now, t_at_entry) in years for THIS leg's own expiry close."""
        tot = max(60.0, (_leg_close_dt(leg) - entry_et).total_seconds())
        rem = tot - elapsed_seconds
        t_now_leg = 0.0 if rem <= 0 else max(60.0, rem) / SECONDS_PER_YEAR
        return t_now_leg, tot / SECONDS_PER_YEAR

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
            _leg_t(leg)[1],  # this leg's own time-to-expiry at entry
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

    # Per-share aggregator across legs: sign × contracts × bs_intraday, each leg
    # at its OWN remaining time-to-expiry.
    def _portfolio_value(s: float) -> float:
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
                s, strike, _leg_t(leg)[0], rate, iv_used, side
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
        [_portfolio_value(float(s)) for s in prices_np]
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

    cv_per_share = _portfolio_value(spot)
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
        leg_g = greeks_intraday(spot, strike, _leg_t(leg)[0], rate, iv_used, side)
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
        order_type=trade.order_type,  # type: ignore[arg-type]
        limit_price=trade.limit_price,
        stop_price=trade.stop_price,
        trail_amount=trade.trail_amount,
        trail_pct=trade.trail_pct,
        trail_hwm=trade.trail_hwm,
        oco_group=trade.oco_group,
        stop_loss=trade.stop_loss,
        take_profit=trade.take_profit,
        tp_premium_mult=trade.tp_premium_mult,
        sl_premium_mult=trade.sl_premium_mult,
        close_limit_price=trade.close_limit_price,
        close_reason=trade.close_reason,  # type: ignore[arg-type]
        time_in_force=trade.time_in_force,  # type: ignore[arg-type]
        combine_id=trade.combine_id,
        origin=trade.origin,
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
