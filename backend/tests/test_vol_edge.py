"""Vol edge synthesis tests — priority order matters.

Crisis overrides pre-earnings rich. Pre-earnings rich overrides generic
favor-selling. Data-availability fallthrough is honest Neutral, not
warning-worthy.
"""

import pytest

from calculations.vol_edge import (
    PREEARNINGS_DAYS,
    VRP_PREEARNINGS_RICH_THRESHOLD,
    VRP_PREMIUM_CHEAP_THRESHOLD,
    VRP_PREMIUM_RICH_THRESHOLD,
    compute_vol_edge,
)


# ---------------------------------------------------------------------------
# Priority order — most important tests
# ---------------------------------------------------------------------------


def test_crisis_regime_overrides_pre_earnings_rich():
    """Even a slam-dunk pre-ER setup must yield to a crisis regime override."""
    r = compute_vol_edge(
        predicted_rv=20.0, current_iv30=80.0,        # VRP = +60, very rich
        regime="crisis",
        days_to_earnings=2,                           # within pre-ER window
    )
    assert r.verdict == "elevated_vol_caution"
    assert r.signals_used == ["rf_regime"]
    assert "crisis" in r.rationale


def test_vol_spike_regime_overrides_favor_selling():
    r = compute_vol_edge(
        predicted_rv=25.0, current_iv30=50.0,        # VRP = +25
        regime="vol_spike",
        days_to_earnings=None,
    )
    assert r.verdict == "elevated_vol_caution"


def test_pre_earnings_rich_overrides_generic_favor_selling():
    """When both rules 2 and 3 match, the more specific 'pre-earnings rich'
    label wins because it carries more information for the user."""
    r = compute_vol_edge(
        predicted_rv=30.0, current_iv30=50.0,        # VRP = +20 > both thresholds
        regime="risk_on",
        days_to_earnings=3,                           # within pre-ER window
    )
    assert r.verdict == "pre_earnings_rich"
    assert "lstm_vol" in r.signals_used
    assert "earnings_proximity" in r.signals_used
    assert "3d to earnings" in r.rationale


def test_pre_earnings_only_fires_when_BOTH_conditions_met():
    """Earnings in 3 days but VRP only +12 → doesn't satisfy >15 threshold →
    falls through to generic 'favor selling'."""
    r = compute_vol_edge(
        predicted_rv=30.0, current_iv30=42.0,        # VRP = +12 (< 15)
        regime="risk_on",
        days_to_earnings=3,
    )
    assert r.verdict == "favor_selling"
    assert "earnings_proximity" not in r.signals_used  # only LSTM drove this


def test_generic_favor_selling_when_no_earnings_nearby():
    r = compute_vol_edge(
        predicted_rv=30.0, current_iv30=45.0,        # VRP = +15 (> 10)
        regime="risk_on",
        days_to_earnings=None,
    )
    assert r.verdict == "favor_selling"
    assert r.signals_used == ["lstm_vol"]


def test_favor_buying_on_negative_VRP():
    r = compute_vol_edge(
        predicted_rv=35.0, current_iv30=30.0,        # VRP = -5 (< -3)
        regime="risk_on",
        days_to_earnings=None,
    )
    assert r.verdict == "favor_buying"


def test_neutral_in_fair_value_band():
    r = compute_vol_edge(
        predicted_rv=20.0, current_iv30=22.0,        # VRP = +2, between thresholds
        regime="risk_on",
        days_to_earnings=None,
    )
    assert r.verdict == "neutral"
    assert "lstm_vol" in r.signals_used


# ---------------------------------------------------------------------------
# Data-availability fallthrough — Neutral, NOT a warning
# ---------------------------------------------------------------------------


def test_missing_lstm_yields_neutral_with_explicit_rationale():
    r = compute_vol_edge(
        predicted_rv=None, current_iv30=22.0,
        regime="risk_on", days_to_earnings=None,
    )
    assert r.verdict == "neutral"
    assert r.signals_used == []
    assert "LSTM unavailable" in r.rationale


def test_missing_iv_yields_neutral_with_explicit_rationale():
    r = compute_vol_edge(
        predicted_rv=30.0, current_iv30=None,
        regime="risk_on", days_to_earnings=None,
    )
    assert r.verdict == "neutral"
    assert r.signals_used == []
    assert "Insufficient options data" in r.rationale


def test_missing_regime_does_not_block_other_verdicts():
    """Regime is optional context for some verdicts but not required for
    favor_selling / favor_buying based on VRP alone."""
    r = compute_vol_edge(
        predicted_rv=20.0, current_iv30=45.0,        # VRP = +25
        regime=None, days_to_earnings=None,
    )
    assert r.verdict == "favor_selling"


# ---------------------------------------------------------------------------
# Threshold boundary checks (sanity on the constants)
# ---------------------------------------------------------------------------


def test_VRP_at_rich_threshold_does_not_fire():
    """Strict-greater comparison, not ≥."""
    r = compute_vol_edge(
        predicted_rv=20.0,
        current_iv30=20.0 + VRP_PREMIUM_RICH_THRESHOLD,  # VRP = exactly +10
        regime="risk_on", days_to_earnings=None,
    )
    assert r.verdict == "neutral"


def test_VRP_just_above_rich_threshold_fires_selling():
    r = compute_vol_edge(
        predicted_rv=20.0,
        current_iv30=20.0 + VRP_PREMIUM_RICH_THRESHOLD + 0.01,  # VRP > +10
        regime="risk_on", days_to_earnings=None,
    )
    assert r.verdict == "favor_selling"


def test_pre_earnings_window_boundary():
    """≤ PREEARNINGS_DAYS is inclusive — exactly on the boundary fires."""
    r = compute_vol_edge(
        predicted_rv=20.0,
        current_iv30=20.0 + VRP_PREEARNINGS_RICH_THRESHOLD + 1,
        regime="risk_on",
        days_to_earnings=PREEARNINGS_DAYS,
    )
    assert r.verdict == "pre_earnings_rich"


def test_pre_earnings_day_after_window_falls_to_generic():
    r = compute_vol_edge(
        predicted_rv=20.0,
        current_iv30=20.0 + VRP_PREEARNINGS_RICH_THRESHOLD + 1,
        regime="risk_on",
        days_to_earnings=PREEARNINGS_DAYS + 1,
    )
    assert r.verdict == "favor_selling"
