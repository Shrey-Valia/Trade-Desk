"""GET /api/models/{symbol} — model inference for the Model Signals Row.

Phase 6: only catboost_er_move is populated. Other 4 cells return None
and the frontend renders a "Phase 7" placeholder.

CatBoost prediction logic:
- Resolve next earnings within 30 days via cached Finnhub calendar
- Build features (PIT-strict) from cached price series + DB earnings history
- Predict abs % move
- Compare to TODAY's implied move from the live chain straddle
- Return value + comparison + interpretation, plus n_training_events and
  baseline_beaten so the UI can render confidence/warning indicators
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter
from sqlalchemy import select

import numpy as np

from calculations.expected_move import atm_straddle_price, expected_move
from database import SessionLocal
from ml.earnings_catboost import load_metadata, load_model
from ml.features import (
    PriorEarning,
    build_features,
    feature_matrix,
    sector_for,
)
from ml.lstm_vol import (
    load_lstm,
    load_lstm_metadata,
    load_lstm_norm_stats,
    predict_lstm,
)
from ml.ensemble import (
    attribute as ensemble_attribute,
    load_ensemble,
    load_ensemble_metadata,
    predict_ensemble,
)
from ml.ensemble_features import REGIME_FEATURE_NAMES
from ml.mlp_trend import load_mlp, load_mlp_metadata, predict_proba_up as mlp_predict_proba
from ml.sector_map import VIX_SYMBOL
from ml.trend_features import (
    FEATURE_NAMES as TREND_FEATURE_NAMES,
    build_ticker_trend_dataframe,
    sector_for as trend_sector_for,
)
from ml.vol_features import LOOKBACK, build_ticker_dataframe
from models.historical_earnings_event import HistoricalEarningsEvent
from schemas.models import (
    CatboostErMove,
    EnsembleComponents,
    EnsembleEdge,
    LstmVolForecast,
    MlpTrend,
    ModelSignalsResponse,
    RegimeSignal as RegimeSignalSchema,
    RfRegime,
    VolEdge,
)
from calculations.vol_edge import compute_vol_edge
from services.alpaca_client import get_daily_bars_history, get_quotes
from services.cache import cache
from services.finnhub_client import next_earnings_for
from services.fred_client import vix_history

router = APIRouter(prefix="/api/models", tags=["models"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_FEATURE_TTL = 3600  # 1h — features don't change intraday


@router.get("/{symbol}", response_model=ModelSignalsResponse)
def get_model_signals(symbol: str) -> ModelSignalsResponse:
    symbol = symbol.upper()
    # Phase 7.9: MLP + Ensemble cards removed from production. The helper
    # functions (_mlp_trend, _ensemble_edge) remain in this file for future
    # revival when more training data swings the ablation outcome — they're
    # just not called by the orchestrator. Schema fields stay as null for
    # API-shape compatibility.
    lstm = _lstm_vol_forecast(symbol)
    catboost = _catboost_er_move(symbol)
    regime = _rf_regime()
    vol_edge = _vol_edge(symbol, lstm, regime)
    return ModelSignalsResponse(
        catboost_er_move=catboost,
        lstm_vol_forecast=lstm,
        rf_regime=regime,
        mlp_trend=None,
        ensemble_edge=None,
        vol_edge=vol_edge,
        updated_at=datetime.now(timezone.utc),
    )


def _vol_edge(
    symbol: str,
    lstm: LstmVolForecast | None,
    regime: RfRegime | None,
) -> VolEdge | None:
    """Synthesize LSTM + Regime + earnings proximity into a single verdict."""
    predicted_rv = lstm.predicted_rv_7d if lstm is not None else None
    current_iv = lstm.current_iv30 if lstm is not None else None
    regime_name = regime.regime if regime is not None else None

    # days_to_earnings comes from the same cached Finnhub call the price
    # header uses — no new API hit.
    days_to_er: int | None = None
    next_er = next_earnings_for(symbol)
    if next_er:
        try:
            er_date = datetime.fromisoformat(next_er).date()
            days_to_er = (er_date - datetime.now(_ET).date()).days
        except ValueError:
            pass

    result = compute_vol_edge(
        predicted_rv=predicted_rv,
        current_iv30=current_iv,
        regime=regime_name,
        days_to_earnings=days_to_er,
    )
    return VolEdge(
        verdict=result.verdict,
        label=result.label,
        rationale=result.rationale,
        signals_used=result.signals_used,
    )


_ENSEMBLE_REGIME_ORDER = ("crisis", "vol_spike", "defensive", "risk_on", "mean_reverting_chop")


def _ensemble_edge(
    symbol: str,
    lstm: LstmVolForecast | None,
    catboost: CatboostErMove | None,
    mlp: MlpTrend | None,
    regime: RfRegime | None,
) -> EnsembleEdge | None:
    """Compose the 4 base-model outputs into the ensemble's feature vector,
    predict, z-score, and attribute. Cached 5min per symbol."""
    cache_key = f"ml:ensemble:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    payload = load_ensemble_metadata() or {}
    md = payload.get("metadata") or {}
    metrics = payload.get("metrics") or {}
    feature_names: list[str] = md.get("feature_names") or []
    target_mean = float(md.get("target_mean", 0.0))
    target_std = float(md.get("target_std", 1.0))

    if not feature_names:
        return None

    loaded = load_ensemble()
    if loaded is None:
        return None
    model = loaded["model"]
    scaler = loaded["scaler"]
    feature_training_stds = loaded["feature_training_stds"]

    if lstm is None or regime is None:
        return None  # need at minimum LSTM + regime to score

    # Build feature vector aligned with feature_names (handles both full and
    # ablated production sets transparently).
    earnings_active = 1.0 if catboost is not None and catboost.n_training_events > 0 and catboost.value > 0 else 0.0
    feature_values: dict[str, float] = {
        "lstm_pred_rv": float(lstm.predicted_rv_7d),
        "catboost_value": float(catboost.value) if catboost else 5.0,  # imputed median fallback
        "earnings_active": earnings_active,
        "mlp_prob_up": float(mlp.prob_up) if mlp else 0.5,
    }
    for r in _ENSEMBLE_REGIME_ORDER:
        feature_values[f"regime_{r}"] = 1.0 if regime.regime == r else 0.0
    x = np.array([feature_values[name] for name in feature_names], dtype=np.float64)

    raw_pred = float(predict_ensemble(model, scaler, x.reshape(1, -1))[0])
    z_score = (raw_pred - target_mean) / target_std if target_std > 0 else 0.0

    components_dict = ensemble_attribute(
        model, scaler, feature_names, x, feature_training_stds
    )
    interpretation = _ensemble_interpretation(z_score)

    # baseline_beaten: from training metrics — true if the WINNING ensemble
    # (full or ablated, whichever shipped to production) beat both baselines
    # during walk-forward CV.
    winner = "full" if md.get("notes", "").startswith("Full") else "ablated"
    winner_metrics = (metrics.get(winner) or {})
    baseline_beaten = bool(winner_metrics.get("baseline_beaten", False))
    mlp_in_production = (winner == "full")

    result = EnsembleEdge(
        z_score=z_score,
        raw_predicted_return=raw_pred,
        interpretation=interpretation,
        baseline_beaten=baseline_beaten,
        components=EnsembleComponents(**components_dict),
        mlp_in_production=mlp_in_production,
    )
    cache.set(cache_key, result, ttl_seconds=300)
    return result


def _ensemble_interpretation(z: float) -> str:
    if z > 2.0:
        return f"Strong setup (+{z:.1f}σ)"
    if z > 1.0:
        return f"Moderate setup (+{z:.1f}σ)"
    if z < -2.0:
        return f"Strong bearish setup ({z:.1f}σ)"
    if z < -1.0:
        return f"Moderate bearish setup ({z:.1f}σ)"
    return f"Neutral ({z:+.1f}σ)"


def _mlp_trend(symbol: str) -> MlpTrend | None:
    """Run the MLP at today's most recent valid prediction date. Cached 1h."""
    cache_key = f"ml:mlp:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    payload = load_mlp_metadata() or {}
    md = payload.get("metadata", {})
    metrics = payload.get("metrics", {}) or {}
    n_training = int(md.get("n_trainable_windows", 0))
    baseline_beaten = bool((metrics.get("aggregate") or {}).get("baseline_beaten", False))

    if n_training == 0:
        return None

    loaded = load_mlp()
    if loaded is None:
        return None
    model, scaler = loaded

    bars = get_daily_bars_history(symbol, years_back=1)
    if not bars or len(bars) < 70:  # WARMUP_DAYS=60 + buffer
        return None
    closes = pd.Series(
        {pd.Timestamp(b.timestamp.date()): float(b.close) for b in bars}
    ).sort_index()
    volumes = pd.Series(
        {pd.Timestamp(b.timestamp.date()): float(b.volume or 0) for b in bars}
    ).sort_index()

    sector_etf = trend_sector_for(symbol)
    sector_closes = None
    if sector_etf is not None:
        sec_bars = get_daily_bars_history(sector_etf, years_back=1)
        if sec_bars:
            sector_closes = pd.Series(
                {pd.Timestamp(b.timestamp.date()): float(b.close) for b in sec_bars}
            ).sort_index()

    td = build_ticker_trend_dataframe(symbol, closes, volumes, sector_closes)
    if td.df.empty:
        return None

    feature_names = md.get("feature_names", TREND_FEATURE_NAMES)
    available = td.df[feature_names].dropna()
    if available.empty:
        return None
    latest_row = available.iloc[-1]
    feats = latest_row.to_numpy(dtype=np.float32).reshape(1, -1)
    prob_up = float(mlp_predict_proba(model, scaler, feats)[0])
    interpretation = _trend_interpretation(prob_up)

    result = MlpTrend(
        prob_up=prob_up,
        interpretation=interpretation,
        baseline_beaten=baseline_beaten,
        n_training_windows=n_training,
    )
    cache.set(cache_key, result, ttl_seconds=3600)
    return result


