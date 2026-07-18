"""Legal consent — /api/legal/* + the services.legal gates.

Covers: acceptance idempotency, version-bump staleness, the consent and
funded-agreement 403 gates (machine-readable "<code>: …" details), typed-name
e-sign validation, and IP capture on the acceptance rows.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.agreement import AgreementAcceptance
from models.user import User
from services.legal import (
    LEGAL_DOC_VERSIONS,
    assert_consented,
    assert_funded_agreement_signed,
)

ALL_DOCS = ("tos", "privacy", "refund", "risk", "funded_agreement")


def _acceptance_rows(session_factory, doc_key: str | None = None):
    session = session_factory()
    try:
        stmt = select(AgreementAcceptance)
        if doc_key is not None:
            stmt = stmt.where(AgreementAcceptance.doc_key == doc_key)
        return session.execute(stmt).scalars().all()
    finally:
        session.close()


def _with_user(session_factory, email: str = "trader@test.local"):
    """(session, user) for direct service-gate calls. Caller closes."""
    session = session_factory()
    user = session.execute(select(User).where(User.email == email)).scalar_one()
    return session, user


# -- auth boundary -----------------------------------------------------------


def test_legal_endpoints_require_auth(api_client):
    assert api_client.get("/api/legal/status").status_code == 401
    assert (
        api_client.post("/api/legal/accept", json={"doc_keys": ["tos"]}).status_code
        == 401
    )
    assert (
        api_client.post(
            "/api/legal/sign-funded-agreement", json={"typed_name": "A Name"}
        ).status_code
        == 401
    )


# -- status map ---------------------------------------------------------------


def test_status_starts_unaccepted_for_all_docs(auth_client):
    res = auth_client.get("/api/legal/status")
    assert res.status_code == 200
    status = res.json()
    assert set(status) == set(ALL_DOCS)
    for key in ALL_DOCS:
        assert status[key]["accepted_version"] is None
        assert status[key]["current_version"] == LEGAL_DOC_VERSIONS[key]
        assert status[key]["current"] is False


# -- acceptance + idempotency --------------------------------------------------


def test_accept_records_current_versions(auth_client, session_factory):
    res = auth_client.post("/api/legal/accept", json={"doc_keys": ["tos", "risk"]})
    assert res.status_code == 200
    status = res.json()
    assert status["tos"] == {
        "accepted_version": 1,
        "current_version": 1,
        "current": True,
    }
    assert status["risk"]["current"] is True
    assert status["privacy"]["current"] is False

    rows = _acceptance_rows(session_factory)
    assert {(r.doc_key, r.doc_version) for r in rows} == {("tos", 1), ("risk", 1)}
    # Client IP captured on every acceptance row (dispute evidence).
    assert all(r.ip for r in rows)
    assert all(r.signature_name is None for r in rows)


def test_reaccepting_same_version_is_a_noop(auth_client, session_factory):
    auth_client.post("/api/legal/accept", json={"doc_keys": ["tos", "risk"]})
    auth_client.post("/api/legal/accept", json={"doc_keys": ["tos", "risk"]})
    # Duplicate keys within ONE request are also collapsed.
    auth_client.post("/api/legal/accept", json={"doc_keys": ["tos", "tos"]})
    assert len(_acceptance_rows(session_factory)) == 2


def test_unknown_doc_key_is_422(auth_client, session_factory):
    res = auth_client.post(
        "/api/legal/accept", json={"doc_keys": ["tos", "not_a_doc"]}
    )
    assert res.status_code == 422
    assert res.json()["detail"].startswith("unknown_doc_key:")
    # Nothing partial lands — the whole request is refused.
    assert _acceptance_rows(session_factory) == []


def test_empty_doc_keys_is_422(auth_client):
    res = auth_client.post("/api/legal/accept", json={"doc_keys": []})
    assert res.status_code == 422


# -- version bump = staleness ---------------------------------------------------


def test_version_bump_makes_acceptance_stale(auth_client, session_factory, monkeypatch):
    auth_client.post("/api/legal/accept", json={"doc_keys": ["tos", "risk"]})

    monkeypatch.setitem(LEGAL_DOC_VERSIONS, "tos", 2)

    status = auth_client.get("/api/legal/status").json()
    assert status["tos"] == {
        "accepted_version": 1,
        "current_version": 2,
        "current": False,
    }
    assert status["risk"]["current"] is True  # unbumped docs unaffected

    # The stale doc gates again until re-accepted at the new version.
    session, user = _with_user(session_factory)
    try:
        with pytest.raises(HTTPException) as exc:
            assert_consented(session, user)
        assert exc.value.status_code == 403
        assert exc.value.detail.startswith("consent_required:")
    finally:
        session.close()

    # Re-accept → a NEW row at v2 (v1 row is history, not overwritten).
    res = auth_client.post("/api/legal/accept", json={"doc_keys": ["tos"]})
    assert res.json()["tos"]["current"] is True
    tos_rows = _acceptance_rows(session_factory, "tos")
    assert sorted(r.doc_version for r in tos_rows) == [1, 2]


# -- consent gate ---------------------------------------------------------------


def test_assert_consented_requires_both_tos_and_risk(auth_client, session_factory):
    session, user = _with_user(session_factory)
    try:
        with pytest.raises(HTTPException) as exc:
            assert_consented(session, user)
        assert exc.value.status_code == 403
        assert exc.value.detail.startswith("consent_required:")
    finally:
        session.close()

    # tos alone is NOT enough — risk disclosure is required too.
    auth_client.post("/api/legal/accept", json={"doc_keys": ["tos"]})
    session, user = _with_user(session_factory)
    try:
        with pytest.raises(HTTPException) as exc:
            assert_consented(session, user)
        assert exc.value.status_code == 403
    finally:
        session.close()

    auth_client.post("/api/legal/accept", json={"doc_keys": ["risk"]})
    session, user = _with_user(session_factory)
    try:
        assert_consented(session, user)  # no raise
    finally:
        session.close()


# -- funded-agreement e-sign ------------------------------------------------------


def test_checkbox_acceptance_does_not_satisfy_esign_gate(auth_client, session_factory):
    # Accepting funded_agreement WITHOUT a typed name (checkbox path) must
    # not unlock activation — the gate requires a signature.
    auth_client.post("/api/legal/accept", json={"doc_keys": ["funded_agreement"]})
    session, user = _with_user(session_factory)
    try:
        with pytest.raises(HTTPException) as exc:
            assert_funded_agreement_signed(session, user)
        assert exc.value.status_code == 403
        assert exc.value.detail.startswith("agreement_required:")
    finally:
        session.close()


def test_sign_funded_agreement_records_stripped_name(auth_client, session_factory):
    res = auth_client.post(
        "/api/legal/sign-funded-agreement", json={"typed_name": "  Shrey Valia  "}
    )
    assert res.status_code == 200
    assert res.json()["funded_agreement"]["current"] is True

    rows = _acceptance_rows(session_factory, "funded_agreement")
    assert len(rows) == 1
    assert rows[0].signature_name == "Shrey Valia"
    assert rows[0].ip

    session, user = _with_user(session_factory)
    try:
        assert_funded_agreement_signed(session, user)  # no raise
    finally:
        session.close()


def test_sign_after_checkbox_accept_still_appends_signed_row(
    auth_client, session_factory
):
    auth_client.post("/api/legal/accept", json={"doc_keys": ["funded_agreement"]})
    res = auth_client.post(
        "/api/legal/sign-funded-agreement", json={"typed_name": "Shrey Valia"}
    )
    assert res.status_code == 200
    rows = _acceptance_rows(session_factory, "funded_agreement")
    # Unsigned checkbox row + the signed row — both history, one signature.
    assert len(rows) == 2
    assert sorted(bool(r.signature_name) for r in rows) == [False, True]

    session, user = _with_user(session_factory)
    try:
        assert_funded_agreement_signed(session, user)
    finally:
        session.close()


def test_resigning_same_version_is_a_noop(auth_client, session_factory):
    auth_client.post(
        "/api/legal/sign-funded-agreement", json={"typed_name": "Shrey Valia"}
    )
    auth_client.post(
        "/api/legal/sign-funded-agreement", json={"typed_name": "Someone Else"}
    )
    rows = _acceptance_rows(session_factory, "funded_agreement")
    # The FIRST signature is the binding record; a re-sign doesn't duplicate.
    assert len(rows) == 1
    assert rows[0].signature_name == "Shrey Valia"


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 121])
def test_typed_name_must_be_present_and_bounded(auth_client, bad_name):
    res = auth_client.post(
        "/api/legal/sign-funded-agreement", json={"typed_name": bad_name}
    )
    assert res.status_code == 422


def test_acceptances_are_per_user(auth_client, second_user_client, session_factory):
    auth_client.post("/api/legal/accept", json={"doc_keys": ["tos", "risk"]})
    status = second_user_client.get("/api/legal/status").json()
    assert status["tos"]["current"] is False

    session, rival = _with_user(session_factory, "rival@test.local")
    try:
        with pytest.raises(HTTPException):
            assert_consented(session, rival)
    finally:
        session.close()
