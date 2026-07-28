"""Tests for rolling-window behaviour around Feb 29 and the end of February.

The shipped record (2011-2012) has only one leap day, so it cannot exercise the cases
that actually matter. These tests use synthetic records instead:

* a **multi-year** record (2011-2020) containing three leap years, and
* a **leap-free** record (2021-2023) containing none,

to pin the two questions that are otherwise impossible to see working:

1. Does a Feb 28 window pool Feb 29 from the leap years *and* Mar 1 from every year?
2. With no leap year in the record at all, can Feb 29 still be generated from its
   late-February and early-March neighbours?

See ``CHANGELOG.md`` (0.2.0) and ``docs/design/completed/rolling-day-window.md`` (Caveat B).
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth import DayWindowGenerator, MetDataProcessor, day_slot

LEAP_YEARS = (2012, 2016, 2020)


def _synthetic_record(start_year: int, end_year: int, seed: int = 0) -> MetDataProcessor:
    """An hourly record with a realistic diurnal cycle and exactly-zero nights.

    The night mask is explicit rather than a ``clip`` because ``np.sin(np.pi)`` is
    ``1.22e-16``, not ``0``, and a clipped sine therefore leaves ~1e-14 residue at dusk.
    That used to defeat ``_cat_singularity``'s exact ``std == 0`` check and route a
    physically-constant hour into the 2D KDE path.

    Degeneracy detection is scale-aware since 2026-07-28, so residue no longer breaks
    anything -- ``tests/test_markov_chain_simulator_singularity.py`` covers that
    deliberately. The mask stays explicit here so this fixture keeps testing *leap-year
    windowing* against clean data, rather than quietly doubling as a residue test.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31 23:00", freq="h")
    hour = index.hour.to_numpy()
    day_of_year = index.dayofyear.to_numpy()

    daylight = np.zeros(len(index))
    lit = (hour >= 7) & (hour <= 17)
    daylight[lit] = np.sin((hour[lit] - 6) / 12 * np.pi)
    seasonal = 0.5 + 0.5 * np.sin((day_of_year - 80) / 365 * 2 * np.pi)

    df = pd.DataFrame(
        {"year": index.year, "month": index.month, "day": index.day, "hour": hour}
    )
    df["poa_direct"] = 800 * daylight * seasonal + rng.normal(0, 5, len(index)) * daylight
    df["poa_sky_diffuse"] = 100 * daylight + rng.normal(0, 2, len(index)) * daylight
    df["poa_ground_diffuse"] = 0.0
    df["solar_elevation"] = 60 * daylight
    df["temp_air"] = 15 + 10 * seasonal + rng.normal(0, 1, len(index))
    df["wind_speed"] = np.abs(rng.normal(4, 1.5, len(index)))
    df["Int"] = 0
    return MetDataProcessor(df)


@pytest.fixture
def leap_record():
    """Ten years (2011-2020), of which 2012, 2016 and 2020 are leap years."""
    return _synthetic_record(2011, 2020)


@pytest.fixture
def leapfree_record():
    """Three years (2021-2023), none of them leap years."""
    return _synthetic_record(2021, 2023)


def _years_by_calendar_day(subset):
    """{(month, day): {years contributing that calendar day}}."""
    out = {}
    for year, month, day in zip(subset["year"], subset["month"], subset["day"]):
        out.setdefault((month, day), set()).add(year)
    return out


def _calendar_days(subset):
    return {(m, d) for m, d in zip(subset["month"], subset["day"])}


# --- the fixtures themselves -------------------------------------------------------

def test_fixture_nights_are_exactly_zero(leap_record):
    """Keeps this file testing leap-year windowing and nothing else.

    Residue-laden nights are handled correctly now, but they exercise a *different*
    code path (the degeneracy tolerance, covered in
    ``test_markov_chain_simulator_singularity.py``). Keeping the fixture exactly zero
    means a failure below is a leap-year finding rather than an ambiguous one.
    """
    night = leap_record.met_data[leap_record.met_data["hour"] == 22]["poa_direct"].values
    assert np.unique(night).tolist() == [0.0]
    assert night.std() == 0.0