def _trend_interpretation(p: float) -> str:
    """Threshold-bucketed label per Phase 7.7 spec."""
    if p > 0.65:
        return "Strong bullish"
    if p > 0.55:
        return "Moderate bullish bias"
    if p > 0.45:
        return "Neutral"
    if p > 0.35:
        return "Moderate bearish bias"
    return "Strong bearish"


_REGIME_LABELS = {
    "crisis": "Crisis",
    "vol_spike": "Vol Spike",
    "defensive": "Defensive",
    "risk_on": "Risk-on",
    "mean_reverting_chop": "Mean-reverting chop",
}


def _rf_regime() -> RfRegime | None:
    """Regime is symbol-agnostic — same value for every ticker. We call the
    /api/regime endpoint logic in-process to reuse the 60s cache."""
    try:
        from routers.regime import get_regime
        r = get_regime()
    except Exception:  # noqa: BLE001
        log.exception("regime lookup failed")
        return None
    return RfRegime(
        regime=r.regime,
        label=_REGIME_LABELS.get(r.regime, r.regime),
        confidence=r.confidence,
        contributing_signals=[
            RegimeSignalSchema(name=s.name, value=s.value, rule=s.rule, satisfied=s.satisfied)
            for s in r.contributing_signals
        ],
    )


def _lstm_vol_forecast(symbol: str) -> LstmVolForecast | None:
    """Run the LSTM at today's most recent valid prediction date.

    Cached 1h per symbol — same TTL we use for other ML features.
    """
    cache_key = f"ml:lstm:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    metadata = load_lstm_metadata() or {}
    md = metadata.get("metadata", {})
    metrics = metadata.get("metrics", {})
    n_training_windows = int(md.get("n_trainable_windows", 0))
    baseline_beaten = bool((metrics.get("aggregate") or {}).get("baseline_beaten", False))

    if n_training_windows == 0:
        return None  # model never trained

    model = load_lstm()
    norm_stats = load_lstm_norm_stats() or {}
    if model is None or symbol not in norm_stats:
        return None

    bars = get_daily_bars_history(symbol, years_back=2)
    if not bars or len(bars) < LOOKBACK + 30:
        return None
    closes, highs, lows, volumes = {}, {}, {}, {}
    for b in bars:
        d = pd.Timestamp(b.timestamp.date())
        closes[d] = float(b.close)
        highs[d] = float(b.high)
        lows[d] = float(b.low)
        volumes[d] = float(b.volume or 0)
    closes_s = pd.Series(closes).sort_index()
    highs_s = pd.Series(highs).sort_index()
    lows_s = pd.Series(lows).sort_index()
    volumes_s = pd.Series(volumes).sort_index()

    use_vix = bool(md.get("use_vix", False))
    vix_by_date = None
    if use_vix:
        from datetime import timedelta
        end = closes_s.index.max().date()
        vix_by_date = vix_history(end - timedelta(days=400), end)

    td = build_ticker_dataframe(symbol, closes_s, highs_s, lows_s, volumes_s, vix_by_date)
    if td.df.empty:
        return None

    feature_names = md.get("feature_names", [])
    # Find the most recent row where every feature is non-NaN; use the
    # 30-row window ENDING at that row as the lookback.
    available = td.df[feature_names].dropna()
    if len(available) < LOOKBACK:
        return None
    cutoff_ts = available.index[-1]
    last_valid_pos = td.df.index.get_loc(cutoff_ts)
    window_df = td.df.iloc[last_valid_pos - LOOKBACK + 1 : last_valid_pos + 1]
    assert len(window_df) == LOOKBACK

    stats = norm_stats[symbol]
    feature_norm: dict[str, tuple[float, float]] = {
        k: (v[0], v[1]) for k, v in stats["features"].items()
    }

    feats = np.empty((LOOKBACK, len(feature_names)), dtype=np.float32)
    for col_i, col in enumerate(feature_names):
        mu, sigma = feature_norm[col]
        if sigma <= 0:
            return None
        raw = window_df[col].to_numpy(dtype=np.float32)
        feats[:, col_i] = (raw - mu) / sigma

    pred_norm = float(predict_lstm(model, feats[np.newaxis, :, :])[0])
    pred_raw = pred_norm * float(stats["target_sigma"]) + float(stats["target_mu"])

    iv30 = _live_implied_vol(symbol)
    vrp_implied = (iv30 - pred_raw) if iv30 is not None else None
    interpretation = _vrp_interpretation(vrp_implied, pred_raw, iv30)

    result = LstmVolForecast(
        predicted_rv_7d=float(pred_raw),
        current_iv30=float(iv30) if iv30 is not None else None,
        vrp_implied=float(vrp_implied) if vrp_implied is not None else None,
        interpretation=interpretation,
        baseline_beaten=baseline_beaten,
        n_training_windows=n_training_windows,
    )
    cache.set(cache_key, result, ttl_seconds=3600)
    return result


