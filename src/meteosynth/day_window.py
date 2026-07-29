"""Canonical calendar helpers for rolling day-of-year windows.

Transition models can be trained either on a calendar-month subset
(:meth:`~meteosynth.dataset.MetDataset.get_month_subset`) or on a
rolling window of +/- n days centred on a target day
(:meth:`~meteosynth.dataset.MetDataset.get_day_window_subset`). This
module provides the calendar arithmetic the latter needs, as pure functions over
``(month, day)`` pairs with no pandas dependency.

Days are indexed by a **slot** on the ``all_leap`` calendar (CF-conventions ``all_leap``
/ ``366_day``): every year is treated as if it had 366 days, so ``Feb 29`` owns slot 60
and ``Mar 1`` is always slot 61 regardless of the year::

    Jan 1 -> 1  ...  Feb 28 -> 59,  Feb 29 -> 60,  Mar 1 -> 61  ...  Dec 31 -> 366

Non-leap years simply never emit slot 60. This keeps the mapping leap-independent, so
records pooled from leap and non-leap years line up. Note that pandas'
``.dt.dayofyear`` does *not* have this property: it shifts by one after February in leap
years, which would misalign the whole March-December calendar when pooling years.

See ``docs/design/completed/rolling-day-window.md`` for the full rationale.
"""

from __future__ import annotations

from typing import Tuple, Union

import numpy as np

#: Number of slots in the canonical ``all_leap`` year.
DAYS_IN_YEAR = 366

#: Length of each month on the ``all_leap`` calendar (February always has 29 days).
_MONTH_LENGTHS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

#: ``_MONTH_OFFSETS[m - 1]`` is the number of slots before the 1st of month ``m``.
_MONTH_OFFSETS = tuple(int(x) for x in np.concatenate([[0], np.cumsum(_MONTH_LENGTHS)[:-1]]))

#: Maximum possible circular distance between two slots.
MAX_HALF_WIDTH = DAYS_IN_YEAR // 2  # 183


def day_slot(month: int, day: int) -> int:
    """
    Map a calendar ``(month, day)`` to its slot on the ``all_leap`` calendar.

    The mapping is leap-independent: ``Feb 29`` is an ordinary slot (60), and every
    date after February keeps the same slot in leap and non-leap years alike.

    Parameters
    ----------
    month : int
        Month of the year (1-12).
    day : int
        Day of the month (1-31), validated against the ``all_leap`` month length, so
        ``(2, 29)`` is accepted but ``(2, 30)`` and ``(4, 31)`` are not.

    Returns
    -------
    int
        Slot in ``1..366``.

    Raises
    ------
    ValueError
        If ``month`` is outside 1-12, or ``day`` is not a valid day of that month.

    Examples
    --------
    >>> day_slot(1, 1)
    1
    >>> day_slot(2, 29)
    60
    >>> day_slot(12, 31)
    366
    """
    month = int(month)
    day = int(day)

    if not 1 <= month <= 12:
        raise ValueError(f"month must be in 1..12, got {month}")

    max_day = _MONTH_LENGTHS[month - 1]
    if not 1 <= day <= max_day:
        raise ValueError(f"day must be in 1..{max_day} for month {month}, got {day}")

    return _MONTH_OFFSETS[month - 1] + day


def day_slots(months, days) -> np.ndarray:
    """
    Vectorised :func:`day_slot` for array-likes of months and days.

    Parameters
    ----------
    months, days : array-like of int
        Broadcastable arrays of months (1-12) and days of the month.

    Returns
    -------
    np.ndarray
        Integer array of slots in ``1..366``, with the broadcast shape.

    Raises
    ------
    ValueError
        If any ``(month, day)`` pair is not a valid ``all_leap`` date.
    """
    months = np.asarray(months, dtype=np.int64)
    days = np.asarray(days, dtype=np.int64)

    if np.any((months < 1) | (months > 12)):
        raise ValueError("all months must be in 1..12")

    lengths = np.asarray(_MONTH_LENGTHS, dtype=np.int64)[months - 1]
    if np.any((days < 1) | (days > lengths)):
        raise ValueError("all days must be valid for their month on the all_leap calendar")

    offsets = np.asarray(_MONTH_OFFSETS, dtype=np.int64)[months - 1]
    return offsets + days


