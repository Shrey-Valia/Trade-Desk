"""Calculation correctness — known inputs, known outputs."""

from datetime import date

import pytest

from calculations.expected_move import (
    atm_straddle_price,
    expected_move,
    expected_move_bands,
)
from calculations.gamma_exposure import (
    gamma_flip,
    gex_by_strike,
    largest_oi_strike,
    max_pain,
)
from calculations.iv_metrics import iv_percentile, iv_rank, vrp
from calculations.pc_ratio import pc_ratio
from calculations.realized_vol import realized_vol
from calculations.skew import skew_25d
from calculations.types import ContractRow

EXP = date(2026, 5, 16)


def _row(**kw):
    base = dict(strike=100.0, expiry=EXP, type="call")
    base.update(kw)
    return ContractRow(**base)


# ---------- iv_metrics ----------


def test_iv_rank_canonical():
    assert iv_rank(50, [0, 100]) == pytest.approx(50.0)
    assert iv_rank(75, [50, 100]) == pytest.approx(50.0)


def test_iv_rank_returns_none_when_history_too_short():
    assert iv_rank(50, []) is None
    assert iv_rank(50, [50]) is None


def test_iv_rank_returns_none_when_min_equals_max():
    assert iv_rank(50, [50, 50, 50]) is None


def test_iv_percentile_proxy():
    assert iv_percentile(50, [10, 20, 30, 40, 60]) == pytest.approx(80.0)
    assert iv_percentile(0, [10, 20, 30]) == pytest.approx(0.0)


def test_vrp_signed():
    assert vrp(35, 25) == 10
    assert vrp(20, 30) == -10


# ---------- realized_vol ----------


def test_realized_vol_returns_none_below_window():
    assert realized_vol([100, 101, 102], window=30) is None


def test_realized_vol_zero_for_flat_series():
    flat = [100.0] * 60
    assert realized_vol(flat, window=30) == pytest.approx(0.0)


def test_realized_vol_positive_for_volatile_series():
    closes = [100, 105, 95, 110, 90, 115, 85] * 10
    rv = realized_vol(closes, window=30)
    assert rv is not None and rv > 50  # very volatile series, RV should be high


# ---------- expected_move ----------


def test_expected_move_heuristic():
    assert expected_move(2.5, 2.5) == pytest.approx(4.25)


def test_expected_move_bands_symmetric():
    upper, lower = expected_move_bands(spot=100, em=5)
    assert (upper, lower) == (105, 95)


def test_atm_straddle_picks_closest_strike():
    chain = [
        _row(strike=98, type="call", bid=2.0, ask=2.4),
        _row(strike=98, type="put", bid=1.0, ask=1.4),
        _row(strike=100, type="call", bid=1.0, ask=1.2),
        _row(strike=100, type="put", bid=1.5, ask=1.7),
    ]
    result = atm_straddle_price(chain, spot=100.5, expiry=EXP)
    assert result is not None
    call_mid, put_mid = result
    assert call_mid == pytest.approx(1.1)
    assert put_mid == pytest.approx(1.6)


# ---------- gamma_exposure ----------


def test_max_pain_simple_balanced_chain():
    """Per README §13 example."""
    chain = [
        _row(strike=100, type="call", open_interest=1000),
        _row(strike=105, type="call", open_interest=500),
        _row(strike=95, type="put", open_interest=1000),
        _row(strike=100, type="put", open_interest=500),
    ]
    assert max_pain(chain) == 100


def test_max_pain_returns_none_for_empty_chain():
    assert max_pain([]) is None


def test_gex_by_strike_sign_convention():
    chain = [
        _row(strike=100, type="call", open_interest=10, gamma=0.05),
        _row(strike=100, type="put", open_interest=10, gamma=0.05),
    ]
    gex = gex_by_strike(chain, spot=100)
    # Calls (-) and puts (+) at same strike + gamma should net to zero.
    assert gex[100] == pytest.approx(0.0)


def test_gamma_flip_finds_first_nonneg_strike():
    gex = {90: -100, 95: -50, 100: +30, 105: +20}
    # cumulative: 90: -100, 95: -150, 100: -120, 105: -100 → never crosses
    assert gamma_flip(gex) is None
    gex2 = {90: -100, 95: -50, 100: +200}
    # cumulative: -100, -150, +50 → flips at 100
    assert gamma_flip(gex2) == 100


def test_largest_oi_strike():
    chain = [
        _row(strike=100, type="call", open_interest=500),
        _row(strike=110, type="call", open_interest=2000),
        _row(strike=120, type="call", open_interest=300),
    ]
    assert largest_oi_strike(chain, "call") == (110, 2000)
    assert largest_oi_strike(chain, "put") is None


# ---------- skew ----------


def test_skew_25d_positive_for_put_skew():
    chain = [
        _row(strike=90, type="put", delta=-0.25, iv=0.40),
        _row(strike=110, type="call", delta=0.25, iv=0.30),
    ]
    assert skew_25d(chain, expiry=EXP) == pytest.approx(0.10)


def test_skew_25d_returns_none_when_one_side_missing():
    chain = [_row(strike=90, type="put", delta=-0.25, iv=0.40)]
    assert skew_25d(chain, expiry=EXP) is None


def test_skew_25d_filters_by_delta_window():
    chain = [
        _row(strike=80, type="put", delta=-0.40, iv=0.99),  # outside window
        _row(strike=110, type="call", delta=0.25, iv=0.30),
    ]
    assert skew_25d(chain, expiry=EXP) is None


# ---------- pc_ratio ----------


def test_pc_ratio_returns_none_for_zero_calls():
    assert pc_ratio(0, 100) is None


def test_pc_ratio_basic():
    assert pc_ratio(100, 50) == 0.5
    assert pc_ratio(100, 200) == 2.0