def _live_implied_vol(symbol: str) -> float | None:
    """ATM IV (annualized %) at the near-term expiry from the live chain."""
    try:
        from routers.ticker import _chain_with_oi_proxy, _pick_near_term_expiry

        chain, _ = _chain_with_oi_proxy(symbol)
        quote = get_quotes([symbol]).get(symbol)
        if not chain or quote is None:
            return None
        expiry = _pick_near_term_expiry(chain)
        if expiry is None:
            return None
        # Mean of call+put IV at the ATM strike for this expiry, *100 to %.
        same = [c for c in chain if c.expiry == expiry]
        atm = min({c.strike for c in same}, key=lambda k: abs(k - quote.price))
        ivs = [c.iv for c in same if c.strike == atm and c.iv is not None]
        if not ivs:
            return None
        return float(sum(ivs) / len(ivs)) * 100
    except Exception:  # noqa: BLE001
        log.exception("LSTM: live IV30 lookup failed for %s", symbol)
        return None


def _vrp_interpretation(vrp: float | None, predicted: float, iv30: float | None) -> str:
    if vrp is None or iv30 is None:
        return f"Predicted RV {predicted:.1f}% (no live IV to compare)"
    if vrp > 5:
        return f"Premium rich (favor selling): IV {iv30:.1f}% vs predicted RV {predicted:.1f}%"
    if vrp < -2:
        return f"Premium cheap (favor buying): IV {iv30:.1f}% vs predicted RV {predicted:.1f}%"
    return f"Fair value: IV {iv30:.1f}% vs predicted RV {predicted:.1f}%"


