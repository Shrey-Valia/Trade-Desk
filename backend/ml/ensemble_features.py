"""Phase 7.8 ensemble feature builder.

Joins per-fold OOS predictions from LSTM, MLP, CatBoost (written by the
respective base trainers as parquet files) and computes historical regime
deterministically. Builds the training set the ensemble consumes.

Inputs (9 features):
  1. lstm_pred_rv             — raw LSTM predicted 7d realized vol %
  2. catboost_value            — predicted abs earnings move % (imputed)
  3. earnings_active           — 1 if (date, symbol) is within 30 days of an
                                 upcoming earnings event in the CatBoost OOS
                                 set; 0 otherwise. Missing-indicator pattern.
  4. mlp_prob_up               — MLP P(close[T+5] > close[T])
  5-9. regime_one_hot          — {crisis, vol_spike, defensive, risk_on, chop}

Target: signed 5-day forward return = (close[T+5] - close[T]) / close[T].
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from calculations.regime import (
    PRIORITY_ORDER,
    MarketSnapshot,
    classify,
)
from config import PROJECT_ROOT, settings
from ml.sector_map import SECTOR_ETFS
from services.alpaca_client import get_daily_bars_history
from services.fred_client import vix_history

log = logging.getLogger(__name__)

MODEL_DIR = PROJECT_ROOT / "data" / "models"
LSTM_OOS = MODEL_DIR / "lstm_vol_oos_predictions.parquet"
MLP_OOS = MODEL_DIR / "mlp_trend_oos_predictions.parquet"
CATBOOST_OOS = MODEL_DIR / "earnings_catboost_oos_predictions.parquet"

# Days before an earnings event during which the CatBoost prediction is
# considered "active". Matches the inference-time window.
EARNINGS_ACTIVE_DAYS = 30

# Forward-return target horizon (matches MLP target).
FORWARD = 5

# Ordered regime feature names. Used at both training + inference for the
# uniform-baseline finite-difference attribution.
REGIME_FEATURE_NAMES = [f"regime_{r}" for r in PRIORITY_ORDER]

# Full ordered feature list. ABLATED variant simply drops "mlp_prob_up".
FEATURE_NAMES_FULL = (
    ["lstm_pred_rv", "catboost_value", "earnings_active", "mlp_prob_up"]
    + REGIME_FEATURE_NAMES
)
FEATURE_NAMES_ABLATED = (
    ["lstm_pred_rv", "catboost_value", "earnings_active"]
    + REGIME_FEATURE_NAMES
)


def load_base_oos_predictions() -> dict[str, pd.DataFrame]:
    """Load all 3 base-model OOS prediction parquet files. Empty df when
    a file is missing — caller handles the CatBoost-sparse case."""
    out: dict[str, pd.DataFrame] = {}
    for name, path in [("lstm", LSTM_OOS), ("mlp", MLP_OOS), ("catboost", CATBOOST_OOS)]:
        if path.exists():
            df = pd.read_parquet(path)
            out[name] = df
            log.info("loaded %d rows from %s", len(df), path.name)
        else:
            out[name] = pd.DataFrame()
            log.warning("%s OOS predictions not found at %s", name, path)
    return out


def compute_regime_per_date(dates: Iterable[date]) -> dict[date, str]:
    """Deterministic regime label per historical date.

    Caches one MarketSnapshot per date — computed from cached SPY/VIX/sector
    historical bars. Same classifier used by /api/regime.
    """
    dates_sorted = sorted(set(dates))
    if not dates_sorted:
        return {}

    spy_closes = _closes_series("SPY")
    vix = vix_history(dates_sorted[0] - timedelta(days=60), dates_sorted[-1] + timedelta(days=2))
    vix_series = pd.Series(
        {pd.Timestamp(d): v for d, v in vix.items()}
    ).sort_index() if vix else pd.Series(dtype=float)
    sector_series = {
        etf: _closes_series(etf) for etf in SECTOR_ETFS if etf not in ("SPY", "QQQ")
    }

    out: dict[date, str] = {}
    for d in dates_sorted:
        snap = _build_snapshot_for_date(d, spy_closes, vix_series, sector_series)
        if snap is None:
            out[d] = "mean_reverting_chop"
        else:
            out[d] = classify(snap).regime
    return out


def _closes_series(symbol: str) -> pd.Series:
    bars = get_daily_bars_history(symbol, years_back=5)
    if not bars:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    return pd.Series(
        {pd.Timestamp(b.timestamp.date()): float(b.close) for b in bars}
    ).sort_index()


def _build_snapshot_for_date(
    target_date: date,
    spy_closes: pd.Series,
    vix_series: pd.Series,
    sector_series: dict[str, pd.Series],
) -> MarketSnapshot | None:
    cutoff = pd.Timestamp(target_date)
    spy_prior = spy_closes[spy_closes.index <= cutoff]
    if len(spy_prior) < 25:
        return None
    spy_20 = _pct_change(spy_prior, 20)
    spy_5 = _pct_change(spy_prior, 5)

    vix_prior = vix_series[vix_series.index <= cutoff] if not vix_series.empty else pd.Series(dtype=float)
    vix_level = float(vix_prior.iloc[-1]) if not vix_prior.empty else 17.0
    vix_5d = _pct_change(vix_prior, 5) if len(vix_prior) >= 6 else 0.0

    sector_5d = {}
    for etf, s in sector_series.items():
        s_prior = s[s.index <= cutoff]
        if len(s_prior) >= 6:
            sector_5d[etf] = _pct_change(s_prior, 5)

    return MarketSnapshot(
        vix_level=vix_level,
        vix_5d_change_pct=vix_5d,
        spy_20d_return_pct=spy_20,
        spy_5d_return_pct=spy_5,
        sector_5d_returns=sector_5d,
        hyg_lqd_ratio=None,
    )


def _pct_change(series: pd.Series, n: int) -> float:
    if len(series) < n + 1:
        return 0.0
    latest = series.iloc[-1]
    prior = series.iloc[-(n + 1)]
    if prior == 0:
        return 0.0
    return float((latest - prior) / prior * 100)


def compute_targets_for(
    pairs: Iterable[tuple[date, str]],
) -> dict[tuple[date, str], float]:
    """Compute signed 5-day forward return for each (date, symbol).

    Returns dict keyed by (date, symbol) → return%. Missing when the symbol
    has no bars at T or no close at T+5 (last 5 days of series).
    """
    # Cache per-symbol close series to avoid re-fetching across pairs.
    per_symbol: dict[str, pd.Series] = {}
    out: dict[tuple[date, str], float] = {}
    for d, sym in pairs:
        if sym not in per_symbol:
            per_symbol[sym] = _closes_series(sym)
        s = per_symbol[sym]
        d_ts = pd.Timestamp(d)
        if d_ts not in s.index:
            continue
        pos = s.index.get_loc(d_ts)
        if pos + FORWARD >= len(s):
            continue
        c0 = float(s.iloc[pos])
        cT = float(s.iloc[pos + FORWARD])
        if c0 == 0:
            continue
        out[(d, sym)] = (cT - c0) / c0 * 100  # percent
    return out


def build_ensemble_dataset() -> tuple[pd.DataFrame, list[str]]:
    """Returns (df, feature_columns) for ensemble training.

    Columns: date, symbol, all features in FEATURE_NAMES_FULL, target.
    """
    base = load_base_oos_predictions()
    lstm_df = base["lstm"]
    mlp_df = base["mlp"]
    catboost_df = base["catboost"]

    if lstm_df.empty or mlp_df.empty:
        log.error("missing LSTM or MLP OOS predictions — re-run base trainings first")
        return pd.DataFrame(), FEATURE_NAMES_FULL

    # Inner-join LSTM and MLP on (date, symbol) — both are daily granularity.
    joined = pd.merge(
        lstm_df, mlp_df, on=["date", "symbol"], how="inner"
    )
    log.info("LSTM ∩ MLP join: %d rows", len(joined))

    # CatBoost join: for each (date, symbol), look up earnings_date within
    # +30 days. earnings_active = 1 if found, 0 otherwise.
    catboost_df = catboost_df.copy()
    if not catboost_df.empty:
        catboost_df["earnings_date"] = pd.to_datetime(catboost_df["earnings_date"])
    cb_lookup: dict[str, list[tuple[pd.Timestamp, float]]] = defaultdict(list)
    for _, row in catboost_df.iterrows():
        cb_lookup[row["symbol"]].append(
            (row["earnings_date"], float(row["predicted_abs_move_pct"]))
        )
    for sym in cb_lookup:
        cb_lookup[sym].sort()

    cb_value = []
    earnings_active = []
    for _, row in joined.iterrows():
        sym = row["symbol"]
        date_ts = row["date"]
        events = cb_lookup.get(sym, [])
        match: float | None = None
        for ev_date, predicted in events:
            delta_days = (ev_date - date_ts).days
            if 0 <= delta_days <= EARNINGS_ACTIVE_DAYS:
                match = predicted
                break
        if match is not None:
            cb_value.append(match)
            earnings_active.append(1.0)
        else:
            cb_value.append(np.nan)
            earnings_active.append(0.0)
    joined["catboost_value"] = cb_value
    joined["earnings_active"] = earnings_active

    # Median-impute catboost_value (per spec — Option (b))
    median_cb = (
        float(np.nanmedian(joined["catboost_value"])) if joined["catboost_value"].notna().any() else 5.0
    )
    joined["catboost_value"] = joined["catboost_value"].fillna(median_cb)

    # Regime one-hot per date.
    unique_dates = {d.date() for d in joined["date"]}
    regime_by_date = compute_regime_per_date(unique_dates)
    for r in PRIORITY_ORDER:
        joined[f"regime_{r}"] = joined["date"].apply(
            lambda d, _r=r: 1.0 if regime_by_date.get(d.date()) == _r else 0.0
        )

    # Rename for ensemble feature schema.
    joined = joined.rename(columns={"lstm_pred_rv": "lstm_pred_rv", "mlp_proba": "mlp_prob_up"})

    # Targets: signed forward return per (date, symbol).
    pairs = [(row["date"].date(), row["symbol"]) for _, row in joined.iterrows()]
    targets = compute_targets_for(pairs)
    joined["target"] = [targets.get((row["date"].date(), row["symbol"]), np.nan)
                        for _, row in joined.iterrows()]
    n_before = len(joined)
    joined = joined.dropna(subset=["target"] + FEATURE_NAMES_FULL)
    log.info("ensemble dataset: %d rows (dropped %d for NaN target/features)",
             len(joined), n_before - len(joined))

    return joined.sort_values("date").reset_index(drop=True), FEATURE_NAMES_FULL
