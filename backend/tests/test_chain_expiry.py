"""Multi-expiry chain browsing — /expirations + the chain/table expiry param.

Browsing any listed expiry is allowed (expiry_is_today=False marks the table
display-only); OPENING remains strictly 0DTE via _require_today_expiry. A
no-0DTE day now falls back to the nearest upcoming expiry instead of
dead-terminaling the chain panel with a 409.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta

from routers import zerodte

_TODAY = datetime.now(zerodte._ET).date()
_FUT = _TODAY + timedelta(days=3)
_FAR = _TODAY + timedelta(days=10)


def _rows(expiries):
    return [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=e,
            bid=1.0, ask=1.2, last=None, open_interest=None, iv=0.25,
        )
        for e in expiries
        for k in (95.0, 100.0, 105.0)
        for side in ("call", "put")
    ]


def _stub(monkeypatch, expiries):
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot",
        lambda sym, with_volume=False: _rows(expiries),
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def test_default_prefers_todays_expiry(auth_client, monkeypatch):
    _stub(monkeypatch, [_TODAY, _FUT])
    res = auth_client.get("/api/zerodte/chain/table?symbol=SPY")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expiry"] == _TODAY.isoformat()
    assert body["expiry_is_today"] is True


def test_no_0dte_day_falls_back_to_nearest_upcoming(auth_client, monkeypatch):
    """The dead-terminal fix: a day with no 0DTE used to 409; it now serves
    the nearest listed expiry, flagged browse-only."""
    _stub(monkeypatch, [_FUT, _FAR])
    res = auth_client.get("/api/zerodte/chain/table?symbol=SPY")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expiry"] == _FUT.isoformat()
    assert body["expiry_is_today"] is False


def test_explicit_expiry_browses_that_date(auth_client, monkeypatch):
    _stub(monkeypatch, [_TODAY, _FUT])
    res = auth_client.get(
        f"/api/zerodte/chain/table?symbol=SPY&expiry={_FUT.isoformat()}"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expiry"] == _FUT.isoformat()
    assert body["expiry_is_today"] is False
    # More time on the clock than the 0DTE table.
    today_t = auth_client.get("/api/zerodte/chain/table?symbol=SPY").json()[
        "t_years_to_close"
    ]
    assert body["t_years_to_close"] > today_t


def test_unlisted_expiry_404_and_bad_format_422(auth_client, monkeypatch):
    _stub(monkeypatch, [_TODAY])
    res = auth_client.get("/api/zerodte/chain/table?symbol=SPY&expiry=2099-01-01")
    assert res.status_code == 404
    res = auth_client.get("/api/zerodte/chain/table?symbol=SPY&expiry=garbage")
    assert res.status_code == 422


def test_empty_chain_still_409s(auth_client, monkeypatch):
    _stub(monkeypatch, [])
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot",
        lambda sym, with_volume=False: _rows([_TODAY - timedelta(days=1)]),
    )
    res = auth_client.get("/api/zerodte/chain/table?symbol=SPY")
    assert res.status_code == 409


def test_expirations_endpoint_lists_upcoming_sorted(auth_client, monkeypatch):
    _stub(monkeypatch, [_FAR, _TODAY, _FUT, _TODAY - timedelta(days=1)])
    res = auth_client.get("/api/zerodte/expirations?symbol=SPY")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [e["expiry"] for e in body["expirations"]] == [
        _TODAY.isoformat(), _FUT.isoformat(), _FAR.isoformat()
    ]
    assert body["expirations"][0]["is_today"] is True
    assert body["expirations"][1]["dte"] == 3


# --- IV term structure -------------------------------------------------------


def test_term_structure_points_and_shape(auth_client, monkeypatch):
    """Future expiries only (clock-independent: after today's bell a 0DTE
    point correctly has no solvable forward IV). A far premium fat enough
    relative to its extra time back-solves to higher IV → contango."""
    fat = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=e,
            bid=b, ask=b + 0.2, last=None, open_interest=None, iv=None,
        )
        for e, b in ((_FUT, 2.0), (_FAR, 6.0))
        for k in (95.0, 100.0, 105.0)
        for side in ("call", "put")
    ]
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: fat
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    res = auth_client.get("/api/zerodte/term?symbol=SPY")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [p["expiry"] for p in body["points"]] == [
        _FUT.isoformat(), _FAR.isoformat()
    ]
    assert all(p["atm_strike"] == 100.0 for p in body["points"])
    ivs = [p["atm_iv"] for p in body["points"]]
    assert all(v is not None and v > 0 for v in ivs)
    assert body["slope"] is not None
    assert body["shape"] in ("contango", "backwardation", "flat")


def test_term_structure_unquoted_expiry_is_none(auth_client, monkeypatch):
    rows = [
        types.SimpleNamespace(
            strike=100.0, type=side, expiry=e,
            bid=(2.0 if e == _FUT else None),
            ask=(2.2 if e == _FUT else None),
            last=None, open_interest=None, iv=None,
        )
        for e in (_FUT, _FAR)
        for side in ("call", "put")
    ]
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    res = auth_client.get("/api/zerodte/term?symbol=SPY")
    assert res.status_code == 200
    pts = {p["expiry"]: p["atm_iv"] for p in res.json()["points"]}
    assert pts[_FUT.isoformat()] is not None
    assert pts[_FAR.isoformat()] is None
    assert res.json()["slope"] is None  # one solved point can't make a curve
