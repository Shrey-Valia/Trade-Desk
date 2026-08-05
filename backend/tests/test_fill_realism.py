"""Fill realism (audit C4) — every fill pays the spread, not the perfect mid.

Covers the shared spread-crossing machinery in services.fills:
  * touch-based working-order triggers (BUY limit on the ASK, SELL on the
    BID; stops on the adverse side) with the mid rule as fallback;
  * monitor entry fills crossing the spread (capped at the limit);
  * exit friction subtracted from every close booking (bracket / manual /
    flatten / PATCH), with liquidations stressing the size term 1.5×;
  * expiry settlement charging NO friction (cash-settled at intrinsic);
  * /reverse re-opens crossing the spread.

Live quotes are injected by monkeypatching the services.fills seam — the
real get_live_option_quotes binding is exercised elsewhere.
"""

from __future__ import annotations

import types
from datetime import datetime, time as dt_time, timezone

import pytest

import models.combine_event  # noqa: F401 — combine_snapshot writes events
import services.fills as fills
from config import settings
from models.trade import Trade
from services.order_monitor import _book_close, run_order_monitor
from tests.conftest import make_combine

_TODAY = datetime.now(timezone.utc).date()


def _quote(bid=None, ask=None, last=None):
    return types.SimpleNamespace(bid=bid, ask=ask, last=last)


def _patch_quotes(monkeypatch, mapping):
    """Pin the live-quote seam: {(strike, side): quote}. Patched in BOTH
    namespaces — services.fills (close_friction + the monitor's module-attr
    call) and routers.zerodte (which binds the name at import)."""

    def _fake(symbol, legs):
        return dict(mapping)

    monkeypatch.setattr("services.fills.live_leg_quotes", _fake)
    monkeypatch.setattr("routers.zerodte._live_leg_quotes", _fake)


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    t = Trade(**defaults)
    t.legs = legs or [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _get(session_factory, tid) -> Trade:
    s = session_factory()
    t = s.get(Trade, tid)
    s.expunge(t)
    s.close()
    return t


def _run(session_factory, **kw):
    params = dict(
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 0.0,
        # Pin the monitor clock to MID-SESSION on the seeded legs' expiry
        # date — after the 16:00 ET close the wall clock turns every seeded
        # 0DTE leg into an expired-contract cancel (see test_order_monitor).
        now=datetime.combine(_TODAY, dt_time(17, 0), tzinfo=timezone.utc),
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


# --- crossed / inverted book (P1: fantasy-credit guard) -----------------------


def test_pick_fill_price_crossed_book_is_unusable():
    """A crossed quote (ask BELOW bid) is stale/erroneous data — its mid is
    meaningless and `max(0, ask−bid)` collapses the spread to 0, which let a
    SELL fill at the fantasy mid. pick_fill_price must return 0 (no usable
    quote) for both sides so the caller refuses / falls back to the model."""
    crossed = _quote(bid=5.00, ask=0.01)
    assert fills.pick_fill_price(crossed, "sell", 1) == 0.0
    assert fills.pick_fill_price(crossed, "buy", 1) == 0.0
    # A locked market (bid == ask) is still valid — spread 0, fills at the touch.
    locked = _quote(bid=1.00, ask=1.00)
    assert fills.pick_fill_price(locked, "sell", 1) == pytest.approx(1.00)
    assert fills.pick_fill_price(locked, "buy", 1) == pytest.approx(1.00)


def test_quote_quality_gate_rejects_crossed_sell():
    """The sell-side anti-fantasy-market gate must reject a crossed book. The
    relative-spread test (ask−bid)/mid goes NEGATIVE when crossed and would
    otherwise pass, letting the fill machinery mint premium at the mid."""
    from fastapi import HTTPException

    from routers.zerodte import _require_quote_quality

    crossed = _quote(bid=5.00, ask=0.01)
    with pytest.raises(HTTPException) as ei:
        _require_quote_quality("SPY", [("call 100", crossed, "sell")])
    assert ei.value.status_code == 422
    assert "crossed" in str(ei.value.detail).lower()
    # A clean two-sided market passes.
    _require_quote_quality("SPY", [("call 100", _quote(bid=1.0, ask=1.1), "sell")])


# --- touch-based triggers -----------------------------------------------------


def test_buy_limit_fires_on_ask_touch_not_mid(auth_client, session_factory, monkeypatch):
    """The ASK trading through the limit fills a buy even when the (injected)
    mid says otherwise — the touch is the executable side."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="limit", limit_price=1.0)
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=0.90, ask=0.98)})
    # mid rule alone would NOT fill (2.0 > limit 1.0) — the touch must win.
    summary = _run(session_factory, option_mark=lambda t, s: 2.0)
    assert summary["filled"] == 1
    t = _get(session_factory, tid)
    assert t.status == "open"
    # Crossed fill: mid 0.94 + half-spread 0.04 = 0.98 (the offer), ≤ limit.
    assert t.legs[0]["entry_price"] == pytest.approx(0.98)


def test_buy_limit_blocked_until_ask_reaches_limit(auth_client, session_factory, monkeypatch):
    """A mid through the limit is NOT a fill while the offer sits above it —
    the old mid rule fabricated fills the market never offered."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="limit", limit_price=1.0)
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=0.20, ask=1.30)})
    summary = _run(session_factory, option_mark=lambda t, s: 0.75)  # mid ≤ limit
    assert summary["filled"] == 0
    assert _get(session_factory, tid).status == "working"


