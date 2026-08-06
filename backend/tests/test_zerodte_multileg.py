"""WS5 — multi-leg open endpoint + server-side contract clamping."""

from __future__ import annotations

import types
from datetime import UTC, datetime

from models.trade import Trade
from routers import zerodte
from tests.conftest import make_combine

_TODAY = datetime.now(zerodte._ET).date()


def _row(strike: float, type_: str, bid=1.0, ask=1.2):
    """A duck-typed ContractRow with what the multi-leg pricer reads."""
    return types.SimpleNamespace(
        strike=float(strike),
        type=type_,
        expiry=_TODAY,
        bid=bid,
        ask=ask,
        last=None,
        open_interest=None,
        iv=None,
    )


def _stub_chain(monkeypatch, strikes=(95.0, 100.0, 105.0)):
    """Session-open + a small same-day chain with call+put at each strike."""
    rows = []
    for k in strikes:
        rows.append(_row(k, "call"))
        rows.append(_row(k, "put"))
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot",
        lambda sym, with_volume=False: rows,
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


# --- multi-leg open ---------------------------------------------------------


def test_multileg_vertical_opens_with_two_legs(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": "SPY",
            "contracts": 1,
            "strategy": "vertical",
            "legs": [
                {"side": "call", "action": "buy", "strike": 100, "ratio": 1},
                {"side": "call", "action": "sell", "strike": 105, "ratio": 1},
            ],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["strategy"] == "vertical"
    assert len(body["legs"]) == 2
    sides = {(leg["side"], leg["action"], leg["strike"]) for leg in body["legs"]}
    assert ("call", "buy", 100.0) in sides
    assert ("call", "sell", 105.0) in sides


def test_multileg_iron_condor_four_legs(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch, strikes=(90.0, 95.0, 105.0, 110.0))
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": "SPY",
            "contracts": 1,
            "strategy": "iron_condor",
            "legs": [
                {"side": "put", "action": "buy", "strike": 90},
                {"side": "put", "action": "sell", "strike": 95},
                {"side": "call", "action": "sell", "strike": 105},
                {"side": "call", "action": "buy", "strike": 110},
            ],
        },
    )
    assert res.status_code == 201, res.text
    assert len(res.json()["legs"]) == 4


def test_multileg_butterfly_ratio_doubles_body(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch, strikes=(95.0, 100.0, 105.0))
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": "SPY",
            "contracts": 1,  # base 1 × Σratio 4 = 4 total ≤ cap 5
            "strategy": "butterfly",
            "legs": [
                {"side": "call", "action": "buy", "strike": 95, "ratio": 1},
                {"side": "call", "action": "sell", "strike": 100, "ratio": 2},
                {"side": "call", "action": "buy", "strike": 105, "ratio": 1},
            ],
        },
    )
    assert res.status_code == 201, res.text
    legs = {leg["strike"]: leg["contracts"] for leg in res.json()["legs"]}
    # ratio × base contracts: wings 1×1=1, body 2×1=2.
    assert legs[95.0] == 1 and legs[105.0] == 1
    assert legs[100.0] == 2


def test_multileg_ratio_cannot_bypass_scaling_cap(auth_client, session_factory, monkeypatch):
    """The aggregate scaling cap counts TOTAL contracts across all legs. A
    butterfly with base = cap and Σratio = 4 consumes 4× the cap — the gate must
    reject it. Regression: the cap was checked on the BASE, not base × Σratio, so
    a multi-leg structure could be persisted well past the cap."""
    make_combine(auth_client, "50K")  # scaling cap = 5 contracts at $0 built equity
    _stub_chain(monkeypatch, strikes=(95.0, 100.0, 105.0))
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": "SPY",
            "contracts": 5,  # base=5 × Σratio 4 = 20 total >> cap 5
            "strategy": "butterfly",
            "legs": [
                {"side": "call", "action": "buy", "strike": 95, "ratio": 1},
                {"side": "call", "action": "sell", "strike": 100, "ratio": 2},
                {"side": "call", "action": "buy", "strike": 105, "ratio": 1},
            ],
        },
    )
    assert res.status_code == 422, res.text  # rejected on the EFFECTIVE largest-leg size


def test_multileg_rejects_missing_strike(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch, strikes=(100.0,))
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": "SPY",
            "legs": [
                {"side": "call", "action": "buy", "strike": 100},
                {"side": "call", "action": "sell", "strike": 200},  # not listed
            ],
        },
    )
    assert res.status_code == 422, res.text


