"""Combine lifecycle — purchase, 5-cap, rename, archive, activate,
cross-user isolation."""

from __future__ import annotations

import re

from sqlalchemy import select

from models.payment import Payment
from tests.conftest import make_combine


def test_combines_require_auth(client):
    assert client.get("/api/combines").status_code == 401
    assert (
        client.post("/api/combines/purchase", json={"tier": "50K"}).status_code == 401
    )


def test_purchase_creates_combine_and_payment(auth_client, session_factory):
    body = make_combine(auth_client, "50K")
    assert body["tier"] == "50K"
    assert body["name"] == "50K Combine"
    assert body["status"] == "active"
    assert body["starting_balance"] == 50_000
    assert body["balance"] == 50_000
    assert body["hwm"] == 50_000
    assert body["mll"] == 48_000
    assert body["profit_target"] == 3_000
    assert body["objective_progress"] == 0
    # Topstep-style account code.
    assert re.fullmatch(r"50KTC-\d+-\d{8}", body["account_code"])

    # Default plan: 80/20 split on the activation path → $69/mo for 50K.
    assert body["pricing_path"] == "activation"
    assert body["profit_split"] == 0.80
    assert body["monthly_price"] == 69.0

    with session_factory() as s:
        payments = s.execute(select(Payment)).scalars().all()
        assert len(payments) == 1
        assert payments[0].status == "paid"
        assert payments[0].amount == 69.0
        assert payments[0].combine_id == body["id"]
        assert payments[0].tier == "50K"


def test_purchase_custom_name(auth_client):
    body = make_combine(auth_client, "100K", name="My Big Eval")
    assert body["name"] == "My Big Eval"


def test_first_purchase_auto_activates(auth_client):
    c = make_combine(auth_client, "50K")
    listing = auth_client.get("/api/combines").json()
    assert listing["active_combine_id"] == c["id"]
    # Second purchase does NOT steal activation.
    make_combine(auth_client, "100K")
    listing = auth_client.get("/api/combines").json()
    assert listing["active_combine_id"] == c["id"]


def test_five_cap_blocks_sixth_purchase(auth_client):
    for i in range(5):
        make_combine(auth_client, "50K", name=f"C{i}")
    res = auth_client.post("/api/combines/purchase", json={"tier": "50K"})
    assert res.status_code == 409
    assert "combine limit" in res.json()["detail"]
    listing = auth_client.get("/api/combines").json()
    assert listing["slots_used"] == 5
    assert listing["slots_total"] == 5


def test_archive_frees_a_slot(auth_client):
    combines = [make_combine(auth_client, "50K", name=f"C{i}") for i in range(5)]
    assert (
        auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code
        == 409
    )
    archived = auth_client.post(f"/api/combines/{combines[0]['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    # Slot freed — purchase succeeds now.
    assert (
        auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code
        == 201
    )


def test_archiving_active_combine_repoints(auth_client):
    a = make_combine(auth_client, "50K", name="A")
    b = make_combine(auth_client, "100K", name="B")
    assert auth_client.get("/api/combines").json()["active_combine_id"] == a["id"]

    auth_client.post(f"/api/combines/{a['id']}/archive")
    # Repointed to the newest remaining active combine.
    assert auth_client.get("/api/combines").json()["active_combine_id"] == b["id"]

    auth_client.post(f"/api/combines/{b['id']}/archive")
    listing = auth_client.get("/api/combines").json()
    assert listing["active_combine_id"] is None
    assert listing["slots_used"] == 0
    # State now reports no active combine.
    assert auth_client.get("/api/account/state").status_code == 404


def test_rename(auth_client):
    c = make_combine(auth_client, "50K")
    res = auth_client.patch(
        f"/api/combines/{c['id']}", json={"name": "Renamed Eval"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed Eval"


def test_activate_switches_state(auth_client):
    make_combine(auth_client, "50K")
    b = make_combine(auth_client, "100K")
    state = auth_client.post(f"/api/combines/{b['id']}/activate").json()
    assert state["combine_id"] == b["id"]
    assert state["active_tier"] == "100K"
    assert auth_client.get("/api/account/state").json()["combine_id"] == b["id"]


def test_activate_archived_combine_409(auth_client):
    a = make_combine(auth_client, "50K")
    make_combine(auth_client, "100K")
    auth_client.post(f"/api/combines/{a['id']}/archive")
    assert auth_client.post(f"/api/combines/{a['id']}/activate").status_code == 409


def test_cross_user_combine_404(auth_client, second_user_client):
    c = make_combine(auth_client, "50K")
    assert (
        second_user_client.post(f"/api/combines/{c['id']}/activate").status_code == 404
    )
    assert (
        second_user_client.patch(
            f"/api/combines/{c['id']}", json={"name": "stolen"}
        ).status_code
        == 404
    )
    assert (
        second_user_client.post(f"/api/combines/{c['id']}/archive").status_code == 404
    )
    # And their listing is empty.
    assert second_user_client.get("/api/combines").json()["combines"] == []
