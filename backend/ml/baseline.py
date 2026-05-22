"""Naive baseline that the CatBoost model must beat."""

from __future__ import annotations

from collections import defaultdict

import numpy as np


def ticker_median_baseline(
    train_symbols: list[str],
    train_targets: list[float],
    eval_symbols: list[str],
    fallback: float = 5.0,
) -> list[float]:
    """For each eval row, predict the median |move| of that ticker's training rows.

    Falls back to `fallback` (default 5%) if the eval ticker has no training
    history at all — represents "we have no idea, guess the macro median."
    """
    by_ticker: dict[str, list[float]] = defaultdict(list)
    for s, t in zip(train_symbols, train_targets):
        by_ticker[s].append(t)
    medians = {s: float(np.median(v)) for s, v in by_ticker.items() if v}
    global_median = float(np.median(train_targets)) if train_targets else fallback
    return [medians.get(s, global_median) for s in eval_symbols]
