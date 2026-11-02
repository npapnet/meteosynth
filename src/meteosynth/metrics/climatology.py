"""
The typical value of an attribute at each hour of each day of the year.

Subtracting it leaves the *weather*: an anomaly autocorrelation measures memory, where a raw
one mostly measures whether the average day and the average year have the right shape.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..day_window import DAYS_IN_YEAR, MAX_HALF_WIDTH
from .series import SeriesSet


@dataclass(frozen=True, eq=False)
class Climatology:
    """
    Mean per ``(day-of-year slot, hour)``, smoothed over a circular calendar window.

    Parameters
    ----------
    means : np.ndarray
        ``(366, 24)``; row ``slot - 1`` holds the 24 hourly means of that ``all_leap`` slot.
    half_width : int
        The ``+/-`` days each slot was pooled over.

    Notes
    -----
    Build it from the **reference** only, and subtract the same object from both sides, so
    each is measured against one baseline. Comparing two ensembles (e.g. generated with
    ``+/-7`` and ``+/-15`` day windows) is only fair against one shared climatology, which
    is why it is an argument to
    :meth:`~meteosynth.metrics.TemporalFidelity.evaluate` rather than computed inside it.
    """

    means: np.ndarray
    half_width: int

    @classmethod
    def from_series(cls, reference: SeriesSet, half_width: int = 15) -> "Climatology":
        """
        Estimate from the reference members.

        A raw ``(slot, hour)`` mean has one value per member -- 19 for a 19-year record --
        which is too noisy to subtract, so each slot pools the ``+/-half_width`` slots
        around it, wrapping across New Year. Slots with no data (Feb 29, absent from a
        :class:`SeriesSet`) are filled by that pooling. The default of 15 days matches the
        generator's own default training window.

        The slots beside that gap (Feb 28, Mar 1) pool one slot fewer on one side, so on a
        steep seasonal slope they sit very slightly off it -- 1 slot of 31 at the default.


        Raises
        ------
        ValueError
            If ``half_width`` is outside ``0..183``, or a slot is still empty after pooling.
        """
        if not 0 <= half_width <= MAX_HALF_WIDTH:
            raise ValueError(f"half_width must be in 0..{MAX_HALF_WIDTH}, got {half_width}")

        cell = np.tile((reference.slots - 1) * 24 + reference.hour, reference.n_members)
        n_cells = DAYS_IN_YEAR * 24
        sums = np.bincount(cell, weights=reference.values.ravel(), minlength=n_cells)
        counts = np.bincount(cell, minlength=n_cells)
        raw_sums = sums.reshape(DAYS_IN_YEAR, 24)
        raw_counts = counts.reshape(DAYS_IN_YEAR, 24).astype(np.float64)

        # Mean of the per-slot means over the window -- each slot weighted once, as the
        # smoothing of a (slot, hour) table, regardless of how many members fed it.
        with np.errstate(invalid="ignore", divide="ignore"):
            raw = raw_sums / raw_counts
        present = raw_counts > 0
        idx = np.arange(DAYS_IN_YEAR)
        gap = np.abs(((idx[None, :] - idx[:, None] + DAYS_IN_YEAR // 2) % DAYS_IN_YEAR)
                     - DAYS_IN_YEAR // 2)
        window = (gap <= half_width).astype(np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            means = (window @ np.where(present, raw, 0.0)) / (window @ present)
        if np.isnan(means).any():
            raise ValueError(
                f"{int(np.isnan(means).any(axis=1).sum())} day-of-year slots have no data "
                f"within +/-{half_width} days; widen half_width"
            )
        return cls(means=means, half_width=half_width)

    def baseline(self, series: SeriesSet) -> np.ndarray:
        """The climatological value at every column of ``series``: ``(n_hours,)``."""
        return self.means[series.slots - 1, series.hour]

    def anomalies(self, series: SeriesSet) -> np.ndarray:
        """``series.values`` minus the climatology: ``(n_members, n_hours)``, a new array."""
        return series.values - self.baseline(series)
