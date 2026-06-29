"""WS5 — Monte-Carlo terminal-value simulator + /api/analytics/montecarlo."""

from __future__ import annotations

from datetime import UTC, datetime

from calculations.monte_carlo import (
    position_cost_basis,
    simulate_terminal_pnl,
)
from models.trade import Trade
from tests.conftest import make_combine

# --- pure calculator --------------------------------------------------------


def _long_call(strike=100.0, premium=1.0, contracts=1):
    return [
        {"side": "call", "action": "buy", "strike": strike,
         "contracts": contracts, "entry_price": premium}
    ]


def test_cost_basis_long_is_debit():
    cb = position_cost_basis(_long_call(premium=1.5, contracts=2))
    # debit = 1.5 × 100 × 2 = 300, positive.
    assert cb == 300.0


def test_cost_basis_short_is_credit():
    legs = [{"side": "put", "action": "sell", "strike": 100, "contracts": 1, "entry_price": 2.0}]
    assert position_cost_basis(legs) == -200.0


def test_result_shape_and_bounds():
    r = simulate_terminal_pnl(
        legs=_long_call(),
        spot=100.0,
        sigma=0.3,
        horizon_days=5,
        paths=5000,
        seed=42,
    )
    # Histogram invariants.
    assert len(r.hist_bin_edges) == len(r.hist_counts) + 1
    assert sum(r.hist_counts) == r.paths
    assert 0.0 <= r.prob_profit <= 1.0
    assert r.pnl_p05 <= r.median_pnl <= r.pnl_p95
    assert r.max_simulated_loss <= r.expected_pnl <= r.max_simulated_profit
    assert r.var_95 >= 0.0
    assert len(r.sample_terminal_prices) <= 500


def test_deterministic_with_seed():
    a = simulate_terminal_pnl(legs=_long_call(), spot=100, sigma=0.3, horizon_days=5, paths=2000, seed=7)
    b = simulate_terminal_pnl(legs=_long_call(), spot=100, sigma=0.3, horizon_days=5, paths=2000, seed=7)
    assert a.expected_pnl == b.expected_pnl
    assert a.prob_profit == b.prob_profit
    assert a.hist_counts == b.hist_counts


def test_long_call_max_loss_is_the_debit():
    # A long call's worst case at expiry is losing the full premium.
    r = simulate_terminal_pnl(
        legs=_long_call(premium=1.0, contracts=1),
        spot=100.0,
        sigma=0.3,
        horizon_days=5,
        paths=10000,
        seed=1,
    )
    # Cost basis is $100; loss can't exceed that (intrinsic floor 0).
    assert r.max_simulated_loss >= -100.0 - 1e-6
    assert r.cost_basis == 100.0


def test_paths_clamped_to_max():
    r = simulate_terminal_pnl(
        legs=_long_call(), spot=100, sigma=0.3, horizon_days=5, paths=10_000_000, seed=1
    )
    assert r.paths == 200_000  # MAX_PATHS


def test_higher_drift_raises_prob_profit_for_long_call():
    base = simulate_terminal_pnl(
        legs=_long_call(strike=100, premium=1.0),
        spot=100, sigma=0.3, horizon_days=10, paths=20000, seed=3, drift=0.0,
    )
    bull = simulate_terminal_pnl(
        legs=_long_call(strike=100, premium=1.0),
        spot=100, sigma=0.3, horizon_days=10, paths=20000, seed=3, drift=0.8,
    )
    assert bull.prob_profit >= base.prob_profit


# --- endpoint ---------------------------------------------------------------


def test_montecarlo_endpoint_hypothetical_legs(auth_client):
    make_combine(auth_client, "50K")
    res = auth_client.post(
        "/api/analytics/montecarlo",
        json={
            "legs": [
                {"side": "call", "action": "buy", "strike": 100, "contracts": 1, "entry_price": 1.0}
            ],
            "spot": 100.0,
            "sigma": 0.3,
            "horizon_days": 5,
            "paths": 3000,
            "seed": 11,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["paths"] == 3000
    assert len(body["hist_bin_edges"]) == len(body["hist_counts"]) + 1
    assert 0.0 <= body["prob_profit"] <= 1.0


def test_montecarlo_endpoint_from_open_trade(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    s = session_factory()
    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(UTC),
        entry_underlying_price=100.0,
        net_debit_credit=100.0,
        is_paper=True,
        tier="50K",
        combine_id=c["id"],
        status="open",
    )
    t.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": "2026-01-01", "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()

    res = auth_client.post(
        "/api/analytics/montecarlo",
        json={"trade_id": tid, "spot": 100.0, "sigma": 0.3, "horizon_days": 5, "seed": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["cost_basis"] == 100.0


def test_montecarlo_endpoint_foreign_trade_404(auth_client, second_user_client, session_factory):
    # Trade owned by the rival user; the auth_client must not see it.
    c = make_combine(second_user_client, "50K")
    s = session_factory()
    t = Trade(
        symbol="SPY", strategy="long_call", entry_date=datetime.now(UTC),
        entry_underlying_price=100.0, net_debit_credit=100.0, is_paper=True,
        tier="50K", combine_id=c["id"], status="open",
    )
    t.legs = [{"side": "call", "action": "buy", "strike": 100.0, "expiry": "2026-01-01", "contracts": 1, "entry_price": 1.0}]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()

    res = auth_client.post(
        "/api/analytics/montecarlo",
        json={"trade_id": tid, "spot": 100.0, "sigma": 0.3, "horizon_days": 5},
    )
    assert res.status_code == 404


def test_montecarlo_endpoint_requires_legs_or_trade(auth_client):
    make_combine(auth_client, "50K")
    res = auth_client.post(
        "/api/analytics/montecarlo",
        json={"spot": 100.0, "sigma": 0.3, "horizon_days": 5},
    )
    assert res.status_code == 422