def _catboost_er_move(symbol: str) -> CatboostErMove | None:
    """Predict + compare to live implied move. None when no upcoming ER ≤30d."""
    next_er_iso = next_earnings_for(symbol, days_forward=30)
    if not next_er_iso:
        return None  # No upcoming earnings — nothing to predict.

    metadata_payload = load_metadata() or {}
    metadata = metadata_payload.get("metadata", {})
    metrics = metadata_payload.get("metrics", {})
    n_training = int(metadata.get("n_trainable_events", 0))
    aggregate = metrics.get("aggregate") or {}
    baseline_beaten = bool(
        aggregate
        and aggregate.get("model_mae") is not None
        and aggregate.get("baseline_mae") is not None
        and aggregate["model_mae"] < aggregate["baseline_mae"]
    )

    # If we couldn't train at all, surface that honestly rather than
    # hallucinating a prediction.
    if n_training == 0:
        notes = metadata.get("notes", "Model not trained")
        return CatboostErMove(
            value=0.0,
            implied_compare=_live_implied_move(symbol),
            interpretation=notes,
            n_training_events=0,
            baseline_beaten=False,
        )

    try:
        event_date = datetime.fromisoformat(next_er_iso).date()
    except ValueError:
        return None

    feats = _build_inference_features(symbol, event_date)
    if feats is None:
        return CatboostErMove(
            value=0.0,
            implied_compare=_live_implied_move(symbol),
            interpretation="Insufficient earnings history",
            n_training_events=n_training,
            baseline_beaten=baseline_beaten,
        )

    model = load_model()
    if model is None:
        return CatboostErMove(
            value=0.0,
            implied_compare=_live_implied_move(symbol),
            interpretation="Model artifact missing — retrain",
            n_training_events=n_training,
            baseline_beaten=baseline_beaten,
        )

    X, _ = feature_matrix([feats])
    predicted = float(model.predict(X)[0])
    implied = _live_implied_move(symbol)
    interpretation = _interpret(predicted, implied)
    return CatboostErMove(
        value=predicted,
        implied_compare=implied,
        interpretation=interpretation,
        n_training_events=n_training,
        baseline_beaten=baseline_beaten,
    )


