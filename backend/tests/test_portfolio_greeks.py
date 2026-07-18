"""Portfolio Greeks — pure aggregation + the /api/journal/portfolio/greeks endpoint."""

from __future__ import annotations

import types
from datetime import UTC, datetime

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from calculations.portfolio_greeks import aggregate_portfolio_greeks, beta_for
from models.trade import Trade
from tests.conftest import make_combine

_TODAY = datetime.now(UTC).date()


# --- pure aggregation --------------------------------------------------------


def test_nets_sum_across_positions():
    rows = [
        {"symbol": "SPY", "spot": 500.0, "delta": 50.0, "gamma": 2.0, "theta": -30.0, "vega": 10.0},
        {"symbol": "SPY", "spot": 500.0, "delta": -20.0, "gamma": 1.0, "theta": -10.0, "vega": 5.0},
    ]
    out = aggregate_portfolio_greeks(rows, spy_spot=500.0)
    assert out["positions"] == 2
    assert out["net"]["delta"] == 30.0
    assert out["net"]["theta"] == -40.0
    # SPY beta-weights to itself 1:1.
    assert out["beta_weighted_delta"] == 30.0


def test_beta_weighting_restates_in_spy_shares():
    # 100 QQQ-share deltas at QQQ=400 vs SPY=500 with beta 1.18:
    # 100 × (400/500) × 1.18 = 94.4 SPY-share equivalents.
    rows = [{"symbol": "QQQ", "spot": 400.0, "delta": 100.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}]
    out = aggregate_portfolio_greeks(rows, spy_spot=500.0)
    assert out["beta_weighted_delta"] == round(100 * (400 / 500) * beta_for("QQQ"), 2)


def test_no_spy_spot_means_no_beta_weighting():
    rows = [{"symbol": "QQQ", "spot": 400.0, "delta": 100.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}]
    out = aggregate_portfolio_greeks(rows, spy_spot=None)
    assert out["beta_weighted_delta"] is None
    assert out["by_symbol"][0]["beta_weighted_delta"] is None
    assert out["net"]["delta"] == 100.0  # nets still sum


def test_by_symbol_sorted_by_exposure():
    rows = [
        {"symbol": "IWM", "spot": 200.0, "delta": 10.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0},
        {"symbol": "QQQ", "spot": 400.0, "delta": -100.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0},
    ]
    out = aggregate_portfolio_greeks(rows, spy_spot=500.0)
    assert [r["symbol"] for r in out["by_symbol"]] == ["QQQ", "IWM"]


def test_unknown_symbol_falls_back_to_beta_1():
    assert beta_for("XYZ") == 1.0


# --- endpoint ----------------------------------------------------------------


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(UTC),
        entry_underlying_price=500.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="open",
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    t = Trade(**defaults)
    t.legs = legs or [
        {
            "side": "call",
            "action": "buy",
            "strike": 500.0,
            "expiry": _TODAY.isoformat(),
            "contracts": 1,
            "entry_price": 2.0,
        }
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _pin_quotes(monkeypatch, price=500.0):
    monkeypatch.setattr(
        "routers.journal.get_quotes",
        lambda syms: {s: types.SimpleNamespace(price=price) for s in syms},
    )


def test_endpoint_empty_book(auth_client, session_factory):
    make_combine(auth_client, "50K")
    res = auth_client.get("/api/journal/portfolio/greeks")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["positions"] == 0
    assert body["net"] == {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}


def test_endpoint_aggregates_open_positions(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    _seed(session_factory, c["id"])
    _seed(session_factory, c["id"], strategy="long_put", _legs=[
        {"side": "put", "action": "buy", "strike": 500.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 2.0},
    ])
    _pin_quotes(monkeypatch)
    res = auth_client.get("/api/journal/portfolio/greeks")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["positions"] == 2
    assert body["spy_spot"] == 500.0
    assert body["beta_weighted_delta"] is not None
    # ATM long call + ATM long put ≈ delta-neutral straddle: |net Δ| well
    # below a single leg's ~50-share delta; theta strictly negative.
    assert abs(body["net"]["delta"]) < 25.0
    assert body["net"]["theta"] < 0
    assert body["by_symbol"][0]["symbol"] == "SPY"


def test_endpoint_excludes_closed_and_manual_rows(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    _seed(session_factory, c["id"], status="closed")
    _seed(session_factory, c["id"], origin="manual")
    _pin_quotes(monkeypatch)
    res = auth_client.get("/api/journal/portfolio/greeks")
    assert res.status_code == 200
    assert res.json()["positions"] == 0


def test_endpoint_503_when_feed_cold(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    _seed(session_factory, c["id"])

    def _boom(_syms):
        raise RuntimeError("feed down")

    monkeypatch.setattr("routers.journal.get_quotes", _boom)
    res = auth_client.get("/api/journal/portfolio/greeks")
    assert res.status_code == 503
