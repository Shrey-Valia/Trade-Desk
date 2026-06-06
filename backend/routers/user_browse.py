"""User-facing browse endpoints — stars, popular slate, selection log.

Backs the new search modal:
  GET  /api/user/stars              — list user's starred symbols
  POST /api/user/stars/{symbol}     — add a star
  DELETE /api/user/stars/{symbol}   — remove a star
  GET  /api/ticker/popular          — curated popular slate
  POST /api/ticker/selection        — fire-and-forget selection log

`user_id` is hardcoded to 1 (single-tenant) — same convention as
`account_state`. Adding auth later means swapping `_CURRENT_USER_ID`
for a real dependency without touching the data model.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_session
from models.ticker_selection import TickerSelection
from models.user_star import UserStar
from services import curated_universe
from services.chain_availability import has_zero_dte_bulk

_CURRENT_USER_ID = 1


router_user = APIRouter(prefix="/api/user", tags=["user"])
router_ticker = APIRouter(prefix="/api/ticker", tags=["ticker"])


class StarsOut(BaseModel):
    symbols: list[str] = Field(
        ..., description="Starred symbols, oldest-first by created_at."
    )


class PopularEntry(BaseModel):
    symbol: str
    name: str
    has_0dte_today: bool


class PopularOut(BaseModel):
    results: list[PopularEntry]


class SelectionIn(BaseModel):
    symbol: str


# ---------------------------------------------------------------------------
# Stars CRUD
# ---------------------------------------------------------------------------


@router_user.get("/stars", response_model=StarsOut)
def list_stars(session: Session = Depends(get_session)) -> StarsOut:
    rows = session.execute(
        select(UserStar.symbol)
        .where(UserStar.user_id == _CURRENT_USER_ID)
        .order_by(UserStar.created_at.asc(), UserStar.id.asc())
    ).all()
    return StarsOut(symbols=[r[0] for r in rows])


@router_user.post("/stars/{symbol}", response_model=StarsOut)
def add_star(symbol: str, session: Session = Depends(get_session)) -> StarsOut:
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(400, "symbol is required")
    # Constrain stars to the curated universe — otherwise a typo could
    # plant a ghost entry that the modal can't render an entry for.
    if not curated_universe.is_in_universe(sym):
        raise HTTPException(
            400, f"symbol '{sym}' is not in the curated universe"
        )
    try:
        session.add(UserStar(user_id=_CURRENT_USER_ID, symbol=sym))
        session.commit()
    except IntegrityError:
        # UniqueConstraint hit — already starred. Idempotent: re-read
        # and return the current list rather than 409.
        session.rollback()
    return list_stars(session)


@router_user.delete("/stars/{symbol}", response_model=StarsOut)
def remove_star(symbol: str, session: Session = Depends(get_session)) -> StarsOut:
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(400, "symbol is required")
    row = session.execute(
        select(UserStar)
        .where(UserStar.user_id == _CURRENT_USER_ID)
        .where(UserStar.symbol == sym)
    ).scalar_one_or_none()
    if row is not None:
        session.delete(row)
        session.commit()
    return list_stars(session)


# ---------------------------------------------------------------------------
# Popular slate
# ---------------------------------------------------------------------------


@router_ticker.get("/popular", response_model=PopularOut)
def get_popular_slate() -> PopularOut:
    """Curated popular tickers + their live 0DTE-availability flag.

    Today this returns `curated_universe.POPULAR_TICKERS`. Flipping to
    algorithmic-popular is a one-line swap to `ticker_analytics.get_popular_tickers`
    (see that module's docstring for the rollout plan).
    """
    entries = curated_universe.get_popular()
    zdte = has_zero_dte_bulk([e.symbol for e in entries])
    return PopularOut(
        results=[
            PopularEntry(
                symbol=e.symbol,
                name=e.name,
                has_0dte_today=bool(zdte.get(e.symbol, False)),
            )
            for e in entries
        ]
    )


# ---------------------------------------------------------------------------
# Selection logging
# ---------------------------------------------------------------------------


@router_ticker.post("/selection", status_code=204)
def log_selection(
    payload: SelectionIn,
    session: Session = Depends(get_session),
) -> None:
    """Append-only selection log. Fire-and-forget from the frontend —
    response is 204, no body. Symbol must be in the curated universe;
    out-of-universe input is rejected so the log stays clean for the
    future algorithmic-popular feed."""
    sym = (payload.symbol or "").strip().upper()
    if not sym:
        raise HTTPException(400, "symbol is required")
    if not curated_universe.is_in_universe(sym):
        raise HTTPException(
            400, f"symbol '{sym}' is not in the curated universe"
        )
    session.add(TickerSelection(user_id=_CURRENT_USER_ID, symbol=sym))
    session.commit()
