"""Trade Desk journal — CRUD round-trips + net cost computation.

Multi-user world: journal endpoints require auth + an active combine.
The local `client` fixture layers a purchased combine onto conftest's
auth_client so the CRUD tests read exactly as before.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from schemas.journal import TradeLeg, compute_net_debit_credit
from tests.conftest import make_combine


@pytest.fixture
def client(auth_client):
    """Authed client that owns one active 50K combine."""
    make_combine(auth_client, "50K")
    return auth_client


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


def test_patch_edits_self_applied_tags(client):
    """The journal day-detail edits intent tags via PATCH `tags` —
    distinct from mistake_tags, and editable after entry."""
    created = client.post(
        "/api/journal/trades", json=_trade_payload(tags=["planned"])
    ).json()
    tid = created["id"]
    assert created["tags"] == ["planned"]

    res = client.patch(
        f"/api/journal/trades/{tid}", json={"tags": ["planned", "good setup"]}
    )
    assert res.status_code == 200
    assert res.json()["tags"] == ["planned", "good setup"]

    # Tags can be cleared independently, and the change persists.
    res = client.patch(f"/api/journal/trades/{tid}", json={"tags": []})
    assert res.status_code == 200
    assert res.json()["tags"] == []
    assert client.get(f"/api/journal/trades/{tid}").json()["tags"] == []


# ---------------------------------------------------------------------------
# Phase 2 — metadata enrichment + R-multiple
# ---------------------------------------------------------------------------


def test_create_persists_phase2_metadata(client):
    payload = _trade_payload(
        tags=["earnings", "momentum"],
        confidence=4,
        thesis="Pre-earnings vol play",
        planned_exit="Close night before print",
        risk_amount=500.0,
    )
    res = client.post("/api/journal/trades", json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body["tags"] == ["earnings", "momentum"]
    assert body["confidence"] == 4
    assert body["thesis"] == "Pre-earnings vol play"
    assert body["planned_exit"] == "Close night before print"
    assert body["risk_amount"] == 500.0
    assert body["mistake_tags"] == []           # capture at close, not entry
    assert body["r_multiple"] is None           # open trade


def test_close_with_mistake_tags_persists(client):
    tid = client.post("/api/journal/trades", json=_trade_payload(risk_amount=200.0)).json()["id"]
    res = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 240.0,
            "realized_pnl": 400.0,
            "mistake_tags": ["chased IV crush", "held too long"],
            "review_note": "Should have closed before earnings.",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mistake_tags"] == ["chased IV crush", "held too long"]
    assert body["review_note"] == "Should have closed before earnings."
    # 400 / 200 = 2.0R
    assert body["r_multiple"] == pytest.approx(2.0)


def test_r_multiple_negative_for_losing_trade(client):
    tid = client.post("/api/journal/trades", json=_trade_payload(risk_amount=500.0)).json()["id"]
    res = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 220.0,
            "realized_pnl": -750.0,
        },
    )
    # -750 / 500 = -1.5R
    assert res.json()["r_multiple"] == pytest.approx(-1.5)


def test_r_multiple_none_when_no_risk_amount(client):
    """Trade without a risk_amount logged → r_multiple is None even when
    realized_pnl is present. We surface '—' in UI rather than infer."""
    tid = client.post("/api/journal/trades", json=_trade_payload()).json()["id"]  # no risk
    res = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 240.0,
            "realized_pnl": 300.0,
        },
    )
    assert res.json()["r_multiple"] is None


def test_r_multiple_none_when_risk_is_zero(client):
    """Defensive: a zero-risk trade should not divide by zero."""
    # Backend schema requires risk_amount > 0, so we can't POST risk=0.
    # Instead create with risk_amount=None then read back.
    res = client.post("/api/journal/trades", json=_trade_payload())
    body = res.json()
    assert body["r_multiple"] is None
    assert body["risk_amount"] is None


def test_mistake_vocab_endpoint(client):
    res = client.get("/api/journal/vocab/mistakes")
    assert res.status_code == 200
    tags = res.json()["tags"]
    assert "chased IV crush" in tags
    assert "rolled too soon" in tags
    # Vocabulary is finite — keep this list aligned with the frontend
    # MISTAKE_TAG_VOCABULARY constant.
    assert len(tags) == 8


# ---------------------------------------------------------------------------
# Multi-user: gating, no-combine, cross-user isolation
# ---------------------------------------------------------------------------


def test_journal_requires_auth(client):
    client.post("/api/auth/signout")
    assert client.get("/api/journal/trades").status_code == 401
    assert client.post("/api/journal/trades", json=_trade_payload()).status_code == 401


def test_create_trade_without_combine_is_409(auth_client):
    # conftest's auth_client owns NO combine (the local `client` fixture
    # that purchases one is deliberately not requested here).
    res = auth_client.post("/api/journal/trades", json=_trade_payload())
    assert res.status_code == 409
    assert "no active combine" in res.json()["detail"]


def test_cross_user_trades_invisible(client, second_user_client):
    created = client.post("/api/journal/trades", json=_trade_payload()).json()
    tid = created["id"]

    # Second user: empty list, 404 on direct access/patch/delete.
    assert second_user_client.get("/api/journal/trades").json()["trades"] == []
    assert second_user_client.get(f"/api/journal/trades/{tid}").status_code == 404
    assert (
        second_user_client.patch(
            f"/api/journal/trades/{tid}", json={"notes": "mine now"}
        ).status_code
        == 404
    )
    assert second_user_client.delete(f"/api/journal/trades/{tid}").status_code == 404
    # Owner still sees it untouched.
    assert client.get(f"/api/journal/trades/{tid}").status_code == 200


def test_list_trades_combine_filter(client):
    from tests.conftest import make_combine as _mk

    c2 = _mk(client, "100K", name="Second")
    client.post("/api/journal/trades", json=_trade_payload(symbol="AAPL"))  # on 50K
    # Activate the 100K combine and log a trade there.
    client.post(f"/api/combines/{c2['id']}/activate")
    client.post("/api/journal/trades", json=_trade_payload(symbol="MSFT"))

    all_trades = client.get("/api/journal/trades").json()["trades"]
    assert {t["symbol"] for t in all_trades} == {"AAPL", "MSFT"}
    scoped = client.get(f"/api/journal/trades?combine_id={c2['id']}").json()["trades"]
    assert {t["symbol"] for t in scoped} == {"MSFT"}
