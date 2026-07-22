"""Support truncation: generated irradiance must never be negative.

The regression that pays for itself. Before this change, 1.29% of generated
``poa_direct`` and 1.99% of ``poa_sky_diffuse`` values were negative (minimum
-7.63 W/m2), all of it traceable to one hour -- the dawn hour, where ``previous`` is
constant zero and the 1D KDE path runs. That path padded its evaluation domain by
+/-10%, so an hour observed over [0.00, 81.00] was evaluated down to -8.10 and 30.8% of
its samples came out below zero.

Since ``np.interp`` cannot return a value outside the domain it is given, clamping the
domain to the spec's support makes out-of-support values *unsamplable by construction*
rather than merely unlikely.
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth.generators import DayWindowGenerator
from meteosynth.markov_chain_simulator_kde2d import Kind, MarkovChainSimulator2dKDE
from meteosynth.variables import IRRADIANCE, TEMP_AIR

IRRADIANCE_ATTRS = ["poa_direct", "poa_sky_diffuse"]


@pytest.mark.parametrize("attr", IRRADIANCE_ATTRS)
def test_generated_irradiance_is_never_negative(synthetic_mdp, attr):
    """Over a large ensemble, at every hour. This is the headline guarantee."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str=attr, n_days=15)
    rng = np.random.default_rng(0)
    ensemble = np.vstack(
        [generator.generate_series((5, 15), 1, rng=rng) for _ in range(200)]
    )

    assert ensemble.min() >= 0.0
    assert (ensemble < 0).sum() == 0


@pytest.mark.parametrize("attr", IRRADIANCE_ATTRS)
def test_a_whole_generated_year_is_never_negative(synthetic_mdp, attr):
    """The chained path too, not just independent days."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str=attr, n_days=15)
    year = generator.generate_series((1, 1), 365, seed=3)

    assert year.min() >= 0.0
    assert np.isfinite(year).all()


def test_the_1d_cdf_domain_starts_at_the_observed_minimum():
    """Pin the dawn hour directly: the domain minimum is 0.00, not -8.10.

    Reconstructs the shape of the real dawn hour -- constant zero previous, current
    piled against the zero bound over roughly [0, 81].
    """
    rng = np.random.default_rng(0)
    dawn = np.clip(rng.gamma(1.2, 18.0, 500), 0, 81.0)
    dawn[0] = 0.0
    pairs = pd.DataFrame({"previous": np.zeros(len(dawn)), "current": dawn})

    simulator = MarkovChainSimulator2dKDE(pairs, bandwidth=0.1, spec=IRRADIANCE)

    assert simulator.kind is Kind.KDE_1D
    assert simulator._cdf_table.x.min() == pytest.approx(0.0, abs=1e-12)
    assert simulator._cdf_table.x.min() >= 0.0     # never -8.10 again


def test_the_1d_path_no_longer_pads_its_domain():
    """The padding is gone outright, not merely clamped away by the support.

    A variable whose support does not reach the data's edges would otherwise still be
    padded, so this checks the domain equals the observed range exactly.
    """
    rng = np.random.default_rng(0)
    values = rng.normal(20.0, 3.0, 400)
    pairs = pd.DataFrame({"previous": np.zeros(len(values)), "current": values})

    simulator = MarkovChainSimulator2dKDE(pairs, bandwidth=0.1, spec=TEMP_AIR)

    assert simulator._cdf_table.x.min() == pytest.approx(values.min(), abs=1e-9)
    assert simulator._cdf_table.x.max() == pytest.approx(values.max(), abs=1e-9)


def test_the_2d_path_is_clamped_too():
    """Truncation applies in both sampling paths, not only the 1D one."""
    rng = np.random.default_rng(0)
    previous = np.clip(rng.normal(30, 20, 400), 0, None)
    current = np.clip(previous + rng.normal(0, 10, 400), 0, None)
    pairs = pd.DataFrame({"previous": previous, "current": current})

    simulator = MarkovChainSimulator2dKDE(pairs, bandwidth=0.1, spec=IRRADIANCE)
    assert simulator.kind is Kind.KDE_2D

    # Even asked for padding, the domain cannot leave the support.
    domain = simulator._get_x_domain(resolution=100, padding=0.5)
    assert domain.min() >= 0.0

    draws = [simulator.get_next_state(5.0, rng=rng) for _ in range(300)]
    assert min(draws) >= 0.0


def test_without_a_spec_the_domain_is_the_data_alone():
    """No spec means no truncation -- the constraint is declared, never inferred."""
    rng = np.random.default_rng(0)
    values = rng.normal(0.0, 1.0, 300)
    pairs = pd.DataFrame({"previous": np.zeros(len(values)), "current": values})

    simulator = MarkovChainSimulator2dKDE(pairs, bandwidth=0.1, spec=None)

    assert simulator._cdf_table.x.min() == pytest.approx(values.min(), abs=1e-9)
    assert simulator._cdf_table.x.min() < 0.0     # negatives are real data here


@pytest.mark.parametrize("attr", IRRADIANCE_ATTRS)
def test_real_record_generates_no_negatives(real_mdp, attr):
    """The same guarantee against the shipped PVGIS record, where the bug was found."""
    generator = DayWindowGenerator(real_mdp, attr_str=attr, n_days=15)
    rng = np.random.default_rng(0)
    ensemble = np.vstack(
        [generator.generate_series((5, 15), 1, rng=rng) for _ in range(100)]
    )

    assert ensemble.min() >= 0.0
