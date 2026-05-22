"""Deterministic regime classifier tests.

Critical case: a single extreme threshold (e.g. VIX>30) must NOT trigger
crisis when paired with a benign SPY 5d return — crisis requires both.
"""

import pytest

from calculations.regime import (
    MIN_CONFIDENCE,
    PRIORITY_ORDER,
    MarketSnapshot,
    _sector_dispersion,
    classify,
)


def _snap(**kw) -> MarketSnapshot:
    base = dict(
        vix_level=17.0,
        vix_5d_change_pct=0.0,
        spy_20d_return_pct=2.0,
        spy_5d_return_pct=0.5,
        sector_5d_returns={
            "XLK": 1.0, "XLF": 0.8, "XLV": 0.6, "XLY": 0.9, "XLP": 0.5,
            "XLI": 0.7, "XLE": 0.4, "XLB": 0.6, "XLU": 0.3, "XLRE": 0.5, "XLC": 0.8,
        },
        hyg_lqd_ratio=None,
    )
    base.update(kw)
    return MarketSnapshot(**base)


# ---------------------------------------------------------------------------
# Priority ordering — most severe wins
# ---------------------------------------------------------------------------


def test_priority_order_constants_match_evaluators():
    assert PRIORITY_ORDER[0] == "crisis"
    assert PRIORITY_ORDER[-1] == "mean_reverting_chop"


def test_crisis_when_both_conditions_extreme():
    # VIX > 30 AND SPY 5d down > 5% — both crisis rules satisfied.
    r = classify(_snap(vix_level=42.0, spy_5d_return_pct=-7.0, vix_5d_change_pct=50.0))
    assert r.regime == "crisis"
    assert r.confidence == 1.0
    assert {s.name for s in r.contributing_signals} == {"VIX level", "SPY 5-day return"}


def test_vol_spike_when_vix_jumps_but_spy_holds():
    # VIX rose >30% but SPY isn't crashed — should be vol_spike, NOT crisis.
    r = classify(_snap(vix_level=25.0, vix_5d_change_pct=45.0, spy_5d_return_pct=-1.0))
    assert r.regime == "vol_spike"


# ---------------------------------------------------------------------------
# The user's specific test: a near-miss on one extreme condition must NOT
# accidentally trigger crisis. Crisis requires BOTH VIX>30 AND SPY 5d down >5%.
# ---------------------------------------------------------------------------


def test_high_vix_alone_does_not_trigger_crisis():
    """VIX=35 but SPY is flat → only 1/2 crisis rules satisfied = 0.5 conf.
    Below MIN_CONFIDENCE — must NOT classify as crisis. Should fall through."""
    r = classify(_snap(vix_level=35.0, spy_5d_return_pct=0.5, vix_5d_change_pct=10.0))
    assert r.regime != "crisis"
    # And confidence on crisis would have been 0.5 — verify it's below the gate.
    assert 0.5 < MIN_CONFIDENCE


def test_sharp_spy_drop_alone_does_not_trigger_crisis():
    """SPY -7% but VIX hasn't blown out (still 24) → 1/2 crisis rules.
    Not crisis. Likely vol_spike if VIX is rising fast."""
    r = classify(_snap(vix_level=24.0, vix_5d_change_pct=15.0, spy_5d_return_pct=-7.0))
    assert r.regime != "crisis"


# ---------------------------------------------------------------------------
# Risk-on / defensive / chop happy paths
# ---------------------------------------------------------------------------


def test_risk_on_when_spy_up_vix_low_breadth_broad():
    r = classify(_snap(
        vix_level=14.0, spy_20d_return_pct=4.0, vix_5d_change_pct=-2.0,
        sector_5d_returns={k: 1.0 for k in ("XLK", "XLF", "XLV", "XLY", "XLP", "XLI", "XLE", "XLB", "XLU", "XLRE", "XLC")},
    ))
    assert r.regime == "risk_on"
    assert r.confidence == 1.0


def test_defensive_when_xlu_outperforms_xly_and_vix_rising():
    # All three tightened defensive rules: XLU>XLY, VIX 5d change >5%,
    # VIX absolute level ≥ 18.
    r = classify(_snap(
        vix_level=22.0,
        vix_5d_change_pct=8.0,
        spy_20d_return_pct=-1.0,
        sector_5d_returns={"XLU": 2.0, "XLY": -1.5, "XLK": 0.0, "XLF": 0.0},
    ))
    assert r.regime == "defensive"


def test_falls_through_to_chop_when_nothing_matches():
    # Quiet sideways market: VIX 17, SPY flat, no extreme moves anywhere.
    r = classify(_snap(
        vix_level=17.0, spy_20d_return_pct=0.5, spy_5d_return_pct=0.1,
        vix_5d_change_pct=1.0,
    ))
    assert r.regime == "mean_reverting_chop"


# ---------------------------------------------------------------------------
# Contributing signals: only satisfied ones returned
# ---------------------------------------------------------------------------


def test_contributing_signals_only_includes_satisfied():
    r = classify(_snap(
        vix_level=14.0, spy_20d_return_pct=4.0, vix_5d_change_pct=-2.0,
        sector_5d_returns={k: 1.0 for k in ("XLK", "XLF", "XLV", "XLY", "XLP", "XLI", "XLE", "XLB", "XLU", "XLRE", "XLC")},
    ))
    for s in r.contributing_signals:
        assert s.satisfied is True
    names = [s.name for s in r.contributing_signals]
    assert "Sector dispersion (breadth proxy)" in names  # transparency on the substitution


# ---------------------------------------------------------------------------
# Sector dispersion helper
# ---------------------------------------------------------------------------


def test_sector_dispersion_zero_when_uniform():
    assert _sector_dispersion({"XLK": 1.0, "XLF": 1.0, "XLV": 1.0}) == pytest.approx(0.0)


def test_sector_dispersion_high_when_narrow():
    # One sector huge, rest flat → high dispersion.
    d = _sector_dispersion({"XLK": 10.0, "XLF": 0.0, "XLV": 0.0, "XLY": 0.0})
    assert d > 3.0


def test_sector_dispersion_empty_safe():
    assert _sector_dispersion({}) == 0.0
