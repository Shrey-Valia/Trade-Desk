"""Phase 7 LSTM vol-forecast feature pipeline.

Convention (per spec):
- Prediction date T: morning of T, only data with index < T is known.
- Features: rows T-30 .. T-1 inclusive (30 trading sessions, all < T).
- Target: realized vol of returns r_T .. r_{T+6} (7 forward returns),
  computed using closes T-1 .. T+6 (denominator close_{T-1} is shared
  with features as the latest input but used differently for target).

The off-by-one trap is silent and catastrophic. `_assert_no_leak` raises
if any feature row touches data on or after T. Tests cover this directly,
including a fixture where close_T is set to 10000 to confirm it never
leaks into the feature window.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

LOOKBACK = 30                  # trading days of history per training window
FORWARD = 7                    # trading days of forward RV target
ROLL_WINDOW = 252              # ~1 year for normalization stats
TARGET_WINSOR_QUANTILE = 0.99  # cap target at p99 per ticker (training only)
TRADING_DAYS_PER_YEAR = 252

# Feature names in fixed order. day_of_week is one-hot Mon..Fri (5 binaries).
DOW_NAMES = ["dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri"]
NUMERIC_FEATURES = [
    "log_return",
    "intraday_range",
    "volume_zscore",
    "vix_level",
    "vix_5d_change",
    "rv_20d",
]
ALL_FEATURES = NUMERIC_FEATURES + DOW_NAMES


@dataclass
class TickerData:
    """Per-ticker prepared dataframe with raw features + target column.

    Columns: close, log_return, intraday_range, volume_zscore, vix_level,
    vix_5d_change, rv_20d, dow_mon..dow_fri, target.
    Target may be NaN at the head (insufficient history) and tail (no future
    closes available); training iterator filters those out.
    """

    symbol: str
    df: pd.DataFrame


def _assert_no_leak(window_df: pd.DataFrame, prediction_date: date) -> None:
    """Raise if any row in the feature window has index >= prediction_date.

    Convention: features for prediction date T must use only data strictly
    before T. close_T leaking into a single feature row breaks PIT.
    """
    if len(window_df) == 0:
        return
    last = window_df.index.max()
    if hasattr(last, "date"):
        last = last.date()
    if last >= prediction_date:
        raise AssertionError(
            f"vol-feature leak: window last index {last} >= prediction date {prediction_date}"
        )


def build_ticker_dataframe(
    symbol: str,
    closes: pd.Series,
    highs: pd.Series,
    lows: pd.Series,
    volumes: pd.Series,
    vix_by_date: dict[date, float] | None,
) -> TickerData:
    """Assemble the full per-ticker dataframe of features + target.

    `closes/highs/lows/volumes` are tz-naive DatetimeIndex Series sorted
    ascending. `vix_by_date` is None when VIX is unavailable — we then
    leave vix_level / vix_5d_change as NaN and the training pipeline
    drops them globally.
    """
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": volumes})
    df = df.dropna(subset=["close"])
    if df.empty:
        return TickerData(symbol=symbol, df=df)

    df["log_return"] = np.log(df["close"] / df["close"].shift(1))
    df["intraday_range"] = (df["high"] - df["low"]) / df["close"]
    # Volume Z-score: (today_vol - rolling_20_mean_excluding_today) / rolling_20_std.
    # Use shift(1) so today's volume is never in its own normalization window.
    rolling_vol = df["volume"].shift(1).rolling(20, min_periods=20)
    df["volume_zscore"] = (df["volume"] - rolling_vol.mean()) / rolling_vol.std()

    if vix_by_date:
        df["vix_level"] = pd.Series(
            {pd.Timestamp(d): v for d, v in vix_by_date.items()},
        ).reindex(df.index).ffill()
        df["vix_5d_change"] = df["vix_level"] - df["vix_level"].shift(5)
    else:
        df["vix_level"] = np.nan
        df["vix_5d_change"] = np.nan

    # 20-day annualized realized vol of log returns, computed strictly from
    # past returns (the rolling window is on log_return which is itself a
    # backward-looking quantity).
    df["rv_20d"] = (
        df["log_return"]
        .rolling(20, min_periods=20)
        .std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    )
    # Carry-along trailing RV horizons used by the HAR-RV + trailing baselines.
    # NOT LSTM features — stored on the dataframe so the training-window
    # iterator can attach raw values per row for the baselines to consume.
    df["trailing_rv_1d"] = df["log_return"].abs() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    df["trailing_rv_5d"] = (
        df["log_return"].rolling(5, min_periods=5).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    )
    df["trailing_rv_7d"] = (
        df["log_return"].rolling(7, min_periods=7).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    )
    df["trailing_rv_22d"] = (
        df["log_return"].rolling(22, min_periods=22).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    )

    # One-hot day-of-week (Mon=0 .. Fri=4 in DatetimeIndex weekday()).
    weekdays = df.index.weekday
    for i, name in enumerate(DOW_NAMES):
        df[name] = (weekdays == i).astype(np.float32)

    # Target: 7-day forward annualized RV.
    # For row T, target uses returns r_T .. r_{T+6}, i.e. log_return at
    # rows T, T+1, ..., T+6. df["log_return"].shift(-i) gives row T's value
    # at column shift -i. We compute std over a forward 7-row window.
    fwd_returns = pd.concat(
        [df["log_return"].shift(-i) for i in range(FORWARD)],
        axis=1,
    )
    # skipna=False so rows missing ANY forward return get NaN target. Without
    # this, the last FORWARD-1 rows produce a target computed from fewer
    # returns — silent off-by-one that would later poison the model.
    df["target"] = fwd_returns.std(axis=1, skipna=False) * np.sqrt(TRADING_DAYS_PER_YEAR) * 100

    return TickerData(symbol=symbol, df=df)


def rolling_normalizer(
    series: pd.Series, window: int = ROLL_WINDOW, quarantine: int = 0
) -> tuple[pd.Series, pd.Series]:
    """Rolling mean+std of `series`, point-in-time correct.

    quarantine=0 (features): stats at row T use rows < T (because the
    pandas rolling starts at the row's own position, we shift first).
    quarantine=k (target): stats at row T exclude the last k realized
    targets — those used data through T-1 only IF k == FORWARD-1=6,
    OR equivalently we skip the last FORWARD=7 to be safe. The target
    realized at date t requires close_{t+FORWARD-1}; for it to be known
    by T-1 we need t+FORWARD-1 <= T-1, i.e. t <= T-FORWARD.
    """
    base = series.shift(1 + quarantine)
    mu = base.rolling(window, min_periods=window // 4).mean()
    sigma = base.rolling(window, min_periods=window // 4).std()
    return mu, sigma


def winsorize_per_ticker(targets: pd.Series, q: float = TARGET_WINSOR_QUANTILE) -> pd.Series:
    """Cap targets at p99 (training only). Symmetric: only an upper cap
    applies because RV is non-negative."""
    cap = targets.quantile(q)
    return targets.clip(upper=cap)


@dataclass
class TrainingWindow:
    """One training example: a single (lookback, target) pair.

    `trailing_*` are raw (un-normalized) values at row T-1 carried along
    for the HAR-RV + trailing-RV baselines. Adding them here keeps the
    baseline implementations dead-simple — no recomputation from features.
    """

    symbol: str
    prediction_date: date
    features: np.ndarray
    target: float
    target_raw: float
    trailing_rv_1d: float
    trailing_rv_5d: float
    trailing_rv_7d: float
    trailing_rv_22d: float
    # Per-row target normalization stats — needed to denormalize predictions
    # back to vol-percent at validation/inference. Captured at PIT.
    target_mu: float
    target_sigma: float


def iter_training_windows(
    td: TickerData,
    use_vix: bool,
) -> Iterator[TrainingWindow]:
    """Yield one TrainingWindow per valid prediction date for this ticker.

    Valid = has 30 prior days of complete features AND a non-NaN target.
    Features are PIT-normalized using the ticker's own trailing 252-day
    distribution. Target is winsorized at p99 per ticker before normalization.
    """
    if td.df.empty:
        return

    feature_cols = list(NUMERIC_FEATURES if use_vix else [c for c in NUMERIC_FEATURES if "vix" not in c])
    feature_cols = feature_cols + DOW_NAMES

    # Per-feature rolling normalization stats (PIT, no quarantine — features
    # at row T-1 are already known at prediction time T).
    mus: dict[str, pd.Series] = {}
    sigmas: dict[str, pd.Series] = {}
    for col in feature_cols:
        mu, sigma = rolling_normalizer(td.df[col], window=ROLL_WINDOW, quarantine=0)
        mus[col] = mu
        sigmas[col] = sigma

    # Target normalization with FORWARD-day quarantine — see rolling_normalizer
    # docstring. Winsorize first so the cap doesn't get diluted by rare spikes.
    winsor_target = winsorize_per_ticker(td.df["target"])
    t_mu, t_sigma = rolling_normalizer(winsor_target, window=ROLL_WINDOW, quarantine=FORWARD)

    df = td.df
    n_rows = len(df)
    for i in range(LOOKBACK, n_rows - FORWARD):
        prediction_date = df.index[i].date()
        target_raw = df["target"].iloc[i]
        if pd.isna(target_raw):
            continue
        # Lookback rows i-LOOKBACK .. i-1 (LOOKBACK rows total, all strictly < i)
        window_df = df.iloc[i - LOOKBACK : i]
        _assert_no_leak(window_df, prediction_date)

        # Pull normalization stats at prediction date (= row at index i, but
        # mus/sigmas were built with shift(1) so they reflect through i-1).
        mu_at = {c: mus[c].iloc[i] for c in feature_cols}
        sig_at = {c: sigmas[c].iloc[i] for c in feature_cols}
        target_mu = t_mu.iloc[i]
        target_sigma = t_sigma.iloc[i]
        if any(pd.isna(v) for v in (*mu_at.values(), *sig_at.values(), target_mu, target_sigma)):
            continue
        if any(s == 0 for s in (*sig_at.values(), target_sigma)):
            continue

        feats = np.empty((LOOKBACK, len(feature_cols)), dtype=np.float32)
        for col_i, col in enumerate(feature_cols):
            raw = window_df[col].to_numpy(dtype=np.float32)
            if np.isnan(raw).any():
                feats = None
                break
            feats[:, col_i] = (raw - mu_at[col]) / sig_at[col]
        if feats is None:
            continue

        target_norm = (winsor_target.iloc[i] - target_mu) / target_sigma
        # Trailing-RV values at row i-1 (the latest known data point at
        # prediction date T = row i). Skip the row entirely if any trailing
        # RV is NaN — the baselines need all four.
        prev_row = df.iloc[i - 1]
        trailing_vals = (
            prev_row["trailing_rv_1d"],
            prev_row["trailing_rv_5d"],
            prev_row["trailing_rv_7d"],
            prev_row["trailing_rv_22d"],
        )
        if any(pd.isna(v) for v in trailing_vals):
            continue
        yield TrainingWindow(
            symbol=td.symbol,
            prediction_date=prediction_date,
            features=feats,
            target=float(target_norm),
            target_raw=float(target_raw),
            trailing_rv_1d=float(trailing_vals[0]),
            trailing_rv_5d=float(trailing_vals[1]),
            trailing_rv_7d=float(trailing_vals[2]),
            trailing_rv_22d=float(trailing_vals[3]),
            target_mu=float(target_mu),
            target_sigma=float(target_sigma),
        )


def get_target_norm_stats(td: TickerData) -> tuple[float, float]:
    """Return (mu, sigma) for target denormalization at INFERENCE time.

    Uses the most recent point-in-time stats available — same primitive
    as training, evaluated at the latest valid row.
    """
    winsor_target = winsorize_per_ticker(td.df["target"])
    t_mu, t_sigma = rolling_normalizer(winsor_target, window=ROLL_WINDOW, quarantine=FORWARD)
    valid = (~t_mu.isna()) & (~t_sigma.isna()) & (t_sigma > 0)
    if not valid.any():
        return float("nan"), float("nan")
    last_idx = valid[valid].index[-1]
    return float(t_mu.loc[last_idx]), float(t_sigma.loc[last_idx])


def get_feature_norm_stats(
    td: TickerData, use_vix: bool
) -> dict[str, tuple[float, float]] | None:
    """Inference-time per-feature (mu, sigma)."""
    feature_cols = (
        list(NUMERIC_FEATURES if use_vix else [c for c in NUMERIC_FEATURES if "vix" not in c])
        + DOW_NAMES
    )
    out: dict[str, tuple[float, float]] = {}
    for col in feature_cols:
        mu_s, sigma_s = rolling_normalizer(td.df[col])
        valid = (~mu_s.isna()) & (~sigma_s.isna()) & (sigma_s > 0)
        if not valid.any():
            return None
        last_idx = valid[valid].index[-1]
        out[col] = (float(mu_s.loc[last_idx]), float(sigma_s.loc[last_idx]))
    return out
