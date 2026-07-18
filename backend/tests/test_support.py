"""Support tickets — /api/support/* (trader form + admin queue).

Covers: ticket creation with auto-attached combine context, validation,
own-ticket scoping, admin authz (403 for traders), the AdminAction audit row
on every admin change, and the support_reply Notification on an admin note.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import settings
from main import app
from models.admin_action import AdminAction
from models.notification import Notification
from tests.conftest import _signup, make_combine


@pytest.fixture
def admin_client(api_client, monkeypatch):
    """An authenticated ADMIN on the same database. Bootstraps through the
    settings.admin_emails allowlist (promoted on first admin-endpoint touch),
    exactly like the first real operator seat. Separate TestClient so cookie
    jars don't mix; api_client keeps the get_session override installed."""
    monkeypatch.setattr(settings, "admin_emails", ("admin@test.local",))
    c = TestClient(app)
    _signup(c, "admin@test.local")
    return c


def _create_ticket(client, **overrides) -> dict:
    payload = {
        "category": "billing",
        "subject": "Charged twice",
        "body": "My card shows two charges for the same combine.",
        **overrides,
    }
    res = client.post("/api/support/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _all_rows(session_factory, model):
    session = session_factory()
    try:
        return session.execute(select(model)).scalars().all()
    finally:
        session.close()


# -- auth boundary -----------------------------------------------------------


def test_support_endpoints_require_auth(api_client):
    assert api_client.get("/api/support/tickets").status_code == 401
    assert (
        api_client.post(
            "/api/support/tickets",
            json={"category": "bug", "subject": "s", "body": "b"},
        ).status_code
        == 401
    )


# -- creation -----------------------------------------------------------------


def test_create_ticket_without_combine_has_empty_context(auth_client):
    ticket = _create_ticket(auth_client)
    assert ticket["status"] == "open"
    assert ticket["context"] == {}
    assert ticket["admin_note"] is None
    assert ticket["category"] == "billing"


def test_create_ticket_attaches_active_combine_context(auth_client):
    combine = make_combine(auth_client, tier="50K")
    ticket = _create_ticket(auth_client, category="rule_dispute")
    assert ticket["context"] == {
        "combine_id": combine["id"],
        "tier": "50K",
        "status": "active",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "nonsense"},
        {"subject": ""},
        {"subject": "x" * 161},
        {"body": ""},
        {"body": "x" * 5001},
    ],
)
def test_create_ticket_validation(auth_client, overrides):
    payload = {
        "category": "bug",
        "subject": "Subject",
        "body": "Body",
        **overrides,
    }
    res = auth_client.post("/api/support/tickets", json=payload)
    assert res.status_code == 422


# -- own-ticket list ------------------------------------------------------------


def test_list_own_tickets_newest_first_and_scoped(auth_client, second_user_client):
    first = _create_ticket(auth_client, subject="first")
    second = _create_ticket(auth_client, subject="second")
    _create_ticket(second_user_client, subject="rival ticket")

    res = auth_client.get("/api/support/tickets")
    assert res.status_code == 200
    tickets = res.json()["tickets"]
    assert [t["id"] for t in tickets] == [second["id"], first["id"]]
    assert all(t["subject"] != "rival ticket" for t in tickets)


# -- admin authz ------------------------------------------------------------------


def test_admin_endpoints_reject_non_admin(auth_client):
    ticket = _create_ticket(auth_client)
    assert auth_client.get("/api/support/admin/tickets").status_code == 403
    res = auth_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}", json={"status": "closed"}
    )
    assert res.status_code == 403


# -- admin queue -------------------------------------------------------------------


def test_admin_queue_lists_all_users_with_email(
    auth_client, second_user_client, admin_client
):
    _create_ticket(auth_client, subject="mine")
    _create_ticket(second_user_client, subject="rivals", category="payout")

    res = admin_client.get("/api/support/admin/tickets")
    assert res.status_code == 200
    tickets = res.json()["tickets"]
    assert len(tickets) == 2
    emails = {t["user_email"] for t in tickets}
    assert emails == {"trader@test.local", "rival@test.local"}


