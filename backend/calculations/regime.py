"""Deterministic market-regime classifier (no ML).

5 regime labels per README §9.3 — but implemented as rules rather than as
a trained classifier. Reasoning: the original "RF" framing was circular
because rules and labels are computed from the same primitives. A
classifier would just re-derive the rules at ~95% accuracy and tell us
nothing. The honest version is to compute the label directly and label
it "Rule-based, not ML" in the UI.

Priority order (most severe first) — when multiple regimes' confidence
exceeds the threshold, the highest-priority one wins. Falls through to
`mean_reverting_chop` when nothing else fully matches.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal

RegimeName = Literal[
    "crisis", "vol_spike", "defensive", "risk_on", "mean_reverting_chop"
]

PRIORITY_ORDER: tuple[RegimeName, ...] = (
    "crisis",
    "vol_spike",
    "defensive",
    "risk_on",
    "mean_reverting_chop",
)

# Minimum fraction of a regime's rules that must be satisfied for that
# regime to "win". Below this, fall through to the next-priority regime.
# 0.7 means a 3-rule regime needs all 3 (2/3 = 0.667 < 0.7), and a 2-rule
# regime needs both (1/2 = 0.5 < 0.7). Conservative classification —
# false-positives feel worse than "chop by default" in a UI context.
MIN_CONFIDENCE = 0.7


@dataclass
class Signal:
    name: str
    value: float
    rule: str          # human-readable comparison, e.g. "< 15"
    satisfied: bool


@dataclass
class RegimeClassification:
    regime: RegimeName
    confidence: float
    contributing_signals: list[Signal]


@dataclass
class MarketSnapshot:
    """All inputs needed for classification — pure, no I/O. Caller composes
    from cached price series + computed sector returns."""

    vix_level: float
    vix_5d_change_pct: float           # percent change in VIX level over last 5 sessions
    spy_20d_return_pct: float           # SPY total return % over last 20 sessions
    spy_5d_return_pct: float            # SPY total return % over last 5 sessions
    sector_5d_returns: dict[str, float]  # {"XLK": 1.2, "XLF": -0.4, ...} percents
    hyg_lqd_ratio: float | None         # credit spread proxy; None if unavailable


# ---------------------------------------------------------------------------
# Per-regime rule evaluators. Each returns (signals_examined, n_satisfied).
# ---------------------------------------------------------------------------


def _evaluate_crisis(s: MarketSnapshot) -> list[Signal]:
    return [
        Signal("VIX level", s.vix_level, "> 30", s.vix_level > 30),
        Signal("SPY 5-day return", s.spy_5d_return_pct, "< -5", s.spy_5d_return_pct < -5),
    ]


def _evaluate_vol_spike(s: MarketSnapshot) -> list[Signal]:
    return [
        Signal(
            "VIX 5-day change",
            s.vix_5d_change_pct,
            "> +30%",
            s.vix_5d_change_pct > 30,
        ),
        Signal("VIX level", s.vix_level, "> 20", s.vix_level > 20),
    ]


def _evaluate_defensive(s: MarketSnapshot) -> list[Signal]:
    xlu = s.sector_5d_returns.get("XLU", 0.0)
    xly = s.sector_5d_returns.get("XLY", 0.0)
    # Thresholds tightened from the README's loose phrasing to avoid false
    # positives on quiet sideways markets — "≥0% rising" + "≥15 VIX" was
    # tripping benign tape as defensive. The corrected version requires a
    # real VIX rise AND elevated absolute level, not just non-negative.
    return [
        Signal("XLU vs XLY (5d)", xlu - xly, "XLU outperforming XLY", xlu > xly),
        Signal("VIX 5-day change", s.vix_5d_change_pct, "> +5%", s.vix_5d_change_pct > 5),
        Signal("VIX level", s.vix_level, "≥ 18", s.vix_level >= 18),
    ]


def _evaluate_risk_on(s: MarketSnapshot) -> list[Signal]:
    dispersion = _sector_dispersion(s.sector_5d_returns)
    return [
        # SPY threshold tightened from README's "> 0" — a barely-positive 20d
        # return on a quiet market isn't a risk-on regime, it's chop. The 2%
        # cutoff means "actual trend up, not noise". (Annualized that's ~30%
        # which is high but the trigger is one-tail.)
        Signal("SPY 20-day return", s.spy_20d_return_pct, "> 2%", s.spy_20d_return_pct > 2),
        Signal("VIX level", s.vix_level, "< 20", s.vix_level < 20),
        # Sector dispersion as breadth proxy — FRED carries no NYAD/breadth
        # series (verified 2026-05-16). Low dispersion = broad participation
        # = "risk-on character". We label it explicitly so UI users see the
        # source.
        Signal(
            "Sector dispersion (breadth proxy)",
            dispersion,
            "< 1.5%",
            dispersion < 1.5,
        ),
    ]


def _evaluate_mean_reverting_chop(s: MarketSnapshot) -> list[Signal]:
    return [
        Signal("VIX level", s.vix_level, "15 – 20", 15 <= s.vix_level <= 20),
        Signal("SPY 20-day return", s.spy_20d_return_pct, "|·| < 3", abs(s.spy_20d_return_pct) < 3),
    ]


_EVALUATORS = {
    "crisis": _evaluate_crisis,
    "vol_spike": _evaluate_vol_spike,
    "defensive": _evaluate_defensive,
    "risk_on": _evaluate_risk_on,
    "mean_reverting_chop": _evaluate_mean_reverting_chop,
}


def _sector_dispersion(sector_returns: dict[str, float]) -> float:
    """Std of sector ETF 5-day returns. Low = broad participation, high = narrow leadership."""
    values = list(sector_returns.values())
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def classify(snapshot: MarketSnapshot) -> RegimeClassification:
    """Evaluate regimes in priority order; first to clear MIN_CONFIDENCE wins.

    `contributing_signals` only includes the signals that were SATISFIED
    for the winning regime — keeps the UI tooltip readable.
    """
    for regime in PRIORITY_ORDER:
        signals = _EVALUATORS[regime](snapshot)
        satisfied = [s for s in signals if s.satisfied]
        confidence = len(satisfied) / len(signals) if signals else 0.0

        if regime == "mean_reverting_chop":
            # Default fallthrough — always wins if nothing else did.
            return RegimeClassification(
                regime=regime,
                confidence=confidence,
                contributing_signals=satisfied,
            )

        if confidence >= MIN_CONFIDENCE:
            return RegimeClassification(
                regime=regime,
                confidence=confidence,
                contributing_signals=satisfied,
            )

    # Defensive — shouldn't reach since mean_reverting_chop is the default.
    return RegimeClassification(
        regime="mean_reverting_chop",
        confidence=0.0,
        contributing_signals=[],
    )
