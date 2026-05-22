"""Phase 7.7 MLP trend-direction features.

Convention:
- Prediction date T: morning of T, only data with index < T is known.
- Features: derived from rows ≤ T-1 (one feature row per prediction date).
- Target: 1 if close[T+5] > close[T] else 0.
  Note close[T] is "future" relative to features but IS needed to know the
  target — same shared-but-different role as the LSTM (T's close enters
  the target but never the features).

The off-by-one trap is the same silent killer as Phase 7. `_assert_no_leak`
raises if any feature row touches data on or after T. The close_T=10000
test from `test_trend_features.py` confirms feature arrays don't change
when T's close is perturbed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ml.sector_map import sector_etf_for
from ml.technical_indicators import macd_histogram, rsi_wilder

log = logging.getLogger(__name__)

FORWARD = 5  # predict P(close[T+5] > close[T])
WARMUP_DAYS = 60  # need ~50 for distance_from_50d_ma_z + extra for MACD warmup

FEATURE_NAMES = [
    "mom_5d",
    "mom_10d",
    "mom_20d",
    "mom_50d",
    "rsi_14",
    "macd_signal",       # MACD histogram = MACD line - signal line
    "volume_z_20d",
    "sector_etf_5d_return",
    "distance_from_50d_ma_z",
]

# NOTE: dropped from README §9.4
#   - "News sentiment 5-day average" — Finnhub free returns no per-article
#     scores; no historical Stocktwits corpus on free tier.
#   - "Beta to SPY" — per-(ticker × date) historical regressions add
#     complexity for marginal lift; defer to a later iteration.


@dataclass
class TickerTrendData:
    symbol: str
    df: pd.DataFrame   # close, volume + 9 feature cols + target


@dataclass
class TrendWindow:
    symbol: str
    prediction_date: date
    features: np.ndarray   # shape (n_features,) — MLP takes flat vectors
    target: int            # 0 or 1
    mom_20d_raw: float     # carried for the conditional-momentum baseline


def _assert_no_leak(window_df: pd.Series | pd.DataFrame, prediction_date: date, name: str) -> None:
    if len(window_df) == 0:
        return
    last = window_df.index.max()
    if hasattr(last, "date"):
        last = last.date()
    if last >= prediction_date:
        raise AssertionError(
            f"trend-feature leak in {name}: latest index {last} >= prediction date {prediction_date}"
        )


def _pct_return(series: pd.Series, n: int) -> pd.Series:
    """N-day percent return: (s[T-1] - s[T-1-n]) / s[T-1-n] evaluated at row T.

    Implemented via shift so that the row at index T uses ONLY closes ≤ T-1:
       latest_close_known_at_T = series.shift(1)[T]      = series[T-1]
       n_back_close            = series.shift(1+n)[T]    = series[T-1-n]
    Returns pct = (latest - n_back) / n_back.
    """
    latest = series.shift(1)
    n_back = series.shift(1 + n)
    return (latest - n_back) / n_back


def build_ticker_trend_dataframe(
    symbol: str,
    closes: pd.Series,
    volumes: pd.Series,
    sector_closes: pd.Series | None,
) -> TickerTrendData:
    """Assemble the per-ticker dataframe of 9 features + target.

    `closes/volumes` are tz-naive DatetimeIndex sorted ascending.
    `sector_closes` aligned to the same index (any missing rows become NaN
    in `sector_etf_5d_return` — model handles NaN via dropna at training time).
    """
    df = pd.DataFrame({"close": closes, "volume": volumes})
    df = df.dropna(subset=["close"])
    if df.empty:
        return TickerTrendData(symbol=symbol, df=df)

    # Momentum (1-9): all use ≤ T-1 data via the shift in _pct_return.
    df["mom_5d"] = _pct_return(df["close"], 5) * 100
    df["mom_10d"] = _pct_return(df["close"], 10) * 100
    df["mom_20d"] = _pct_return(df["close"], 20) * 100
    df["mom_50d"] = _pct_return(df["close"], 50) * 100

    # RSI / MACD: compute on UNSHIFTED closes, then shift the output by 1.
    # This keeps the PIT property (value at row T uses closes through T-1)
    # without injecting a leading NaN into the EMA recurrence that would
    # poison every downstream value.
    rsi_array = rsi_wilder(df["close"].to_numpy(), period=14)
    macd_array = macd_histogram(df["close"].to_numpy(), fast=12, slow=26, signal_period=9)
    df["rsi_14"] = pd.Series(rsi_array, index=df.index).shift(1)
    df["macd_signal"] = pd.Series(macd_array, index=df.index).shift(1)

    # Volume z-score: (vol[T-1] - mean_20[ending T-2]) / std_20[ending T-2].
    # The shift(1) on the rolling window guarantees volume[T-1] is never in
    # its own normalizer window — same pattern as Phase 7 LSTM features.
    prior_vol = df["volume"].shift(1)
    rolling = prior_vol.shift(1).rolling(20, min_periods=20)
    df["volume_z_20d"] = (prior_vol - rolling.mean()) / rolling.std()

    # Sector 5-day return through T-1.
    if sector_closes is not None:
        sector_aligned = sector_closes.reindex(df.index).ffill()
        df["sector_etf_5d_return"] = _pct_return(sector_aligned, 5) * 100
    else:
        df["sector_etf_5d_return"] = np.nan

    # Distance from 50-day MA, z-scored by 50-day std.
    prior_close = df["close"].shift(1)
    ma50 = prior_close.rolling(50, min_periods=50).mean()
    std50 = prior_close.rolling(50, min_periods=50).std()
    df["distance_from_50d_ma_z"] = (prior_close - ma50) / std50

    # Target: close[T+5] > close[T]. shift(-FORWARD) brings close[T+5] to row T.
    df["target"] = (df["close"].shift(-FORWARD) > df["close"]).astype("Int64")
    # Last FORWARD rows have NaN target (no future closes available).
    df.loc[df["close"].shift(-FORWARD).isna(), "target"] = pd.NA

    return TickerTrendData(symbol=symbol, df=df)


def iter_trend_windows(td: TickerTrendData) -> Iterator[TrendWindow]:
    """Yield one TrendWindow per valid prediction date.

    Skips rows where any feature is NaN (insufficient warmup) or target
    is NaN (last FORWARD rows). PIT assertion fires on every yield to
    catch any future-leak bug we might introduce.
    """
    if td.df.empty:
        return

    df = td.df
    feature_cols = FEATURE_NAMES
    n_rows = len(df)
    for i in range(WARMUP_DAYS, n_rows - FORWARD):
        target = df["target"].iloc[i]
        if pd.isna(target):
            continue
        prediction_date = df.index[i].date()

        # Feature row at position i — already constructed to use only data
        # through index i-1 (via the various shifts above).
        # Defensive PIT check: the close/volume rows that *contributed* to
        # this feature row are indices < i. Assert on a 1-row "window" view.
        prior_view = df.iloc[i - 1 : i]  # exactly the most-recent informative row
        _assert_no_leak(prior_view, prediction_date, f"{td.symbol} prior_view")

        feats = df[feature_cols].iloc[i].to_numpy(dtype=np.float32)
        if np.isnan(feats).any():
            continue
        mom_20d = float(df["mom_20d"].iloc[i])
        yield TrendWindow(
            symbol=td.symbol,
            prediction_date=prediction_date,
            features=feats,
            target=int(target),
            mom_20d_raw=mom_20d,
        )


def sector_for(symbol: str) -> str | None:
    return sector_etf_for(symbol)
