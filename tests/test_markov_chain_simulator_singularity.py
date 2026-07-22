"""Degenerate-data handling: the Kind enum that replaced the CC/CN/NC/NN codes.

Degeneracy is a property of the *data*, not of the variable: irradiance is identically
zero at night and so degenerates there, while wind and temperature never do. Which hours
degenerate depends on latitude and season, so it is detected empirically and cannot be
declared in a VariableSpec.
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth.markov_chain_simulator_kde2d import Kind, MarkovChainSimulator2dKDE
from meteosynth.variables import IRRADIANCE


def test_constant_current_returns_the_constant():
    """Previous constant, current constant -- the old CC."""
    cur_val = 3.0
    data = pd.DataFrame({'previous': np.zeros(20), 'current': cur_val * np.ones(20)})
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.CONSTANT
    assert simulator.is_degenerate
    assert simulator.get_next_state(current_state=0, rng=42) == cur_val


@pytest.mark.parametrize("current_state", [0.0, 1.0, 0.5, -1.0])
def test_constant_current_ignores_whatever_it_is_conditioned_on(current_state):
    """Previous varies, current constant -- the old NC.

    NC and CC collapsed into one Kind because both already dispatched to the same
    routine: return the constant. The distinction never affected behaviour.
    """
    curr_value = 3.0
    rng = np.random.default_rng(0)
    data = pd.DataFrame(
        {'previous': rng.random(size=20), 'current': curr_value * np.ones(20)}
    )
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.CONSTANT
    assert simulator.get_next_state(current_state=current_state, rng=42) == curr_value


def test_constant_previous_samples_the_marginal():
    """Previous constant, current varies -- the old CN, now Kind.KDE_1D."""
    rng = np.random.default_rng(0)
    data = pd.DataFrame(
        {'previous': np.zeros(200), 'current': rng.normal(10, 2, 200)}
    )
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.KDE_1D
    assert simulator.is_degenerate

    draws = [simulator.get_next_state(0.0, rng=rng) for _ in range(50)]
    assert len(set(draws)) > 1                      # it really does sample
    assert min(draws) >= data['current'].min()      # and stays inside the observed range
    assert max(draws) <= data['current'].max()


def test_both_varying_builds_a_2d_kde():
    """The ordinary case -- the old NN."""
    rng = np.random.default_rng(0)
    previous = rng.normal(0, 1, 500)
    data = pd.DataFrame(
        {'previous': previous, 'current': previous + rng.normal(0, 0.5, 500)}
    )
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.KDE_2D
    assert not simulator.is_degenerate
    assert simulator.joint_kde is not None


def test_degenerate_paths_consume_no_randomness():
    """A constant hour must not perturb a shared RNG stream.

    The day walkers share one generator across all 24 hours. If the degenerate hours
    drew from it, adding or removing a night hour would change every later draw.
    """
    data = pd.DataFrame({'previous': np.zeros(20), 'current': 3.0 * np.ones(20)})
    simulator = MarkovChainSimulator2dKDE(data)

    rng = np.random.default_rng(5)
    reference = np.random.default_rng(5)

    simulator.get_next_state(0.0, rng=rng)
    simulator.get_next_state(0.0, rng=rng)

    assert rng.random() == reference.random()


def test_support_truncation_keeps_the_1d_domain_non_negative():
    """The KDE_1D path is where generated irradiance used to go negative.

    Its domain was padded by +/-10%, so an hour observed over [0, 81] was evaluated down
    to -8.10 and ~30% of its samples came out below zero. With the padding gone and the
    domain clamped to the spec's support, negatives are impossible rather than rare.
    """
    rng = np.random.default_rng(0)
    dawn = np.clip(rng.normal(20, 25, 400), 0, None)   # piles against the zero bound
    data = pd.DataFrame({'previous': np.zeros(len(dawn)), 'current': dawn})

    unconstrained = MarkovChainSimulator2dKDE(data)
    constrained = MarkovChainSimulator2dKDE(data, spec=IRRADIANCE)

    assert unconstrained._cdf_table.x.min() == pytest.approx(0.0)
    assert constrained._cdf_table.x.min() == pytest.approx(0.0)

    draws = [constrained.get_next_state(0.0, rng=rng) for _ in range(500)]
    assert min(draws) >= 0.0
