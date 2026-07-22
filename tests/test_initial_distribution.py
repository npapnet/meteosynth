"""pi(x0): the initial distribution that replaced ``start_value``.

A Markov chain is an initial distribution plus transitions. This package used to fake
the first by feeding a caller-supplied ``start_value`` into hour 0's model as though it
were an hour-23 value. The default of 0.0 was *outside the observed domain* for both
non-degenerate variables, and far enough out it did not merely bias the result -- the
KDE returned all-zero density and the next hour died with
``ValueError: array must not contain infs or NaNs``.
"""

import numpy as np
import pytest

from meteosynth.generators import DayWindowGenerator, EnvSeriesGenerator
from meteosynth.markov_chain_simulator_kde2d import Kind


def test_irradiance_initial_distribution_is_degenerate(synthetic_mdp):
    """Every observed 00:00 irradiance is zero, so pi(x0) is a spike at zero.

    "Irradiance starts at zero" therefore falls out of the data rather than being
    hard-coded into a default argument.
    """
    generator = DayWindowGenerator(synthetic_mdp, attr_str="poa_direct", n_days=15)
    initial = generator.for_day(6, 15).initial

    assert initial.kind is Kind.CONSTANT
    rng = np.random.default_rng(0)
    assert all(initial.get_next_state(0.0, rng=rng) == 0.0 for _ in range(20))


@pytest.mark.parametrize("attr", ["temp_air", "wind_speed"])
def test_non_degenerate_starts_come_from_the_observed_hour0_domain(synthetic_mdp, attr):
    """The two variables 0.0 was wrong for now start inside their own data."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str=attr, n_days=15)
    subset = synthetic_mdp.get_day_window_subset(6, 15, n_days=15)
    observed = subset[subset["hour"] == 0][attr]

    rng = np.random.default_rng(0)
    draws = [generator.for_day(6, 15).gen_day(rng=rng)[0] for _ in range(100)]

    assert min(draws) >= observed.min()
    assert max(draws) <= observed.max()
    assert 0.0 not in draws          # the old default, outside the domain for both


def test_an_ensemble_gets_many_different_starts(synthetic_mdp):
    """Today's headline defect: generate_ensemble gave 500 *identical* starts.

    Independent days are now n one-day calls, each redrawing pi(x0).
    """
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    rng = np.random.default_rng(0)
    starts = [generator.generate_series((6, 15), 1, rng=rng)[0, 0] for _ in range(200)]

    assert len(set(starts)) == 200


def test_irradiance_ensemble_starts_are_all_zero(synthetic_mdp):
    """The counterpart: where the data *is* degenerate, every start is the constant."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str="poa_direct", n_days=15)
    rng = np.random.default_rng(0)
    starts = [generator.generate_series((6, 15), 1, rng=rng)[0, 0] for _ in range(50)]

    assert set(starts) == {0.0}


# THE CONCEPTUAL POINT. pi(x0) is not "the distribution of midnight values" -- it is
# "the distribution of midnight values near a particular time of year". A pi(x0) that
# does not know when it is being asked about is fitted to January and July at once and
# is right for neither. This is why generate_series requires a start date.
def test_initial_distribution_is_dated(synthetic_mdp):
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)

    def sample(month, day, n=300):
        rng = np.random.default_rng(0)
        gen = generator.for_day(month, day)
        return np.array([gen.initial.get_next_state(0.0, rng=rng) for _ in range(n)])

    january, july = sample(1, 15), sample(7, 15)
    separation = abs(july.mean() - january.mean())

    # The seasonal difference dwarfs the within-season spread: pooling them would be a
    # distribution with no mass where either season actually lives.
    assert separation > 2 * max(january.std(), july.std())


def test_seeded_days_are_reproducible(synthetic_mdp):
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    np.testing.assert_array_equal(
        generator.gen_day(6, 15, seed=7), generator.gen_day(6, 15, seed=7)
    )


def test_start_value_is_gone_from_the_api(synthetic_mdp):
    """The breaking change, asserted rather than assumed."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)

    with pytest.raises(TypeError):
        generator.gen_day(6, 15, start_value=0.0)
    assert not hasattr(generator, "gen_day_sequence")
    assert not hasattr(generator.for_day(6, 15), "generate_ensemble")


def test_hour_zero_has_no_within_day_simulator(synthetic_mdp):
    """23 within-day transitions, not 24: hour 0's slot belongs to pi(x0)."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    day = generator.for_day(6, 15)

    assert set(day.simulators) == set(range(1, 24))
    assert day.initial is not None


def test_generator_without_full_record_cannot_continue_a_chain(synthetic_mdp):
    """gen_day_from needs the cross-midnight model, which needs the whole record."""
    subset = synthetic_mdp.get_day_window_subset(6, 15, n_days=15)
    day = EnvSeriesGenerator(subset, attr_str="temp_air")

    assert day.cross_midnight is None
    with pytest.raises(ValueError, match="no cross-midnight model"):
        day.gen_day_from(12.0)
