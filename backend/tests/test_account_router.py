"""Router tests for routers/account.py — gaps not covered elsewhere.

/state happy-path + 404 live in test_account_state.py, and the
dll-overrides clamping / unknown-tier / disable round-trip live in
test_rules_enforcement.py. This file fills the remaining gaps: auth gating
on the dll-overrides endpoints and the "editable before any combine is
purchased" default-empty read. Pure DB, no network.
"""

from __future__ import annotations


def test_get_dll_overrides_requires_auth(client):
    assert client.get("/api/account/dll-overrides").status_code == 401


def test_put_dll_overrides_requires_auth(client):
    res = client.put("/api/account/dll-overrides", json={"overrides": {"50K": 800}})
    assert res.status_code == 401


def test_get_dll_overrides_default_empty_before_any_combine(auth_client):
    """The Settings editor must work before a combine is purchased, so the
    GET returns empty defaults (no 404) for a fresh signup."""
    body = auth_client.get("/api/account/dll-overrides").json()
    assert body == {"overrides": {}, "disabled": []}


def test_dll_overrides_isolated_per_user(auth_client, second_user_client):
    """One user's overrides must not bleed into another's."""
    auth_client.put("/api/account/dll-overrides", json={"overrides": {"50K": 900}})
    # The rival user still sees their own empty defaults.
    rival = second_user_client.get("/api/account/dll-overrides").json()
    assert rival["overrides"] == {}
    # And the original user's value persisted (clamped into the 50K band).
    mine = auth_client.get("/api/account/dll-overrides").json()
    assert mine["overrides"]["50K"] == 900
