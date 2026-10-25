"""Tests for the metrics data object, `SeriesSet`, and the helpers that build one."""

import numpy as np
import pandas as pd
import pytest

from meteosynth.ensemble import Ensemble
from meteosynth.metrics import SeriesSet, no_leap_calendar


def _one_day_calendar(n_days=2):
    month = np.ones(24 * n_days, dtype=int)
    day = np.repeat(np.arange(1, n_days + 1), 24)
    hour = np.tile(np.arange(24), n_days)
    return month, day, hour


def _long_record(years, drop=()):
    """An hourly long frame over whole calendar years; `value` encodes (year, hour)."""
    frames = []
    for y in years:
        idx = pd.date_range(f"{y}-01-01", f"{y}-12-31 23:00", freq="h")
        frames.append(pd.DataFrame({
            "year": idx.year, "month": idx.month, "day": idx.day, "hour": idx.hour,
            "value": y + idx.hour / 100.0,
        }))
    df = pd.concat(frames, ignore_index=True)
    return df.drop(index=list(drop)).reset_index(drop=True)


# The calendar every ensemble is on: 365 days, Feb 29 absent.
def test_no_leap_calendar():
    month, day, hour = no_leap_calendar()
    assert len(month) == len(day) == len(hour) == 8760
    assert not np.any((month == 2) & (day == 29))
    assert (month[0], day[0], hour[0]) == (1, 1, 0)
    assert (month[-1], day[-1], hour[-1]) == (12, 31, 23)


def test_shape_properties_and_cell():
    month, day, hour = _one_day_calendar(2)
    values = np.arange(3 * 48, dtype=float).reshape(3, 48)
    s = SeriesSet(values, month, day, hour, attr="x")
    assert (s.n_members, s.hours_per_member) == (3, 48)
    assert list(s.members) == [0, 1, 2]
    assert s.cell(1, 5).shape == (3, 2)
    np.testing.assert_array_equal(s.cell(1, 5)[0], [5, 29])
    assert s.cell(7, 5).shape == (3, 0)        # month not covered
    np.testing.assert_array_equal(s.slots[::24], [1, 2])


@pytest.mark.parametrize("breaker, message", [
    (lambda v, m, d, h: (v[0], m, d, h), "2-D"),
    (lambda v, m, d, h: (v, m[:-1], d, h), "one entry per column"),
    (lambda v, m, d, h: (v[:, :30], m[:30], d[:30], h[:30]), "multiple of 24"),
    (lambda v, m, d, h: (v, m, d, np.roll(h, 1)), "0..23"),
    (lambda v, m, d, h: (v, m, np.where(np.arange(48) == 5, 2, d), h), "changes within a day"),
])
def test_rejects_malformed_input(breaker, message):
    month, day, hour = _one_day_calendar(2)
    values = np.zeros((2, 48))
    with pytest.raises(ValueError, match=message):
        SeriesSet(*breaker(values, month, day, hour))


def test_rejects_nan_and_bad_dates():
    month, day, hour = _one_day_calendar(2)
    values = np.zeros((2, 48))
    values[1, 3] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        SeriesSet(values, month, day, hour)
    with pytest.raises(ValueError, match="valid"):
        SeriesSet(np.zeros((1, 24)), np.full(24, 2), np.full(24, 30), np.arange(24))


def test_rejects_member_label_mismatch():
    month, day, hour = _one_day_calendar(1)
    with pytest.raises(ValueError, match="one label per row"):
        SeriesSet(np.zeros((2, 24)), month, day, hour, members=[2020])


# Feb 29 goes, incomplete years go and are reported, every member lands on one calendar.
def test_from_reference_frame_drops_feb29_and_incomplete_years():
    df = _long_record([2019, 2020, 2021], drop=range(0, 5))   # 2019 loses 5 hours
    s = SeriesSet.from_reference_frame(df, "value")
    assert list(s.members) == [2020, 2021]
    assert s.dropped == (2019,)
    assert s.hours_per_member == 8760
    month, day, hour = no_leap_calendar()
    np.testing.assert_array_equal(s.month, month)
    np.testing.assert_array_equal(s.day, day)
    # 2020 is a leap year: its Mar 1 must sit where every other year's Mar 1 sits.
    mar1 = np.flatnonzero((s.month == 3) & (s.day == 1) & (s.hour == 7))[0]
    assert s.values[0, mar1] == pytest.approx(2020.07)


def test_from_reference_frame_errors():
    df = _long_record([2021])
    with pytest.raises(KeyError, match="lacks"):
        SeriesSet.from_reference_frame(df.drop(columns="hour"), "value")
    with pytest.raises(ValueError, match="repeats"):
        SeriesSet.from_reference_frame(pd.concat([df, df.iloc[:1]]), "value")
    with pytest.raises(ValueError, match="no year covers"):
        SeriesSet.from_reference_frame(df.iloc[:-1], "value")


def _ensemble_frame(n_real=3, n_days=4, start_month=12, start_day=30):
    """Long ensemble frame in the file's own row order (day-major), wrapping New Year."""
    dates = pd.date_range(f"2023-{start_month}-{start_day}", periods=n_days, freq="D")
    rows = []
    for d, date in enumerate(dates):
        for r in range(n_real):
            for h in range(24):
                rows.append((r, d, date.month, date.day, h, 1000 * r + 24 * d + h))
    return pd.DataFrame(rows, columns=["realisation", "day_index", "month", "day", "hour", "x"])


# One member per realisation, calendar order, whatever the frame's row order.
def test_from_ensemble_frame():
    frame = _ensemble_frame().sample(frac=1.0, random_state=0)
    s = SeriesSet.from_ensemble_frame(frame, "x")
    assert (s.n_members, s.hours_per_member) == (3, 96)
    np.testing.assert_array_equal(s.values[2, :3], [2000, 2001, 2002])
    np.testing.assert_array_equal(s.values[1], 1000 + np.arange(96))
    np.testing.assert_array_equal(s.month[::24], [12, 12, 1, 1])
    np.testing.assert_array_equal(s.day[::24], [30, 31, 1, 2])
    assert list(s.members) == [0, 1, 2]


def test_from_ensemble_matches_frame_helper():
    frame = _ensemble_frame()
    a = SeriesSet.from_ensemble(Ensemble(frame=frame), "x")
    b = SeriesSet.from_ensemble_frame(frame, "x")
    np.testing.assert_array_equal(a.values, b.values)
    with pytest.raises(KeyError):
        SeriesSet.from_ensemble(Ensemble(frame=frame), "missing")