def test_sell_limit_fires_on_bid_touch(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], status="working", order_type="limit",
        limit_price=1.0, strategy="short_call",
        _legs=[{"side": "call", "action": "sell", "strike": 100.0,
                "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}],
    )
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=1.05, ask=1.50)})
    # mid rule alone would NOT fill a sell at 0.5 < 1.0 — the bid touch wins.
    summary = _run(session_factory, option_mark=lambda t, s: 0.5)
    assert summary["filled"] == 1
    t = _get(session_factory, tid)
    # Crossed: mid 1.275 − half-spread 0.225 = 1.05 (the bid), ≥ limit.
    assert t.legs[0]["entry_price"] == pytest.approx(1.05)


def test_buy_stop_triggers_on_adverse_ask(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="stop", limit_price=1.0)
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=0.70, ask=1.02)})
    # mid 0.5 < stop 1.0 wouldn't trigger; the ask (the side a buy stop pays)
    # already trades at/through the stop — trigger + crossed market fill.
    summary = _run(session_factory, option_mark=lambda t, s: 0.5)
    assert summary["filled"] == 1
    t = _get(session_factory, tid)
    # mid 0.86 + half-spread 0.16 = 1.02 — pays the offer, no cap on a stop.
    assert t.legs[0]["entry_price"] == pytest.approx(1.02)


def test_mid_rule_fallback_without_two_sided_quote(auth_client, session_factory, monkeypatch):
    """No two-sided quote → legacy behavior: mid trigger, fill AT the limit."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="limit", limit_price=1.0)
    _patch_quotes(monkeypatch, {})
    summary = _run(session_factory, option_mark=lambda t, s: 0.80)
    assert summary["filled"] == 1
    assert _get(session_factory, tid).legs[0]["entry_price"] == 1.0


# --- exit friction --------------------------------------------------------------


def test_close_friction_charges_half_spread_per_contract():
    quotes = {(100.0, "call"): _quote(bid=1.0, ask=1.2)}
    legs = [{"side": "call", "action": "buy", "strike": 100.0,
             "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}]
    # half-spread 0.1 × 1 contract × 100 shares = $10.
    assert fills.close_friction("SPY", legs, quotes=quotes) == pytest.approx(10.0)


def test_close_friction_liquidation_stresses_size_term():
    quotes = {(100.0, "call"): _quote(bid=1.0, ask=1.2)}  # mid 1.1
    legs = [{"side": "call", "action": "buy", "strike": 100.0,
             "expiry": _TODAY.isoformat(), "contracts": 3, "entry_price": 1.0}]
    # normal: (0.1 + 1.1×0.01) × 3 × 100 = 33.30
    assert fills.close_friction("SPY", legs, quotes=quotes) == pytest.approx(33.30)
    # stressed: size term ×1.5 → (0.1 + 1.1×0.015) × 300 = 34.95
    assert fills.close_friction(
        "SPY", legs, stressed=True, quotes=quotes
    ) == pytest.approx(34.95)


def test_close_friction_missing_quote_contributes_zero():
    legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0},
        {"side": "put", "action": "sell", "strike": 95.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0},
    ]
    quotes = {(100.0, "call"): _quote(bid=1.0, ask=1.2)}  # put unquoted
    assert fills.close_friction("SPY", legs, quotes=quotes) == pytest.approx(10.0)
    assert fills.close_friction("SPY", legs, quotes={}) == 0.0


def test_bracket_close_books_friction(auth_client, session_factory, monkeypatch):
    """A monitor bracket close subtracts the spread-crossing friction from the
    mid-based unrealized (plus the exit commission, as before)."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", take_profit=110.0)
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=1.0, ask=1.2)})
    summary = _run(
        session_factory,
        spot_for=lambda sym: 111.0,
        unrealized_for=lambda t, s: 100.0,
    )
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    fee = 1 * settings.per_contract_fee
    assert t.close_reason == "take_profit"
    assert t.realized_pnl == pytest.approx(round(100.0 - fee - 10.0, 2))


