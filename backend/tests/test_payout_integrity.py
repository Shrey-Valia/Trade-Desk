"""Payout-request integrity — the P0 double-spend race + idempotency guard.

`request_payout` used to read `available = eligible − prior_requests` and book
an event in two un-serialized steps, so two racing requests could each book the
full balance (a double-spend of the ledger). The fix takes a row lock on the
combine (`SELECT … FOR UPDATE`) and reads `available` under it in the same
transaction that books the payout, plus an idempotency window that rejects a
duplicate request on the same combine.

These tests drive the real endpoint. The in-memory SQLite + StaticPool the
suite uses serializes writers, so we can't spawn truly-parallel HTTP requests
here; instead we prove the INVARIANT the lock guarantees: across any sequence
of payout requests, the total booked can never exceed the eligible balance, and
a same-combine duplicate inside the window is rejected.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import routers.combines as combines_router
from database import get_session
from models.combine import Combine
from models.combine_event import CombineEvent
from models.trade import Trade
from tests.conftest import make_combine

_PT = ZoneInfo("America/Los_Angeles")


def _et_noon_on(day_offset: int) -> datetime:
    """Noon PT `day_offset` days ago, UTC-aware — safely inside a distinct
    5pm-PT trading day so two such timestamps count as two trading days."""
    from datetime import timedelta

    d = (datetime.now(_PT) - timedelta(days=day_offset)).date()
    return datetime.combine(d, time(12, 0), tzinfo=_PT).astimezone(timezone.utc)


def _seed_closed(session, combine_id: int, realized: float, exit_at: datetime) -> None:
    trade = Trade(
        symbol="SPY",
        strategy="long_straddle",
        entry_date=exit_at,
        entry_underlying_price=400.0,
        net_debit_credit=0.0,
        status="closed",
        is_paper=True,
        notes="seed",
        tier="50K",
        combine_id=combine_id,
        exit_date=exit_at,
        exit_underlying_price=400.0,
        realized_pnl=realized,
        legs_json="[]",
    )
    session.add(trade)


def _fund_and_activate(client, combine_id: int, total_profit: float) -> None:
    """Push a combine to FUNDED + ACTIVATED with a known FUNDED-STAGE realized
    profit.

    Stamps funded_at / funded_activated_at / funded_epoch_at directly (skipping
    the eval + activation endpoints), with the accounting EPOCH before the
    seeded trades so they count as funded-stage profit. The profit is spread
    across five winning days (each ≥ the $150 winning-day bar) so the payout
    policy gates are satisfied and these tests stay focused on booking
    integrity."""
    session = next(client.app.dependency_overrides[get_session]())
    per_day = round(total_profit / 5, 2)
    for offset in range(5, 1, -1):
        _seed_closed(session, combine_id, per_day, _et_noon_on(offset))
    _seed_closed(
        session, combine_id, round(total_profit - 4 * per_day, 2), _et_noon_on(1)
    )
    combine = session.get(Combine, combine_id)
    epoch = _et_noon_on(6)
    combine.outcome = "passed"
    combine.funded_at = epoch
    combine.funded_activated_at = epoch
    combine.funded_epoch_at = epoch
    session.add(combine)
    session.commit()
    session.close()


def _booked_payouts(client, combine_id: int) -> list[float]:
    session = next(client.app.dependency_overrides[get_session]())
    from sqlalchemy import select

    from services.combine_state import PAYOUT_DEBIT_TYPES

    rows = session.execute(
        select(CombineEvent.amount).where(
            CombineEvent.combine_id == combine_id,
            CombineEvent.type.in_(PAYOUT_DEBIT_TYPES),
        )
    ).all()
    session.close()
    return [float(r[0] or 0.0) for r in rows]


def test_single_payout_books_the_full_eligible_split(auth_client):
    c = make_combine(auth_client, "50K")
    # $3,000 realized → 80/20 split → $2,400 eligible.
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    res = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert res.status_code == 200, res.text
    assert res.json()["amount"] == 2_400.0
    assert _booked_payouts(auth_client, c["id"]) == [2_400.0]


def test_duplicate_within_idempotency_window_is_rejected(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    first = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert first.status_code == 200, first.text
    # Immediate second request → inside the window → 409, nothing booked twice.
    second = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert second.status_code == 409
    assert _booked_payouts(auth_client, c["id"]) == [2_400.0]


def test_concurrent_requests_cannot_double_book(auth_client, monkeypatch):
    """Two payout requests that BOTH read `available` before either books must
    still never book more than the eligible balance in total.

    We disable the idempotency window AND the 24h pacing gate so the only thing
    standing between the two requests is the FOR-UPDATE serialization + the
    under-lock re-read of `_payouts_requested`. After the first books $2,400 the
    eligible balance is fully consumed, so the second must find $0 available and
    409 — never a second $2,400 event."""
    monkeypatch.setattr(combines_router, "PAYOUT_IDEMPOTENCY_WINDOW_S", 0)
    monkeypatch.setattr(combines_router, "PAYOUT_MIN_INTERVAL_H", 0)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)

    r1 = auth_client.post(f"/api/combines/{c['id']}/payout")
    r2 = auth_client.post(f"/api/combines/{c['id']}/payout")

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], (r1.status_code, r2.status_code, r1.text, r2.text)
    booked = _booked_payouts(auth_client, c["id"])
    # Exactly one booking, and the total can't exceed eligible.
    assert booked == [2_400.0]
    assert sum(booked) <= 2_400.0


def test_second_payout_after_more_profit_only_books_the_delta(auth_client, monkeypatch):
    """Once a payout is booked, a later request nets out prior requests: more
    realized profit only pays the incremental split, never re-paying the base."""
    monkeypatch.setattr(combines_router, "PAYOUT_IDEMPOTENCY_WINDOW_S", 0)
    monkeypatch.setattr(combines_router, "PAYOUT_MIN_INTERVAL_H", 0)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)

    first = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert first.status_code == 200
    assert first.json()["amount"] == 2_400.0

    # Add $1,000 more realized profit → +$800 eligible (80% split).
    session = next(auth_client.app.dependency_overrides[get_session]())
    _seed_closed(session, c["id"], 1_000.0, _et_noon_on(1))
    session.commit()
    session.close()

    second = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert second.status_code == 200, second.text
    assert second.json()["amount"] == 800.0
    assert sum(_booked_payouts(auth_client, c["id"])) == 3_200.0  # 80% of $4,000
