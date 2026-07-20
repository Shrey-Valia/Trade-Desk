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


# --- pre-trade time scrubber on /preview -------------------------------------


def _pin_session_clock(monkeypatch, hours=3.0):
    """Pin the chain table's time-to-close (wall-clock-free tests: after the
    bell the real value floors at 60s and nothing could decay)."""
    from calculations.intraday_analytics import SECONDS_PER_YEAR

    monkeypatch.setattr(
        "routers.zerodte._t_years_to_close",
        lambda: hours * 3600.0 / SECONDS_PER_YEAR,
    )


def test_preview_time_scrubber_decays_the_today_curve(
    auth_client, stubbed_chain, monkeypatch
):
    _pin_session_clock(monkeypatch, hours=3.0)
    base = auth_client.post(
        "/api/zerodte/preview",
        json={"symbol": "SPY", "kind": "leg", "side": "call", "strike": 100.0},
    ).json()
    scrubbed = auth_client.post(
        "/api/zerodte/preview",
        json={
            "symbol": "SPY", "kind": "leg", "side": "call", "strike": 100.0,
            "minutes_to_close": 2,
        },
    ).json()
    # Entry pricing is unchanged (you buy at the market NOW)…
    assert scrubbed["entry_price"] == base["entry_price"]
    assert scrubbed["payoff_expiration"] == base["payoff_expiration"]
    # …but the T+0 curve has decayed toward expiry: AT THE MONEY (where the
    # time value lives) the what-if value at 2 minutes sits well below the
    # 3-hour value.
    atm_i = min(
        range(len(base["prices"])), key=lambda i: abs(base["prices"][i] - 100.0)
    )
    assert scrubbed["payoff_today"][atm_i] < base["payoff_today"][atm_i]
    # …and the scrubbed curve sits BETWEEN now and expiry (time only decays
    # toward the expiration payoff, never through it).
    assert scrubbed["payoff_today"][atm_i] >= base["payoff_expiration"][atm_i]


def test_preview_scrub_cannot_add_time(auth_client, stubbed_chain, monkeypatch):
    _pin_session_clock(monkeypatch, hours=3.0)
    base = auth_client.post(
        "/api/zerodte/preview",
        json={"symbol": "SPY", "kind": "leg", "side": "call", "strike": 100.0},
    ).json()
    huge = auth_client.post(
        "/api/zerodte/preview",
        json={
            "symbol": "SPY", "kind": "leg", "side": "call", "strike": 100.0,
            "minutes_to_close": 100000,
        },
    ).json()
    assert huge["payoff_today"] == pytest.approx(base["payoff_today"])  # clamped


# --- pre-trade BP requirement -------------------------------------------------


def test_preview_reports_bp_requirement_per_direction(auth_client, stubbed_chain, monkeypatch):
    _pin_session_clock(monkeypatch, hours=3.0)
    body = auth_client.post(
        "/api/zerodte/preview",
        json={"symbol": "SPY", "kind": "leg", "side": "call", "strike": 100.0},
    ).json()
    # Long requirement = the debit (mid 1.1 × 100).
    assert body["bp_requirement_long"] == pytest.approx(110.0, abs=1.0)
    # Short = Reg-T-style naked call: (0.20×100 + 1.1) × 100 — many times
    # the premium collected. The asymmetry is the point of showing it.
    assert body["bp_requirement_short"] == pytest.approx(2110.0, abs=5.0)


def test_preview_multi_reports_as_submitted_requirement(auth_client, stubbed_chain):
    body = auth_client.post(
        "/api/zerodte/preview-multi",
        json={
            "symbol": "SPY", "contracts": 1,
            "legs": [
                {"side": "put", "action": "sell", "strike": 100.0, "ratio": 1},
                {"side": "put", "action": "buy", "strike": 95.0, "ratio": 1},
            ],
        },
    ).json()
    # Defined-risk credit spread: width $5 − net credit ($0) at equal mids
    # → ≈ $500 requirement.
    assert body["bp_requirement_long"] == pytest.approx(500.0, abs=15.0)
    assert body["bp_requirement_short"] is None