def test_admin_queue_status_filter(auth_client, admin_client):
    open_ticket = _create_ticket(auth_client, subject="stays open")
    closing = _create_ticket(auth_client, subject="gets closed")
    admin_client.patch(
        f"/api/support/admin/tickets/{closing['id']}", json={"status": "closed"}
    )

    res = admin_client.get("/api/support/admin/tickets", params={"status": "open"})
    assert [t["id"] for t in res.json()["tickets"]] == [open_ticket["id"]]
    res = admin_client.get("/api/support/admin/tickets", params={"status": "closed"})
    assert [t["id"] for t in res.json()["tickets"]] == [closing["id"]]


# -- admin update: audit + notification -----------------------------------------------


def test_admin_update_writes_admin_action(auth_client, admin_client, session_factory):
    ticket = _create_ticket(auth_client)
    res = admin_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}",
        json={"status": "replied", "admin_note": "Refund issued."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "replied"
    assert body["admin_note"] == "Refund issued."
    assert body["user_email"] == "trader@test.local"

    actions = _all_rows(session_factory, AdminAction)
    assert len(actions) == 1
    action = actions[0]
    assert action.action == "support.update"
    assert action.target_type == "support_ticket"
    assert action.target_id == ticket["id"]
    assert json.loads(action.before_json) == {"status": "open", "admin_note": None}
    assert json.loads(action.after_json) == {
        "status": "replied",
        "admin_note": "Refund issued.",
    }


def test_admin_note_notifies_ticket_owner_truncated(
    auth_client, admin_client, session_factory
):
    ticket = _create_ticket(auth_client)
    long_note = "n" * 250
    admin_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}", json={"admin_note": long_note}
    )

    notes = _all_rows(session_factory, Notification)
    assert len(notes) == 1
    note = notes[0]
    assert note.kind == "support_reply"
    assert note.title == "Support replied to your ticket"
    assert note.body == "n" * 200  # first 200 chars only
    # Notification goes to the ticket's OWNER, not the admin.
    session = session_factory()
    try:
        from models.user import User

        owner = session.get(User, note.user_id)
        assert owner.email == "trader@test.local"
    finally:
        session.close()


def test_status_only_update_does_not_notify(auth_client, admin_client, session_factory):
    ticket = _create_ticket(auth_client)
    admin_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}", json={"status": "closed"}
    )
    assert _all_rows(session_factory, Notification) == []
    assert len(_all_rows(session_factory, AdminAction)) == 1


def test_noop_update_writes_no_audit_or_notification(
    auth_client, admin_client, session_factory
):
    ticket = _create_ticket(auth_client)
    admin_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}",
        json={"status": "replied", "admin_note": "done"},
    )
    # Same values again — nothing changed, nothing audited, no second ping.
    res = admin_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}",
        json={"status": "replied", "admin_note": "done"},
    )
    assert res.status_code == 200
    assert len(_all_rows(session_factory, AdminAction)) == 1
    assert len(_all_rows(session_factory, Notification)) == 1


def test_admin_update_edge_cases(auth_client, admin_client):
    ticket = _create_ticket(auth_client)
    # Empty payload → 400 (nothing to update).
    res = admin_client.patch(f"/api/support/admin/tickets/{ticket['id']}", json={})
    assert res.status_code == 400
    # Unknown ticket → 404.
    res = admin_client.patch(
        "/api/support/admin/tickets/999999", json={"status": "closed"}
    )
    assert res.status_code == 404
    # Illegal status → 422.
    res = admin_client.patch(
        f"/api/support/admin/tickets/{ticket['id']}", json={"status": "escalated"}
    )
    assert res.status_code == 422
