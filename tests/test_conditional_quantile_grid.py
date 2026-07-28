"""The cached conditional-quantile grid (PERF-1).

Sampling used to evaluate a 1000-point KDE grid on *every* call. A simulator asked for
many samples now caches the conditional inverse CDF over a grid of ``previous`` values
and answers with two interpolations instead.

The cache is a **performance** change that must not be a **behaviour** change, and the
two halves of that claim are tested separately: that the grid appears only when it pays
for itself, and that what it samples is distributionally the same as what the direct path
samples. See ``docs/design/precomputed-conditional-quantiles.md``.
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

import meteosynth.markov_chain_simulator_kde2d as kde2d
from meteosynth.markov_chain_simulator_kde2d import (
    _CDF_GRID_NODES,
    _GRID_ACTIVATION_CALLS,
    Kind,
    MarkovChainSimulator2dKDE,
)


@pytest.fixture
def correlated_pairs():
    """A well-behaved 2D transition: both axes vary, the conditional shifts with prev."""
    rng = np.random.default_rng(42)
    previous = rng.normal(0, 1, 500)
    current = previous + rng.normal(0, 0.5, 500)
    return pd.DataFrame({"previous": previous, "current": current})


@pytest.fixture
def simulator(correlated_pairs):
    return MarkovChainSimulator2dKDE(correlated_pairs, bandwidth=0.1)


# ======================================================================================
# When the grid appears
# ======================================================================================


def test_no_grid_before_the_threshold(simulator):
    """A simulator asked for a few samples must not pay to build a grid.

    This is what keeps ``generate_series`` unaffected: a year-long walk takes exactly one
    sample from each of a day's 24 hourly simulators and then moves on.
    """
    rng = np.random.default_rng(0)
    for _ in range(_GRID_ACTIVATION_CALLS):
        simulator.get_next_state(0.0, rng=rng)

    assert not simulator.has_quantile_grid


def test_grid_appears_once_past_the_threshold(simulator):
    rng = np.random.default_rng(0)
    for _ in range(_GRID_ACTIVATION_CALLS + 1):
        simulator.get_next_state(0.0, rng=rng)

    assert simulator.has_quantile_grid
    assert simulator._grid_quantiles.shape[0] == _CDF_GRID_NODES
    assert simulator._grid_prev_nodes.shape == (_CDF_GRID_NODES,)


def test_below_the_threshold_the_draws_are_bit_for_bit_the_old_ones(simulator, monkeypatch):
    """Under the threshold, nothing about the sampler has changed.

    Compared against a simulator whose threshold is unreachable, so it can only ever take
    the direct path.
    """
    monkeypatch.setattr(kde2d, "_GRID_ACTIVATION_CALLS", 10**9)
    direct = MarkovChainSimulator2dKDE(simulator.data, bandwidth=0.1)

    a = [simulator.get_next_state(0.3, rng=np.random.default_rng(7)) for _ in range(20)]
    b = [direct.get_next_state(0.3, rng=np.random.default_rng(7)) for _ in range(20)]

    assert not simulator.has_quantile_grid
    assert a == b


def test_degenerate_kinds_never_build_a_grid():
    """The 1D and constant paths are already a lookup; a grid would be pure overhead."""
    constant = MarkovChainSimulator2dKDE(
        pd.DataFrame({"previous": np.linspace(0, 1, 200), "current": np.zeros(200)})
    )
    one_d = MarkovChainSimulator2dKDE(
        pd.DataFrame({
            "previous": np.zeros(200),
            "current": np.random.default_rng(0).normal(5, 1, 200),
        })
    )
    assert constant.kind is Kind.CONSTANT
    assert one_d.kind is Kind.KDE_1D

    rng = np.random.default_rng(0)
    for simulator in (constant, one_d):
        for _ in range(_GRID_ACTIVATION_CALLS * 2):
            simulator.get_next_state(0.5, rng=rng)
        assert not simulator.has_quantile_grid
        simulator.precompute_grid()          # explicit request is a no-op too
        assert not simulator.has_quantile_grid


def test_precompute_grid_is_explicit_and_idempotent(simulator):
    simulator.precompute_grid()
    assert simulator.has_quantile_grid

    first = simulator._grid_quantiles
    simulator.precompute_grid()
    assert simulator._grid_quantiles is first


# ======================================================================================
# That it samples the same distribution
# ======================================================================================


def _draws(simulator, prev, n, seed):
    rng = np.random.default_rng(seed)
    return np.array([simulator.get_next_state(prev, rng=rng) for _ in range(n)])


def test_grid_and_direct_agree_distributionally(correlated_pairs, monkeypatch):
    """The claim the whole change rests on.

    Tolerances are set from measurement, not taste: on real irradiance the cached sampler
    tracks the direct one to ~0.03 % of the mean per transition. 2 % here is loose enough
    that Monte-Carlo noise cannot trip it and tight enough that a genuine regression -- a
    mis-indexed node, an un-normalised row -- could not hide.

    Both samplers are driven from the same seed, so the comparison is near-deterministic
    rather than a two-sample estimate: 1200 draws is ample, and the direct path is slow
    enough that asking for more would cost minutes of suite time for no extra power.
    """
    grid_sim = MarkovChainSimulator2dKDE(correlated_pairs, bandwidth=0.1)
    grid_sim.precompute_grid()

    monkeypatch.setattr(kde2d, "_GRID_ACTIVATION_CALLS", 10**9)
    direct_sim = MarkovChainSimulator2dKDE(correlated_pairs, bandwidth=0.1)

    for prev in (-1.0, 0.8):
        grid = _draws(grid_sim, prev, 1200, seed=11)
        direct = _draws(direct_sim, prev, 1200, seed=11)

        assert grid.mean() == pytest.approx(direct.mean(), abs=0.02 * direct.std())
        assert grid.std() == pytest.approx(direct.std(), rel=0.02)
        assert stats.ks_2samp(grid, direct).pvalue > 0.01


def test_grid_respects_the_domain_and_the_clamp(simulator):
    """Sampling stays inside the evaluation domain, and conditioning outside the fitted
    range is clamped rather than extrapolated -- both as the direct path does."""
    simulator.precompute_grid()
    domain = simulator._get_x_domain(1000)

    rng = np.random.default_rng(3)
    far_outside = [simulator.get_next_state(1e6, rng=rng) for _ in range(200)]
    at_the_edge = [
        simulator.get_next_state(float(simulator.previous_values.max()), rng=rng)
        for _ in range(200)
    ]

    for draws in (far_outside, at_the_edge):
        assert min(draws) >= domain[0] - 1e-9
        assert max(draws) <= domain[-1] + 1e-9

    # Clamping means "far outside" and "at the edge" are the same question.
    assert np.mean(far_outside) == pytest.approx(np.mean(at_the_edge), rel=0.1)


def test_the_grid_does_not_perturb_the_random_stream(correlated_pairs, monkeypatch):
    """Both paths consume exactly one number per call.

    If they did not, crossing the threshold mid-ensemble would desynchronise every other
    attribute drawing from the same generator, and the effect would look like a modelling
    difference rather than a plumbing one.
    """
    monkeypatch.setattr(kde2d, "_GRID_ACTIVATION_CALLS", 5)
    simulator = MarkovChainSimulator2dKDE(correlated_pairs, bandwidth=0.1)

    rng = np.random.default_rng(99)
    for _ in range(20):
        simulator.get_next_state(0.0, rng=rng)
    after_sampling = rng.random()

    reference = np.random.default_rng(99)
    reference.random(20)
    assert after_sampling == reference.random()


def test_sampling_stays_reproducible_across_the_threshold(correlated_pairs, monkeypatch):
    monkeypatch.setattr(kde2d, "_GRID_ACTIVATION_CALLS", 5)
    runs = []
    for _ in range(2):
        simulator = MarkovChainSimulator2dKDE(correlated_pairs, bandwidth=0.1)
        runs.append(_draws(simulator, 0.2, 40, seed=5))

    np.testing.assert_array_equal(runs[0], runs[1])