def slot_to_month_day(slot: int) -> Tuple[int, int]:
    """
    Invert :func:`day_slot`.

    Parameters
    ----------
    slot : int
        Slot in ``1..366``.

    Returns
    -------
    tuple of (int, int)
        The ``(month, day)`` owning that slot.

    Raises
    ------
    ValueError
        If ``slot`` is outside ``1..366``.

    Examples
    --------
    >>> slot_to_month_day(60)
    (2, 29)
    """
    slot = int(slot)
    if not 1 <= slot <= DAYS_IN_YEAR:
        raise ValueError(f"slot must be in 1..{DAYS_IN_YEAR}, got {slot}")

    month = int(np.searchsorted(np.cumsum(_MONTH_LENGTHS), slot, side="left")) + 1
    return month, slot - _MONTH_OFFSETS[month - 1]


def circular_delta(
    slots: Union[int, np.ndarray],
    center: int,
    period: int = DAYS_IN_YEAR,
) -> np.ndarray:
    """
    Circular distance in days between ``slots`` and ``center``.

    The calendar wraps, so the distance from Dec 31 (366) to Jan 1 (1) is 1, not 365.

    Parameters
    ----------
    slots : int or np.ndarray
        Slot(s) to measure.
    center : int
        Slot at the centre of the window.
    period : int, optional
        Length of the calendar. **This is not a free parameter** -- it is fixed by the
        slot index and defaults to :data:`DAYS_IN_YEAR`. The slot axis has unit spacing
        over ``1..366``, so only ``period=366`` makes the Dec 31 -> Jan 1 wrap cost
        exactly 1 day. Passing 365 collapses Dec 31 onto Jan 1; passing 365.25 or 366.25
        opens a phantom gap at the wrap. It is exposed only so that the invariant can be
        tested explicitly.

    Returns
    -------
    np.ndarray
        Distance(s) in days, in ``0..period // 2``.

    Examples
    --------
    >>> int(circular_delta(day_slot(1, 1), day_slot(12, 31)))
    1
    """
    d = np.mod(np.asarray(slots) - center, period)
    return np.minimum(d, period - d)


def window_slots(month: int, day: int, n_days: int = 15) -> np.ndarray:
    """
    The slots lying within ``n_days`` of ``(month, day)``, wrapping across New Year.

    Parameters
    ----------
    month : int
        Month of the target day (1-12).
    day : int
        Day of the target month.
    n_days : int, optional
        Half-width of the window in days. Defaults to 15, giving a 31-slot window.
        ``n_days=0`` selects the target day alone; any ``n_days >= 183`` selects the
        whole year.

    Returns
    -------
    np.ndarray
        Sorted array of slots, of length ``min(2 * n_days + 1, 366)``.

    Raises
    ------
    ValueError
        If ``n_days`` is negative, or ``(month, day)`` is not a valid date.

    Examples
    --------
    Feb 29 is an ordinary target -- no special-casing needed:

    >>> len(window_slots(2, 29, n_days=15))
    31

    The window wraps across the year boundary:

    >>> [slot_to_month_day(s) for s in window_slots(1, 2, n_days=4)]
    [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (12, 29), (12, 30), (12, 31)]
    """
    n_days = int(n_days)
    if n_days < 0:
        raise ValueError(f"n_days must be non-negative, got {n_days}")

    center = day_slot(month, day)
    all_slots = np.arange(1, DAYS_IN_YEAR + 1)
    return all_slots[circular_delta(all_slots, center) <= n_days]
