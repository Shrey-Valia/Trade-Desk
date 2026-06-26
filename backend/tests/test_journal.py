"""Trade Desk journal — CRUD round-trips + net cost computation.

Multi-user world: journal endpoints require auth + an active combine.
The local `client` fixture layers a purchased combine onto conftest's
auth_client so the CRUD tests read exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest

import routers.journal as journal_router
from schemas.journal import TradeLeg, compute_net_debit_credit
from tests.conftest import make_combine


@pytest.fixture
def client(auth_client):
    """Authed client that owns one active 50K combine."""
    make_combine(auth_client, "50K")
    return auth_client


@dataclass
class _StubQuote:
    """Minimal quote stand-in — the close/scale-out recompute only reads
    `.price` off the get_quotes() result."""

    price: float


@pytest.fixture
def mock_quote(monkeypatch):
    """Patch the journal router's get_quotes so the server-side P&L recompute
    runs off a KNOWN spot (deterministic) instead of the live feed. Returns a
    setter so each test can pin its own price."""

    state: dict[str, float] = {"price": 230.0}

    def _fake_get_quotes(symbols):
        return {sym: _StubQuote(price=state["price"]) for sym in symbols}

    monkeypatch.setattr(journal_router, "get_quotes", _fake_get_quotes)

    def _set(price: float) -> None:
        state["price"] = price

    return _set


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


def _expected_realized(session_factory, tid: int) -> float:
    """The realized P&L the server SHOULD book on a full close of `tid`:
    the recomputed folded unrealized minus the exit-side commission. Calls
    the exact router helper so the test tracks the production math."""
    from config import settings

    s = session_factory()
    try:
        from models.trade import Trade

        trade = s.get(Trade, tid)
        unreal = journal_router._recompute_unrealized(trade)
        contracts = max(
            (int(leg.get("contracts", 1) or 1) for leg in trade.legs), default=1
        )
        exit_comm = contracts * settings.commission_per_contract
        return round(unreal - exit_comm, 2)
    finally:
        s.close()


def test_close_trade_via_patch_recomputes_realized(client, session_factory, mock_quote):
    """A manual close RECOMPUTES realized server-side from the live mark and
    IGNORES the deprecated client `realized_pnl`."""
    mock_quote(245.0)  # pin the recompute spot
    created = client.post("/api/journal/trades", json=_trade_payload()).json()
    tid = created["id"]
    expected = _expected_realized(session_factory, tid)

    close = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 245.0,
            "realized_pnl": 9999.0,        # deliberately wrong — must be ignored
        },
    )
    assert close.status_code == 200
    body = close.json()
    assert body["status"] == "closed"
    assert body["exit_underlying_price"] == 245.0
    # Server booked the RECOMPUTED number, not the lying 9999 the client sent.
    assert body["realized_pnl"] != 9999.0
    assert body["realized_pnl"] == pytest.approx(expected)


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


def test_close_with_mistake_tags_persists(client, session_factory, mock_quote):
    mock_quote(240.0)
    tid = client.post("/api/journal/trades", json=_trade_payload(risk_amount=200.0)).json()["id"]
    expected = _expected_realized(session_factory, tid)
    res = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 240.0,
            "realized_pnl": 400.0,        # ignored — server recomputes
            "mistake_tags": ["chased IV crush", "held too long"],
            "review_note": "Should have closed before earnings.",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mistake_tags"] == ["chased IV crush", "held too long"]
    assert body["review_note"] == "Should have closed before earnings."
    # Realized is the server recompute (NOT 400), and r_multiple derives from it.
    assert body["realized_pnl"] == pytest.approx(expected)
    assert body["r_multiple"] == pytest.approx(expected / 200.0)


def test_r_multiple_tracks_recomputed_realized(client, session_factory, mock_quote):
    """r_multiple is derived from the SERVER-RECOMPUTED realized, not the
    client's number. A spot well below entry recomputes a loss."""
    mock_quote(200.0)  # underwater long straddle → recompute < 0
    tid = client.post("/api/journal/trades", json=_trade_payload(risk_amount=500.0)).json()["id"]
    expected = _expected_realized(session_factory, tid)
    res = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 200.0,
            "realized_pnl": -750.0,       # ignored — server recomputes
        },
    )
    body = res.json()
    assert body["realized_pnl"] == pytest.approx(expected)
    assert body["r_multiple"] == pytest.approx(expected / 500.0)


def test_r_multiple_none_when_no_risk_amount(client, mock_quote):
    """Trade without a risk_amount logged → r_multiple is None even when
    realized_pnl is present. We surface '—' in UI rather than infer."""
    mock_quote(240.0)
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


