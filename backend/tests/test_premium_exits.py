"""Premium-denominated TP/SL (Tastytrade "manage winners") — Feature 2.

Monitor triggers on the |net premium| mark vs |net entry premium|:
  NET-DEBIT (long):  TP at mark ≥ entry×tp (tp>1), SL at mark ≤ entry×sl (0<sl<1)
  NET-CREDIT (short): tp is the buy-back FRACTION of the credit (0<tp<1),
                      sl the cut multiple (>1) — the inverted semantics.

Plus: open-time direction validation (400s), persistence via the open
endpoints (stubbed chain, no network), and verbatim mirroring to copy-trade
followers.
"""

from __future__ import annotations

import types
from datetime import datetime, time as dt_time, timezone

from sqlalchemy import select

import models.combine_event  # noqa: F401 — ensure combine_events table exists
from models.combine import Combine
from models.trade import Trade
from routers import zerodte
from services.copy_trade import mirror_open
from services.order_monitor import run_order_monitor
from tests.conftest import make_combine

# "Today" is the EASTERN trading day (the 0DTE engine + monitor resolve the
# session in ET); a UTC date flips a day early after ~20:00 ET.
_TODAY_DATE = datetime.now(zerodte._ET).date()
_TODAY = _TODAY_DATE.isoformat()
# Pin the monitor clock to MID-SESSION ET so the seeded 0DTE legs are never
# treated as expired, whatever wall-clock time the suite runs at (the default
# run_order_monitor `now` is the real time — past 16:00 ET it settles them).
_NOON_ET = datetime.combine(_TODAY_DATE, dt_time(12, 0), tzinfo=zerodte._ET)


def _seed(session_factory, combine_id, *, action="buy", entry_price=1.0,
          contracts=1, legs=None, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call" if action == "buy" else "short_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        status="open",
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
    )
    defaults.update(kw)
    t = Trade(**defaults)
    t.legs = legs or [
        {"side": "call", "action": action, "strike": 100.0,
         "expiry": _TODAY, "contracts": contracts, "entry_price": entry_price}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _run(session_factory, **kw):
    params = dict(
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 0.0,
        now=_NOON_ET,
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


def _get(session_factory, tid) -> Trade:
    s = session_factory()
    t = s.get(Trade, tid)
    s.expunge(t)
    s.close()
    return t


# --- long (net-debit) triggers ------------------------------------------------


def test_premium_tp_long_fires_at_entry_times_mult(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], entry_price=1.0, tp_premium_mult=2.0)
    summary = _run(session_factory, option_mark=lambda t, s: 2.1,
                   unrealized_for=lambda t, s: 110.0)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.status == "closed"
    assert t.close_reason == "take_profit"
    assert "premium target 2×" in (t.notes or "")


def test_premium_sl_long_fires_on_decay(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], entry_price=1.0, sl_premium_mult=0.5)
    summary = _run(session_factory, option_mark=lambda t, s: 0.45,
                   unrealized_for=lambda t, s: -55.0)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.close_reason == "stop_loss"
    assert "premium stop 0.5×" in (t.notes or "")


def test_premium_long_no_fire_inside_band(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], entry_price=1.0,
                tp_premium_mult=2.0, sl_premium_mult=0.5)
    summary = _run(session_factory, option_mark=lambda t, s: 1.5)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


def test_premium_scales_with_contracts_and_legs(auth_client, session_factory):
    """entry and mark are both contracts-scaled, so the ratio is scale-free:
    a 2-lot straddle at $1.00/leg has entry_net = 4.0; the injected mark is
    the same Σ sign·contracts·px shape the production pricer returns."""
    c = make_combine(auth_client, "50K")
    legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY, "contracts": 2, "entry_price": 1.0},
        {"side": "put", "action": "buy", "strike": 100.0,
         "expiry": _TODAY, "contracts": 2, "entry_price": 1.0},
    ]
    tid = _seed(session_factory, c["id"], legs=legs, strategy="long_straddle",
                tp_premium_mult=2.0)
    # mark 7.9 < 8.0 → no fire; then 8.5 ≥ 4.0 × 2.0 → fires.
    assert _run(session_factory, option_mark=lambda t, s: 7.9)["closed"] == 0
    summary = _run(session_factory, option_mark=lambda t, s: 8.5,
                   unrealized_for=lambda t, s: 450.0)
    assert summary["closed"] == 1
    assert _get(session_factory, tid).close_reason == "take_profit"


# --- short (net-credit) triggers — inverted semantics ---------------------------


def test_premium_tp_short_buys_back_at_fraction_of_credit(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    # Sold at 2.00 credit; tp 0.5 → buy back when the mark decays to ≤ 1.00.
    tid = _seed(session_factory, c["id"], action="sell", entry_price=2.0,
                tp_premium_mult=0.5)
    # Production marks are SIGNED (short leg → negative); |−0.9| = 0.9 ≤ 1.0.
    summary = _run(session_factory, option_mark=lambda t, s: -0.9,
                   unrealized_for=lambda t, s: 110.0)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.close_reason == "take_profit"
    assert "premium target 0.5× credit" in (t.notes or "")


def test_premium_sl_short_cuts_at_multiple_of_credit(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    # Sold at 2.00 credit; sl 2.0 → cut when the mark expands to ≥ 4.00.
    tid = _seed(session_factory, c["id"], action="sell", entry_price=2.0,
                sl_premium_mult=2.0)
    summary = _run(session_factory, option_mark=lambda t, s: -4.1,
                   unrealized_for=lambda t, s: -210.0)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.close_reason == "stop_loss"
    assert "premium stop 2×" in (t.notes or "")


def test_premium_short_no_fire_inside_band(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], action="sell", entry_price=2.0,
                tp_premium_mult=0.5, sl_premium_mult=2.0)
    summary = _run(session_factory, option_mark=lambda t, s: -2.5)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


# --- open-time validation + persistence (stubbed chain, no network) -------------


def _row(strike: float, type_: str, bid=1.0, ask=1.2):
    return types.SimpleNamespace(
        strike=float(strike), type=type_,
        expiry=datetime.now(zerodte._ET).date(),
        bid=bid, ask=ask, last=None, open_interest=None, iv=None,
    )


def _stub_chain(monkeypatch, rows=None):
    rows = rows or [_row(100.0, "call"), _row(100.0, "put")]
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0, as_of=None)},
    )


