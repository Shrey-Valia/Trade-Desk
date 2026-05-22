from datetime import datetime

from pydantic import BaseModel, Field


class CatboostErMove(BaseModel):
    value: float                              # predicted abs % move
    implied_compare: float | None = None       # current straddle-implied move
    interpretation: str
    n_training_events: int                     # so UI can show low-confidence sublabel
    baseline_beaten: bool                      # false → UI shows warning border


class LstmVolForecast(BaseModel):
    predicted_rv_7d: float                     # annualized %, denormalized
    current_iv30: float | None                 # annualized %, from live chain ATM IV
    vrp_implied: float | None                  # iv - predicted
    interpretation: str
    baseline_beaten: bool
    n_training_windows: int


class RegimeSignal(BaseModel):
    name: str
    value: float
    rule: str
    satisfied: bool


class RfRegime(BaseModel):
    """Rule-based market regime — Phase 7.6 ships this deterministic instead
    of as an ML classifier (rules and labels would be circular). UI labels it
    'Rule-based, not ML' to be transparent about the source."""

    regime: str                          # crisis | vol_spike | defensive | risk_on | mean_reverting_chop
    label: str                           # human-readable e.g. "Risk-on"
    confidence: float                    # 0..1 — fraction of rules satisfied
    contributing_signals: list[RegimeSignal] = Field(default_factory=list)


class MlpTrend(BaseModel):
    prob_up: float                           # 0..1 probability of close[T+5] > close[T]
    interpretation: str                      # threshold-bucketed label
    baseline_beaten: bool
    n_training_windows: int


class EnsembleComponents(BaseModel):
    lstm_contribution: float | None = None
    catboost_contribution: float | None = None  # null when earnings_active=0
    mlp_contribution: float | None = None        # null in ablated production model
    regime_contribution: float | None = None


class EnsembleEdge(BaseModel):
    z_score: float
    raw_predicted_return: float                  # percent
    interpretation: str                          # threshold-bucketed label
    baseline_beaten: bool
    components: EnsembleComponents
    mlp_in_production: bool                      # ablation outcome — UI uses for transparency


class VolEdge(BaseModel):
    """Phase 7.9 rule-based synthesis replacing the failed-baseline Ensemble
    card. Combines LSTM + RF Regime + earnings proximity into one verdict."""

    verdict: str                                 # machine-readable enum value
    label: str                                   # human-readable string
    rationale: str                               # one-line "why" citing the numbers
    signals_used: list[str] = Field(default_factory=list)


class ModelSignalsResponse(BaseModel):
    lstm_vol_forecast: LstmVolForecast | None = None
    catboost_er_move: CatboostErMove | None = None
    rf_regime: RfRegime | None = None
    # mlp_trend + ensemble_edge intentionally kept as null-returning fields:
    # preserves API shape for external consumers, internal helpers in the
    # router are dormant but easy to re-enable when data depth swings the
    # ablation outcome.
    mlp_trend: MlpTrend | None = None
    ensemble_edge: EnsembleEdge | None = None
    vol_edge: VolEdge | None = None              # Phase 7.9 synthesis card
    updated_at: datetime = Field(default_factory=datetime.utcnow)