def test_liquidation_close_books_stressed_friction(session_factory, auth_client, monkeypatch):
    """_book_close with reason='liquidation' charges the 1.5× size term;
    reason='expiry' charges no friction at all (cash settlement)."""
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], status="open",
        _legs=[{"side": "call", "action": "buy", "strike": 100.0,
                "expiry": _TODAY.isoformat(), "contracts": 3, "entry_price": 1.0}],
    )
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=1.0, ask=1.2)})
    now = datetime.now(timezone.utc)
    fee = 3 * settings.per_contract_fee

    s = session_factory()
    t = s.get(Trade, tid)
    assert _book_close(s, t, 100.0, now, lambda tr, sp: -50.0, "liquidation")
    s.commit()
    liq_realized = t.realized_pnl
    s.close()
    assert liq_realized == pytest.approx(round(-50.0 - fee - 34.95, 2))

    tid2 = _seed(
        session_factory, c["id"], status="open",
        _legs=[{"side": "call", "action": "buy", "strike": 100.0,
                "expiry": _TODAY.isoformat(), "contracts": 3, "entry_price": 1.0}],
    )
    s = session_factory()
    t2 = s.get(Trade, tid2)
    assert _book_close(s, t2, 100.0, now, lambda tr, sp: -50.0, "expiry")
    s.commit()
    exp_realized = t2.realized_pnl
    s.close()
    # Expiry is cash-settled at intrinsic — no spread to cross.
    assert exp_realized == pytest.approx(round(-50.0 - fee, 2))


def test_flatten_close_books_friction(auth_client, session_factory, monkeypatch):
    """The /flatten manual close path routes through _book_close and pays the
    same exit friction as any other close."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=1.0, ask=1.2)})
    monkeypatch.setattr(
        "services.order_monitor._default_unrealized_for", lambda t, s, now: 100.0
    )
    res = auth_client.post("/api/zerodte/flatten")
    assert res.status_code == 200, res.text
    t = _get(session_factory, tid)
    fee = 1 * settings.per_contract_fee
    assert t.status == "closed"
    assert t.realized_pnl == pytest.approx(round(100.0 - fee - 10.0, 2))
    assert res.json()["realized"] == pytest.approx(round(100.0 - fee - 10.0, 2))


def test_reverse_reopen_crosses_the_spread(auth_client, session_factory, monkeypatch):
    """A /reverse re-open is a market fill: the flipped leg prices at the
    crossed live quote (a SELL receives the bid side), not the frictionless
    model mid."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", strategy="long_call")
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    _patch_quotes(monkeypatch, {(100.0, "call"): _quote(bid=1.0, ask=1.2)})
    monkeypatch.setattr(
        "services.order_monitor._default_unrealized_for", lambda t, s, now: 0.0
    )
    res = auth_client.post("/api/zerodte/reverse")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["closed"] == [tid]
    s = session_factory()
    rev = s.get(Trade, body["opened"][0])
    # Flipped to SELL: crossed fill = mid 1.1 − half-spread 0.1 = 1.0 (the bid).
    assert rev.legs[0]["action"] == "sell"
    assert rev.legs[0]["entry_price"] == pytest.approx(1.0)
    s.close()


def test_multileg_working_fill_capped_at_net_limit(
    auth_client, session_factory, monkeypatch
):
    """recent-waves #7: a multi-leg NET-limit order must not fill THROUGH its
    limit. Crossing the spread on each leg pushes the booked net past the mid
    that triggered — the booked net must be CAPPED at the signed limit_price
    (the multi-leg analog of the single-leg min(crossed, trigger))."""
    import services.order_monitor as om

    c = make_combine(auth_client, "50K")
    legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 0.0},
        {"side": "call", "action": "sell", "strike": 105.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 0.0},
    ]
    # Debit vertical, net limit = 1.00 (debit positive).
    tid = _seed(session_factory, c["id"], status="working",
                order_type="limit", limit_price=1.00, _legs=legs)

    # Frictionless per-leg mids: buy 2.00 / sell 1.00 → mid net = 1.00 == limit.
    mids = {(100.0, "call"): 2.00, (105.0, "call"): 1.00}
    monkeypatch.setattr(om, "_option_chain_rows", lambda sym: None)
    monkeypatch.setattr(om, "_rate", lambda: 0.04)
    monkeypatch.setattr(
        om, "_leg_model_price",
        lambda rows, leg, spot, now, rate: mids[(float(leg["strike"]), leg["side"])],
    )
    # WIDE two-sided quotes so crossing (buy→ask, sell→bid) blows the net to
    # 2.5 − 0.5 = 2.00, well through the 1.00 limit without the cap.
    def _lq(symbol, legs_):
        return {
            (100.0, "call"): types.SimpleNamespace(bid=1.5, ask=2.5, last=2.0),
            (105.0, "call"): types.SimpleNamespace(bid=0.5, ask=1.5, last=1.0),
        }
    monkeypatch.setattr(fills, "live_leg_quotes", _lq)

    with session_factory() as s:
        t = s.get(Trade, tid)
        # option_mark returns the mid net (== limit) so the trigger fires.
        om._process_working_multi(
            s, t, spot=100.0, now=datetime.now(timezone.utc),
            option_mark=lambda tr, sp: 1.00,
        )
        s.commit()

    with session_factory() as s:
        t = s.get(Trade, tid)
        assert t.status == "open"
        px = {(float(l["strike"]), l["side"]): l["entry_price"] for l in t.legs}
        booked_net = px[(100.0, "call")] - px[(105.0, "call")]  # buy − sell, base 1
        assert booked_net <= 1.00 + 1e-6   # never filled through the limit