def test_fixture_leap_years_are_as_expected(leap_record, leapfree_record):
    leap_days = leap_record.met_data[
        (leap_record.met_data["month"] == 2) & (leap_record.met_data["day"] == 29)
    ]
    assert set(leap_days["year"].unique()) == set(LEAP_YEARS)

    free_days = leapfree_record.met_data[
        (leapfree_record.met_data["month"] == 2) & (leapfree_record.met_data["day"] == 29)
    ]
    assert free_days.empty


# --- Q1: a Feb 28 window on a record that HAS leap years ---------------------------

def test_feb28_window_pools_leap_day_from_leap_years_only(leap_record):
    """The headline question: Feb 29 from the leap years, Mar 1 from all of them."""
    by_day = _years_by_calendar_day(leap_record.get_day_window_subset(2, 28, n_days=2))

    assert set(by_day) == {(2, 26), (2, 27), (2, 28), (2, 29), (3, 1)}

    # Ordinary days: every year contributes.
    for day in [(2, 26), (2, 27), (2, 28), (3, 1)]:
        assert len(by_day[day]) == 10, f"{day} should come from all 10 years"

    # The leap day: only the years that actually have one.
    assert by_day[(2, 29)] == set(LEAP_YEARS)


def test_feb28_window_reaches_into_march(leap_record):
    subset = leap_record.get_day_window_subset(2, 28, n_days=2)
    march = _years_by_calendar_day(subset)[(3, 1)]
    assert len(march) == 10


def test_feb29_target_pools_real_leap_days_when_present(leap_record):
    subset = leap_record.get_day_window_subset(2, 29, n_days=15)
    by_day = _years_by_calendar_day(subset)
    assert by_day[(2, 29)] == set(LEAP_YEARS)


# --- Q2: Feb 29 on a record with NO leap years -------------------------------------

def test_feb29_window_on_leapfree_record_is_not_empty(leapfree_record):
    subset = leapfree_record.get_day_window_subset(2, 29, n_days=15)
    assert not subset.empty


def test_feb29_window_on_leapfree_record_spans_feb14_to_mar15(leapfree_record):
    """Slot 60 contributes nothing, so the target is built from its neighbours."""
    subset = leapfree_record.get_day_window_subset(2, 29, n_days=15)
    days = _calendar_days(subset)

    expected = {(2, d) for d in range(14, 29)} | {(3, d) for d in range(1, 16)}
    assert days == expected
    assert (2, 29) not in days  # the record has no leap day to contribute


def test_feb29_generator_builds_from_a_leapfree_record(leapfree_record):
    """Requirement: generate Feb 29 even with no observed Feb 29 anywhere.

    No start value has to be supplied any more -- hour 0 comes from that day's own
    pi(x0), which is fitted from the neighbouring days the window pooled.
    """
    for attr in ("poa_direct", "wind_speed", "temp_air"):
        generator = DayWindowGenerator(leapfree_record, attr_str=attr, n_days=15)
        profile = generator.gen_day(2, 29, seed=1)

        assert profile.shape == (24,)
        assert np.isfinite(profile).all(), f"{attr} produced a non-finite Feb 29"


# --- the slot-60 boundary ----------------------------------------------------------