# ---------------------------------------------------------------------------
# WS1 — server-side P&L recompute (integrity fix)
# ---------------------------------------------------------------------------


def test_close_ignores_lying_client_realized_pnl(client, session_factory, mock_quote):
    """The headline integrity guarantee: a client can send ANY realized_pnl on
    a close and the server discards it, booking its own recompute instead."""
    mock_quote(255.0)
    tid = client.post("/api/journal/trades", json=_trade_payload()).json()["id"]
    expected = _expected_realized(session_factory, tid)

    body = client.patch(
        f"/api/journal/trades/{tid}",
        json={
            "status": "closed",
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "exit_underlying_price": 255.0,
            "realized_pnl": 9999.0,        # the lie
        },
    ).json()
    assert body["realized_pnl"] == pytest.approx(expected)
    assert body["realized_pnl"] != 9999.0


def _two_contract_payload(**overrides):
    """A 2-contract-per-leg straddle so a scale-out (qty=1) leaves a remainder."""
    p = _trade_payload()
    for leg in p["legs"]:
        leg["contracts"] = 2
    p.update(overrides)
    return p


def test_scale_out_recomputes_slice_and_ignores_client_pnl(
    client, session_factory, mock_quote
):
    """Scale-out books `unrealized × qty/held − qty·commission` recomputed
    server-side, IGNORING the client's realized_pnl. The position stays open
    with the remaining contracts and the booked slice accumulates onto
    realized_pnl."""
    from config import settings
    from models.trade import Trade

    mock_quote(250.0)
    tid = client.post("/api/journal/trades", json=_two_contract_payload()).json()["id"]

    # Compute the EXPECTED slice the same way the router does, BEFORE the
    # scale-out reduces the legs (held = 2, closing qty = 1).
    s = session_factory()
    trade = s.get(Trade, tid)
    position_unrealized = journal_router._recompute_unrealized(trade)
    s.close()
    held, qty = 2, 1
    exit_comm = qty * settings.commission_per_contract
    expected_slice = round(position_unrealized * (qty / held) - exit_comm, 2)

    res = client.post(
        f"/api/journal/trades/{tid}/scale-out",
        json={"qty": qty, "realized_pnl": 9999.0, "exit_underlying_price": 250.0},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Still OPEN with the remaining contract on each leg.
    assert body["status"] == "open"
    assert all(leg["contracts"] == held - qty for leg in body["legs"])
    # Booked the RECOMPUTED slice — not the lying 9999.
    assert body["realized_pnl"] == pytest.approx(expected_slice)
    assert body["realized_pnl"] != 9999.0


def test_scale_out_accumulates_across_two_slices(client, mock_quote):
    """Two successive scale-outs ACCUMULATE realized; each books its own
    recomputed slice (running total, not a replace)."""
    mock_quote(250.0)
    # 3 contracts so we can scale out twice (1, then 1) and still hold 1.
    payload = _trade_payload()
    for leg in payload["legs"]:
        leg["contracts"] = 3
    tid = client.post("/api/journal/trades", json=payload).json()["id"]

    first = client.post(
        f"/api/journal/trades/{tid}/scale-out", json={"qty": 1}
    ).json()
    after_first = first["realized_pnl"]
    assert all(leg["contracts"] == 2 for leg in first["legs"])

    second = client.post(
        f"/api/journal/trades/{tid}/scale-out", json={"qty": 1}
    ).json()
    after_second = second["realized_pnl"]
    assert all(leg["contracts"] == 1 for leg in second["legs"])
    # Accumulation: the running total moved by the second slice (same sign,
    # roughly doubled at the same spot) — it is not a replace.
    assert after_second != after_first
    assert after_second == pytest.approx(after_first * 2, rel=0.05)


def test_scale_out_rejects_qty_at_or_above_held(client, mock_quote):
    """qty must be strictly fewer than held — closing the rest uses PATCH."""
    mock_quote(250.0)
    tid = client.post("/api/journal/trades", json=_two_contract_payload()).json()["id"]
    res = client.post(f"/api/journal/trades/{tid}/scale-out", json={"qty": 2})
    assert res.status_code == 400
    assert "fewer than" in res.json()["detail"]


def test_scale_out_requires_open_position(client, mock_quote):
    """Scale-out on a non-open (e.g. closed) trade is a 409."""
    mock_quote(245.0)
    tid = client.post("/api/journal/trades", json=_two_contract_payload()).json()["id"]
    client.patch(
        f"/api/journal/trades/{tid}",
        json={"status": "closed", "exit_underlying_price": 245.0},
    )
    res = client.post(f"/api/journal/trades/{tid}/scale-out", json={"qty": 1})
    assert res.status_code == 409
