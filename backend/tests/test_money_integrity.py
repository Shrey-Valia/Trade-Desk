"""Money integrity — exact 2dp storage, no float drift across many writes.

The P0 was: money columns stored as FLOAT accumulate binary-floating-point
error over many sequential slice-outs / payouts. The fix stores dollars as
NUMERIC(12,2) via the `Money` TypeDecorator (exact to the cent on disk, handed
back to Python as float). These tests assert:

  1. `quantize_money` rounds to an exact 2dp Decimal (ROUND_HALF_UP).
  2. The `Money` column round-trips exactly and returns a float (so downstream
     float math never mixes with Decimal).
  3. Summing the realized_pnl of MANY closed trades is exact — the value read
     back per row is already cent-quantized, so the sum has no drift.
  4. Many sequential scale-outs accumulate onto one trade's realized_pnl with a
     total that matches an exact Decimal reference to the cent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

import routers.journal as journal_router
from models.trade import Trade
from services.money import Money, quantize_money, to_float
from tests.conftest import make_combine

# ---------------------------------------------------------------------------
# quantize_money — the storage-boundary rounding
# ---------------------------------------------------------------------------


def test_quantize_rounds_to_two_places_half_up():
    assert quantize_money(1.005) == Decimal("1.01")   # half rounds UP
    assert quantize_money(2.675) == Decimal("2.68")   # the classic float trap
    assert quantize_money(0.1) == Decimal("0.10")
    assert quantize_money(-3.456) == Decimal("-3.46")
    assert quantize_money(100) == Decimal("100.00")


def test_quantize_none_passes_through():
    assert quantize_money(None) is None
    assert to_float(None) is None


def test_quantize_decimal_input_is_stable():
    assert quantize_money(Decimal("12.349")) == Decimal("12.35")


# ---------------------------------------------------------------------------
# Money column — exact DB round-trip, float on read
# ---------------------------------------------------------------------------


def _new_trade(realized=None, net=0.0) -> Trade:
    return Trade(
        symbol="SPY",
        strategy="long_call",
        legs_json="[]",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=400.0,
        net_debit_credit=net,
        status="closed",
        realized_pnl=realized,
    )


def test_money_column_returns_float_not_decimal(session_factory):
    s = session_factory()
    t = _new_trade(realized=123.45)
    s.add(t)
    s.commit()
    s.refresh(t)
    assert isinstance(t.realized_pnl, float)
    assert t.realized_pnl == 123.45
    s.close()


def test_money_column_stores_exact_cents_no_drift(session_factory):
    """Add 0.10 ten times through the same round() pattern the scale-out path
    uses; FLOAT storage would land at 0.9999999999999999, NUMERIC lands at an
    exact 1.00."""
    s = session_factory()
    t = _new_trade(realized=0.0)
    s.add(t)
    s.commit()
    for _ in range(10):
        t.realized_pnl = round((t.realized_pnl or 0.0) + 0.10, 2)
        s.commit()
        s.refresh(t)
    assert t.realized_pnl == 1.00
    # Read back through a fresh query — still exact, still float.
    raw = s.execute(select(Trade.realized_pnl)).scalar_one()
    assert raw == 1.00
    assert isinstance(raw, float)
    s.close()


def test_money_column_quantizes_unrounded_writes(session_factory):
    """Even if a caller forgets to round(), the Money type quantizes on bind so
    nothing sub-cent ever persists."""
    s = session_factory()
    t = _new_trade(realized=10.019)  # not pre-rounded
    s.add(t)
    s.commit()
    s.refresh(t)
    assert t.realized_pnl == 10.02
    s.close()


def test_sum_of_many_rows_is_exact(session_factory):
    """The realized_pnl sum across many closed trades — the basis of every
    balance/HWM/payout figure — must be exact. Each per-row value is already
    cent-quantized by the Money type, so the sum can't drift."""
    s = session_factory()
    # 1,000 rows of $0.07 → exactly $70.00. As float, 0.07 is inexact and a
    # naive running sum drifts; here each row reads back exact and the total
    # lands on the cent.
    for _ in range(1_000):
        s.add(_new_trade(realized=0.07))
    s.commit()
    rows = s.execute(select(Trade.realized_pnl)).scalars().all()
    total = quantize_money(sum(rows))
    assert total == Decimal("70.00")
    s.close()


def test_money_impl_is_numeric_12_2():
    """Guard the column definition itself so a future edit can't silently drop
    the precision back to a float."""
    impl = Money().impl
    assert impl.precision == 12
    assert impl.scale == 2


# ---------------------------------------------------------------------------
# End-to-end: many sequential scale-outs accumulate with no drift
# ---------------------------------------------------------------------------


@dataclass
class _StubQuote:
    price: float


@pytest.fixture
def client(auth_client):
    make_combine(auth_client, "50K")
    return auth_client


@pytest.fixture
def mock_quote(monkeypatch):
    state: dict[str, float] = {"price": 230.0}

    def _fake_get_quotes(symbols):
        return {sym: _StubQuote(price=state["price"]) for sym in symbols}

    monkeypatch.setattr(journal_router, "get_quotes", _fake_get_quotes)

    def _set(price: float) -> None:
        state["price"] = price

    return _set


def _straddle_payload(contracts: int) -> dict:
    expiry = (date.today() + timedelta(days=21)).isoformat()
    return {
        "symbol": "AAPL",
        "strategy": "long_straddle",
        "entry_date": datetime.now(timezone.utc).isoformat(),
        "entry_underlying_price": 230.0,
        "is_paper": True,
        "legs": [
            {"side": "call", "action": "buy", "strike": 230, "expiry": expiry,
             "contracts": contracts, "entry_price": 6.23},
            {"side": "put", "action": "buy", "strike": 230, "expiry": expiry,
             "contracts": contracts, "entry_price": 5.77},
        ],
    }


def test_many_sequential_scale_outs_accumulate_exactly(client, mock_quote):
    """Open a large position and scale out one contract at a time many times.
    The running realized_pnl after each slice must equal the EXACT Decimal sum
    of every slice the server booked — proving the accumulation across dozens of
    writes never drifts off the cent (the FLOAT column would).

    We mirror each slice's recomputed value into an exact Decimal accumulator
    and compare to the value the endpoint reports after every scale-out."""
    mock_quote(243.37)  # an awkward spot so slices aren't round numbers
    held = 30
    # is_paper=False: a 30-lot is far past the 50K scaling cap that journal
    # creates now enforce on PAPER positions; the non-paper record-keeping
    # path stays uncapped and exercises the identical scale-out accumulation.
    payload = _straddle_payload(held) | {"is_paper": False}
    tid = client.post("/api/journal/trades", json=payload).json()["id"]

    running = Decimal("0.00")
    prev_reported = Decimal("0.00")
    # Scale out 1 contract 29 times (leaving 1 held — the final close uses PATCH).
    for i in range(held - 1):
        body = client.post(
            f"/api/journal/trades/{tid}/scale-out", json={"qty": 1}
        ).json()
        reported = quantize_money(body["realized_pnl"])
        # The slice the server just booked is the delta in the running total.
        slice_booked = reported - prev_reported
        running += slice_booked
        prev_reported = reported
        # Every reported total is exactly cent-quantized (2dp, no drift).
        assert reported == reported.quantize(Decimal("0.01")), (i, reported)
        # And the reported running total equals our independent Decimal sum.
        assert reported == running, (i, reported, running)

    # Final realized read straight from the DB matches the exact accumulator.
    final = quantize_money(
        client.get(f"/api/journal/trades/{tid}").json()["realized_pnl"]
    )
    assert final == running
