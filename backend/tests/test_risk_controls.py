"""Risk controls (B5) — operator kill switch, suspension, universe, quote gates.

Covers the four risk doors added to the 0DTE open paths and the order monitor:

  * account suspension  — opens 403 "account_suspended:", closes untouched;
  * platform trading mode — "halted" 503s every open, "close_only" 409s opens
    while closes keep working; the monitor skips working ENTRY fills in both
    modes (skip, not cancel) while exits/brackets still run;
  * tradeable universe — settings.zero_dte_universe + the DB-backed ban list
    enforced at open (422 "symbol_not_tradeable:") when
    settings.enforce_tradeable_universe is on; closes are never symbol-gated,
    /reverse (which re-opens) is;
  * option quote quality — an immediate market fill refuses a leg whose mid is
    under settings.min_option_mid, whose spread ratio exceeds
    settings.max_option_spread_ratio, or which has no two-sided NBBO
    (422 "quote_quality:"); working placements and closes are not quote-gated.

Market data is stubbed exactly like test_orders_api (chain rows +
SimpleNamespace quotes); the monitor runs with injected callables per
test_order_monitor. No network anywhere.
"""

from __future__ import annotations

import types
from datetime import datetime, time, timezone

from sqlalchemy import select

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from models.trade import Trade
from models.user import User
from routers import zerodte
from services import platform_state
from services.order_monitor import run_order_monitor
from tests.conftest import make_combine

_TODAY = datetime.now(zerodte._ET).date()
# A deterministic mid-session instant (3pm ET today) so working orders seeded
# with today's expiry are never treated as expired contracts by the monitor,
# whatever wall-clock time the suite runs at.
_NOW = datetime.combine(_TODAY, time(15, 0), tzinfo=zerodte._ET).astimezone(timezone.utc)


# --- shared stubs (test_orders_api / test_order_monitor patterns) ------------


def _stub_market(monkeypatch, strikes=(95.0, 100.0, 105.0), bid=1.0, ask=1.2, last=None):
    """Session open + a live chain for ANY symbol, with controllable quotes."""
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=_TODAY,
            bid=bid, ask=ask, last=last, open_interest=None, iv=None,
        )
        for k in strikes
        for side in ("call", "put")
    ]
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def _set_mode(session_factory, mode: str) -> None:
    s = session_factory()
    platform_state.set_trading_mode(s, mode)
    s.close()


def _ban(session_factory, symbols: list[str]) -> None:
    s = session_factory()
    platform_state.set_banned_symbols(s, symbols)
    s.close()


def _suspend(session_factory, email: str = "trader@test.local") -> None:
    s = session_factory()
    user = s.execute(select(User).where(User.email == email)).scalar_one()
    user.suspended_at = datetime.now(timezone.utc)
    s.commit()
    s.close()


def _open_leg(client, symbol: str = "SPY", **overrides):
    payload = {
        "symbol": symbol, "side": "call", "action": "buy",
        "strike": 100, "entry_price": 0,
    }
    payload.update(overrides)
    return client.post("/api/zerodte/open-leg", json=payload)


def _open_straddle(client, symbol: str = "SPY"):
    return client.post("/api/zerodte/open", json={"symbol": symbol, "contracts": 1})


def _open_multi(client, symbol: str = "SPY"):
    return client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": symbol,
            "contracts": 1,
            "legs": [
                {"side": "call", "action": "buy", "strike": 100, "ratio": 1},
                {"side": "put", "action": "buy", "strike": 100, "ratio": 1},
            ],
        },
    )


