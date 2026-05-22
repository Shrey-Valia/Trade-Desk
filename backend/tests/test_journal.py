"""Trade Desk journal — CRUD round-trips + net cost computation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_session
from main import app
from schemas.journal import TradeLeg, compute_net_debit_credit


# ---------------------------------------------------------------------------
# Test scaffolding: fresh in-memory SQLite per test, overriding the get_session
# dependency so neither the real DB nor the seed job interferes.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    # Importing the Trade model has the side effect of registering it on
    # Base.metadata — necessary before create_all on a brand-new engine.
    import models.trade  # noqa: F401

    # `:memory:` per-connection sqlite is a separate DB per connection,
    # which fights SQLAlchemy's connection pool. StaticPool reuses one
    # connection so the override session and any other call see the same
    # in-memory schema.
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def _future_expiry(days: int = 21) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _trade_payload(**overrides):
    base = {
        "symbol": "aapl",                       # exercises uppercase normalization
        "strategy": "long_straddle",
        "entry_date": datetime.now(timezone.utc).isoformat(),
        "entry_underlying_price": 230.0,
        "is_paper": True,
        "notes": "demo",
        "legs": [
            {
                "side": "call", "action": "buy",
                "strike": 230, "expiry": _future_expiry(),
                "contracts": 1, "entry_price": 6.20,
            },
            {
                "side": "put", "action": "buy",
                "strike": 230, "expiry": _future_expiry(),
                "contracts": 1, "entry_price": 5.80,
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_net_cost_simple_long_call():
    legs = [
        TradeLeg(side="call", action="buy", strike=100, expiry=date.today() + timedelta(days=21),
                 contracts=1, entry_price=2.50),
    ]
    # 2.50 × 1 × 100 = +$250 debit
    assert compute_net_debit_credit(legs) == 250.0


def test_net_cost_vertical_spread_debit():
    legs = [
        TradeLeg(side="call", action="buy", strike=230, expiry=date.today() + timedelta(days=21),
                 contracts=2, entry_price=6.20),
        TradeLeg(side="call", action="sell", strike=240, expiry=date.today() + timedelta(days=21),
                 contracts=2, entry_price=2.10),
    ]
    # (6.20 - 2.10) × 2 × 100 = +$820 debit
    assert compute_net_debit_credit(legs) == 820.0


def test_net_cost_iron_condor_credit():
    expiry = date.today() + timedelta(days=21)
    legs = [
        TradeLeg(side="call", action="sell", strike=750, expiry=expiry, contracts=1, entry_price=4.10),
        TradeLeg(side="call", action="buy",  strike=760, expiry=expiry, contracts=1, entry_price=2.30),
        TradeLeg(side="put",  action="sell", strike=720, expiry=expiry, contracts=1, entry_price=3.80),
        TradeLeg(side="put",  action="buy",  strike=710, expiry=expiry, contracts=1, entry_price=2.05),
    ]
    # net credit of 4.10 - 2.30 + 3.80 - 2.05 = 3.55 → -$355 (credit is negative)
    assert compute_net_debit_credit(legs) == -355.0


# ---------------------------------------------------------------------------
# CRUD round-trips
# ---------------------------------------------------------------------------


def test_create_normalizes_symbol_and_computes_net(client):
    res = client.post("/api/journal/trades", json=_trade_payload())
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["symbol"] == "AAPL"                   # lowercased input normalized
    assert body["status"] == "open"
    assert body["net_debit_credit"] == 1200.0         # (6.20 + 5.80) × 1 × 100
    assert body["is_paper"] is True
    assert len(body["legs"]) == 2


def test_create_respects_explicit_net(client):
    payload = _trade_payload(net_debit_credit=999.99)
    res = client.post("/api/journal/trades", json=payload)
    assert res.json()["net_debit_credit"] == 999.99


def test_create_warns_on_leg_count_mismatch(client):
    # iron_condor declared but only one leg supplied → soft warning header
    payload = _trade_payload(
        strategy="iron_condor",
        legs=[{
            "side": "call", "action": "buy",
            "strike": 100, "expiry": _future_expiry(),
            "contracts": 1, "entry_price": 1.0,
        }],
    )
    res = client.post("/api/journal/trades", json=payload)
    assert res.status_code == 201
    assert "X-Journal-Warnings" in res.headers
    assert "iron_condor" in res.headers["X-Journal-Warnings"]


def test_list_filters_by_status_and_paper(client):
    # Two paper opens.
    client.post("/api/journal/trades", json=_trade_payload(symbol="AAPL"))
    client.post("/api/journal/trades", json=_trade_payload(symbol="MSFT"))
    # One real-journaled.
    client.post("/api/journal/trades", json=_trade_payload(symbol="NVDA", is_paper=False))

    paper = client.get("/api/journal/trades?is_paper=true").json()["trades"]
    real = client.get("/api/journal/trades?is_paper=false").json()["trades"]
    assert {t["symbol"] for t in paper} == {"AAPL", "MSFT"}
    assert {t["symbol"] for t in real} == {"NVDA"}


def test_close_trade_via_patch_sets_realized_pnl(client):
    created = client.post("/api/journal/trades", json=_trade_payload()).json()
    tid = created["id"]
    close = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 245.0,
            "realized_pnl": 540.0,
        },
    )
    assert close.status_code == 200
    body = close.json()
    assert body["status"] == "closed"
    assert body["realized_pnl"] == 540.0
    assert body["exit_underlying_price"] == 245.0


def test_delete_removes_trade(client):
    tid = client.post("/api/journal/trades", json=_trade_payload()).json()["id"]
    assert client.delete(f"/api/journal/trades/{tid}").status_code == 204
    assert client.get(f"/api/journal/trades/{tid}").status_code == 404
