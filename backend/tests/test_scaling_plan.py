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
    # Flat cap: 5 contracts from the start, regardless of built equity.
    assert max_contracts("50K", 0) == 5
    assert max_contracts("50K", 9_999) == 5


def test_100k_and_150k_tables():
    # Flat per-tier caps from the start.
    assert max_contracts("100K", 0) == 10
    assert max_contracts("100K", 4_000) == 10
    assert max_contracts("150K", 0) == 15
    assert max_contracts("150K", 6_000) == 15


def test_unknown_tier_fails_safe():
    assert max_contracts("999K", 100_000) == 1


# --- snapshot ---------------------------------------------------------------


def test_fresh_combine_starts_at_base_size(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    s = session_factory()
    snap = combine_snapshot(s, s.get(Combine, c["id"]))
    assert snap.max_contracts == 5  # flat 50K cap from the start
    s.close()


def test_cap_is_flat_regardless_of_equity(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    s = session_factory()
    combine = s.get(Combine, c["id"])
    combine.settled_hwm = 52_000.0  # +$2,000 built equity
    s.commit()
    snap = combine_snapshot(s, combine)
    assert snap.max_contracts == 5  # flat cap — no build-equity ramp
    s.close()


# --- open enforcement -------------------------------------------------------


def _stub_market(monkeypatch, strikes=(95.0, 100.0, 105.0)):
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=_TODAY,
            bid=1.0, ask=1.2, last=None, open_interest=None, iv=None,
        )
        for k in strikes
        for side in ("call", "put")
    ]
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot",
        lambda sym, with_volume=False: rows,
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def test_open_over_scaling_limit_rejected(auth_client, monkeypatch):
    make_combine(auth_client, "50K")  # flat max = 5 contracts
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy",
              "strike": 100, "entry_price": 1.0, "contracts": 6},
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
    assert body["max_contracts"] == 5


def test_straddle_counts_two_contracts_against_cap(auth_client, monkeypatch):
    """A straddle is 2 legs, so it consumes 2× the per-leg size against the
    total-contract cap. With cap 5: a 3-contract straddle is 6 total → rejected;
    a 2-contract straddle is 4 total → ok."""
    make_combine(auth_client, "50K")  # cap 5
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr("routers.zerodte._require_today_expiry", lambda e: None)
    q = types.SimpleNamespace(bid=1.0, ask=1.2, last=1.1)
    monkeypatch.setattr(
        "routers.zerodte._resolve_atm_chain",
        lambda sym: ("SPY", 100.0, _TODAY, 100.0, q, q),
    )
    over = auth_client.post("/api/zerodte/open", json={"symbol": "SPY", "action": "buy", "contracts": 3})
    assert over.status_code == 422, over.text  # 3 × 2 legs = 6 > 5
    ok = auth_client.post("/api/zerodte/open", json={"symbol": "SPY", "action": "buy", "contracts": 2})
    assert ok.status_code == 201, ok.text  # 2 × 2 = 4 ≤ 5
    assert all(leg["contracts"] == 2 for leg in ok.json()["legs"])


def test_open_blocked_when_live_urpl_breaches_mll(auth_client, monkeypatch):
    """Fine on REALIZED P&L, but OPEN positions are deeply underwater (live MLL
    breach) → a new open is blocked. The order-time gate is mark-to-market
    aware, not realized-only."""
    make_combine(auth_client, "50K")  # balance 50,000; MLL floor 48,000
    _stub_market(monkeypatch)
    monkeypatch.setattr("routers.zerodte._live_combine_urpl", lambda s, c: -2_500.0)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy",
              "strike": 100, "entry_price": 1.0, "contracts": 1},
    )
    assert res.status_code == 403
    assert "mll" in res.json()["detail"].lower()


def test_open_allowed_when_live_urpl_small(auth_client, monkeypatch):
    """A small open loss that keeps the live balance above the floor doesn't
    block opening."""
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    monkeypatch.setattr("routers.zerodte._live_combine_urpl", lambda s, c: -100.0)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy",
              "strike": 100, "entry_price": 1.0, "contracts": 1},
    )
    assert res.status_code == 201, res.text
