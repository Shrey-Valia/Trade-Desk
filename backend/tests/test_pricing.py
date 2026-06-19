"""Combine pricing matrix + the funded-account activation gate.

Covers the pure pricing module, the path/split choices flowing through the
purchase endpoint into the payment ledger, and the $149 activation gate on
payouts (activation path) vs the free auto-activation (no_activation path).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from models.combine import Combine
from models.combine_event import CombineEvent
from models.payment import Payment
from models.user import User
from services import pricing
from services.account_tiers import TIERS


# --- pure pricing module --------------------------------------------------


def test_base_monthly_matrix():
    # With-activation, 80/20 (the base): D1 + $20 options premium.
    assert pricing.monthly_price("50K") == 69.0
    assert pricing.monthly_price("100K") == 119.0
    assert pricing.monthly_price("150K") == 169.0


def test_no_activation_adds_flat_premium():
    assert pricing.monthly_price("50K", "no_activation") == 119.0
    assert pricing.monthly_price("100K", "no_activation") == 169.0
    assert pricing.monthly_price("150K", "no_activation") == 219.0


def test_fifty_fifty_split_discount():
    assert pricing.monthly_price("50K", "activation", 0.50) == 59.0
    assert pricing.monthly_price("100K", "no_activation", 0.50) == 159.0
    assert pricing.monthly_price("150K", "activation", 0.50) == 159.0


def test_activation_fee_by_path():
    assert pricing.activation_fee("activation") == 149.0
    assert pricing.activation_fee("no_activation") == 0.0


def test_split_token_roundtrip():
    assert pricing.split_value("80_20") == 0.80
    assert pricing.split_value("50_50") == 0.50
    assert pricing.split_value("garbage") == pricing.DEFAULT_SPLIT
    assert pricing.split_token(0.50) == "50_50"
    assert pricing.split_token(0.80) == "80_20"


# --- purchase carries the chosen path + split -----------------------------


def test_purchase_no_activation_path(auth_client, session_factory):
    body = auth_client.post(
        "/api/combines/purchase",
        json={"tier": "50K", "pricing_path": "no_activation"},
    ).json()
    assert body["pricing_path"] == "no_activation"
    assert body["monthly_price"] == 119.0
    assert body["activation_fee"] == 0.0
    with session_factory() as s:
        payment = s.execute(select(Payment)).scalars().one()
        assert payment.amount == 119.0
        assert payment.status == "paid"


def test_purchase_fifty_fifty_split(auth_client, session_factory):
    body = auth_client.post(
        "/api/combines/purchase",
        json={"tier": "100K", "split": "50_50"},
    ).json()
    assert body["profit_split"] == 0.50
    assert body["monthly_price"] == 109.0  # 119 base − 10 split discount
    with session_factory() as s:
        combine = s.execute(select(Combine)).scalars().one()
        assert combine.profit_split == 0.50
        assert combine.pricing_path == "activation"


# --- funded-account activation gate ---------------------------------------


def _trader_id(session_factory) -> int:
    with session_factory() as s:
        return s.execute(
            select(User.id).where(User.email == "trader@test.local")
        ).scalar_one()


def _insert_funded_combine(
    session_factory,
    uid: int,
    *,
    path: str = "activation",
    split: float = 0.80,
    tier: str = "50K",
    activated: bool = False,
) -> int:
    """Insert a passed/funded combine directly (skips the eval) so the
    activation gate can be tested without simulating a winning streak."""
    now = datetime.now(timezone.utc)
    start = TIERS[tier].starting_balance
    with session_factory() as s:
        c = Combine(
            user_id=uid,
            tier=tier,
            name=f"{tier} Funded",
            account_code=f"{tier}TC-{uid}-90000001",
            hwm=start,
            settled_hwm=start,
            last_settled_at=now,
            status="active",
            outcome="passed",
            funded_at=now,
            funded_activated_at=now if activated else None,
            pricing_path=path,
            profit_split=split,
        )
        s.add(c)
        s.commit()
        return c.id


def test_activation_path_locks_payout_until_paid(auth_client, session_factory):
    uid = _trader_id(session_factory)
    cid = _insert_funded_combine(session_factory, uid, path="activation")

    # Funded but not activated → the combine surfaces the activation gate.
    listing = auth_client.get("/api/combines").json()
    row = next(c for c in listing["combines"] if c["id"] == cid)
    assert row["funded"] is True
    assert row["activation_required"] is True
    assert row["activation_fee"] == 149.0
    assert row["funded_activated"] is False

    # Payout is blocked with the activation message.
    res = auth_client.post(f"/api/combines/{cid}/payout")
    assert res.status_code == 409
    assert "activation" in res.json()["detail"].lower()

    # Pay the activation fee → unlocks.
    paid = auth_client.post(f"/api/combines/{cid}/activate-account")
    assert paid.status_code == 200, paid.text
    body = paid.json()
    assert body["funded_activated"] is True
    assert body["activation_required"] is False

    # A $149 activation payment + event were recorded.
    with session_factory() as s:
        pay = s.execute(
            select(Payment).where(Payment.status == "activation_paid")
        ).scalars().one()
        assert pay.amount == 149.0
        ev = s.execute(
            select(CombineEvent).where(CombineEvent.type == "activation")
        ).scalars().one()
        assert ev.amount == 149.0

    # Gate is lifted: payout now fails only for lack of profit, not activation.
    res2 = auth_client.post(f"/api/combines/{cid}/payout")
    assert res2.status_code == 409
    assert "activation" not in res2.json()["detail"].lower()


def test_no_activation_path_activates_for_free(auth_client, session_factory):
    """No-activation funded accounts still go through the SAME activate step
    — the fee is just $0 — so the UX is one unified flow."""
    uid = _trader_id(session_factory)
    cid = _insert_funded_combine(session_factory, uid, path="no_activation")

    row = next(
        c for c in auth_client.get("/api/combines").json()["combines"] if c["id"] == cid
    )
    assert row["funded"] is True
    assert row["activation_required"] is True
    assert row["activation_fee"] == 0.0
    assert row["funded_activated"] is False

    # Activate for $0 → unlocks; no $0 payment row is written.
    body = auth_client.post(f"/api/combines/{cid}/activate-account").json()
    assert body["funded_activated"] is True
    assert body["activation_required"] is False
    with session_factory() as s:
        paid = s.execute(
            select(Payment).where(Payment.status == "activation_paid")
        ).scalars().all()
        assert paid == []  # no payment row for a $0 activation
        ev = s.execute(
            select(CombineEvent).where(CombineEvent.type == "activation")
        ).scalars().one()
        assert ev.amount == 0.0

    # Already activated → second activate is a 409.
    res = auth_client.post(f"/api/combines/{cid}/activate-account")
    assert res.status_code == 409
    assert "already activated" in res.json()["detail"]