def _flatten_ok(client, monkeypatch):
    """Flatten with the booking math pinned — the assertion here is REACHING
    the close, not its P&L (test_fill_realism owns the friction numbers)."""
    monkeypatch.setattr(
        "services.order_monitor._default_unrealized_for", lambda t, s, now: 0.0
    )
    return client.post("/api/zerodte/flatten")


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=_NOW,
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
    )
    defaults.update(kw)
    t = Trade(**defaults)
    t.legs = [
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
        now=_NOW,
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 0.0,
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


# --- suspension ---------------------------------------------------------------


def test_suspended_user_open_403_close_allowed(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = _open_leg(auth_client)
    assert res.status_code == 201, res.text
    tid = res.json()["id"]

    _suspend(session_factory)
    for blocked in (
        _open_leg(auth_client),
        _open_straddle(auth_client),
        _open_multi(auth_client),
    ):
        assert blocked.status_code == 403, blocked.text
        assert blocked.json()["detail"].startswith("account_suspended:")

    # Closing the existing position must still work.
    res = _flatten_ok(auth_client, monkeypatch)
    assert res.status_code == 200, res.text
    assert tid in res.json()["closed"]


def test_monitor_skips_suspended_owner_entry_but_runs_exits(
    auth_client, session_factory, monkeypatch
):
    c = make_combine(auth_client, "50K")
    working = _seed(
        session_factory, c["id"], status="working", order_type="limit", limit_price=1.5
    )
    exiting = _seed(session_factory, c["id"], status="open", take_profit=110.0)
    _suspend(session_factory)

    summary = _run(session_factory, spot_for=lambda sym: 111.0)
    assert summary["filled"] == 0
    assert summary["closed"] == 1
    assert _get(session_factory, working).status == "working"  # skipped, NOT cancelled
    assert _get(session_factory, exiting).status == "closed"   # exits always run


# --- platform trading mode ------------------------------------------------------


def test_halted_blocks_every_open_path(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    _seed(session_factory, c["id"], status="open")  # so /reverse has a book
    _set_mode(session_factory, "halted")

    for blocked in (
        _open_leg(auth_client),
        _open_straddle(auth_client),
        _open_multi(auth_client),
        auth_client.post("/api/zerodte/reverse"),
    ):
        assert blocked.status_code == 503, blocked.text
        assert blocked.json()["detail"].startswith("trading_halted:")

    # Closes still work while halted.
    res = _flatten_ok(auth_client, monkeypatch)
    assert res.status_code == 200, res.text
    assert len(res.json()["closed"]) == 1


def test_close_only_blocks_opens_allows_closes(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = _open_leg(auth_client)
    assert res.status_code == 201, res.text
    tid = res.json()["id"]

    _set_mode(session_factory, "close_only")
    blocked = _open_leg(auth_client)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"].startswith("close_only:")

    res = _flatten_ok(auth_client, monkeypatch)
    assert res.status_code == 200, res.text
    assert tid in res.json()["closed"]


def test_monitor_entry_fills_respect_kill_switch(auth_client, session_factory):
    """halted / close_only skip working ENTRY fills (order survives untouched);
    back in normal mode the same order fills — proving skip, not cancel."""
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], status="working", order_type="limit", limit_price=1.5
    )

    for mode in ("halted", "close_only"):
        _set_mode(session_factory, mode)
        summary = _run(session_factory)  # mark 1.0 ≤ limit 1.5 → would fill
        assert summary["filled"] == 0, mode
        assert _get(session_factory, tid).status == "working", mode

    _set_mode(session_factory, "normal")
    summary = _run(session_factory)
    assert summary["filled"] == 1
    assert _get(session_factory, tid).status == "open"


def test_monitor_exits_still_run_while_halted(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", take_profit=110.0)
    _set_mode(session_factory, "halted")

    summary = _run(session_factory, spot_for=lambda sym: 111.0)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.status == "closed"
    assert t.close_reason == "take_profit"


# --- tradeable universe ---------------------------------------------------------


def test_banned_symbol_rejected(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    _ban(session_factory, ["SPY"])
    res = _open_leg(auth_client)
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == "symbol_not_tradeable: SPY is not in the tradeable universe"


def test_non_universe_symbol_rejected(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    for res in (
        _open_leg(auth_client, symbol="NVDA"),
        _open_straddle(auth_client, symbol="NVDA"),
        _open_multi(auth_client, symbol="NVDA"),
    ):
        assert res.status_code == 422, res.text
        assert res.json()["detail"].startswith("symbol_not_tradeable: NVDA")


def test_universe_symbols_and_lowercase_pass(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = _open_leg(auth_client, symbol="spy")  # normalization guard
    assert res.status_code == 201, res.text
    assert res.json()["symbol"] == "SPY"


def test_universe_enforcement_can_be_disabled(auth_client, session_factory, monkeypatch):
    from config import settings

    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    monkeypatch.setattr(settings, "enforce_tradeable_universe", False)
    res = _open_leg(auth_client, symbol="NVDA")
    assert res.status_code == 201, res.text


def test_banned_symbol_close_allowed_reverse_refused(
    auth_client, session_factory, monkeypatch
):
    """A ban lands mid-day with a position open: /reverse (which re-OPENS the
    symbol) refuses atomically — the book is untouched — while /flatten still
    exits it."""
    c = make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    tid = _seed(session_factory, c["id"], status="open")
    _ban(session_factory, ["SPY"])

    res = auth_client.post("/api/zerodte/reverse")
    assert res.status_code == 422, res.text
    assert res.json()["detail"].startswith("symbol_not_tradeable: SPY")
    assert _get(session_factory, tid).status == "open"  # nothing half-done

    res = _flatten_ok(auth_client, monkeypatch)
    assert res.status_code == 200, res.text
    assert tid in res.json()["closed"]


# --- quote quality --------------------------------------------------------------


# The full anti-fantasy-market gate (min mid, spread cap, two-sided book)
# applies to SELL legs — writing premium into a market nobody makes is the
# exploit. BUY legs get a lighter check (see the defined-risk test below).


def test_quote_quality_sell_mid_below_floor_rejected(
    auth_client, session_factory, monkeypatch
):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, bid=0.03, ask=0.05)  # mid $0.04 < $0.05 floor
    res = _open_leg(auth_client, action="sell")
    assert res.status_code == 422, res.text
    assert res.json()["detail"].startswith("quote_quality:")


def test_quote_quality_sell_wide_spread_rejected(
    auth_client, session_factory, monkeypatch
):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, bid=0.40, ask=1.60)  # mid 1.00, spread ratio 1.2 > 1.0
    res = _open_leg(auth_client, action="sell")
    assert res.status_code == 422, res.text
    assert res.json()["detail"].startswith("quote_quality:")
    assert "spread" in res.json()["detail"]


def test_quote_quality_sell_zero_bid_one_sided_rejected(
    auth_client, session_factory, monkeypatch
):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, bid=None, ask=0.50)  # nobody bidding
    res = _open_leg(auth_client, action="sell")
    assert res.status_code == 422, res.text
    assert res.json()["detail"].startswith("quote_quality:")
    assert "one-sided" in res.json()["detail"]


def test_quote_quality_buy_wing_with_cheap_or_zero_bid_is_allowed(
    auth_client, session_factory, monkeypatch
):
    """The defined-risk fix: a protective long (BUY) wing is normally a cheap,
    wide, often zero-bid far-OTM contract. It must open on a real ask alone —
    the sell-side floor/spread/two-sided checks would wrongly block every
    defined-risk structure while leaving the naked short openable."""
    make_combine(auth_client, "50K")
    # Sub-nickel mid AND zero bid — fails every sell-side check, but this is a
    # legitimate long wing with a real offer to lift.
    _stub_market(monkeypatch, bid=None, ask=0.03)
    res = _open_leg(auth_client, action="buy")
    assert res.status_code == 201, res.text


def test_quote_quality_buy_with_no_offer_rejected(
    auth_client, session_factory, monkeypatch
):
    """A buy still needs a real ask to cross to — a fully empty book is
    refused even for a buy leg."""
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, bid=None, ask=None)
    res = _open_leg(auth_client, action="buy")
    assert res.status_code == 422, res.text
    assert res.json()["detail"].startswith("quote_quality:")


def test_quote_quality_healthy_market_passes(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)  # bid 1.0 / ask 1.2 — mid 1.1, ratio ~0.18
    res = _open_straddle(auth_client)
    assert res.status_code == 201, res.text


def test_quote_quality_does_not_gate_working_placement(
    auth_client, session_factory, monkeypatch
):
    """A limit placement doesn't fill against today's quote — it rests for the
    monitor and fills at the user's own price — so it is not quote-gated."""
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, bid=None, ask=0.50)
    res = _open_leg(auth_client, order_type="limit", limit_price=0.25)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "working"


def test_quote_quality_never_blocks_closes(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = _open_leg(auth_client)
    assert res.status_code == 201, res.text
    tid = res.json()["id"]

    # The market turns to garbage after entry — the exit still goes through.
    _stub_market(monkeypatch, bid=None, ask=0.02)
    res = _flatten_ok(auth_client, monkeypatch)
    assert res.status_code == 200, res.text
    assert tid in res.json()["closed"]


# --- admin service surface -------------------------------------------------------


def test_platform_status_snapshot(session_factory):
    s = session_factory()
    assert platform_state.platform_status(s) == {
        "trading_mode": "normal",
        "banned_symbols": [],
    }
    platform_state.set_trading_mode(s, "close_only")
    platform_state.set_banned_symbols(s, ["qqq", "SPY"])
    assert platform_state.platform_status(s) == {
        "trading_mode": "close_only",
        "banned_symbols": ["QQQ", "SPY"],
    }
    s.close()
