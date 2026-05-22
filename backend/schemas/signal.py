"""API schema for the /signal route — the synthesis surface.

Mirrors the SignalVerdict dataclass produced by calculations/signal_composer.py.
Kept here (separate from the calc-layer dataclass) so the API shape can
evolve independently of the rule engine internals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VerdictType = Literal[
    "sell_premium",
    "buy_premium",
    "directional_long",
    "directional_short",
    "neutral",
    "avoid",
]

ConvictionLabel = Literal["high", "moderate", "low"]


class SignalReason(BaseModel):
    """One rule outcome — fed into either the agreeing or conflicting list."""

    label: str             # short headline (e.g. "VRP rich")
    detail: str            # one-line factual elaboration with the numbers
    weight: int            # contribution to the conviction calc


class MockSweep(BaseModel):
    """Single sweep print, surfaced to the UI for transparency about what
    flow data shaped the verdict. Always `is_mock=True` until a real
    provider replaces services/mock_flow.py."""

    strike: float
    expiry: str
    side: Literal["call", "put"]
    premium: float
    contracts: int
    aggressor: Literal["bid", "ask"]
    timestamp: str
    is_mock: bool


class SignalDebug(BaseModel):
    """Raw scalar inputs the composer evaluated against. Surfaced behind
    ?debug=true so we can see which value was None when a rule should
    have fired but didn't."""

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
    mock_flow_direction: str | None = None
    mock_flow_strength: float | None = None
    # Per-source "did this lookup work?" trace — populated by the router
    # so we can distinguish "got None because the metric isn't computable"
    # from "got None because the lookup raised".
    lookup_status: dict[str, str] = Field(default_factory=dict)


class SignalVerdictOut(BaseModel):
    symbol: str
    verdict: str                            # headline string ("Sell premium into earnings")
    verdict_type: VerdictType
    conviction: int = Field(ge=0, le=100)
    conviction_label: ConvictionLabel
    signals_agreeing: list[SignalReason] = Field(default_factory=list)
    signals_conflicting: list[SignalReason] = Field(default_factory=list)
    thesis: str
    suggested_structure: str | None = None
    suggested_structure_detail: str | None = None
    mock_flow_used: bool = False
    mock_sweeps: list[MockSweep] = Field(default_factory=list)
    debug: SignalDebug | None = None        # set when caller passes ?debug=true