def _open_leg(client, **kw):
    body = {"symbol": "SPY", "side": "call", "action": "buy",
            "strike": 100, "contracts": 1}
    body.update(kw)
    return client.post("/api/zerodte/open-leg", json=body)


def test_open_leg_validation_400s(auth_client, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch)
    # Long (net debit): tp must be > 1, sl must be in (0, 1).
    assert _open_leg(auth_client, tp_premium_mult=0.5).status_code == 400
    assert _open_leg(auth_client, tp_premium_mult=1.0).status_code == 400
    assert _open_leg(auth_client, sl_premium_mult=1.5).status_code == 400
    # Short (net credit): inverted — tp in (0, 1), sl > 1.
    assert _open_leg(auth_client, action="sell", tp_premium_mult=1.5).status_code == 400
    assert _open_leg(auth_client, action="sell", sl_premium_mult=0.5).status_code == 400
    # ≤ 0 is rejected by the schema itself.
    assert _open_leg(auth_client, tp_premium_mult=-1).status_code == 422


def test_open_leg_persists_premium_mults(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch)
    res = _open_leg(auth_client, tp_premium_mult=2.0, sl_premium_mult=0.5)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["tp_premium_mult"] == 2.0
    assert body["sl_premium_mult"] == 0.5
    s = session_factory()
    t = s.get(Trade, body["id"])
    assert t.tp_premium_mult == 2.0
    assert t.sl_premium_mult == 0.5
    s.close()


def test_open_straddle_validates_before_pricing(auth_client, monkeypatch):
    make_combine(auth_client, "50K")
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    # A short straddle with a long-style tp must 400 (no chain data needed —
    # validation runs before any pricing work).
    res = auth_client.post(
        "/api/zerodte/open",
        json={"symbol": "SPY", "contracts": 1, "action": "sell",
              "tp_premium_mult": 2.0},
    )
    assert res.status_code == 400


def test_open_multi_direction_from_priced_net(auth_client, monkeypatch):
    """The multi-leg path derives direction from the PRICED net premium: a
    credit vertical accepts short-style mults and rejects long-style ones."""
    make_combine(auth_client, "50K")
    rows = [
        _row(100.0, "call", bid=2.0, ask=2.2),  # sold — rich
        _row(105.0, "call", bid=0.5, ask=0.7),  # bought — cheap
    ]
    _stub_chain(monkeypatch, rows=rows)
    legs = [
        {"side": "call", "action": "sell", "strike": 100, "ratio": 1},
        {"side": "call", "action": "buy", "strike": 105, "ratio": 1},
    ]
    # Long-style tp on a net-credit structure → 400.
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={"symbol": "SPY", "contracts": 1, "legs": legs,
              "strategy": "vertical", "tp_premium_mult": 2.0},
    )
    assert res.status_code == 400
    # Short-style mults → accepted and persisted.
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={"symbol": "SPY", "contracts": 1, "legs": legs,
              "strategy": "vertical", "tp_premium_mult": 0.5,
              "sl_premium_mult": 2.0},
    )
    assert res.status_code == 201, res.text
    assert res.json()["net_debit_credit"] < 0  # really a credit
    assert res.json()["tp_premium_mult"] == 0.5
    assert res.json()["sl_premium_mult"] == 2.0


# --- copy-trade mirroring -------------------------------------------------------


def test_premium_mults_mirrored_to_followers(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    follower = make_combine(auth_client, "50K", name="F1")
    res = auth_client.put(
        "/api/combines/copy-config",
        json={"lead_combine_id": lead["id"],
              "followers": [{"combine_id": follower["id"], "multiplier": 1.0}]},
    )
    assert res.status_code == 200, res.text

    s = session_factory()
    lead_c = s.get(Combine, lead["id"])
    t = Trade(
        symbol="SPY", strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0, net_debit_credit=-100.0,
        status="open", is_paper=True, tier="50K", combine_id=lead["id"],
        tp_premium_mult=2.0, sl_premium_mult=0.5,
    )
    t.legs = [{"side": "call", "action": "buy", "strike": 100.0,
               "expiry": _TODAY, "contracts": 1, "entry_price": 1.0}]
    t.tags = ["0dte"]
    t.mistake_tags = []
    s.add(t)
    s.commit()
    s.refresh(t)

    result = mirror_open(s, lead_c, t)
    assert follower["id"] in result.mirrored
    mirrored = s.execute(
        select(Trade).where(Trade.combine_id == follower["id"])
    ).scalars().one()
    assert mirrored.tp_premium_mult == 2.0  # copied verbatim
    assert mirrored.sl_premium_mult == 0.5
    s.close()
