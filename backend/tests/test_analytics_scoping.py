"""GET /api/analytics — per-user scoping + combine_id filter."""

from __future__ import annotations

from datetime import datetime, timezone

from database import get_session
from models.trade import Trade
from tests.conftest import make_combine


def _seed_closed(client, combine_id: int, symbol: str, pnl: float) -> None:
    session = next(client.app.dependency_overrides[get_session]())
    session.add(
        Trade(
            symbol=symbol,
            strategy="long_call",
            entry_date=datetime.now(timezone.utc),
            entry_underlying_price=100.0,
            net_debit_credit=100.0,
            status="closed",
            is_paper=True,
            tier="50K",
            combine_id=combine_id,
            exit_date=datetime.now(timezone.utc),
            exit_underlying_price=101.0,
            realized_pnl=pnl,
            legs_json="[]",
        )
    )
    session.commit()
    session.close()


def test_analytics_requires_auth(client):
    assert client.get("/api/analytics").status_code == 401


def test_analytics_scoped_to_own_combines(auth_client, second_user_client):
    mine = make_combine(auth_client, "50K")
    theirs = make_combine(second_user_client, "50K")
    _seed_closed(auth_client, mine["id"], "SPY", 100.0)
    _seed_closed(second_user_client, theirs["id"], "QQQ", -999.0)

    r = auth_client.get("/api/analytics").json()
    assert r["kpis"]["closed_trades"] == 1
    assert r["kpis"]["net_pnl"] == 100.0
    assert {b["symbol"] for b in r["by_symbol"]} == {"SPY"}


def test_analytics_combine_filter(auth_client):
    a = make_combine(auth_client, "50K", name="A")
    b = make_combine(auth_client, "100K", name="B")
    _seed_closed(auth_client, a["id"], "SPY", 50.0)
    _seed_closed(auth_client, b["id"], "IWM", 75.0)

    both = auth_client.get("/api/analytics").json()
    assert both["kpis"]["closed_trades"] == 2

    only_b = auth_client.get(f"/api/analytics?combine_id={b['id']}").json()
    assert only_b["kpis"]["closed_trades"] == 1
    assert only_b["kpis"]["net_pnl"] == 75.0


def test_analytics_foreign_combine_404(auth_client, second_user_client):
    theirs = make_combine(second_user_client, "50K")
    res = auth_client.get(f"/api/analytics?combine_id={theirs['id']}")
    assert res.status_code == 404
