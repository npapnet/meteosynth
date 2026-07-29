"""Tests for MetDataset.get_day_window_subset (rolling day windows)."""

import numpy as np
import pandas as pd
import pytest

from meteosynth.day_window import day_slot
from meteosynth.dataset import MetDataset


@pytest.fixture
def mdp_fixture():
    """Three years of synthetic hourly data (2011-2013), including the 2012 leap day.

    Values are unique per (date, hour) so that any mis-selection or mis-alignment is
    detectable rather than hidden behind repeated numbers.
    """
    index = pd.date_range("2011-01-01", "2013-12-31 23:00", freq="h")
    df = pd.DataFrame(
        {
            "year": index.year,
            "month": index.month,
            "day": index.day,
            "hour": index.hour,
        }
    )
    # A distinct, reproducible value per row.
    marker = index.dayofyear * 100.0 + index.hour + (index.year - 2011) * 1e5
    for col in ["poa_direct", "poa_sky_diffuse", "poa_ground_diffuse",
                "solar_elevation", "temp_air", "wind_speed", "Int"]:
        df[col] = marker
    return MetDataset(df)


def _dates(subset):
    return {(y, m, d) for y, m, d in zip(subset["year"], subset["month"], subset["day"])}


def test_window_pools_every_year(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(6, 15, n_days=2)
    assert set(subset["year"].unique()) == {2011, 2012, 2013}
    # 5 days x 3 years x 24 hours
    assert len(subset) == 5 * 3 * 24


def test_window_is_centred_on_the_target(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(6, 15, n_days=2)
    days = {(m, d) for _, m, d in _dates(subset)}
    assert days == {(6, 13), (6, 14), (6, 15), (6, 16), (6, 17)}


def test_window_wraps_backwards_over_new_year(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(1, 2, n_days=4)
    days = {(m, d) for _, m, d in _dates(subset)}
    assert days == {
        (12, 29), (12, 30), (12, 31),
        (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
    }


def test_window_wraps_forwards_over_new_year(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(12, 30, n_days=4)
    days = {(m, d) for _, m, d in _dates(subset)}
    assert days == {
        (12, 26), (12, 27), (12, 28), (12, 29), (12, 30), (12, 31),
        (1, 1), (1, 2), (1, 3),
    }


# Requirement: Feb 29 must not be dropped from the dataset.
def test_feb29_is_pooled_into_nearby_windows(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(2, 27, n_days=3)
    assert (2012, 2, 29) in _dates(subset)


# Requirement: it must be possible to generate data for Feb 29 on request.
def test_feb29_is_requestable_as_a_target(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(2, 29, n_days=15)
    assert not subset.empty
    assert (2012, 2, 29) in _dates(subset)
    days = {(m, d) for _, m, d in _dates(subset)}
    assert (2, 14) in days and (3, 15) in days


# Only 2012 has a Feb 29, so non-leap years contribute one day fewer. This is faithful
# to the calendar, not a defect: those days genuinely do not exist.
def test_only_leap_years_contribute_a_leap_day(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(2, 29, n_days=1)
    assert _dates(subset) == {
        (2011, 2, 28), (2012, 2, 28), (2013, 2, 28),
        (2012, 2, 29),
        (2011, 3, 1), (2012, 3, 1), (2013, 3, 1),
    }


def test_window_of_zero_selects_the_target_day_only(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(2, 29, n_days=0)
    assert _dates(subset) == {(2012, 2, 29)}
    assert len(subset) == 24


def test_subset_carries_date_id_and_day_slot(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(2, 29, n_days=1)
    assert "date_id" in subset.columns
    assert "day_slot" in subset.columns
    assert "2012-2-29" in set(subset["date_id"])
    leap_rows = subset[subset["date_id"] == "2012-2-29"]
    assert set(leap_rows["day_slot"]) == {day_slot(2, 29)}


def test_every_selected_day_is_complete(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(1, 2, n_days=4)
    counts = subset.groupby("date_id").size()
    assert set(counts) == {24}


def test_default_half_width_is_15_days(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(6, 15)
    days = {(m, d) for _, m, d in _dates(subset)}
    assert len(days) == 31


# The window must not mutate or depend on the caller's frame.
def test_subset_is_a_copy(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(6, 15, n_days=1)
    subset.loc[subset.index[0], "temp_air"] = -999.0
    assert (mdp_fixture.met_data["temp_air"] != -999.0).all()
    assert "day_slot" not in mdp_fixture.met_data.columns


def test_month_subset_still_works_unchanged(mdp_fixture):
    """The two strategies are selectable; adding the window must not disturb the month."""
    month = mdp_fixture.get_month_subset(5)
    assert set(month["month"].unique()) == {5}
    assert len(month) == 31 * 3 * 24
    assert "date_id" in month.columns
    assert "day_slot" not in month.columns


@pytest.mark.parametrize("month, day", [(2, 30), (13, 1), (4, 31)])
def test_invalid_target_dates_raise(mdp_fixture, month, day):
    with pytest.raises(ValueError):
        mdp_fixture.get_day_window_subset(month, day)


# A negative half-width must raise here exactly as it does in window_slots, rather than
# yielding an empty frame that only fails much later, at KDE fitting, with a message
# pointing at the wrong cause.
@pytest.mark.parametrize("n_days", [-1, -15])
def test_negative_half_width_raises(mdp_fixture, n_days):
    with pytest.raises(ValueError, match="n_days must be non-negative"):
        mdp_fixture.get_day_window_subset(6, 15, n_days=n_days)


def test_wide_half_width_selects_the_whole_year(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(6, 15, n_days=183)
    assert len(subset) == len(mdp_fixture.met_data)


# The slot cache must not leak between differently-centred windows.
def test_repeated_windows_are_consistent(mdp_fixture):
    first = mdp_fixture.get_day_window_subset(6, 15, n_days=2)
    other = mdp_fixture.get_day_window_subset(1, 2, n_days=4)
    again = mdp_fixture.get_day_window_subset(6, 15, n_days=2)

    pd.testing.assert_frame_equal(first, again)
    assert _dates(first) != _dates(other)


def test_day_slot_column_matches_the_records_date(mdp_fixture):
    subset = mdp_fixture.get_day_window_subset(1, 2, n_days=4)
    expected = [day_slot(m, d) for m, d in zip(subset["month"], subset["day"])]
    np.testing.assert_array_equal(subset["day_slot"].values, expected)
