"""Monte Carlo correctness."""

import numpy as np
import pytest

from calculations.monte_carlo import (
    monte_carlo_paths,
    percentile_bands,
    prob_close_above,
    prob_close_below,
    prob_touch,
)


def test_paths_shape_and_starting_price():
    paths = monte_carlo_paths(S0=100, mu=0, sigma=0.20, T=1 / 12, n_steps=21, n_paths=500, seed=1)
    assert paths.shape == (500, 22)
    assert np.allclose(paths[:, 0], 100.0)


def test_seeded_paths_are_deterministic():
    a = monte_carlo_paths(100, 0, 0.20, 1 / 12, 21, 200, seed=42)
    b = monte_carlo_paths(100, 0, 0.20, 1 / 12, 21, 200, seed=42)
    assert np.array_equal(a, b)


def test_zero_vol_paths_are_constant():
    # σ → 0 with μ = 0 means no drift, no diffusion → flat price.
    paths = monte_carlo_paths(100, 0, 0.0, 1 / 12, 21, 50, seed=0)
    assert np.allclose(paths, 100.0)


def test_terminal_mean_close_to_S0_under_zero_drift():
    paths = monte_carlo_paths(100, 0, 0.20, 1 / 12, 21, 10000, seed=7)
    # Risk-neutral with μ=0 has E[S_T] = S0 * exp(-σ²T/2 + σ²T/2) = S0; sample
    # mean should be within ~2% of S0 with 10K paths.
    assert paths[:, -1].mean() == pytest.approx(100.0, rel=0.02)


def test_percentile_bands_monotone_at_terminal():
    paths = monte_carlo_paths(100, 0, 0.30, 1 / 12, 21, 5000, seed=3)
    bands = percentile_bands(paths, [10, 25, 50, 75, 90])
    finals = [bands[p][-1] for p in (10, 25, 50, 75, 90)]
    assert finals == sorted(finals)


def test_prob_touch_above_and_below():
    # Symmetric distribution → roughly equal touch probabilities for symmetric levels.
    paths = monte_carlo_paths(100, 0, 0.30, 1 / 12, 21, 5000, seed=11)
    p_up = prob_touch(paths, 110, spot=100)
    p_dn = prob_touch(paths, 90, spot=100)
    assert 0.0 < p_up < 1.0
    assert abs(p_up - p_dn) < 0.10  # symmetric within Monte Carlo noise


def test_prob_close_above_below_complementary():
    paths = monte_carlo_paths(100, 0, 0.20, 1 / 12, 21, 2000, seed=5)
    above = prob_close_above(paths, 100)
    below = prob_close_below(paths, 100)
    # The two events partition the sample space minus exact-equality (negligible
    # for a continuous distribution), so they sum to ~1.
    assert above + below == pytest.approx(1.0, abs=1e-6)