def test_multileg_rejected_when_market_closed(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch)
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: False)
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={
            "symbol": "SPY",
            "legs": [
                {"side": "call", "action": "buy", "strike": 100},
                {"side": "put", "action": "buy", "strike": 100},
            ],
        },
    )
    assert res.status_code == 409


def test_multileg_requires_min_two_legs(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-multi",
        json={"symbol": "SPY", "legs": [{"side": "call", "action": "buy", "strike": 100}]},
    )
    assert res.status_code == 422  # pydantic min_length


# --- server-side contract clamping (folded from WS3) ------------------------


def _seed_open(session_factory, combine_id, contracts):
    s = session_factory()
    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(UTC),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="open",
    )
    t.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": contracts, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    s.close()


def test_clamp_helper_caps_to_remaining(session_factory, auth_client, monkeypatch):
    """_clamp_contracts_to_cap returns remaining capacity, not the request."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    s = session_factory()
    combine = s.get(Combine, c["id"])

    # 50K cap at base equity is small; force a known cap via the snapshot.
    monkeypatch.setattr(
        "routers.zerodte.combine_snapshot",
        lambda sess, comb: types.SimpleNamespace(max_contracts=3),
    )
    # nothing open → request honored up to the cap
    assert zerodte._clamp_contracts_to_cap(s, combine, 2) == 2
    assert zerodte._clamp_contracts_to_cap(s, combine, 10) == 3  # clamped to cap
    s.close()


def test_clamp_helper_accounts_for_open_contracts(session_factory, auth_client, monkeypatch):
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    _seed_open(session_factory, c["id"], contracts=2)  # 2 already open
    s = session_factory()
    combine = s.get(Combine, c["id"])
    monkeypatch.setattr(
        "routers.zerodte.combine_snapshot",
        lambda sess, comb: types.SimpleNamespace(max_contracts=3),
    )
    # cap 3, 2 open → only 1 remaining; a 5-lot clamps to 1.
    assert zerodte._clamp_contracts_to_cap(s, combine, 5) == 1
    s.close()


def test_clamp_helper_floors_to_structure_unit(session_factory, auth_client, monkeypatch):
    """Regression (P2): the clamp floors to a whole `unit` (per-1x structure
    total contracts) so a caller backing out base = returned // unit can't
    re-inflate above the cap, and a no-room clamp returns 0 (not the full
    request as before)."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    s = session_factory()
    combine = s.get(Combine, c["id"])
    monkeypatch.setattr(
        "routers.zerodte.combine_snapshot",
        lambda sess, comb: types.SimpleNamespace(max_contracts=5),
    )
    # cap 5, nothing open, iron condor unit=4, request 8 → floors to 4 (one
    # structure), so base = 4 // 4 = 1 persists 4 ≤ 5. (Unfloored it returned 5,
    # and base = max(1, 5 // 4) = 1 also persisted 4 — but a request that fit
    # exactly one-and-a-fraction structures must land on a whole multiple.)
    assert zerodte._clamp_contracts_to_cap(s, combine, 8, unit=4) == 4
    # A sub-unit remainder yields 0 (not a re-inflatable stub): cap 5, unit 4,
    # request 4 with 3 already... simulate remaining 2 via a smaller cap.
    monkeypatch.setattr(
        "routers.zerodte.combine_snapshot",
        lambda sess, comb: types.SimpleNamespace(max_contracts=2),
    )
    assert zerodte._clamp_contracts_to_cap(s, combine, 4, unit=4) == 0
    # No room at all → 0 (previously returned the full unclamped request).
    monkeypatch.setattr(
        "routers.zerodte.combine_snapshot",
        lambda sess, comb: types.SimpleNamespace(max_contracts=0),
    )
    assert zerodte._clamp_contracts_to_cap(s, combine, 10) == 0
    s.close()


def test_open_leg_persisted_size_never_exceeds_cap(auth_client, session_factory, monkeypatch):
    """End-to-end: the gate would 422, but if cap shifts the persisted leg is
    still clamped. Here we pin a cap of 2 and request 2 — it persists 2."""
    make_combine(auth_client, "50K")
    _stub_chain(monkeypatch)
    monkeypatch.setattr(
        "routers.zerodte.combine_snapshot",
        lambda sess, comb: types.SimpleNamespace(
            outcome="active", day_locked=False, max_contracts=2,
            balance=50_000.0, mll=48_000.0,
        ),
    )
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy", "strike": 100, "entry_price": 1.0, "contracts": 2},
    )
    assert res.status_code == 201, res.text
    assert res.json()["legs"][0]["contracts"] == 2
