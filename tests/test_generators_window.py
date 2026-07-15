"""Tests for DayWindowGenerator: lazy per-day fitting with an LRU cache."""

import numpy as np
import pandas as pd
import pytest

from meteosynth.day_window import day_slot
from meteosynth.generators import DayWindowGenerator, EnvSeriesGenerator
from meteosynth.met_data_processor import MetDataProcessor


@pytest.fixture
def mdp_fixture():
    """Two years of synthetic hourly data (2011-2012) with a plausible daily cycle.

    A smooth diurnal shape plus noise keeps the KDEs non-degenerate, so the generators
    exercise the ordinary (non-singular) code path.
    """
    rng = np.random.default_rng(42)
    index = pd.date_range("2011-01-01", "2012-12-31 23:00", freq="h")
    df = pd.DataFrame(
        {
            "year": index.year,
            "month": index.month,
            "day": index.day,
            "hour": index.hour,
        }
    )
    daylight = np.clip(np.sin((index.hour - 6) / 12 * np.pi), 0, None)
    seasonal = 0.5 + 0.5 * np.sin((index.dayofyear - 80) / 365 * 2 * np.pi)
    df["poa_direct"] = 800 * daylight * seasonal + rng.normal(0, 5, len(index))
    df["poa_sky_diffuse"] = 100 * daylight + rng.normal(0, 2, len(index))
    df["poa_ground_diffuse"] = 20 * daylight + rng.normal(0, 1, len(index))
    df["solar_elevation"] = 60 * daylight - 10
    df["temp_air"] = 15 + 10 * seasonal + rng.normal(0, 1, len(index))
    df["wind_speed"] = np.abs(rng.normal(4, 1.5, len(index)))
    df["Int"] = 0
    return MetDataProcessor(df)


def test_for_day_returns_a_fitted_generator(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=10)
    generator = dwg.for_day(6, 15)
    assert isinstance(generator, EnvSeriesGenerator)
    assert len(generator.simulators) == 24


# Requirement: it must be possible to generate data for Feb 29 on request.
def test_feb29_generates_a_full_day(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=15)
    profile = dwg.gen_day_sequence(2, 29, start_value=0.0, seed=42)
    assert profile.shape == (24,)
    assert np.isfinite(profile).all()


def test_windows_wrapping_new_year_generate(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=15)
    for month, day in [(1, 2), (12, 30), (1, 1), (12, 31)]:
        profile = dwg.gen_day_sequence(month, day, seed=1)
        assert profile.shape == (24,)
        assert np.isfinite(profile).all()


def test_generator_is_cached_not_refitted(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=10)
    assert dwg.for_day(6, 15) is dwg.for_day(6, 15)
    assert dwg.for_slot(day_slot(6, 15)) is dwg.for_day(6, 15)


def test_cache_evicts_least_recently_used(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=5, cache_size=2)
    first = dwg.for_day(3, 1)
    dwg.for_day(6, 1)
    dwg.for_day(9, 1)  # evicts (3, 1)

    assert len(dwg._cache) == 2
    assert dwg.for_day(3, 1) is not first  # refitted, not the cached object


def test_cache_keeps_recently_used_entries(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=5, cache_size=2)
    first = dwg.for_day(3, 1)
    dwg.for_day(6, 1)
    dwg.for_day(3, 1)  # refresh (3, 1), making (6, 1) the LRU
    dwg.for_day(9, 1)  # evicts (6, 1), not (3, 1)

    assert dwg.for_day(3, 1) is first


def test_clear_cache_releases_generators(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=5)
    first = dwg.for_day(6, 15)
    dwg.clear_cache()
    assert len(dwg._cache) == 0
    assert dwg.for_day(6, 15) is not first


def test_seeded_generation_is_reproducible(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=10)
    a = dwg.gen_day_sequence(6, 15, seed=7)
    b = dwg.gen_day_sequence(6, 15, seed=7)
    np.testing.assert_array_equal(a, b)


# The point of the feature: adjacent days must share training data, so the hard
# discontinuity at month boundaries is gone.
def test_adjacent_days_across_a_month_boundary_share_training_data(mdp_fixture):
    may31 = mdp_fixture.get_day_window_subset(5, 31, n_days=15)
    jun01 = mdp_fixture.get_day_window_subset(6, 1, n_days=15)

    slots_may, slots_jun = set(may31["day_slot"]), set(jun01["day_slot"])
    overlap = slots_may & slots_jun
    assert len(overlap) == 30  # 31-day windows one day apart

    # The month split, by contrast, shares nothing.
    month_may = set(mdp_fixture.get_month_subset(5)["date_id"])
    month_jun = set(mdp_fixture.get_month_subset(6)["date_id"])
    assert not (month_may & month_jun)


def test_unknown_attribute_raises(mdp_fixture):
    with pytest.raises(ValueError, match="attr_str must be one of"):
        DayWindowGenerator(mdp_fixture, attr_str="not_an_attribute")


def test_cache_size_must_be_positive(mdp_fixture):
    with pytest.raises(ValueError, match="cache_size"):
        DayWindowGenerator(mdp_fixture, attr_str="poa_direct", cache_size=0)


# Memory is bounded by the cache, not by the calendar: walking the year must never hold
# more than cache_size generators.
def test_walking_the_year_holds_a_bounded_number_of_generators(mdp_fixture):
    dwg = DayWindowGenerator(mdp_fixture, attr_str="poa_direct", n_days=5, cache_size=4)
    for slot in range(1, 40):
        dwg.for_slot(slot)
        assert len(dwg._cache) <= 4