def _build_inference_features(symbol: str, event_date) -> dict | None:
    cache_key = f"ml:features:{symbol}:{event_date.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    bars = get_daily_bars_history(symbol, years_back=2)
    if not bars:
        return None
    sector = sector_for(symbol)
    sector_bars = get_daily_bars_history(sector, years_back=2) if sector else None
    vix_bars = get_daily_bars_history(VIX_SYMBOL, years_back=2) or []

    symbol_closes = _bars_to_series(bars)
    sector_closes = _bars_to_series(sector_bars) if sector_bars else None
    vix_closes = _bars_to_series(vix_bars)

    with SessionLocal() as session:
        prior_rows = session.execute(
            select(HistoricalEarningsEvent)
            .where(HistoricalEarningsEvent.symbol == symbol)
            .where(HistoricalEarningsEvent.earnings_date < event_date)
            .order_by(HistoricalEarningsEvent.earnings_date)
        ).scalars().all()

    priors = [
        PriorEarning(
            earnings_date=p.earnings_date,
            abs_move_pct=p.abs_move_pct,
            eps_surprise_pct=p.eps_surprise_pct,
        )
        for p in prior_rows
    ]
    feats = build_features(
        symbol=symbol,
        event_date=event_date,
        bmo_amc="",  # unknown for inference; categorical "unk"
        symbol_closes=symbol_closes,
        sector_closes=sector_closes,
        vix_closes=vix_closes,
        prior_earnings=priors,
    )
    if feats is not None:
        cache.set(cache_key, feats, ttl_seconds=_FEATURE_TTL)
    return feats


def _bars_to_series(bars) -> pd.Series:
    if not bars:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    closes = {pd.Timestamp(b.timestamp.date()): float(b.close) for b in bars}
    return pd.Series(closes).sort_index()


def _live_implied_move(symbol: str) -> float | None:
    """Today's straddle-implied move % from the live chain."""
    try:
        from routers.ticker import _chain_with_oi_proxy, _pick_near_term_expiry

        chain, _ = _chain_with_oi_proxy(symbol)
        quote = get_quotes([symbol]).get(symbol)
        if not chain or quote is None:
            return None
        expiry = _pick_near_term_expiry(chain)
        if expiry is None:
            return None
        straddle = atm_straddle_price(chain, quote.price, expiry)
        if straddle is None:
            return None
        em = expected_move(*straddle)
        return em / quote.price * 100
    except Exception:  # noqa: BLE001
        log.exception("live implied move failed for %s", symbol)
        return None


def _interpret(predicted: float, implied: float | None) -> str:
    if implied is None:
        return f"Predicted ±{predicted:.1f}% (no live straddle to compare)"
    diff = predicted - implied
    if diff > 1.5:
        return f"Predicted {predicted:.1f}% > implied {implied:.1f}% → straddle cheap"
    if diff < -1.5:
        return f"Predicted {predicted:.1f}% < implied {implied:.1f}% → premium rich"
    return f"Predicted {predicted:.1f}% ≈ implied {implied:.1f}%"
