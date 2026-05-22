"""Ensemble baselines.

1. Naive zero: predict forward_return = 0 for every observation. Floor.
2. LSTM-only OLS: forward_return ~ α + β × (predicted_rv − IV).

The LSTM-only baseline uses a SINGLE-feature linear regression — proxy
for "betting on vol-mispricing direction" without involving the other
models. If the full ensemble can't beat THIS, the other 3 models
contribute nothing meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LinearRegression


def naive_zero_predict(n: int) -> np.ndarray:
    return np.zeros(n)


@dataclass
class LstmOnlyBaseline:
    """forward_return ~ α + β × lstm_pred_rv. Single-feature OLS per fold."""
    intercept: float
    slope: float

    @classmethod
    def fit(cls, lstm_pred_rv: np.ndarray, forward_return: np.ndarray) -> "LstmOnlyBaseline":
        X = np.asarray(lstm_pred_rv, dtype=np.float64).reshape(-1, 1)
        y = np.asarray(forward_return, dtype=np.float64)
        reg = LinearRegression().fit(X, y)
        return cls(intercept=float(reg.intercept_), slope=float(reg.coef_[0]))

    def predict(self, lstm_pred_rv: np.ndarray) -> np.ndarray:
        x = np.asarray(lstm_pred_rv, dtype=np.float64)
        return self.intercept + self.slope * x