@pytest.mark.parametrize(
    "month, day, n_days, expect_leap_day",
    [
        (2, 28, 1, True),    # slots 58..60 -> reaches the leap day
        (2, 28, 0, False),   # slot 59 only
        (2, 27, 1, False),   # slots 57..59 -> stops one short
        (2, 27, 2, True),    # slots 56..60
        (3, 1, 1, True),     # slots 60..62 -> reaches it from the far side
        (3, 2, 1, False),    # slots 61..63
        (3, 2, 2, True),     # slots 60..64
        (6, 15, 15, False),  # nowhere near
    ],
)
def test_leap_day_is_included_exactly_when_the_window_reaches_slot_60(
    leap_record, month, day, n_days, expect_leap_day
):
    subset = leap_record.get_day_window_subset(month, day, n_days=n_days)
    has_leap_day = (2, 29) in _calendar_days(subset)
    assert has_leap_day is expect_leap_day


def test_leap_day_occupies_slot_60(leap_record):
    subset = leap_record.get_day_window_subset(2, 29, n_days=0)
    assert set(subset["day_slot"]) == {60}
    assert set(subset["year"]) == set(LEAP_YEARS)
    assert len(subset) == 3 * 24  # three leap years, 24 hours each


# --- the non-leap deficit ----------------------------------------------------------

def test_non_leap_years_contribute_one_day_fewer(leap_record):
    """Any window spanning slot 60 pools fewer days, by exactly the non-leap count.

    Faithful to the calendar rather than a defect: those days do not exist.
    """
    spanning = leap_record.get_day_window_subset(2, 29, n_days=15)["date_id"].nunique()
    unaffected = leap_record.get_day_window_subset(6, 15, n_days=15)["date_id"].nunique()

    n_non_leap = 10 - len(LEAP_YEARS)
    assert unaffected == 31 * 10          # 31 slots x 10 years, all present
    assert spanning == 30 * 10 + 3        # 30 ordinary slots x 10 yrs, + 3 real leap days
    assert unaffected - spanning == n_non_leap


def test_deficit_equals_every_year_when_no_leap_years_exist(leapfree_record):
    spanning = leapfree_record.get_day_window_subset(2, 29, n_days=15)["date_id"].nunique()
    unaffected = leapfree_record.get_day_window_subset(6, 15, n_days=15)["date_id"].nunique()

    assert unaffected == 31 * 3
    assert spanning == 30 * 3             # slot 60 contributes nothing at all
    assert unaffected - spanning == 3     # all three years are non-leap


@pytest.mark.parametrize("month, day", [(2, 27), (2, 28), (2, 29), (3, 1), (3, 2)])
def test_targets_around_the_leap_slot_pool_31_slots(leap_record, month, day):
    """Slot coverage is symmetric; only the day *count* differs."""
    subset = leap_record.get_day_window_subset(month, day, n_days=15)
    assert subset["day_slot"].nunique() == 31
    assert 60 in set(subset["day_slot"])


@pytest.mark.parametrize("month, day", [(2, 27), (2, 28), (2, 29), (3, 1), (3, 2)])
def test_leapfree_targets_pool_only_30_slots(leapfree_record, month, day):
    """With no leap year anywhere, slot 60 is never populated, so 30 slots carry data.

    The window still *selects* 31 slots -- one of them simply has nothing in it.
    """
    subset = leapfree_record.get_day_window_subset(month, day, n_days=15)
    assert subset["day_slot"].nunique() == 30
    assert 60 not in set(subset["day_slot"])
    assert day_slot(2, 29) == 60


# --- Feb 29 is mostly interpolation, even when leap days exist ---------------------

def test_feb29_model_is_built_mostly_from_neighbouring_days(leap_record):
    """Worth pinning: a 'synthetic Feb 29' is not built from observed Feb 29s.

    Only 3 of 10 years contribute a real leap day, so 3 of the 303 pooled days -- 1% --
    are actual Feb 29 observations. The rest is late February and early March.
    """
    subset = leap_record.get_day_window_subset(2, 29, n_days=15)
    total_days = subset["date_id"].nunique()
    real_leap_days = subset[(subset["month"] == 2) & (subset["day"] == 29)][
        "date_id"
    ].nunique()

    assert real_leap_days == 3
    assert total_days == 303
    assert real_leap_days / total_days < 0.02
