"""Tests for the all_leap calendar arithmetic backing the rolling day window."""

import numpy as np
import pytest

from meteosynth.day_window import (
    DAYS_IN_YEAR,
    circular_delta,
    day_slot,
    day_slots,
    slot_to_month_day,
    window_slots,
)


@pytest.fixture
def anchor_dates():
    """Calendar anchors and their expected all_leap slots."""
    return {
        (1, 1): 1,
        (1, 31): 31,
        (2, 1): 32,
        (2, 28): 59,
        (2, 29): 60,
        (3, 1): 61,
        (12, 31): 366,
    }


# The slots that define the calendar; everything else is derived from them.
def test_day_slot_anchors(anchor_dates):
    for (month, day), expected in anchor_dates.items():
        assert day_slot(month, day) == expected


# Feb 29 is a first-class slot, not an interstitial special case.
def test_feb29_is_an_ordinary_slot():
    assert day_slot(2, 29) == 60
    assert day_slot(2, 28) + 1 == day_slot(2, 29)
    assert day_slot(2, 29) + 1 == day_slot(3, 1)


# The whole point of all_leap: the mapping takes no year, so March onwards cannot drift
# between leap and non-leap years the way pandas' .dt.dayofyear does.
def test_slots_are_leap_independent():
    assert day_slot(3, 1) == 61
    assert day_slot(12, 31) == DAYS_IN_YEAR


def test_slot_to_month_day_roundtrips():
    for slot in range(1, DAYS_IN_YEAR + 1):
        assert day_slot(*slot_to_month_day(slot)) == slot


def test_slot_to_month_day_anchors(anchor_dates):
    for (month, day), slot in anchor_dates.items():
        assert slot_to_month_day(slot) == (month, day)


def test_day_slots_matches_scalar_version():
    months = np.array([1, 2, 2, 3, 12])
    days = np.array([1, 28, 29, 1, 31])
    expected = np.array([day_slot(m, d) for m, d in zip(months, days)])
    np.testing.assert_array_equal(day_slots(months, days), expected)


@pytest.mark.parametrize("month, day", [(0, 1), (13, 1), (2, 30), (4, 31), (1, 0)])
def test_day_slot_rejects_invalid_dates(month, day):
    with pytest.raises(ValueError):
        day_slot(month, day)


@pytest.mark.parametrize("slot", [0, 367, -1])
def test_slot_to_month_day_rejects_invalid_slots(slot):
    with pytest.raises(ValueError):
        slot_to_month_day(slot)


# THE PERIOD GUARD. The slot axis has unit spacing over 1..366, so the New Year wrap must
# cost exactly one day. This test exists so that anyone "correcting" the period to 365
# fails loudly here, rather than silently shifting every December window by a day.
def test_new_year_wrap_costs_exactly_one_day():
    assert int(circular_delta(day_slot(1, 1), day_slot(12, 31))) == 1


@pytest.mark.parametrize(
    "wrong_period, wrong_distance",
    [
        (365, 0),  # collapses Dec 31 onto Jan 1
        (367, 2),  # opens a phantom gap at the wrap
    ],
)
def test_only_366_gives_a_correct_wrap(wrong_period, wrong_distance):
    assert int(circular_delta(day_slot(1, 1), day_slot(12, 31), period=wrong_period)) == wrong_distance


def test_circular_delta_is_symmetric_and_zero_at_centre():
    assert int(circular_delta(day_slot(6, 1), day_slot(6, 1))) == 0
    a, b = day_slot(3, 10), day_slot(4, 10)
    assert int(circular_delta(a, b)) == int(circular_delta(b, a))


def test_circular_delta_never_exceeds_half_a_year():
    center = day_slot(1, 1)
    deltas = circular_delta(np.arange(1, DAYS_IN_YEAR + 1), center)
    assert deltas.max() == DAYS_IN_YEAR // 2


# Caveat A, worked example 1: Jan 2 with n=4 must reach back into December.
def test_window_wraps_backwards_over_new_year():
    got = {slot_to_month_day(s) for s in window_slots(1, 2, n_days=4)}
    assert got == {
        (12, 29), (12, 30), (12, 31),
        (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
    }


# Caveat A, worked example 2: Dec 30 with n=4 must reach forward into January.
def test_window_wraps_forwards_over_new_year():
    got = {slot_to_month_day(s) for s in window_slots(12, 30, n_days=4)}
    assert got == {
        (12, 26), (12, 27), (12, 28), (12, 29), (12, 30), (12, 31),
        (1, 1), (1, 2), (1, 3),
    }


# Caveat B: Feb 29 is requestable as a target, with no special-casing.
def test_feb29_window_is_centred_on_feb29():
    got = {slot_to_month_day(s) for s in window_slots(2, 29, n_days=15)}
    assert (2, 29) in got
    assert got == {slot_to_month_day(s) for s in range(45, 76)}  # Feb 14 .. Mar 15
    assert min(got) == (2, 14) or (2, 14) in got
    assert (3, 15) in got


@pytest.mark.parametrize("n_days", [0, 1, 15, 30, 182])
def test_window_has_2n_plus_1_slots(n_days):
    assert len(window_slots(6, 15, n_days=n_days)) == 2 * n_days + 1


def test_window_of_zero_is_the_target_alone():
    assert window_slots(2, 29, n_days=0).tolist() == [day_slot(2, 29)]


@pytest.mark.parametrize("n_days", [183, 200, 400])
def test_wide_windows_select_the_whole_year(n_days):
    assert len(window_slots(7, 1, n_days=n_days)) == DAYS_IN_YEAR


def test_window_is_sorted_and_unique():
    slots = window_slots(1, 2, n_days=4)
    assert slots.tolist() == sorted(set(slots.tolist()))


def test_window_rejects_negative_half_width():
    with pytest.raises(ValueError):
        window_slots(6, 15, n_days=-1)


# Every day of the year must be a valid target, including the wrap and the leap day.
def test_every_slot_is_a_valid_window_centre():
    for slot in range(1, DAYS_IN_YEAR + 1):
        month, day = slot_to_month_day(slot)
        assert len(window_slots(month, day, n_days=15)) == 31
