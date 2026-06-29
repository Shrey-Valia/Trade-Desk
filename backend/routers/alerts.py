"""Alerts — per-user price / earnings / fill triggers (WS6).

CRUD + a price-evaluation endpoint:

  GET    /api/alerts                 — list the user's alerts (newest first)
  POST   /api/alerts                 — create an alert
  DELETE /api/alerts/{id}            — delete an alert
  POST   /api/alerts/{id}/rearm      — flip a triggered alert back to active
  POST   /api/alerts/evaluate        — evaluate active PRICE alerts against live
                                       quotes; returns the ones that just tripped

The frontend also evaluates price alerts client-side against its existing
5s quote poll (instant toast, no extra round-trip) and POSTs the trip back so
the row's status persists. The server ``evaluate`` endpoint is the
authoritative fallback (and what a future background job would call).

Per-user, cookie-auth scoped — every query filters on ``user.id`` so one
trader can never see or trip another's alerts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.alert import Alert
from models.user import User
from services.alpaca_client import get_quotes
from services.auth import get_current_user

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

_KINDS = ("price", "earnings", "fill")
_DIRECTIONS = ("above", "below")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AlertIn(BaseModel):
    kind: str = Field(..., description="price | earnings | fill")
    symbol: str
    threshold: float | None = Field(
        None, description="Crossing level (required for price alerts)."
    )
    direction: str | None = Field(
        None, description="above | below (required for price alerts)."
    )
    note: str = ""


class AlertOut(BaseModel):
    id: int
    kind: str
    symbol: str
    threshold: float | None
    direction: str | None
    status: str
    note: str
    created_at: datetime
    triggered_at: datetime | None

    model_config = {"from_attributes": True}


class AlertsOut(BaseModel):
    alerts: list[AlertOut]


class EvaluateOut(BaseModel):
    """The alerts that flipped active→triggered during this evaluation."""

    triggered: list[AlertOut]


# ---------------------------------------------------------------------------
# Trigger logic (pure — unit-testable without live quotes)
# ---------------------------------------------------------------------------


def price_alert_tripped(direction: str | None, threshold: float | None, price: float) -> bool:
    """True when a live ``price`` satisfies a price alert's condition.

    ``above`` trips at price >= threshold; ``below`` trips at price <= threshold.
    A malformed alert (missing direction/threshold) never trips.
    """
    if threshold is None or direction not in _DIRECTIONS:
        return False
    if direction == "above":
        return price >= threshold
    return price <= threshold


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=AlertsOut)
def list_alerts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AlertsOut:
    rows = session.execute(
        select(Alert)
        .where(Alert.user_id == user.id)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
    ).scalars().all()
    return AlertsOut(alerts=[AlertOut.model_validate(r) for r in rows])


@router.post("", response_model=AlertOut, status_code=201)
def create_alert(
    payload: AlertIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AlertOut:
    kind = (payload.kind or "").strip().lower()
    if kind not in _KINDS:
        raise HTTPException(400, f"kind must be one of {_KINDS}")
    symbol = (payload.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(400, "symbol is required")

    threshold = payload.threshold
    direction = (payload.direction or "").strip().lower() or None
    if kind == "price":
        if threshold is None or threshold <= 0:
            raise HTTPException(400, "price alerts need a positive threshold")
        if direction not in _DIRECTIONS:
            raise HTTPException(400, f"direction must be one of {_DIRECTIONS}")
    else:
        # earnings/fill don't carry a price condition — clear any stray input.
        threshold = None
        direction = None

    alert = Alert(
        user_id=user.id,
        kind=kind,
        symbol=symbol,
        threshold=threshold,
        direction=direction,
        note=(payload.note or "")[:160],
        status="active",
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return AlertOut.model_validate(alert)


@router.delete("/{alert_id}", status_code=204)
def delete_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    row = session.get(Alert, alert_id)
    # 404 on both missing and not-owned so existence isn't leaked across users.
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "alert not found")
    session.delete(row)
    session.commit()


@router.post("/{alert_id}/rearm", response_model=AlertOut)
def rearm_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AlertOut:
    row = session.get(Alert, alert_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "alert not found")
    row.status = "active"
    row.triggered_at = None
    session.commit()
    session.refresh(row)
    return AlertOut.model_validate(row)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@router.post("/evaluate", response_model=EvaluateOut)
def evaluate_alerts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> EvaluateOut:
    """Evaluate the user's active PRICE alerts against live quotes; persist and
    return the ones that just tripped. Earnings/fill kinds are evaluated by
    their own surfaces (calendar / order monitor) and are skipped here.

    Quote-fetch failures are swallowed per-symbol: a degraded market-data
    path must never 500 the alerts list — un-evaluated alerts simply stay
    active for the next pass.
    """
    active = session.execute(
        select(Alert)
        .where(Alert.user_id == user.id)
        .where(Alert.status == "active")
        .where(Alert.kind == "price")
    ).scalars().all()
    if not active:
        return EvaluateOut(triggered=[])

    symbols = sorted({a.symbol for a in active})
    try:
        quotes = get_quotes(symbols)
    except Exception:  # noqa: BLE001 — degrade gracefully, never 500 the list
        quotes = {}

    fired: list[Alert] = []
    now = datetime.now(timezone.utc)
    for alert in active:
        quote = quotes.get(alert.symbol)
        # A missing OR non-positive price (a bad/empty streamed quote) is NOT a
        # real cross — skip it. Otherwise price=0 trips every "below" alert and
        # permanently marks it triggered.
        if quote is None or not (quote.price > 0):
            continue
        if price_alert_tripped(alert.direction, alert.threshold, quote.price):
            alert.status = "triggered"
            alert.triggered_at = now
            fired.append(alert)
    if fired:
        session.commit()
        for a in fired:
            session.refresh(a)
    return EvaluateOut(triggered=[AlertOut.model_validate(a) for a in fired])
