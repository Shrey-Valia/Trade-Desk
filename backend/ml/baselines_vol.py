"""Vol-forecast baselines. Both predict 7-DAY FORWARD RV (same target as LSTM).

Critical: HAR-RV's canonical formulation predicts NEXT-DAY vol. We deliberately
target 7-day-forward to match the LSTM apples-to-apples — if HAR-RV got the
easier 1-day prediction it would beat the LSTM trivially. Be explicit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


def trailing_rv_baseline_predict(trailing_rv_7d_value: float) -> float:
    """Naive: predict next-7d RV = trailing-7d RV. Hard to beat (vol is autocorrelated)."""
    return trailing_rv_7d_value


def compute_trailing_rv(log_returns: pd.Series, window: int) -> pd.Series:
    """Annualized RV over a trailing window. Index aligned to the END of the window."""
    return log_returns.rolling(window, min_periods=window).std() * np.sqrt(252) * 100


@dataclass
class HarRvModel:
    """Per-ticker linear regression of next-7d RV on trailing 1d/5d/22d RV.

    Trained ONCE per ticker per fold. Predicts the same target as the LSTM
    (7-day-forward RV) — NOT next-day, despite the canonical HAR-RV
    formulation. Three coefficients per ticker.
    """

    coefficients: np.ndarray  # shape (3,)
    intercept: float

    @classmethod
    def fit(
        cls,
        trailing_1d: Sequence[float],
        trailing_5d: Sequence[float],
        trailing_22d: Sequence[float],
        target_7d_fwd: Sequence[float],
    ) -> "HarRvModel":
        X = np.column_stack([trailing_1d, trailing_5d, trailing_22d])
        y = np.asarray(target_7d_fwd, dtype=np.float64)
        reg = LinearRegression().fit(X, y)
        return cls(coefficients=reg.coef_.copy(), intercept=float(reg.intercept_))

    def predict(self, trailing_1d: float, trailing_5d: float, trailing_22d: float) -> float:
        x = np.array([trailing_1d, trailing_5d, trailing_22d])
        return float(self.intercept + np.dot(self.coefficients, x))


def build_har_features(log_returns: pd.Series) -> pd.DataFrame:
    """Returns a DataFrame with columns rv_1d, rv_5d, rv_22d (annualized %).

    rv_1d = today's |log return| × sqrt(252) × 100 (1-day "volatility" proxy).
    rv_5d, rv_22d = trailing 5- and 22-day annualized RVs.
    All point-in-time clean — at row T, all three values use only data through T.
    """
    abs_returns = log_returns.abs()
    rv_1d = abs_returns * np.sqrt(252) * 100
    rv_5d = compute_trailing_rv(log_returns, 5)
    rv_22d = compute_trailing_rv(log_returns, 22)
    return pd.DataFrame({"rv_1d": rv_1d, "rv_5d": rv_5d, "rv_22d": rv_22d})
