"""Vectorized Geometric Brownian Motion Monte Carlo.

Pure NumPy. 10000 paths × 10 steps runs in single-digit milliseconds —
the cost is one (n_paths, n_steps) standard-normal draw plus one cumsum
plus one elementwise exp.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def monte_carlo_paths(
    S0: float,
    mu: float,
    sigma: float,
    T: float,
    n_steps: int,
    n_paths: int,
    seed: int | None = None,
) -> np.ndarray:
    """GBM paths under risk-neutral (mu=0) or drifted dynamics.

    Returns array of shape (n_paths, n_steps + 1) with paths[:, 0] == S0.

    All Z draws happen in one call — no Python loop over paths.
    """
    rng = np.random.default_rng(seed)
    dt = T / n_steps
    Z = rng.standard_normal((n_paths, n_steps))
    # Log-return per step: drift + diffusion. Cumulative sum in log space,
    # then exponentiate once.
    log_step = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z
    cumlog = np.cumsum(log_step, axis=1)
    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = S0
    paths[:, 1:] = S0 * np.exp(cumlog)
    return paths


def percentile_bands(
    paths: np.ndarray, percentiles: Iterable[int] = (10, 25, 50, 75, 90)
) -> dict[int, np.ndarray]:
    """Per-timestep percentile envelopes.

    Returns {percentile: array of shape (n_steps + 1,)}.
    """
    return {p: np.percentile(paths, p, axis=0) for p in percentiles}


def prob_touch(paths: np.ndarray, level: float, spot: float) -> float:
    """P(any path touches `level` over the horizon).

    Direction inferred relative to spot: above-spot levels need max ≥ level;
    below-spot levels need min ≤ level. At-spot levels touch with prob 1.
    """
    if level > spot:
        return float(np.mean(paths.max(axis=1) >= level))
    if level < spot:
        return float(np.mean(paths.min(axis=1) <= level))
    return 1.0


def prob_close_above(paths: np.ndarray, level: float) -> float:
    """P(terminal price > level)."""
    return float(np.mean(paths[:, -1] > level))


def prob_close_below(paths: np.ndarray, level: float) -> float:
    return float(np.mean(paths[:, -1] < level))
