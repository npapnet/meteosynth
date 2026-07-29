"""Tests for transition-pair construction.

Two tests here carry the weight:

* ``test_wide_pairs_match_the_legacy_positional_pairs`` locks in backward compatibility --
  the wide construction must reproduce the old positional one bit-for-bit.
* ``test_pairs_are_order_invariant`` is the executable proof that the alignment hazard is
  disarmed. It fails on the legacy positional implementation and passes on the wide one.

See ``docs/design/completed/transition-pair-alignment.md`` for what the hazard is and why it is
silent.
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth.generators import (
    _to_wide,
    build_cross_midnight_pairs,
    build_transition_pairs,
)
from meteosynth.dataset import MetDataset


@pytest.fixture
def mdp_fixture():
    """Two years of synthetic hourly data (2011-2012) with a value unique per row.

    Uniqueness matters: if every value were repeated, a mispaired frame would still
    compare equal and the order-invariance test would pass vacuously.
    """
    index = pd.date_range("2011-01-01", "2012-12-31 23:00", freq="h")
    df = pd.DataFrame(
        {
            "year": index.year,
            "month": index.month,
            "day": index.day,
            "hour": index.hour,
        }
    )
    marker = index.dayofyear * 100.0 + index.hour + (index.year - 2011) * 1e5
    for col in ["poa_direct", "poa_sky_diffuse", "poa_ground_diffuse",
                "solar_elevation", "temp_air", "wind_speed", "Int"]:
        df[col] = marker
    return MetDataset(df)


def _legacy_positional_pairs(met_data, hour, attr_str):
    """The pre-refactor implementation, kept verbatim as the equivalence reference.

    It zips two hour-filtered slices by position, discarding the dates via ``.values``.
    """
    hour_prev = (hour - 1) % 24
    cur_hour = met_data[met_data["hour"] == hour]
    prev_hour = met_data[met_data["hour"] == hour_prev]
    return pd.DataFrame(
        {
            "previous": prev_hour[attr_str].values,
            "current": cur_hour[attr_str].values,
        }
    )


def _as_pair_set(pairs):
    """Order-independent identity of a pair collection."""
    return pairs.sort_values(["previous", "current"]).to_numpy()


# GOLDEN EQUIVALENCE: this is a change to *how* pairs are built, not *which* pairs are
# built. Verified against the real dataset for all 12 months x 24 hours x 7 attributes.
@pytest.mark.parametrize("hour", range(1, 24))
def test_wide_pairs_match_the_legacy_positional_pairs(mdp_fixture, hour):
    subset = mdp_fixture.get_month_subset(5)
    legacy = _legacy_positional_pairs(subset, hour, "poa_direct")
    wide = build_transition_pairs(_to_wide(subset, "poa_direct"), hour)

    np.testing.assert_array_equal(wide["previous"].values, legacy["previous"].values)
    np.testing.assert_array_equal(wide["current"].values, legacy["current"].values)


def test_wide_pairs_match_legacy_on_a_window_subset(mdp_fixture):
    """Equivalence also holds on a window subset left in its natural order."""
    subset = mdp_fixture.get_day_window_subset(2, 27, n_days=2)
    for hour in range(1, 24):
        legacy = _legacy_positional_pairs(subset, hour, "poa_direct")
        wide = build_transition_pairs(_to_wide(subset, "poa_direct"), hour)
        np.testing.assert_array_equal(wide["previous"].values, legacy["previous"].values)


# THE TEST THAT MATTERS. Shuffle the input; the pairs must not change. This property is
# what makes the pairing correct by construction rather than by luck.
@pytest.mark.parametrize("hour", [1, 6, 12, 18])
def test_pairs_are_order_invariant(mdp_fixture, hour):
    window = mdp_fixture.get_day_window_subset(2, 27, n_days=2)
    baseline = build_transition_pairs(_to_wide(window, "poa_direct"), hour)

    for reordered in (
        window.sort_values("day_slot"),
        window.sort_values("month"),
        window.sample(frac=1, random_state=0),
    ):
        pairs = build_transition_pairs(_to_wide(reordered, "poa_direct"), hour)
        np.testing.assert_array_equal(_as_pair_set(pairs), _as_pair_set(baseline))


# The counterpart: demonstrate the hazard is real, so that if someone ever reverts to the
# positional construction, its failure is documented and reproducible rather than folklore.
def test_legacy_positional_pairs_corrupt_when_reordered(mdp_fixture):
    window = mdp_fixture.get_day_window_subset(2, 27, n_days=2)
    baseline = _legacy_positional_pairs(window, 12, "poa_direct")
    shuffled = _legacy_positional_pairs(
        window.sample(frac=1, random_state=0), 12, "poa_direct"
    )

    # Same length, so nothing raises -- this is exactly why the corruption is silent.
    assert len(shuffled) == len(baseline)
    assert not np.array_equal(_as_pair_set(shuffled), _as_pair_set(baseline))


# Every pair must come from a single day. With the marker values in the fixture, the day
# is recoverable from the value itself, so this checks the invariant directly.
def test_every_pair_comes_from_a_single_day(mdp_fixture):
    window = mdp_fixture.get_day_window_subset(6, 15, n_days=5)
    pairs = build_transition_pairs(_to_wide(window, "poa_direct"), 12)

    # marker = dayofyear * 100 + hour + (year - 2011) * 1e5, so integer-dividing away the
    # hour recovers the (year, dayofyear) the value came from.
    prev_day = ((pairs["previous"] - 11) / 100).round(6)
    curr_day = ((pairs["current"] - 12) / 100).round(6)
    np.testing.assert_array_equal(prev_day.values, curr_day.values)


def test_incomplete_day_drops_only_that_day(mdp_fixture):
    window = mdp_fixture.get_day_window_subset(6, 15, n_days=2).copy()
    complete = build_transition_pairs(_to_wide(window, "poa_direct"), 12)

    # Remove a single hour from a single date (the window spans both years, so the date
    # must be pinned by year as well as by month and day).
    holed = window[
        ~(
            (window["year"] == 2012)
            & (window["month"] == 6)
            & (window["day"] == 15)
            & (window["hour"] == 12)
        )
    ]
    pairs = build_transition_pairs(_to_wide(holed, "poa_direct"), 12)

    assert len(pairs) == len(complete) - 1
    assert not pairs.isna().any().any()
    # The surviving pairs are exactly the others, untouched -- one bad day must not
    # shift every later pair the way positional zipping would.
    survivors = {tuple(row) for row in pairs.to_numpy()}
    original = {tuple(row) for row in complete.to_numpy()}
    assert survivors < original
    assert len(original - survivors) == 1


def test_duplicate_hour_raises_loudly(mdp_fixture):
    window = mdp_fixture.get_day_window_subset(6, 15, n_days=1)
    duped = pd.concat([window, window.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError):
        _to_wide(duped, "poa_direct")


def test_unknown_attribute_raises(mdp_fixture):
    with pytest.raises(ValueError, match="attr_str must be a registered variable"):
        _to_wide(mdp_fixture.get_month_subset(5), "not_an_attribute")


@pytest.mark.parametrize("hour", [-1, 0, 24, 100])
def test_out_of_range_hour_raises_clearly(mdp_fixture, hour):
    """An off-by-one at a call site should say so, not surface as a bare KeyError."""
    wide = _to_wide(mdp_fixture.get_month_subset(5), "poa_direct")
    with pytest.raises(ValueError, match="hour must be in"):
        build_transition_pairs(wide, hour)


# A NaN in the source is the one deliberate deviation from the legacy behaviour: the
# positional version emitted a pair containing the NaN, which would poison the KDE.
def test_nan_in_source_drops_only_that_pair(mdp_fixture):
    subset = mdp_fixture.get_month_subset(5).copy()
    complete = build_transition_pairs(_to_wide(subset, "poa_direct"), 12)

    subset.loc[
        (subset["year"] == 2011) & (subset["day"] == 10) & (subset["hour"] == 12),
        "poa_direct",
    ] = np.nan
    pairs = build_transition_pairs(_to_wide(subset, "poa_direct"), 12)

    assert len(pairs) == len(complete) - 1
    assert not pairs.isna().any().any()
    legacy = _legacy_positional_pairs(subset, 12, "poa_direct")
    assert legacy.isna().any().any()  # the behaviour we deliberately left behind


# generate_hr_simulator is public and exported, but EnvSeriesGenerator no longer routes
# through it, so it needs coverage of its own.
def test_generate_hr_simulator_builds_a_fitted_simulator(mdp_fixture):
    from meteosynth import generate_hr_simulator

    subset = mdp_fixture.get_month_subset(5)
    simulator = generate_hr_simulator(subset, 12, attr_str="poa_direct")

    expected = build_transition_pairs(_to_wide(subset, "poa_direct"), 12)
    np.testing.assert_array_equal(
        simulator.data["previous"].values, expected["previous"].values
    )
    np.testing.assert_array_equal(
        simulator.data["current"].values, expected["current"].values
    )


def test_generate_hr_simulator_validates_its_arguments(mdp_fixture):
    from meteosynth import generate_hr_simulator

    subset = mdp_fixture.get_month_subset(5)
    with pytest.raises(ValueError, match="attr_str must be a registered variable"):
        generate_hr_simulator(subset, 12, attr_str="nope")
    with pytest.raises(ValueError, match="hour must be in"):
        generate_hr_simulator(subset, 24, attr_str="poa_direct")


# The hour-0 quirk, now retired. It used to pair hour 0 with hour 23 of the SAME day --
# a 23-hour backwards jump presented as a one-hour step. Asking for it is now an error
# that names the two replacements.
def test_hour_zero_has_no_within_day_transition(mdp_fixture):
    window = mdp_fixture.get_day_window_subset(6, 15, n_days=2)
    wide = _to_wide(window, "poa_direct")

    with pytest.raises(ValueError, match="build_initial_values"):
        build_transition_pairs(wide, 0)


def test_cross_midnight_pairs_come_from_consecutive_dates(mdp_fixture):
    """previous is 23:00 of the *preceding calendar day*, current is 00:00 of the target.

    With the fixture's marker values a one-day step is recoverable arithmetically:
    marker = dayofyear * 100 + hour, so 23:00 of day d is (d * 100 + 23) and 00:00 of
    day d+1 is ((d + 1) * 100), a difference of -77.
    """
    window = mdp_fixture.get_day_window_subset(6, 15, n_days=2)
    wide_full = _to_wide(mdp_fixture.met_data, "poa_direct")
    pairs = build_cross_midnight_pairs(wide_full, _to_wide(window, "poa_direct").index)

    assert len(pairs) > 0
    np.testing.assert_allclose(
        (pairs["previous"] - pairs["current"]).values,
        np.full(len(pairs), -77.0),
    )


def test_cross_midnight_drops_days_with_no_predecessor(mdp_fixture):
    """The first day of the record has no previous day, so it drops out."""
    wide_full = _to_wide(mdp_fixture.met_data, "poa_direct")

    # A Jan 1 window: 2011-01-01's predecessor (2010-12-31) precedes the record.
    window = mdp_fixture.get_day_window_subset(1, 1, n_days=0)
    target = _to_wide(window, "poa_direct").index
    pairs = build_cross_midnight_pairs(wide_full, target)

    assert len(target) == 2                # 2011-01-01 and 2012-01-01
    assert len(pairs) == 1                 # only 2012-01-01 has a predecessor


# THE TRAP. The training window wraps climatologically, so a Jan 2 window contains
# late-December days. Pairing on the calendar slot rather than the real date would pair
# Dec 31 **2012** with Jan 1 **2012** -- a 364-day *backwards* jump sold as a one-hour
# step. This is the test that would catch that.
#
# marker = dayofyear * 100 + hour + (year - 2011) * 1e5, so a real one-day step within a
# year has difference -77, and the one real year crossing in this 2-year record
# (Dec 31 2011 -> Jan 1 2012) has difference -63577. Both are negative because time moves
# forwards. Every slot-based mispairing is *positive*: +36423 for the Dec 31 2012 ->
# Jan 1 2012 trap, +136423 for Dec 31 2012 -> Jan 1 2011.
def test_cross_midnight_never_pairs_across_the_climatological_wrap(mdp_fixture):
    wide_full = _to_wide(mdp_fixture.met_data, "poa_direct")
    window = mdp_fixture.get_day_window_subset(1, 2, n_days=4)
    pairs = build_cross_midnight_pairs(wide_full, _to_wide(window, "poa_direct").index)

    deltas = (pairs["previous"] - pairs["current"]).values
    assert len(deltas) > 0

    # No backwards jump anywhere: this alone rules out every slot-based mispairing.
    assert (deltas < 0).all(), f"time ran backwards in {deltas[deltas >= 0]}"

    # And the only two things that occur are a within-year step and the single genuine
    # New Year crossing the record contains.
    assert set(np.unique(deltas)) <= {-77.0, -63577.0}
    assert (deltas == -63577.0).sum() == 1
