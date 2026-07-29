"""Degenerate-data handling: the Kind enum that replaced the CC/CN/NC/NN codes.

Degeneracy is a property of the *data*, not of the variable: irradiance is identically
zero at night and so degenerates there, while wind and temperature never do. Which hours
degenerate depends on latitude and season, so it is detected empirically and cannot be
declared in a VariableSpec.
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth.constants import INDEX_COLS
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


# --- floating-point residue ---------------------------------------------------------
#
# Degeneracy detection used to be an exact `np.std(...) == 0`, which worked only because
# PVGIS stores literal zeros at night. Any source that stores a physically-zero night as
# 1e-16 -- interpolation, resampling, unit conversion, or a provider that keeps near-zero
# noise -- landed in the 2D branch instead, and a 2D KDE was fitted across a `previous`
# spanning ~50 against a `current` spanning ~1e-14.
#
# This is the scenario that blocks ingesting a second provider, which is why these
# fixtures use the residue deliberately rather than avoiding it.

#: sin(pi) is 1.2246e-16, not 0. Clipping a sine day-shape at zero therefore leaves this
#: residue where the sun has physically set -- the exact fixture that first exposed it.
_SIN_PI_RESIDUE = np.sin(np.pi)


def test_residue_laden_night_is_still_constant():
    """1e-16 is zero for every purpose except `== 0`."""
    rng = np.random.default_rng(0)
    night = _SIN_PI_RESIDUE * 800 * rng.uniform(0.8, 1.2, 60)
    daytime = rng.uniform(200, 800, 60)

    data = pd.DataFrame({'previous': daytime, 'current': night})
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.CONSTANT
    assert np.isfinite(simulator.get_next_state(400.0, rng=42))


def test_residue_laden_previous_reduces_to_the_marginal():
    """The dawn transition: night residue conditioning a real distribution.

    Fitting a 2D KDE here means a covariance across ~1e-14 and ~800, which is what
    conditions it catastrophically.
    """
    rng = np.random.default_rng(0)
    night = _SIN_PI_RESIDUE * 800 * rng.uniform(0.8, 1.2, 60)

    data = pd.DataFrame({'previous': night, 'current': rng.uniform(100, 400, 60)})
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.KDE_1D
    assert np.isfinite(simulator.get_next_state(float(night[0]), rng=42))


def test_a_whole_residue_laden_day_generates_finite_values():
    """End to end, because one bad hour used to poison every hour after it.

    A NaN escaping one transition arrives at the next as a conditioning value and fails
    there with "array must not contain infs or NaNs", so the blast radius is the rest of
    the day rather than the single hour.
    """
    rng = np.random.default_rng(0)
    rows = []
    for year in (2011, 2012):
        for date in pd.date_range(f"{year}-01-01", f"{year}-12-31"):
            for hour in range(24):
                shape = max(np.sin((hour - 6) / 12 * np.pi), 0.0)
                rows.append((year, date.month, date.day, hour,
                             shape * 800 * rng.uniform(0.7, 1.3)))
    frame = pd.DataFrame(rows, columns=[*INDEX_COLS, "poa_direct"])

    from meteosynth import EnvSeriesGenerator, MetDataset

    ds = MetDataset(frame)
    generator = EnvSeriesGenerator(ds.get_month_subset(5), attr_str="poa_direct")
    day = generator.gen_day(seed=1)

    assert np.isfinite(day).all()
    assert not np.isnan(day).any()


def test_real_signal_just_above_the_tolerance_is_not_swallowed():
    """The tolerance must not eat a small but genuine distribution.

    1e-9 relative sits far below any real meteorological signal; this pins that a slice
    varying by ~0.1% of the data's scale is still modelled, not flattened.
    """
    rng = np.random.default_rng(0)
    data = pd.DataFrame({
        'previous': rng.uniform(700, 800, 400),
        'current': rng.normal(750, 0.8, 400),      # ~0.1% of scale
    })
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.KDE_2D
    assert not simulator.is_degenerate


def test_singular_covariance_degrades_instead_of_crashing():
    """Perfectly collinear data: both axes vary, but the covariance is singular.

    `gaussian_kde` raises LinAlgError, which _build_joint_distribution catches by setting
    joint_kde to None -- and `kind` used to stay KDE_2D with no KDE behind it. The first
    sample then died in get_conditional_density_gen with "ufunc 'isfinite' not supported
    for the input types", which names nothing that went wrong.
    """
    previous = np.linspace(1, 50, 60)
    data = pd.DataFrame({'previous': previous, 'current': 2.0 * previous})

    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.joint_kde is None
    assert simulator.kind is Kind.KDE_1D          # degraded, not left inconsistent
    assert np.isfinite(simulator.get_next_state(25.0, rng=42))


def test_exact_zero_sources_are_unaffected():
    """PVGIS stores literal zeros; the scale-aware test must not change that path.

    When every value is exactly zero the tolerance is zero too, and `<=` still holds.
    """
    data = pd.DataFrame({'previous': np.zeros(20), 'current': np.zeros(20)})
    simulator = MarkovChainSimulator2dKDE(data)

    assert simulator.kind is Kind.CONSTANT
    assert simulator.get_next_state(0.0, rng=42) == 0.0


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
