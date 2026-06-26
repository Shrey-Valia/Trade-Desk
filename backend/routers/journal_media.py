"""Journal trade screenshots — upload + serve.

POST /api/journal/trades/{id}/screenshot   — multipart image upload
GET  /api/journal/trades/{id}/screenshot   — serve the stored image

Kept in its OWN router (not journal.py) so the media concern stays
isolated: the upload is multipart (not JSON), it touches the filesystem,
and it sets the trade's existing `screenshot_url` column. Auth + ownership
mirror the rest of the journal — a trade is reachable only through a
combine the signed-in user owns.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.trade import Trade
from models.user import User
from schemas.journal import TradeOut
from services.auth import get_current_user
from services.file_storage import (
    FileStorageError,
    MAX_BYTES,
    find_screenshot,
    media_type_for,
    save_screenshot,
)

router = APIRouter(prefix="/api/journal", tags=["journal-media"])
log = logging.getLogger(__name__)


def _owned_trade(session: Session, user: User, trade_id: int) -> Trade:
    """Resolve a trade the signed-in user owns (trade → combine → user).
    Foreign / nonexistent trades both 404 — same boundary as journal.py.
    """
    trade = session.get(Trade, trade_id)
    if trade is None or trade.combine_id is None:
        raise HTTPException(404, f"trade {trade_id} not found")
    owned = session.execute(
        select(Combine.id).where(
            Combine.id == trade.combine_id, Combine.user_id == user.id
        )
    ).scalar_one_or_none()
    if owned is None:
        raise HTTPException(404, f"trade {trade_id} not found")
    return trade


@router.post("/trades/{trade_id}/screenshot", response_model=TradeOut)
async def upload_screenshot(
    trade_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Attach a screenshot to an existing trade.

    Multipart `file` field. Validated for size (≤ 5MB) + format (PNG/JPEG)
    in services.file_storage. On success the trade's `screenshot_url` is
    set to the served GET path and the refreshed trade is returned, so the
    client can swap it straight into its trade cache.
    """
    trade = _owned_trade(session, user, trade_id)

    data = await file.read()
    # Guard memory before validation too — read() already buffered, but the
    # explicit ceiling keeps the error message consistent with the service.
    if len(data) > MAX_BYTES:
        raise HTTPException(
            413, f"file too large; max {MAX_BYTES} bytes (5 MB)"
        )
    try:
        url = save_screenshot(trade_id, file.content_type, data)
    except FileStorageError as exc:
        # Bad format / oversize / corrupt → 422 (the client sent something
        # we can't accept), not a server fault.
        raise HTTPException(422, str(exc)) from exc

    trade.screenshot_url = url
    session.commit()
    session.refresh(trade)
    return _to_out(trade)


@router.get("/trades/{trade_id}/screenshot")
def get_screenshot(
    trade_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    """Serve the trade's screenshot bytes (owner-only)."""
    _owned_trade(session, user, trade_id)
    path = find_screenshot(trade_id)
    if path is None:
        raise HTTPException(404, f"no screenshot for trade {trade_id}")
    return FileResponse(path, media_type=media_type_for(path))


def _to_out(trade: Trade) -> TradeOut:
    """Local serializer — mirrors journal.py's _to_out without importing it
    (keeps this router decoupled from journal.py per the WS4 ownership split)."""
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
        close_reason=trade.close_reason,  # type: ignore[arg-type]
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
