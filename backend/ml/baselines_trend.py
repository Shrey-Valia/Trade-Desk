"""Trend-direction baselines that MLP must beat.

50/50: predict P(up) = 0.5 for every observation. No-signal floor.

Conditional-on-momentum-sign: P(up | mom_20d > 0) vs P(up | mom_20d ≤ 0)
fit from training data. Equivalent to what sklearn's CalibratedClassifierCV
would produce if wrapping a "mom_20d > 0" decision rule, but cleaner.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


def fifty_fifty_predict(n: int) -> np.ndarray:
    """Predict P(up) = 0.5 for every observation. No-signal floor."""
    return np.full(n, 0.5)


@dataclass
class ConditionalMomentumBaseline:
    """Conditional probability of up-day given sign of trailing 20d momentum.

    Trained once per walk-forward fold. Predict picks the bin and returns
    that bin's training-period up-rate as the calibrated probability.
    """

    p_up_given_pos: float    # P(up | mom_20d > 0)
    p_up_given_neg: float    # P(up | mom_20d ≤ 0)

    @classmethod
    def fit(cls, mom_20d_train: Sequence[float], y_train: Sequence[int]) -> "ConditionalMomentumBaseline":
        mom = np.asarray(mom_20d_train, dtype=np.float64)
        y = np.asarray(y_train, dtype=np.int64)
        pos_mask = mom > 0
        # Per-bin rates with safe fallback to overall base rate if one bin is empty.
        overall = float(np.mean(y)) if len(y) else 0.5
        p_pos = float(np.mean(y[pos_mask])) if pos_mask.any() else overall
        p_neg = float(np.mean(y[~pos_mask])) if (~pos_mask).any() else overall
        return cls(p_up_given_pos=p_pos, p_up_given_neg=p_neg)

    def predict(self, mom_20d_val: Sequence[float]) -> np.ndarray:
        mom = np.asarray(mom_20d_val, dtype=np.float64)
        return np.where(mom > 0, self.p_up_given_pos, self.p_up_given_neg)
