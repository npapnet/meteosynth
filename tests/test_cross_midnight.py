"""generate_series: chaining across midnight, and what makes it different from days.

The old hour-0 model paired hour 0 with hour 23 of the *same* day -- a 23-hour backwards
jump presented as a one-hour step. A real one-hour step is almost deterministic; the
model was fitting noise. This suite pins the replacement.
"""

import numpy as np
import pytest

from meteosynth.day_window import day_slot
from meteosynth.generators import (
    FEB29_SLOT,
    DayWindowGenerator,
    _to_wide,
    build_cross_midnight_pairs,
)


# --- what the model learns ---------------------------------------------------------

@pytest.mark.parametrize(
    "attr, min_gap",
    [
        # Measured on the shipped PVGIS record (Paris 2011-2012):
        #   wind_speed  cross-midnight 0.981  vs same-day 23->00  0.360
        #   temp_air    cross-midnight 0.998  vs same-day 23->00  0.890
        # The gap is far larger for wind because temperature's strong seasonal component
        # correlates *any* two hours of the same day, which flatters the old model.
        ("wind_speed", 0.5),
        ("temp_air", 0.05),
    ],
)
def test_the_real_step_is_more_correlated_than_the_one_it_replaced(
    real_mdp, attr, min_gap
):
    """A real one-hour step across midnight is nearly deterministic.

    The old model paired hour 0 with hour 23 of the *same* day -- a 23-hour backwards
    jump -- and so fitted a much weaker relationship than the one it claimed to model.
    """
    wide = _to_wide(real_mdp.met_data, attr)

    cross = build_cross_midnight_pairs(wide, wide.index)
    real_corr = np.corrcoef(cross["previous"], cross["current"])[0, 1]

    same_day = wide[[23, 0]].dropna()
    legacy_corr = np.corrcoef(same_day[23], same_day[0])[0, 1]

    assert real_corr > 0.95, "a one-hour step should be nearly deterministic"
    assert real_corr > legacy_corr + min_gap


def test_pairs_are_built_from_the_full_record_not_the_window(real_mdp):
    """A target day's predecessor may legitimately fall outside the training window."""
    wide_full = _to_wide(real_mdp.met_data, "temp_air")
    window = real_mdp.get_day_window_subset(1, 2, n_days=4)
    target = _to_wide(window, "temp_air").index

    pairs = build_cross_midnight_pairs(wide_full, target)

    # 18 target days; all but 2011-01-01 have a predecessor in the record, since
    # 2010-12-31 precedes it.
    assert len(target) == 18
    assert len(pairs) == 17


# --- series vs independent days ----------------------------------------------------

def test_a_series_is_continuous_at_midnight_and_an_ensemble_is_not(real_mdp):
    """The whole difference between the two: midnight is a link or a reset.

    Correlation rather than jump size is the discriminating statistic -- two draws from
    the same seasonal window can happen to be close without being *related*.
    """
    generator = DayWindowGenerator(real_mdp, attr_str="temp_air", n_days=15)

    series = generator.generate_series((6, 15), 60, seed=1)
    chained = np.corrcoef(series[:-1, -1], series[1:, 0])[0, 1]

    rng = np.random.default_rng(1)
    independent = np.vstack(
        [generator.generate_series((6, 15), 1, rng=rng) for _ in range(200)]
    )
    unchained = np.corrcoef(independent[:-1, -1], independent[1:, 0])[0, 1]

    assert chained > 0.8, "a chained midnight must carry the previous day's value"
    # One-sided deliberately: the claim is that chaining creates *forward* dependence.
    # A negative sample correlation is not weak evidence of chaining, it is none, and
    # at n=200 the sampling noise on r is already ~0.07.
    assert unchained < 0.3, "independent days must not carry a value across midnight"
    assert chained > unchained + 0.5


def test_repeated_one_day_calls_are_independent(synthetic_mdp):
    """pi(x0) is redrawn per *call*; the cross-midnight model never crosses calls.

    This is the rule that makes an ensemble the degenerate case of a series.
    """
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    rng = np.random.default_rng(0)
    days = np.vstack(
        [generator.generate_series((6, 15), 1, rng=rng) for _ in range(150)]
    )

    # Consecutive rows are independent draws, so last-hour to next-first-hour carries
    # no correlation.
    correlation = np.corrcoef(days[:-1, -1], days[1:, 0])[0, 1]
    assert abs(correlation) < 0.25


def test_series_shape_and_finiteness(synthetic_mdp):
    generator = DayWindowGenerator(synthetic_mdp, attr_str="wind_speed", n_days=15)
    series = generator.generate_series((3, 1), 40, seed=2)

    assert series.shape == (40, 24)
    assert np.isfinite(series).all()


def test_series_is_reproducible(synthetic_mdp):
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    np.testing.assert_array_equal(
        generator.generate_series((6, 15), 10, seed=5),
        generator.generate_series((6, 15), 10, seed=5),
    )


def test_series_requires_a_start_date(synthetic_mdp):
    """pi(x0) is a dated object, so n_days alone is not a well-formed request."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    with pytest.raises(TypeError):
        generator.generate_series(n_days=10)


def test_series_rejects_a_non_positive_length(synthetic_mdp):
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    with pytest.raises(ValueError, match="n_days must be at least 1"):
        generator.generate_series((6, 15), 0)


# --- the calendar walk -------------------------------------------------------------

def test_a_365_day_walk_skips_feb29(synthetic_mdp):
    """A synthetic non-leap year steps 28 Feb 23:00 -> 1 Mar 00:00.

    1 March's cross-midnight model is fitted from real 1 March dates whose actual
    predecessor was 29 Feb in leap years and 28 Feb otherwise. Correct, and it looks
    enough like a bug to be worth pinning.
    """
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    visited = []

    original = generator.for_slot

    def spy(slot):
        visited.append(slot)
        return original(slot)

    generator.for_slot = spy
    generator.generate_series((1, 1), 365, seed=1)

    assert len(visited) == 365
    assert FEB29_SLOT not in visited
    assert day_slot(2, 28) in visited
    assert day_slot(3, 1) in visited


def test_a_leap_walk_includes_feb29(synthetic_mdp):
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    visited = []
    original = generator.for_slot
    generator.for_slot = lambda slot: (visited.append(slot), original(slot))[1]

    generator.generate_series((1, 1), 366, seed=1, include_feb29=True)

    assert FEB29_SLOT in visited


def test_starting_on_feb29_without_include_feb29_is_an_error(synthetic_mdp):
    """Otherwise the walk would silently skip its own start day."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    with pytest.raises(ValueError, match="include_feb29"):
        generator.generate_series((2, 29), 10)


def test_a_series_wraps_across_new_year(synthetic_mdp):
    """Dec 31 -> Jan 1 is an ordinary step for the walk."""
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15)
    series = generator.generate_series((12, 28), 8, seed=1)

    assert series.shape == (8, 24)
    assert np.isfinite(series).all()


def test_each_day_uses_its_own_models(synthetic_mdp):
    """The chain is time-inhomogeneous at daily resolution.

    Hours of 15 March come from 15 March's window fit, not from the start day's.
    """
    generator = DayWindowGenerator(synthetic_mdp, attr_str="temp_air", n_days=15,
                                   cache_size=8)
    generator.generate_series((3, 14), 3, seed=1)

    assert day_slot(3, 14) in generator._cache
    assert day_slot(3, 15) in generator._cache
    assert day_slot(3, 16) in generator._cache
    assert generator.for_day(3, 14) is not generator.for_day(3, 15)
