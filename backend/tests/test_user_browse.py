"""User-browse endpoints — stars CRUD + popular slate + selection log."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from models.ticker_selection import TickerSelection
from services import ticker_analytics


@pytest.fixture
def client():
    # Register every model that participates in create_all so the
    # in-memory test schema is whole. Watchlist + account state are
    # referenced indirectly via lifespan-less TestClient construction.
    import models.account_state  # noqa: F401
    import models.historical_earnings_event  # noqa: F401
    import models.options_snapshot  # noqa: F401
    import models.ticker_selection  # noqa: F401
    import models.trade  # noqa: F401
    import models.user_star  # noqa: F401
    import models.watchlist_item  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    # Network paths must be stubbed so unit tests don't reach out to
    # Alpaca for the 0DTE-availability check on the popular slate.
    with patch(
        "routers.user_browse.has_zero_dte_bulk",
        return_value={
            "SPY": True, "QQQ": True, "IWM": False, "AAPL": True,
            "NVDA": True, "TSLA": False, "MSFT": True, "AMD": False,
        },
    ):
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_session, None)
            engine.dispose()


# ---------------------------------------------------------------------------
# Stars CRUD
# ---------------------------------------------------------------------------


def test_stars_empty_on_fresh_install(client):
    r = client.get("/api/user/stars")
    assert r.status_code == 200
    assert r.json() == {"symbols": []}


def test_add_star_then_listed(client):
    r = client.post("/api/user/stars/SPY")
    assert r.status_code == 200
    assert r.json()["symbols"] == ["SPY"]

    r2 = client.get("/api/user/stars")
    assert r2.json()["symbols"] == ["SPY"]


def test_add_star_idempotent(client):
    client.post("/api/user/stars/AAPL")
    # Second add must not 409 — return the current list.
    r = client.post("/api/user/stars/AAPL")
    assert r.status_code == 200
    assert r.json()["symbols"] == ["AAPL"]


def test_add_star_lowercase_input_normalizes(client):
    r = client.post("/api/user/stars/spy")
    assert r.status_code == 200
    assert r.json()["symbols"] == ["SPY"]


def test_add_star_rejects_out_of_universe(client):
    # ASTS isn't in the curated universe.
    r = client.post("/api/user/stars/ASTS")
    assert r.status_code == 400
    # And the existing list is untouched.
    assert client.get("/api/user/stars").json()["symbols"] == []


def test_add_star_rejects_index(client):
    # SPX is rejected because it's not in the curated universe (and the
    # universe excludes indices by construction).
    r = client.post("/api/user/stars/SPX")
    assert r.status_code == 400


def test_remove_star(client):
    client.post("/api/user/stars/SPY")
    client.post("/api/user/stars/AAPL")
    r = client.delete("/api/user/stars/SPY")
    assert r.status_code == 200
    assert r.json()["symbols"] == ["AAPL"]


def test_remove_nonexistent_star_is_noop(client):
    # Deleting a non-starred symbol returns the current list, no 404.
    r = client.delete("/api/user/stars/SPY")
    assert r.status_code == 200
    assert r.json()["symbols"] == []


def test_stars_preserve_add_order(client):
    client.post("/api/user/stars/AAPL")
    client.post("/api/user/stars/SPY")
    client.post("/api/user/stars/NVDA")
    r = client.get("/api/user/stars")
    assert r.json()["symbols"] == ["AAPL", "SPY", "NVDA"]


# ---------------------------------------------------------------------------
# Popular slate
# ---------------------------------------------------------------------------


def test_popular_returns_eight_curated_symbols(client):
    r = client.get("/api/ticker/popular")
    assert r.status_code == 200
    body = r.json()
    syms = [e["symbol"] for e in body["results"]]
    assert syms == ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "MSFT", "AMD"]


def test_popular_carries_has_0dte_today_flag(client):
    r = client.get("/api/ticker/popular").json()
    by_sym = {e["symbol"]: e for e in r["results"]}
    # Stubbed bulk-zdte response above: SPY True, IWM False.
    assert by_sym["SPY"]["has_0dte_today"] is True
    assert by_sym["IWM"]["has_0dte_today"] is False


def test_popular_includes_company_name(client):
    r = client.get("/api/ticker/popular").json()
    by_sym = {e["symbol"]: e["name"] for e in r["results"]}
    assert "S&P 500" in by_sym["SPY"]
    assert "Apple" in by_sym["AAPL"]


# ---------------------------------------------------------------------------
# Selection log
# ---------------------------------------------------------------------------


def test_selection_log_writes_a_row(client):
    r = client.post("/api/ticker/selection", json={"symbol": "SPY"})
    assert r.status_code == 204

    session = next(client.app.dependency_overrides[get_session]())
    rows = session.query(TickerSelection).all()
    assert len(rows) == 1
    assert rows[0].symbol == "SPY"
    assert rows[0].user_id == 1


def test_selection_log_rejects_out_of_universe(client):
    r = client.post("/api/ticker/selection", json={"symbol": "ASTS"})
    assert r.status_code == 400


def test_selection_log_normalizes_case(client):
    client.post("/api/ticker/selection", json={"symbol": "spy"})
    session = next(client.app.dependency_overrides[get_session]())
    rows = session.query(TickerSelection).all()
    assert len(rows) == 1
    assert rows[0].symbol == "SPY"


# ---------------------------------------------------------------------------
# ticker_analytics aggregator (dormant — but ready)
# ---------------------------------------------------------------------------


def test_popular_tickers_aggregator_empty_on_no_selections(client):
    session = next(client.app.dependency_overrides[get_session]())
    out = ticker_analytics.get_popular_tickers(session)
    assert out == []


def test_popular_tickers_aggregator_ranks_by_count(client):
    # Selecting SPY three times and AAPL twice → SPY first, AAPL second.
    for _ in range(3):
        client.post("/api/ticker/selection", json={"symbol": "SPY"})
    for _ in range(2):
        client.post("/api/ticker/selection", json={"symbol": "AAPL"})
    client.post("/api/ticker/selection", json={"symbol": "NVDA"})

    session = next(client.app.dependency_overrides[get_session]())
    out = ticker_analytics.get_popular_tickers(session, limit=8)
    by_sym = {p.symbol: p.count for p in out}
    assert by_sym == {"SPY": 3, "AAPL": 2, "NVDA": 1}
    # And the order respects count-desc.
    assert [p.symbol for p in out] == ["SPY", "AAPL", "NVDA"]
