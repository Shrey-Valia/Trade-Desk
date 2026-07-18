"""/api/zerodte/preview-multi — the builder's risk graph for arbitrary legs."""

from __future__ import annotations

import types
from datetime import datetime

import pytest

from routers import zerodte

_TODAY = datetime.now(zerodte._ET).date()


@pytest.fixture()
def stubbed_chain(monkeypatch):
    """Chain rows around 100 with distinct call/put quotes so net premiums
    are deterministic: calls mid 1.1, puts mid 1.1 (bid 1.0 / ask 1.2)."""
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=_TODAY,
            bid=1.0, ask=1.2, last=None, open_interest=None, iv=0.25,
        )
        for k in (95.0, 100.0, 105.0)
        for side in ("call", "put")
    ]
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def _legs_vertical():
    return [
        {"side": "call", "action": "buy", "strike": 100.0, "ratio": 1},
        {"side": "call", "action": "sell", "strike": 105.0, "ratio": 1},
    ]


def test_preview_multi_debit_vertical(auth_client, stubbed_chain):
    res = auth_client.post(
        "/api/zerodte/preview-multi",
        json={"symbol": "SPY", "contracts": 1, "legs": _legs_vertical()},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "multi"
    # Both legs quote mid 1.1 → net ≈ 0, but the structure is defined-risk:
    # bounded both sides, one breakeven, POP defined.
    assert body["max_profit"] is not None
    assert body["max_loss"] is not None
    assert body["pop_long"] is not None
    assert 0.0 <= body["pop_long"] <= 1.0
    assert body["pop_short"] == pytest.approx(1.0 - body["pop_long"], abs=1e-6)


def test_preview_multi_credit_put_spread(auth_client, stubbed_chain):
    legs = [
        {"side": "put", "action": "sell", "strike": 100.0, "ratio": 1},
        {"side": "put", "action": "buy", "strike": 95.0, "ratio": 1},
    ]
    res = auth_client.post(
        "/api/zerodte/preview-multi",
        json={"symbol": "SPY", "contracts": 1, "legs": legs},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Defined-risk credit spread: bounded both ways; payoff flat above the
    # short strike (no net call exposure).
    assert body["max_profit"] is not None
    assert body["max_loss"] is not None
    assert body["prob_itm"] is None  # not a single-contract question


def test_preview_multi_naked_short_call_is_unbounded_loss(auth_client, stubbed_chain):
    legs = [
        {"side": "call", "action": "sell", "strike": 100.0, "ratio": 1},
        {"side": "put", "action": "sell", "strike": 100.0, "ratio": 1},
    ]
    res = auth_client.post(
        "/api/zerodte/preview-multi",
        json={"symbol": "SPY", "contracts": 1, "legs": legs},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["max_loss"] is None       # net short calls → unbounded loss
    assert body["max_profit"] is not None  # credit collected is the cap


def test_preview_multi_validates_leg_count(auth_client, stubbed_chain):
    res = auth_client.post(
        "/api/zerodte/preview-multi",
        json={
            "symbol": "SPY",
            "contracts": 1,
            "legs": [{"side": "call", "action": "buy", "strike": 100.0, "ratio": 1}],
        },
    )
    assert res.status_code == 422
