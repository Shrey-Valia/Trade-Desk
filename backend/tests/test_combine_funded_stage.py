"""Prop-firm rules-engine hardening — the paywall gate, the reset fee +
flat-book requirement, funded-stage termination, the activation
re-baseline (payouts debit a fresh funded balance; the eval profit stays
with the firm), the payout policy gates, and the archived-settle guard.

Funded-stage model under test (services/combine_state + routers/combines):
activation stamps `funded_epoch_at`, re-seeds the HWM basis to the tier
start, and restarts accounting — balance = start + realized-since-epoch −
booked payouts. A funded account keeps trading against the trailing MLL,
so passed → failed is a legal terminal transition.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import routers.combines as combines_router
from database import get_session
from models.combine import Combine
from models.combine_event import CombineEvent
from models.payment import Payment
from models.trade import Trade
from tests.conftest import make_combine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_trade(
    client,
    combine_id: int,
    realized: float | None,
    *,
    status: str = "closed",
    entry_at: datetime | None = None,
    exit_at: datetime | None = None,
) -> None:
    """Write a trade row directly via the test session. `status` lets a test
    park an OPEN position or a WORKING order on the combine."""
    session = next(client.app.dependency_overrides[get_session]())
    closed = status == "closed"
    session.add(
        Trade(
            symbol="SPY",
            strategy="long_straddle",
            entry_date=entry_at or _now(),
            entry_underlying_price=400.0,
            net_debit_credit=0.0,
            status=status,
            is_paper=True,
            notes="seed",
            tier="50K",
            combine_id=combine_id,
            exit_date=(exit_at or _now()) if closed else None,
            exit_underlying_price=400.0 if closed else None,
            realized_pnl=realized if closed else None,
            legs_json="[]",
        )
    )
    session.commit()
    session.close()


def _pass_eval(client, combine_id: int) -> None:
    """Drive a combine through a legitimate PASS: 3_200 realized across two
    distinct trading days (target + min-days + consistency), then a state
    read to persist the outcome + auto-fund."""
    for offset, pnl in ((1, 1_600), (2, 1_600)):
        _seed_trade(
            client,
            combine_id,
            pnl,
            entry_at=_now() - timedelta(days=offset),
            exit_at=_now() - timedelta(days=offset),
        )
    assert client.get("/api/account/state").json()["status"] == "passed"


def _activate(client, combine_id: int) -> None:
    res = client.post(f"/api/combines/{combine_id}/activate-account")
    assert res.status_code == 200, res.text


def _seed_winning_days(client, combine_id: int, days: int, per_day: float) -> None:
    """Funded-stage profit: `days` distinct trading days of `per_day` each,
    opened NOW (after the activation epoch) with exits fanned across days."""
    for offset in range(days):
        _seed_trade(
            client, combine_id, per_day, exit_at=_now() - timedelta(days=offset)
        )


def _card(client, combine_id: int) -> dict:
    return next(
        c for c in client.get("/api/combines").json()["combines"] if c["id"] == combine_id
    )


def _events(client, type_: str) -> list[dict]:
    return [e for e in client.get("/api/combines/events").json() if e["type"] == type_]


# ---------------------------------------------------------------------------
# Paywall gate — free purchase closes when Stripe is on
# ---------------------------------------------------------------------------


def test_purchase_409s_when_stripe_enabled(auth_client, monkeypatch):
    monkeypatch.setattr("services.payments.stripe_enabled", lambda: True)
    res = auth_client.post("/api/combines/purchase", json={"tier": "50K"})
    assert res.status_code == 409
    assert "/api/payments/checkout" in res.json()["detail"]
    # Nothing was provisioned for free.
    assert auth_client.get("/api/combines").json()["combines"] == []


def test_purchase_stays_free_when_stripe_off(auth_client):
    # Simulated mode (no Stripe key configured in tests) keeps working.
    assert auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code == 201


# ---------------------------------------------------------------------------
# Funded termination — passed → failed on an MLL breach
# ---------------------------------------------------------------------------


def test_funded_account_fails_on_mll_breach_after_pass(auth_client):
    c = make_combine(auth_client, "50K")
    _pass_eval(auth_client, c["id"])
    _activate(auth_client, c["id"])
    # Fresh funded basis: balance 50_000, MLL 48_000. A −2_100 realized loss
    # puts the balance at 47_900 ≤ the floor → the funded account terminates.
    _seed_trade(auth_client, c["id"], -2_100)
    r = auth_client.get("/api/account/state").json()
    assert r["status"] == "failed"
    failed = _events(auth_client, "failed")
    assert any("Funded account closed" in e["message"] for e in failed)


def test_lazy_fail_defers_to_monitor_with_open_book(auth_client):
    """With an open position the realized-only snapshot must NOT stamp FAILED
    — live equity may differ; the auto-liquidation monitor owns that case."""
    c = make_combine(auth_client, "50K")
    _seed_trade(auth_client, c["id"], -2_500)      # through the 48_000 floor
    _seed_trade(auth_client, c["id"], None, status="open")
    assert auth_client.get("/api/account/state").json()["status"] == "active"

    # Flatten the book → the next read stamps the fail.
    session = next(auth_client.app.dependency_overrides[get_session]())
    open_trade = session.execute(
        select(Trade).where(Trade.status == "open")
    ).scalars().one()
    open_trade.status = "closed"
    open_trade.exit_date = _now()
    open_trade.realized_pnl = 0.0
    session.commit()
    session.close()
    assert auth_client.get("/api/account/state").json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Activation — flat book + funded-stage re-baseline
# ---------------------------------------------------------------------------


def test_activation_requires_flat_book(auth_client):
    c = make_combine(auth_client, "50K")
    _pass_eval(auth_client, c["id"])
    _seed_trade(auth_client, c["id"], None, status="open")
    res = auth_client.post(f"/api/combines/{c['id']}/activate-account")
    assert res.status_code == 409
    assert "open positions" in res.json()["detail"]


def test_activation_rebaselines_balance_hwm_and_payout(auth_client):
    c = make_combine(auth_client, "50K")
    _pass_eval(auth_client, c["id"])
    _activate(auth_client, c["id"])
    r = auth_client.get("/api/account/state").json()
    # The 3_200 eval profit is NOT withdrawable and no longer in the balance.
    assert r["payout_eligible"] == 0
    assert r["realized_pnl"] == 0
    assert r["balance"] == 50_000
    assert r["high_water_mark"] == 50_000
    assert r["settled_hwm"] == 50_000
    assert r["mll"] == 48_000


def test_funded_epoch_settlement_trails_funded_eod_only(auth_client):
    """The EOD-trailing settlement composes with the funded accounting epoch:
    after activation re-seeds the HWM basis, the floor trails FUNDED-STAGE
    end-of-day balances only — the pre-epoch eval closes (same past days)
    stay out of the basis."""
    c = make_combine(auth_client, "50K")
    _pass_eval(auth_client, c["id"])   # +3_200 closed across the last 2 days
    _activate(auth_client, c["id"])    # epoch stamped; HWM/MLL re-seed to start

    # +500 funded-stage profit KEPT at yesterday's close (opened post-epoch).
    _seed_trade(auth_client, c["id"], 500, exit_at=_now() - timedelta(days=1))

    # Force a settlement (activation stamped last_settled_at at the epoch).
    session = next(auth_client.app.dependency_overrides[get_session]())
    combine = session.get(Combine, c["id"])
    combine.last_settled_at = None
    session.commit()
    session.close()

    r = auth_client.get("/api/account/state").json()
    assert r["balance"] == 50_500
    # 50_000 + 500 kept at the close — NOT 53_200+ (eval profit excluded).
    assert r["settled_hwm"] == 50_500
    assert r["mll"] == 48_500
    assert r["high_water_mark"] == 50_500


def test_payout_debits_balance_everywhere(auth_client):
    c = make_combine(auth_client, "50K")
    _pass_eval(auth_client, c["id"])
    _activate(auth_client, c["id"])
    _seed_winning_days(auth_client, c["id"], days=5, per_day=640)  # +3_200 funded

    res = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert res.status_code == 200, res.text
    assert res.json()["amount"] == pytest.approx(2_560)  # 0.80 × 3_200

    # 50_000 + 3_200 − 2_560 on the card AND the header state.
    assert _card(auth_client, c["id"])["balance"] == pytest.approx(50_640)
    assert auth_client.get("/api/account/state").json()["balance"] == pytest.approx(50_640)


# ---------------------------------------------------------------------------
# Payout policy gates — each rejects with its own 409
# ---------------------------------------------------------------------------


def _funded_with(client, days: int, per_day: float) -> dict:
    c = make_combine(client, "50K")
    _pass_eval(client, c["id"])
    _activate(client, c["id"])
    _seed_winning_days(client, c["id"], days=days, per_day=per_day)
    return c


def test_payout_minimum_125_rejected(auth_client):
    c = _funded_with(auth_client, days=5, per_day=150)  # eligible 5×150×0.8 = 600
    res = auth_client.post(f"/api/combines/{c['id']}/payout", json={"amount": 100})
    assert res.status_code == 409
    assert "minimum" in res.json()["detail"].lower()


def test_payout_exceeding_available_rejected(auth_client):
    c = _funded_with(auth_client, days=5, per_day=640)  # eligible 2_560
    res = auth_client.post(f"/api/combines/{c['id']}/payout", json={"amount": 5_000})
    assert res.status_code == 409
    assert "exceeds" in res.json()["detail"]


def test_payout_needs_five_winning_days(auth_client):
    # Plenty of profit but only 2 winning days since activation.
    c = _funded_with(auth_client, days=2, per_day=1_600)
    res = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert res.status_code == 409
    assert "winning days" in res.json()["detail"]


def test_payout_paced_to_one_per_24h(auth_client, monkeypatch):
    monkeypatch.setattr(combines_router, "PAYOUT_IDEMPOTENCY_WINDOW_S", 0)
    c = _funded_with(auth_client, days=5, per_day=640)
    first = auth_client.post(f"/api/combines/{c['id']}/payout", json={"amount": 200})
    assert first.status_code == 200, first.text
    second = auth_client.post(f"/api/combines/{c['id']}/payout", json={"amount": 200})
    assert second.status_code == 409
    assert "24 hours" in second.json()["detail"]


def test_payout_blocked_when_debit_would_breach_mll(auth_client, monkeypatch):
    """The MLL guard itself: with eligible = split × funded profit the debit
    can't reach the floor organically (the firm's share stays in the account),
    so pin the floor just under the balance and check the gate fires."""
    c = _funded_with(auth_client, days=5, per_day=640)
    real_snapshot = combines_router.combine_snapshot

    def tight_mll(session, combine):
        snap = real_snapshot(session, combine)
        return dataclasses.replace(snap, mll=snap.balance - 200.0)

    monkeypatch.setattr(combines_router, "combine_snapshot", tight_mll)
    res = auth_client.post(f"/api/combines/{c['id']}/payout")  # full 2_560 > 200
    assert res.status_code == 409
    assert "Maximum Loss Limit" in res.json()["detail"]


def test_partial_payout_amount_books_exactly(auth_client):
    c = _funded_with(auth_client, days=5, per_day=640)
    res = auth_client.post(f"/api/combines/{c['id']}/payout", json={"amount": 500})
    assert res.status_code == 200, res.text
    assert res.json()["amount"] == 500.0
    card = _card(auth_client, c["id"])
    assert card["payout_requested"] == 500.0
    assert card["payout_eligible"] == pytest.approx(2_060)  # 2_560 − 500


# ---------------------------------------------------------------------------
# Reset — fee + flat book + throttle
# ---------------------------------------------------------------------------


def _failed_combine(client) -> dict:
    c = make_combine(client, "50K")
    _seed_trade(client, c["id"], -2_500)  # 47_500 ≤ 48_000 floor
    assert client.get("/api/account/state").json()["status"] == "failed"
    return c


def test_reset_books_fee_payment_at_monthly_rate(auth_client, session_factory):
    c = _failed_combine(auth_client)
    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "active"
    with session_factory() as s:
        pay = s.execute(
            select(Payment).where(Payment.status == "reset_paid")
        ).scalars().one()
        assert pay.amount == 69.0  # 50K monthly, activation path, 80/20
        assert pay.combine_id == c["id"]
    reset_events = _events(auth_client, "reset")
    assert reset_events and reset_events[0]["amount"] == 69.0


def test_reset_requires_flat_book(auth_client):
    c = _failed_combine(auth_client)
    _seed_trade(auth_client, c["id"], None, status="working")
    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 409
    assert "working orders" in res.json()["detail"]


def test_reset_throttled_returns_429(auth_client, monkeypatch):
    """Reset shares the per-user financial limiter (its own 'reset' scope).
    Non-failed combines 409 on the merits, but the Nth rapid call 429s."""
    from services.rate_limit import financial_limiter

    monkeypatch.setattr(financial_limiter, "max_attempts", 2)
    c = make_combine(auth_client, "50K")
    path = f"/api/combines/{c['id']}/reset"
    assert auth_client.post(path).status_code == 409  # not failed
    assert auth_client.post(path).status_code == 409
    res = auth_client.post(path)  # 3rd → throttled before the 409
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_reset_clears_funded_stage(auth_client):
    """A terminated funded account resets back to a clean EVAL: the funding,
    activation stamp, and accounting epoch all clear."""
    c = make_combine(auth_client, "50K")
    _pass_eval(auth_client, c["id"])
    _activate(auth_client, c["id"])
    _seed_trade(auth_client, c["id"], -2_100)  # funded termination
    assert auth_client.get("/api/account/state").json()["status"] == "failed"

    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["outcome"] == "active"
    assert body["funded"] is False
    assert body["funded_activated"] is False
    session = next(auth_client.app.dependency_overrides[get_session]())
    combine = session.get(Combine, c["id"])
    assert combine.funded_epoch_at is None
    assert combine.funded_activated_at is None
    session.close()


# ---------------------------------------------------------------------------
# Archived combines are frozen — no settlement events on read
# ---------------------------------------------------------------------------


def test_archived_combine_does_not_settle_on_read(auth_client):
    c = make_combine(auth_client, "50K")
    assert auth_client.post(f"/api/combines/{c['id']}/archive").status_code == 200

    # Force a pending settlement, as if days passed since archiving.
    session = next(auth_client.app.dependency_overrides[get_session]())
    combine = session.get(Combine, c["id"])
    combine.last_settled_at = None
    session.commit()
    session.close()

    before = len(_events(auth_client, "settled"))
    auth_client.get("/api/combines")
    auth_client.get("/api/combines")
    after = len(_events(auth_client, "settled"))
    assert after == before

    session = next(auth_client.app.dependency_overrides[get_session]())
    combine = session.get(Combine, c["id"])
    assert combine.last_settled_at is None  # still frozen, not re-stamped
    session.close()
