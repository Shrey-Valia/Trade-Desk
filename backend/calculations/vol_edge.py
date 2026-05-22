"""Phase 7.9 — Vol Edge synthesis.

Rule-based synthesis card that replaces the failed-baseline Ensemble card.
Uses ONLY signals we trust (LSTM + RF Regime + earnings proximity) to
produce a single actionable verdict.

This is the "what the Ensemble was supposed to do" — but built from rules
because the trained ensemble didn't earn its slot (Phase 7.8 ablation).

Priority order (first match wins):
  1. regime ∈ {crisis, vol_spike}      → "Caution — elevated vol regime"
  2. days_to_earnings ≤ 5 AND VRP > 15  → "Pre-earnings rich"
  3. VRP > 10                           → "Favor selling premium"
  4. VRP < -3                           → "Favor buying premium"
  5. default                            → "Neutral"

`signals_used` is dynamic: lists only the inputs that actually drove
THIS specific verdict — same transparency pattern as the regime card's
`contributing_signals`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Module-level tunable thresholds. Surface here so adjusting after 30-60d
# of live observation is a one-line change. Asymmetric on purpose: selling
# premium is the higher-conviction trade, so it gets a higher VRP bar than
# the lower-conviction "buy premium" call.
VRP_PREMIUM_RICH_THRESHOLD = 10.0
VRP_PREMIUM_CHEAP_THRESHOLD = -3.0
VRP_PREEARNINGS_RICH_THRESHOLD = 15.0
PREEARNINGS_DAYS = 5

CAUTION_REGIMES = {"crisis", "vol_spike"}

Verdict = Literal[
    "favor_selling",
    "favor_buying",
    "pre_earnings_rich",
    "elevated_vol_caution",
    "neutral",
]


@dataclass
class VolEdgeResult:
    verdict: Verdict
    label: str                            # human-readable verdict string
    rationale: str                        # one-line explanation citing the numbers
    signals_used: list[str] = field(default_factory=list)


def compute_vol_edge(
    *,
    predicted_rv: float | None,           # LSTM 7-day predicted realized vol %
    current_iv30: float | None,           # live ATM IV30 %
    regime: str | None,                   # one of the 5 regime labels
    days_to_earnings: int | None,         # None when no upcoming earnings
) -> VolEdgeResult:
    """Rule-based vol-edge verdict. Pure function — no I/O, fully testable."""

    # Hard data-availability checks fall through to honest Neutral with
    # explicit rationale. NO warning treatment downstream — this is just
    # the absence of signal, not a model failure.
    if predicted_rv is None:
        return VolEdgeResult(
            verdict="neutral",
            label="Neutral",
            rationale="LSTM unavailable for this ticker",
            signals_used=[],
        )
    if current_iv30 is None:
        return VolEdgeResult(
            verdict="neutral",
            label="Neutral",
            rationale="Insufficient options data",
            signals_used=[],
        )

    vrp = current_iv30 - predicted_rv

    # Rule 1: caution regimes override everything else. When dealers are
    # in short-gamma territory, no setup is worth the wrong-side exposure.
    if regime in CAUTION_REGIMES:
        return VolEdgeResult(
            verdict="elevated_vol_caution",
            label="Caution — elevated vol regime",
            rationale=f"Regime is {regime} — no premium-selling setup overrides this",
            signals_used=["rf_regime"],
        )

    # Rule 2: pre-earnings rich. Specific high-conviction setup that should
    # fire over the generic "favor selling" when both conditions are met.
    if (
        days_to_earnings is not None
        and 0 <= days_to_earnings <= PREEARNINGS_DAYS
        and vrp > VRP_PREEARNINGS_RICH_THRESHOLD
    ):
        return VolEdgeResult(
            verdict="pre_earnings_rich",
            label="Pre-earnings rich",
            rationale=(
                f"VRP +{vrp:.1f} ({days_to_earnings}d to earnings) — "
                "classic pre-print vol-selling setup"
            ),
            signals_used=["lstm_vol", "earnings_proximity"],
        )

    # Rule 3: generic premium-rich.
    if vrp > VRP_PREMIUM_RICH_THRESHOLD:
        regime_clause = f" in {regime} regime" if regime else ""
        return VolEdgeResult(
            verdict="favor_selling",
            label="Favor selling premium",
            rationale=(
                f"VRP +{vrp:.1f}{regime_clause} — IV is meaningfully above "
                "predicted realized vol"
            ),
            signals_used=["lstm_vol"],
        )

    # Rule 4: premium cheap.
    if vrp < VRP_PREMIUM_CHEAP_THRESHOLD:
        return VolEdgeResult(
            verdict="favor_buying",
            label="Favor buying premium",
            rationale=(
                f"VRP {vrp:+.1f} — predicted realized vol exceeds IV, "
                "options look underpriced"
            ),
            signals_used=["lstm_vol"],
        )

    # Default: neutral.
    return VolEdgeResult(
        verdict="neutral",
        label="Neutral",
        rationale=f"VRP {vrp:+.1f} — within fair-value band",
        signals_used=["lstm_vol"],
    )
