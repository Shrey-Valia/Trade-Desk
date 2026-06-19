"""Scaling plan — contract-size table, snapshot wiring, and open enforcement."""

from __future__ import annotations

import types
from datetime import datetime

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from models.combine import Combine
from routers import zerodte
from services.combine_state import combine_snapshot
from services.scaling_plan import max_contracts
from tests.conftest import make_combine

_TODAY = datetime.now(zerodte._ET).date()


# --- pure table -------------------------------------------------------------


def test_50k_table():
    assert max_contracts("50K", 0) == 2
    assert max_contracts("50K", 1_499) == 2
    assert max_contracts("50K", 1_500) == 3
    assert max_contracts("50K", 1_999) == 3
    assert max_contracts("50K", 2_000) == 5
    assert max_contracts("50K", 9_999) == 5


def test_100k_and_150k_tables():
    assert max_contracts("100K", 0) == 4
    assert max_contracts("100K", 3_000) == 6
    assert max_contracts("100K", 4_000) == 10
    assert max_contracts("150K", 0) == 6
    assert max_contracts("150K", 4_500) == 9
    assert max_contracts("150K", 6_000) == 15


def test_unknown_tier_fails_safe():
    assert max_contracts("999K", 100_000) == 1


# --- snapshot ---------------------------------------------------------------


def test_fresh_combine_starts_at_base_size(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    s = session_factory()
    snap = combine_snapshot(s, s.get(Combine, c["id"]))
    assert snap.max_contracts == 2  # settled_hwm == start → 0 profit
    s.close()


def test_built_equity_scales_up(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    s = session_factory()
    combine = s.get(Combine, c["id"])
    combine.settled_hwm = 52_000.0  # +$2,000 built equity
    s.commit()
    snap = combine_snapshot(s, combine)
    assert snap.max_contracts == 5
    s.close()


# --- open enforcement -------------------------------------------------------


def _stub_market(monkeypatch):
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot",
        lambda sym, with_volume=False: [types.SimpleNamespace(expiry=_TODAY)],
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def test_open_over_scaling_limit_rejected(auth_client, monkeypatch):
    make_combine(auth_client, "50K")  # base max = 2 contracts
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy",
              "strike": 100, "entry_price": 1.0, "contracts": 3},
    )
    assert res.status_code == 422
    assert "scaling plan" in res.json()["detail"].lower()


def test_open_within_scaling_limit_ok(auth_client, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy",
              "strike": 100, "entry_price": 1.0, "contracts": 2},
    )
    assert res.status_code == 201, res.text


def test_account_state_exposes_max_contracts(auth_client):
    make_combine(auth_client, "50K")
    body = auth_client.get("/api/account/state").json()
    assert body["max_contracts"] == 2
