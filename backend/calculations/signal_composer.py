"""Rule-based trade-setup synthesizer.

Pure function. Reads the values the dashboard already computes for a
ticker (LSTM, IV, regime, MC probs, BS strategy suggestion, calendar,
optional mock flow) and produces a single transparent verdict.

Axis-aware conflict detection (post-Phase 9 polish): rules are tagged
with the direction they support; after the dominant direction is
chosen, signals on the *opposite* end of the same axis move to the
conflict column and SUBTRACT from conviction. Orthogonal context
signals (different axis) stay visible in the agreeing list but do not
inflate the conviction score.

Axes:
  vol:       sell_premium ↔ buy_premium
  direction: directional_long ↔ directional_short
  regime:    avoid (no opposite; dominates everything else when severe)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

VerdictType = Literal[
    "sell_premium",
    "buy_premium",
    "directional_long",
    "directional_short",
    "neutral",
    "avoid",
]

# Rule weights. Tuned alongside BASE/SCALE below so a single weight-3
# signal lands in moderate, two aligned signals land in high, and a net
# weight ≤1 after conflict subtraction lands in low.
W_VRP_RICH = 3
W_VRP_VERY_RICH = 4
W_VRP_CHEAP = 3
W_LSTM_RV_RICH = 3
W_LSTM_RV_CHEAP = 3
W_PRE_EARNINGS_RICH = 4
W_PRE_EARNINGS_CHEAP = 3
W_REGIME_CAUTION = 4
W_REGIME_RISK_ON = 1
W_REGIME_DEFENSIVE = 2
W_SKEW_ELEVATED = 2
W_PC_EXTREME = 1
W_MOCK_FLOW = 2

# Conviction = clamp(BASE + SCALE · (agree − conflict), 0, 100).
# Calibration target:
#   net 0  → 30   (low)
#   net 1  → 38   (low)            ← single weight-1 context alone
#   net 2  → 46   (moderate edge)
#   net 3  → 54   (moderate)       ← one weight-3 vol signal
#   net 6  → 78   (high)           ← two aligned weight-3 signals
CONVICTION_BASE = 30
CONVICTION_SCALE = 8

# Directional verdicts require at least one non-context signal — i.e. one
# rule of weight ≥ 2 supporting the dominant direction. Weight-1 rules
# (risk-on regime, P/C extreme) are context only; they shouldn't anchor a
# trade recommendation on their own. Mock flow (w=2) and the regime rules
# (w=2+) all clear this bar.
DIRECTIONAL_MIN_SUPPORTING_WEIGHT = 2

CAUTION_REGIMES = {"crisis", "vol_spike"}

# Axis opposition. None means the verdict has no opposite (avoid /
# neutral never get classified as conflicting against another verdict).
_OPPOSITES: dict[VerdictType, VerdictType | None] = {
    "sell_premium": "buy_premium",
    "buy_premium": "sell_premium",
    "directional_long": "directional_short",
    "directional_short": "directional_long",
    "avoid": None,
    "neutral": None,
}


@dataclass
class SignalReason:
    label: str
    detail: str
    weight: int


@dataclass
class SignalInputs:
    """All scalar inputs the composer needs. Caller assembles this from
    the existing routers/calculations — composer does no I/O."""

    symbol: str
    predicted_rv: float | None = None
    iv30: float | None = None
    vrp: float | None = None
    skew_25d: float | None = None
    pc_ratio: float | None = None
    regime: str | None = None
    regime_confidence: float | None = None
    days_to_earnings: int | None = None
    mc_prob_up_1sigma: float | None = None
    mc_prob_down_1sigma: float | None = None
    bs_strategy_name: str | None = None
    bs_strategy_detail: str | None = None
    bs_prob_profit: float | None = None
    mock_flow_direction: str | None = None
    mock_flow_strength: float | None = None


@dataclass
class SignalVerdict:
    symbol: str
    verdict: str
    verdict_type: VerdictType
    conviction: int
    conviction_label: str
    signals_agreeing: list[SignalReason] = field(default_factory=list)
    signals_conflicting: list[SignalReason] = field(default_factory=list)
    thesis: str = ""
    suggested_structure: str | None = None
    suggested_structure_detail: str | None = None
    mock_flow_used: bool = False


VERDICT_HEADLINES: dict[VerdictType, str] = {
    "sell_premium": "Sell premium",
    "buy_premium": "Buy premium",
    "directional_long": "Directional long bias",
    "directional_short": "Directional short bias",
    "avoid": "Avoid — elevated regime risk",
    "neutral": "Neutral — no clear edge",
}


def compose(inp: SignalInputs) -> SignalVerdict:
    """Pure rule evaluation. Returns a fully-formed verdict object."""

    # Phase 1: fire all rules into a single list with their supported
    # direction. Nothing is classified as agreeing/conflicting yet.
    fired: list[tuple[SignalReason, VerdictType]] = []

    pre_earnings = inp.days_to_earnings is not None and 0 <= inp.days_to_earnings <= 5

    # -- VRP (1, 2, 3) -----------------------------------------------------
    if inp.vrp is not None:
        if inp.vrp > 25:
            fired.append((
                SignalReason(
                    "VRP very rich",
                    f"VRP +{inp.vrp:.1f} — IV trades well above LSTM-predicted RV",
                    W_VRP_VERY_RICH,
                ),
                "sell_premium",
            ))
        elif inp.vrp > 10:
            fired.append((
                SignalReason(
                    "VRP rich",
                    f"VRP +{inp.vrp:.1f} — IV above LSTM-predicted RV",
                    W_VRP_RICH,
                ),
                "sell_premium",
            ))
        elif inp.vrp < -3:
            fired.append((
                SignalReason(
                    "VRP cheap",
                    f"VRP {inp.vrp:+.1f} — predicted RV exceeds IV",
                    W_VRP_CHEAP,
                ),
                "buy_premium",
            ))

    # -- LSTM vs IV30 (4, 5) — distinct read from raw VRP -----------------
    if inp.predicted_rv is not None and inp.iv30 is not None and inp.iv30 > 0:
        ratio = inp.predicted_rv / inp.iv30
        if ratio < 0.6:
            fired.append((
                SignalReason(
                    "LSTM forecast well below IV",
                    f"Predicted RV {inp.predicted_rv:.1f}% vs IV30 {inp.iv30:.1f}% (ratio {ratio:.2f})",
                    W_LSTM_RV_RICH,
                ),
                "sell_premium",
            ))
        elif ratio > 1.2:
            fired.append((
                SignalReason(
                    "LSTM forecast above IV",
                    f"Predicted RV {inp.predicted_rv:.1f}% vs IV30 {inp.iv30:.1f}% (ratio {ratio:.2f})",
                    W_LSTM_RV_CHEAP,
                ),
                "buy_premium",
            ))

    # -- Earnings proximity (6, 7) ----------------------------------------
    if pre_earnings and inp.vrp is not None:
        if inp.vrp > 15:
            fired.append((
                SignalReason(
                    "Pre-earnings rich",
                    f"{inp.days_to_earnings}d to print, VRP +{inp.vrp:.1f} — classic short-vol setup",
                    W_PRE_EARNINGS_RICH,
                ),
                "sell_premium",
            ))
        elif inp.vrp < 5:
            fired.append((
                SignalReason(
                    "Pre-earnings cheap",
                    f"{inp.days_to_earnings}d to print, VRP {inp.vrp:+.1f} — underpriced vol into event",
                    W_PRE_EARNINGS_CHEAP,
                ),
                "buy_premium",
            ))

    # -- Regime (8, 9, 10) ------------------------------------------------
    if inp.regime in CAUTION_REGIMES:
        fired.append((
            SignalReason(
                f"{inp.regime.replace('_', ' ').title()} regime",
                "Dealer short-gamma territory — short-vol setups carry tail risk",
                W_REGIME_CAUTION,
            ),
            "avoid",
        ))
    elif inp.regime == "risk_on":
        fired.append((
            SignalReason(
                "Risk-on regime",
                "Broad market in risk-on mode — mild directional-long context",
                W_REGIME_RISK_ON,
            ),
            "directional_long",
        ))
    elif inp.regime == "defensive":
        fired.append((
            SignalReason(
                "Defensive regime",
                "Defensive rotation underway — supports short bias",
                W_REGIME_DEFENSIVE,
            ),
            "directional_short",
        ))

    # -- 25Δ skew (11) — elevated put skew supports buying premium
    # (downside tail richly priced; selling that tail carries risk). ------
    if inp.skew_25d is not None and inp.skew_25d > 0.15:
        fired.append((
            SignalReason(
                "Elevated 25Δ skew",
                f"Put-call IV skew {inp.skew_25d:+.2f} — downside tail richly priced",
                W_SKEW_ELEVATED,
            ),
            "buy_premium",
        ))

    # -- P/C ratio (12) — directional positioning context -----------------
    if inp.pc_ratio is not None:
        if inp.pc_ratio > 1.3:
            fired.append((
                SignalReason(
                    "Heavy call volume",
                    f"Call/Put volume {inp.pc_ratio:.2f}× — bullish positioning context",
                    W_PC_EXTREME,
                ),
                "directional_long",
            ))
        elif inp.pc_ratio < 0.5:
            fired.append((
                SignalReason(
                    "Heavy put volume",
                    f"Call/Put volume {inp.pc_ratio:.2f}× — bearish positioning context",
                    W_PC_EXTREME,
                ),
                "directional_short",
            ))

    # -- Mock sweep flow (13) — flagged as simulated ----------------------
    mock_used = False
    if inp.mock_flow_direction in ("bullish", "bearish"):
        mock_used = True
        strength = inp.mock_flow_strength or 0.0
        direction: VerdictType = (
            "directional_long" if inp.mock_flow_direction == "bullish" else "directional_short"
        )
        fired.append((
            SignalReason(
                "Simulated sweep flow",
                f"Mock sweeps tilt {inp.mock_flow_direction} (strength {strength:.2f})",
                W_MOCK_FLOW,
            ),
            direction,
        ))

    # Phase 2: tally votes per direction.
    votes: dict[VerdictType, int] = defaultdict(int)
    for reason, direction in fired:
        votes[direction] += reason.weight

    # Phase 3: pick dominant verdict.
    verdict_type = _pick_verdict_type(votes)

    # Calibration floor — directional verdicts collapse to neutral unless
    # at least one weight ≥ 2 signal supports them. Stacking three w=1
    # context signals shouldn't add up to a real trade recommendation.
    if verdict_type in ("directional_long", "directional_short"):
        max_supporting = max(
            (r.weight for r, d in fired if d == verdict_type),
            default=0,
        )
        if max_supporting < DIRECTIONAL_MIN_SUPPORTING_WEIGHT:
            verdict_type = "neutral"

    # Phase 4: classify each fired rule against the dominant verdict.
    opposite = _OPPOSITES.get(verdict_type)
    agreeing: list[SignalReason] = []
    conflicting: list[SignalReason] = []
    agree_weight = 0
    conflict_weight = 0
    for reason, direction in fired:
        if verdict_type == "neutral":
            # No axis to oppose against — every fired rule reads as
            # ambient context. None of it inflates conviction.
            agreeing.append(reason)
            continue
        if direction == verdict_type:
            agreeing.append(reason)
            agree_weight += reason.weight
        elif opposite and direction == opposite:
            conflicting.append(reason)
            conflict_weight += reason.weight
        else:
            # Orthogonal context (different axis). Visible to the reader
            # but does NOT count toward conviction either way.
            agreeing.append(reason)

    # Phase 5: conviction.
    raw = CONVICTION_BASE + CONVICTION_SCALE * (agree_weight - conflict_weight)
    conviction = max(0, min(100, raw))
    conviction_label = (
        "high" if conviction >= 70 else "moderate" if conviction >= 40 else "low"
    )

    headline = _headline_for(verdict_type, pre_earnings)
    structure, detail = _suggest_structure(verdict_type, inp)
    thesis = _build_thesis(inp, verdict_type, agreeing, conflicting, mock_used)

    return SignalVerdict(
        symbol=inp.symbol,
        verdict=headline,
        verdict_type=verdict_type,
        conviction=conviction,
        conviction_label=conviction_label,
        signals_agreeing=sorted(agreeing, key=lambda r: -r.weight),
        signals_conflicting=sorted(conflicting, key=lambda r: -r.weight),
        thesis=thesis,
        suggested_structure=structure,
        suggested_structure_detail=detail,
        mock_flow_used=mock_used,
    )


def _pick_verdict_type(votes: dict[VerdictType, int]) -> VerdictType:
    """Avoid wins outright when it has meaningful weight. Otherwise pick
    the highest-voted direction; default to neutral."""
    if votes.get("avoid", 0) >= W_REGIME_CAUTION:
        return "avoid"
    best_type: VerdictType = "neutral"
    best_score = 0
    for vt, score in votes.items():
        if vt in ("avoid", "neutral"):
            continue
        if score > best_score:
            best_score = score
            best_type = vt
    return best_type if best_score > 0 else "neutral"


def _headline_for(vt: VerdictType, pre_earnings: bool) -> str:
    base = VERDICT_HEADLINES[vt]
    if vt == "sell_premium" and pre_earnings:
        return "Sell premium into earnings"
    if vt == "buy_premium" and pre_earnings:
        return "Buy premium into earnings"
    return base


def _suggest_structure(vt: VerdictType, inp: SignalInputs) -> tuple[str | None, str | None]:
    """Prefer the BS strategy the router fetched after compose() resolved
    the verdict_type; fall back to a plain mapping when BS returned
    nothing."""
    if inp.bs_strategy_name:
        return inp.bs_strategy_name, inp.bs_strategy_detail
    fallback = {
        "sell_premium": ("Short straddle / iron condor", "ATM short straddle is the canonical sell-vol structure"),
        "buy_premium": ("Long straddle", "ATM long straddle expresses long-vol with bounded risk"),
        "directional_long": ("Long call / bull call spread", "Defined-risk upside structure"),
        "directional_short": ("Long put / bear put spread", "Defined-risk downside structure"),
        "avoid": (None, None),
        "neutral": (None, None),
    }
    return fallback[vt]


def _build_thesis(
    inp: SignalInputs,
    vt: VerdictType,
    agreeing: list[SignalReason],
    conflicting: list[SignalReason],
    mock_used: bool,
) -> str:
    """Templated 2-3 sentence prose summary."""
    if vt == "neutral":
        if not agreeing:
            return f"{inp.symbol} reads neutral on the rule set — no signals fired with enough weight to support a verdict."
        return (
            f"{inp.symbol} shows only weak context signals "
            f"({', '.join(r.label.lower() for r in agreeing[:2])}); "
            "no real edge to act on."
        )
    if vt == "avoid":
        return (
            f"{inp.symbol}: market regime is {inp.regime!r}, which dominates any "
            "structure-level edge. Better to sit out than fight regime risk."
        )

    top_two = agreeing[:2]
    bullets = " and ".join(f"{r.label.lower()} ({r.detail.split('—')[0].strip()})" for r in top_two)
    direction_clause = {
        "sell_premium": "favors selling premium",
        "buy_premium": "favors buying premium",
        "directional_long": "supports a directional long",
        "directional_short": "supports a directional short",
    }[vt]

    parts = [f"{inp.symbol} shows {bullets}; the setup {direction_clause}."]
    if conflicting:
        top_conflict = conflicting[0]
        parts.append(
            f"Caveat — {top_conflict.label.lower()}: {top_conflict.detail.split('—')[0].strip()}."
        )
    if mock_used:
        parts.append("(Includes simulated sweep flow.)")
    return " ".join(parts)
