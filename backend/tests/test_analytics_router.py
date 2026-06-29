"""Router tests for routers/analytics.py — KPI + equity-curve response
SHAPE and the filter/serialization glue.

Ownership scoping + the combine_id 404 are covered in
test_analytics_scoping.py; this file complements that with the full
response envelope (every block present), the empty-DB baseline, the
profit_factor inf→null coercion, and filter pass-through. Pure DB, no
network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import get_session
from models.trade import Trade
from tests.conftest import make_combine


def _seed_closed(
    client,
    combine_id: int,
    symbol: str,
    pnl: float,
    *,
    strategy: str = "long_call",
    days_ago: int = 0,
) -> None:
    entry = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    exit_ = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session = next(client.app.dependency_overrides[get_session]())
    session.add(
        Trade(
            symbol=symbol,
            strategy=strategy,
            entry_date=entry,
            entry_underlying_price=100.0,
            net_debit_credit=100.0,
            status="closed",
            is_paper=True,
            tier="50K",
            combine_id=combine_id,
            exit_date=exit_,
            exit_underlying_price=101.0,
            realized_pnl=pnl,
            legs_json="[]",
        )
    )
    session.commit()
    session.close()


_ALL_BLOCKS = {
    "kpis",
    "by_strategy",
    "by_symbol",
    "by_dte",
    "by_time_of_day",
    "by_day_of_week",
    "by_hold_duration",
    "by_mistake",
    "streaks",
    "equity",
    "risk",
    "filters",
}


def test_analytics_empty_db_returns_zeroed_envelope(auth_client):
    make_combine(auth_client, "50K")
    body = auth_client.get("/api/analytics").json()
    # Every top-level block is present even with no trades.
    assert _ALL_BLOCKS <= set(body)
    k = body["kpis"]
    assert k["total_trades"] == 0
    assert k["closed_trades"] == 0
    assert k["net_pnl"] == 0
    assert body["by_symbol"] == []
    assert body["equity"]["points"] == []
    assert body["equity"]["max_drawdown"] == 0


def test_analytics_full_envelope_with_trades(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed(auth_client, c["id"], "SPY", 150.0, days_ago=2)
    _seed_closed(auth_client, c["id"], "QQQ", -50.0, days_ago=1)

    body = auth_client.get("/api/analytics").json()
    assert _ALL_BLOCKS <= set(body)

    k = body["kpis"]
    assert k["closed_trades"] == 2
    assert k["net_pnl"] == 100.0  # 150 - 50
    assert 0.0 <= k["win_rate"] <= 1.0
    assert k["largest_winner"] == 150.0
    assert k["largest_loser"] == -50.0

    # Equity curve: monotonic-by-date points, well-formed.
    points = body["equity"]["points"]
    assert len(points) >= 1
    for p in points:
        assert set(p) == {"date", "cumulative_pnl"}
    assert body["equity"]["final_pnl"] == 100.0

    # Per-symbol buckets reflect both symbols.
    assert {b["symbol"] for b in body["by_symbol"]} == {"SPY", "QQQ"}


def test_analytics_profit_factor_inf_coerced_to_null(auth_client):
    """All winners, no losers → profit_factor is mathematically inf; the
    router coerces inf/nan to None so the JSON stays valid."""
    c = make_combine(auth_client, "50K")
    _seed_closed(auth_client, c["id"], "SPY", 100.0)
    _seed_closed(auth_client, c["id"], "SPY", 200.0)

    body = auth_client.get("/api/analytics").json()
    assert body["kpis"]["profit_factor"] is None
    assert body["kpis"]["closed_trades"] == 2


def test_analytics_filters_pass_through(auth_client):
    make_combine(auth_client, "50K")
    body = auth_client.get(
        "/api/analytics?paper=true&strategy=long_call&since=2026-01-01&until=2026-12-31"
    ).json()
    f = body["filters"]
    assert f["paper"] is True
    assert f["strategy"] == "long_call"
    assert f["since"] == "2026-01-01"
    assert f["until"] == "2026-12-31"


def test_analytics_strategy_filter_narrows_results(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed(auth_client, c["id"], "SPY", 100.0, strategy="long_call")
    _seed_closed(auth_client, c["id"], "QQQ", 50.0, strategy="long_put")

    only_calls = auth_client.get("/api/analytics?strategy=long_call").json()
    assert only_calls["kpis"]["closed_trades"] == 1
    assert only_calls["kpis"]["net_pnl"] == 100.0
