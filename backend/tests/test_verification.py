"""Payout prerequisites — KYC, tax profile, payout methods (workstream B2).

Endpoint coverage through the real auth stack (conftest auth_client), plus
service-level coverage of `decide_kyc` and `assert_payout_eligible` (whose
router consumers land in later workstreams C1/C2).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from config import settings
from models.kyc import KycVerification
from models.payout_method import PayoutMethod, TaxProfile
from models.user import User
from services import verification

ADULT_DOB = "1990-04-12"


# -- helpers -------------------------------------------------------------------

def _submit_kyc(client, country="US", dob=ADULT_DOB, **overrides):
    payload = {
        "legal_name": "Pat Trader",
        "dob": dob,
        "country": country,
        "document_type": "passport",
    }
    payload.update(overrides)
    return client.post("/api/verification/kyc/submit", json=payload)


def _submit_tax(client, form_type="W9", country="US", tin_last4="1234", **overrides):
    payload = {
        "form_type": form_type,
        "legal_name": "Pat Trader",
        "country": country,
        "address": {
            "line1": "1 Main St",
            "city": "Austin",
            "region": "TX",
            "postal": "78701",
            "country": country,
        },
        "tin_last4": tin_last4,
    }
    payload.update(overrides)
    return client.post("/api/verification/tax/submit", json=payload)


def _add_ach(client, label="Chase ****6789", routing="021000021", last4="6789"):
    return client.post(
        "/api/verification/methods",
        json={
            "type": "ach",
            "label": label,
            "details": {"routing_number": routing, "account_last4": last4},
        },
    )


def _add_wire(client, label="HSBC wire"):
    return client.post(
        "/api/verification/methods",
        json={
            "type": "wire",
            "label": label,
            "details": {
                "bank_name": "HSBC",
                "swift": "HBUKGB4B",
                "account_last4": "4321",
            },
        },
    )


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _user(db, email="trader@test.local") -> User:
    return db.execute(select(User).where(User.email == email)).scalar_one()


# -- status baseline -----------------------------------------------------------

def test_status_fresh_user(auth_client):
    res = auth_client.get("/api/verification/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kyc"] == {"status": "unverified", "reject_reason": None}
    assert body["tax"] == {"submitted": False, "form_type": None}
    assert body["payout_methods"] == []
    assert body["requirements"] == {"kyc": True, "tax": True, "method": True}


def test_status_requires_auth(client):
    assert client.get("/api/verification/status").status_code == 401


def test_requirements_mirror_settings(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "payout_require_kyc", False, raising=False)
    monkeypatch.setattr(settings, "payout_require_tax_profile", False, raising=False)
    body = auth_client.get("/api/verification/status").json()
    assert body["requirements"] == {"kyc": False, "tax": False, "method": True}


# -- KYC -----------------------------------------------------------------------

def test_kyc_auto_verify_happy_path(auth_client):
    res = _submit_kyc(auth_client)
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "verified", "reject_reason": None}
    status = auth_client.get("/api/verification/status").json()["kyc"]
    assert status["status"] == "verified"


def test_kyc_ofac_country_rejected_then_resubmit(auth_client, db):
    # Lower-case input exercises the ISO-2 normalization on the way in.
    res = _submit_kyc(auth_client, country="ir")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "rejected"
    assert body["reject_reason"] == verification.OFAC_REJECT_REASON

    # A rejected user may resubmit; the single row is REPLACED, not duplicated.
    res = _submit_kyc(auth_client, country="US")
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "verified", "reject_reason": None}
    rows = db.execute(select(KycVerification)).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "verified"
    assert rows[0].decided_at is not None
    assert json.loads(rows[0].submitted_json)["country"] == "US"


def test_kyc_verified_resubmit_409(auth_client):
    assert _submit_kyc(auth_client).status_code == 200
    res = _submit_kyc(auth_client)
    assert res.status_code == 409
    assert res.json()["detail"].startswith("already_verified:")


def test_kyc_pending_when_auto_verify_off(auth_client, db, monkeypatch):
    monkeypatch.setattr(settings, "kyc_auto_verify", False, raising=False)
    res = _submit_kyc(auth_client)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending"
    row = db.execute(select(KycVerification)).scalar_one()
    assert row.decided_at is None

    # Admin approval path (the admin router wires this in workstream C2).
    decided = verification.decide_kyc(db, _user(db).id, approve=True)
    assert decided.status == "verified"
    assert decided.decided_at is not None
    assert auth_client.get("/api/verification/status").json()["kyc"]["status"] == "verified"


def test_kyc_admin_reject_reason_surfaces(auth_client, db, monkeypatch):
    monkeypatch.setattr(settings, "kyc_auto_verify", False, raising=False)
    assert _submit_kyc(auth_client).status_code == 200
    verification.decide_kyc(db, _user(db).id, approve=False, reason="Document unreadable")
    kyc = auth_client.get("/api/verification/status").json()["kyc"]
    assert kyc == {"status": "rejected", "reject_reason": "Document unreadable"}
    # Rejected → resubmit parks at pending again (still one row).
    assert _submit_kyc(auth_client).json()["status"] == "pending"
    assert len(db.execute(select(KycVerification)).scalars().all()) == 1


def test_decide_kyc_unknown_user_404(db):
    with pytest.raises(HTTPException) as exc:
        verification.decide_kyc(db, 999_999, approve=True)
    assert exc.value.status_code == 404


def test_kyc_under_18_422(auth_client):
    almost_18 = datetime.now(timezone.utc).date() - timedelta(days=17 * 365)
    res = _submit_kyc(auth_client, dob=almost_18.isoformat())
    assert res.status_code == 422
    assert "18" in res.text


def test_kyc_invalid_dates_422(auth_client):
    assert _submit_kyc(auth_client, dob="1990-02-30").status_code == 422
    assert _submit_kyc(auth_client, dob="not-a-date").status_code == 422


def test_kyc_invalid_country_422(auth_client):
    # Wrong length dies at the schema; right length but non-alpha dies in the
    # service's ISO-2 check.
    assert _submit_kyc(auth_client, country="USA").status_code == 422
    res = _submit_kyc(auth_client, country="U1")
    assert res.status_code == 422
    assert res.json()["detail"].startswith("invalid_country:")


def test_kyc_invalid_document_type_422(auth_client):
    assert _submit_kyc(auth_client, document_type="library_card").status_code == 422


# -- Tax profile ---------------------------------------------------------------

def test_tax_w9_happy_path_and_upsert(auth_client, db):
    res = _submit_tax(auth_client)
    assert res.status_code == 200, res.text
    assert res.json() == {"submitted": True, "form_type": "W9"}

    # Resubmitting REPLACES the single row (form switch included).
    res = _submit_tax(auth_client, form_type="W8BEN", country="GB", tin_last4=None)
    assert res.status_code == 200, res.text
    rows = db.execute(select(TaxProfile)).scalars().all()
    assert len(rows) == 1
    assert rows[0].form_type == "W8BEN"
    assert rows[0].country == "GB"
    assert rows[0].tin_last4 is None
    tax = auth_client.get("/api/verification/status").json()["tax"]
    assert tax == {"submitted": True, "form_type": "W8BEN"}


def test_tax_w9_requires_us_country(auth_client):
    res = _submit_tax(auth_client, form_type="W9", country="GB")
    assert res.status_code == 422
    assert res.json()["detail"].startswith("form_country_mismatch:")


def test_tax_w8ben_requires_non_us_country(auth_client):
    res = _submit_tax(auth_client, form_type="W8BEN", country="US")
    assert res.status_code == 422
    assert res.json()["detail"].startswith("form_country_mismatch:")


def test_tax_country_normalized(auth_client, db):
    assert _submit_tax(auth_client, country="us").status_code == 200
    assert db.execute(select(TaxProfile)).scalar_one().country == "US"


def test_tax_tin_last4_format_422(auth_client):
    res = _submit_tax(auth_client, tin_last4="12a4")
    assert res.status_code == 422
    assert res.json()["detail"].startswith("invalid_tin_last4:")


def test_tax_invalid_form_type_422(auth_client):
    assert _submit_tax(auth_client, form_type="1040").status_code == 422


# -- Payout methods --------------------------------------------------------------

def test_method_crud_and_default_uniqueness(auth_client):
    first = _add_ach(auth_client)
    assert first.status_code == 201, first.text
    assert first.json()["is_default"] is True  # first method auto-defaults

    second = _add_wire(auth_client)
    assert second.status_code == 201, second.text
    assert second.json()["is_default"] is False

    # Promote the wire method; exactly one default afterwards.
    res = auth_client.post(f"/api/verification/methods/{second.json()['id']}/default")
    assert res.status_code == 200, res.text
    methods = res.json()
    assert [m["is_default"] for m in methods].count(True) == 1
    assert next(m for m in methods if m["is_default"])["id"] == second.json()["id"]

    # Removing the DEFAULT promotes the oldest survivor.
    res = auth_client.delete(f"/api/verification/methods/{second.json()['id']}")
    assert res.status_code == 204
    methods = auth_client.get("/api/verification/status").json()["payout_methods"]
    assert len(methods) == 1
    assert methods[0]["id"] == first.json()["id"]
    assert methods[0]["is_default"] is True

    res = auth_client.delete(f"/api/verification/methods/{first.json()['id']}")
    assert res.status_code == 204
    assert auth_client.get("/api/verification/status").json()["payout_methods"] == []


def test_method_details_never_leak(auth_client):
    """The raw rail details (routing number, SWIFT, address) must not appear in
    ANY response body — only the masked {id,type,label,is_default,created_at}."""
    routing = "021000021"
    created = _add_ach(auth_client, routing=routing)
    assert created.status_code == 201
    assert routing not in created.text
    assert "routing_number" not in created.text
    assert "details" not in created.json()

    status = auth_client.get("/api/verification/status")
    assert routing not in status.text
    assert "routing_number" not in status.text
    assert set(status.json()["payout_methods"][0]) == {
        "id", "type", "label", "is_default", "created_at",
    }

    promoted = auth_client.post(
        f"/api/verification/methods/{created.json()['id']}/default"
    )
    assert routing not in promoted.text
    assert "routing_number" not in promoted.text


def test_method_details_whitelisted_in_storage(auth_client, db):
    """Stray keys (e.g. a full account number) are dropped before storage."""
    res = auth_client.post(
        "/api/verification/methods",
        json={
            "type": "ach",
            "label": "Chase",
            "details": {
                "routing_number": "021000021",
                "account_last4": "6789",
                "account_number": "000123456789",  # must never be persisted
            },
        },
    )
    assert res.status_code == 201, res.text
    stored = json.loads(db.execute(select(PayoutMethod)).scalar_one().details_json)
    assert set(stored) == {"routing_number", "account_last4"}


def test_method_crypto_happy_path(auth_client):
    res = auth_client.post(
        "/api/verification/methods",
        json={
            "type": "crypto",
            "label": "USDC wallet",
            "details": {"network": "USDC-SOL", "address": "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"},
        },
    )
    assert res.status_code == 201, res.text


def test_method_validation_422(auth_client):
    # Unknown type dies at the schema.
    res = auth_client.post(
        "/api/verification/methods",
        json={"type": "paypal", "label": "x", "details": {}},
    )
    assert res.status_code == 422

    # Missing required rail key.
    res = auth_client.post(
        "/api/verification/methods",
        json={"type": "ach", "label": "x", "details": {"account_last4": "6789"}},
    )
    assert res.status_code == 422
    assert res.json()["detail"].startswith("missing_detail:")

    # Routing number must be exactly 9 digits.
    assert _add_ach(auth_client, routing="12345678").status_code == 422

    # account_last4 must be exactly 4 digits.
    assert _add_ach(auth_client, last4="678").status_code == 422

    # Wire requires swift.
    res = auth_client.post(
        "/api/verification/methods",
        json={
            "type": "wire",
            "label": "x",
            "details": {"bank_name": "HSBC", "account_last4": "4321"},
        },
    )
    assert res.status_code == 422

    # Crypto network must be a supported rail.
    res = auth_client.post(
        "/api/verification/methods",
        json={
            "type": "crypto",
            "label": "x",
            "details": {"network": "DOGE", "address": "D6abc"},
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"].startswith("invalid_network:")


def test_method_cross_user_404(auth_client, second_user_client):
    created = _add_ach(auth_client)
    assert created.status_code == 201
    method_id = created.json()["id"]

    assert second_user_client.delete(
        f"/api/verification/methods/{method_id}"
    ).status_code == 404
    assert second_user_client.post(
        f"/api/verification/methods/{method_id}/default"
    ).status_code == 404
    # Still on file for the owner.
    assert len(auth_client.get("/api/verification/status").json()["payout_methods"]) == 1


def test_method_delete_unknown_404(auth_client):
    assert auth_client.delete("/api/verification/methods/12345").status_code == 404


# -- assert_payout_eligible (the C1 gate) -----------------------------------------

def _assert_blocked_with(db, user, code: str) -> None:
    with pytest.raises(HTTPException) as exc:
        verification.assert_payout_eligible(db, user)
    assert exc.value.status_code == 403
    assert exc.value.detail.startswith(code + ":")


def test_assert_payout_eligible_walks_each_gate(auth_client, db):
    user = _user(db)
    _assert_blocked_with(db, user, "kyc_required")

    assert _submit_kyc(auth_client).status_code == 200
    db.expire_all()
    _assert_blocked_with(db, user, "tax_profile_required")

    assert _submit_tax(auth_client).status_code == 200
    db.expire_all()
    _assert_blocked_with(db, user, "payout_method_required")

    assert _add_ach(auth_client).status_code == 201
    db.expire_all()
    verification.assert_payout_eligible(db, user)  # no raise — fully eligible


def test_assert_payout_eligible_pending_and_rejected_block(auth_client, db, monkeypatch):
    user = _user(db)
    monkeypatch.setattr(settings, "kyc_auto_verify", False, raising=False)
    assert _submit_kyc(auth_client).status_code == 200  # parks at pending
    db.expire_all()
    _assert_blocked_with(db, user, "kyc_required")

    verification.decide_kyc(db, user.id, approve=False, reason="nope")
    _assert_blocked_with(db, user, "kyc_required")


def test_assert_payout_eligible_toggles(auth_client, db, monkeypatch):
    user = _user(db)

    # Each toggle individually skips its gate, exposing the NEXT one.
    monkeypatch.setattr(settings, "payout_require_kyc", False, raising=False)
    _assert_blocked_with(db, user, "tax_profile_required")

    monkeypatch.setattr(settings, "payout_require_tax_profile", False, raising=False)
    _assert_blocked_with(db, user, "payout_method_required")

    monkeypatch.setattr(settings, "payout_require_method", False, raising=False)
    verification.assert_payout_eligible(db, user)  # everything relaxed — no raise
