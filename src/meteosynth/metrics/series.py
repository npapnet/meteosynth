"""
The one data object every fidelity metric takes: a set of equal-length series on a shared
calendar.

Both sides of a comparison arrive in the same form -- the **reference** years (one member
per observed year) and the **synthetic** realisations (one member per realisation) -- so
every metric is written once, for one shape, and never opens a file or reads metadata.

The helpers here convert the two tables the package already produces into that form. They
take in-memory frames, never paths: reading is the caller's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..day_window import day_slots

if TYPE_CHECKING:  # pragma: no cover -- typing only; metrics never needs the class at runtime
    from ..ensemble import Ensemble

#: Days per month on the 365-day calendar the ensembles are generated on (no Feb 29).
_NO_LEAP_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def no_leap_calendar() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    The ``(month, day, hour)`` columns of one 365-day year, Feb 29 absent.

    The calendar every ensemble generated with ``include_feb29=False`` is on, and the one
    :meth:`SeriesSet.from_reference_frame` reshapes each observed year onto. Useful when
    building a :class:`SeriesSet` from arrays directly.

    Returns
    -------
    month, day, hour : np.ndarray
        Each of length 8 760, in calendar order.
    """
    month = np.repeat(np.arange(1, 13), _NO_LEAP_MONTH_LENGTHS)
    day = np.concatenate([np.arange(1, n + 1) for n in _NO_LEAP_MONTH_LENGTHS])
    return np.repeat(month, 24), np.repeat(day, 24), np.tile(np.arange(24), len(day))


@dataclass(frozen=True, eq=False)
class SeriesSet:
    """
    Equal-length hourly series of one attribute, sharing one calendar.

    Parameters
    ----------
    values : np.ndarray
        ``(n_members, n_hours)``. A member is one observed year or one realisation.
    month, day, hour : np.ndarray
        ``(n_hours,)`` each -- the calendar every member is on. Whole days only, hours
        ``0..23`` in order within each day.
    members : np.ndarray, optional
        ``(n_members,)`` labels: the years, or the realisation indices. Defaults to
        ``0..n_members-1``.
    attr : str, optional
        The attribute's column name. Used in messages and summaries only.
    dropped : tuple, optional
        Members a helper removed before construction (e.g. incomplete years), so the caller
        can report them. Informational; nothing reads it.

    Raises
    ------
    ValueError
        If shapes disagree, the hours are not whole days in order, a ``(month, day)`` is
        not a calendar date, or ``values`` holds NaN.

    Notes
    -----
    **The calendar is shared, not per member.** That is what makes the object a plain
    rectangle: every metric can slice members, hours and ``(month, hour)`` cells with array
    indexing, and nothing has to re-check alignment. It is also why Feb 29 is absent from
    the reference side -- the ensembles are generated without it, and keeping it would make
    leap years one day longer than every other member.

    Arrays are held as given, not copied, so a 70 MB ensemble is not duplicated. Do not
    modify them after construction.
    """

    values: np.ndarray
    month: np.ndarray
    day: np.ndarray
    hour: np.ndarray
    members: np.ndarray | None = None
    attr: str = ""
    dropped: tuple = ()
    _slots: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        values = np.asarray(self.values, dtype=np.float64)
        month = np.asarray(self.month, dtype=np.int64)
        day = np.asarray(self.day, dtype=np.int64)
        hour = np.asarray(self.hour, dtype=np.int64)

        if values.ndim != 2:
            raise ValueError(f"values must be 2-D (n_members, n_hours), got shape {values.shape}")
        n_members, n_hours = values.shape
        for name, arr in (("month", month), ("day", day), ("hour", hour)):
            if arr.shape != (n_hours,):
                raise ValueError(
                    f"{name} must have one entry per column of values ({n_hours}), "
                    f"got shape {arr.shape}"
                )
        if n_hours == 0 or n_hours % 24:
            raise ValueError(f"n_hours must be a positive multiple of 24, got {n_hours}")
        if not np.array_equal(hour, np.tile(np.arange(24), n_hours // 24)):
            raise ValueError("hour must run 0..23 within every day, in order")
        per_day = n_hours // 24
        for name, arr in (("month", month), ("day", day)):
            if np.any(arr.reshape(per_day, 24) != arr[::24, None]):
                raise ValueError(f"{name} changes within a day")
        if np.isnan(values).any():
            raise ValueError(
                f"values holds {int(np.isnan(values).sum())} NaN; drop or fill incomplete "
                f"members before building a SeriesSet"
            )

        members = (np.arange(n_members) if self.members is None
                   else np.asarray(self.members))
        if members.shape != (n_members,):
            raise ValueError(
                f"members must have one label per row of values ({n_members}), "
                f"got shape {members.shape}"
            )

        set_ = object.__setattr__
        set_(self, "values", values)
        set_(self, "month", month)
        set_(self, "day", day)
        set_(self, "hour", hour)
        set_(self, "members", members)
        set_(self, "dropped", tuple(self.dropped))
        set_(self, "_slots", day_slots(month, day))   # also validates every (month, day)

    # ------------------------------------------------------------------ shape

    @property
    def n_members(self) -> int:
        """Rows: observed years, or realisations."""
        return self.values.shape[0]

    @property
    def hours_per_member(self) -> int:
        """Columns: the length of every member's series."""
        return self.values.shape[1]

    @property
    def slots(self) -> np.ndarray:
        """Day-of-year slot (1..366, ``all_leap``) of every column."""
        return self._slots

    # ------------------------------------------------------------------ slicing

    def cell_mask(self, month: int, hour: int) -> np.ndarray:
        """Boolean ``(n_hours,)`` mask of the columns in one ``(month, hour)`` cell."""
        return (self.month == month) & (self.hour == hour)

    def cell(self, month: int, hour: int) -> np.ndarray:
        """
        Every value at one hour of one month.

        Returns
        -------
        np.ndarray
            ``(n_members, n_days_in_month)``; zero columns if the month is not covered.
        """
        return self.values[:, self.cell_mask(month, hour)]

    # ------------------------------------------------------------------ helpers

    @classmethod
    def from_reference_frame(cls, frame: pd.DataFrame, attr: str) -> "SeriesSet":
        """
        One member per observed year, from a long ``year, month, day, hour, <attr>`` frame.

        Feb 29 is dropped, so every year sits on :func:`no_leap_calendar`. Years that do not
        cover all 8 760 hours of it (a partial first or last year, gaps, NaN) are left out
        and listed in :attr:`dropped`.

        Parameters
        ----------
        frame : pd.DataFrame
            E.g. ``MetDataset.met_data`` or ``pd.read_parquet(path, columns=[...])``.
        attr : str
            The column to take.

        Raises
        ------
        KeyError
            If a required column is missing.
        ValueError
            If a ``(year, month, day, hour)`` appears twice, or no year is complete.
        """
        needed = ["year", "month", "day", "hour", attr]
        missing = [c for c in needed if c not in frame.columns]
        if missing:
            raise KeyError(f"frame lacks column(s) {missing}; needs {needed}")

        df = frame.loc[~((frame["month"] == 2) & (frame["day"] == 29)), needed]
        if df.duplicated(["year", "month", "day", "hour"]).any():
            raise ValueError("frame repeats a (year, month, day, hour); expected one row each")

        month, day, hour = no_leap_calendar()
        wide = (
            df.set_index(["month", "day", "hour", "year"])[attr]
            .unstack("year")
            .reindex(pd.MultiIndex.from_arrays([month, day, hour]))
        )
        complete = wide.notna().all(axis=0)
        if not complete.any():
            raise ValueError(f"no year covers all 8760 hours of {attr!r}")

        return cls(
            values=wide.loc[:, complete].to_numpy().T,
            month=month, day=day, hour=hour,
            members=wide.columns[complete].to_numpy(),
            attr=attr,
            dropped=tuple(int(y) for y in wide.columns[~complete]),
        )

    @classmethod
    def from_ensemble(cls, ensemble: "Ensemble", attr: str) -> "SeriesSet":
        """
        One member per realisation, from an in-memory :class:`~meteosynth.ensemble.Ensemble`.

        Built on :meth:`Ensemble.to_wide`, so the pivot exists in one place. For a large
        ensemble on disk, reading one attribute day by day into an ``(N, n_hours)`` array
        and calling the constructor directly is far lighter than loading the whole file.
        """
        wide = ensemble.to_wide(attr)                     # (n_hours, N), (day_index, hour)
        calendar = (
            ensemble.frame.groupby("day_index")[["month", "day"]].first()
            .reindex(wide.index.get_level_values("day_index"))
        )
        return cls(
            values=wide.to_numpy().T,
            month=calendar["month"].to_numpy(),
            day=calendar["day"].to_numpy(),
            hour=wide.index.get_level_values("hour").to_numpy(),
            members=np.array([int(c.rsplit("_", 1)[1]) for c in wide.columns]),
            attr=attr,
        )

    @classmethod
    def from_ensemble_frame(cls, frame: pd.DataFrame, attr: str) -> "SeriesSet":
        """
        One member per realisation, from the ensemble's long frame.

        Expects ``realisation, day_index, month, day, hour, <attr>`` -- the layout
        ``pd.read_parquet`` returns for a file written by
        :func:`~meteosynth.ensemble.write_ensemble`.
        """
        from ..ensemble import Ensemble

        return cls.from_ensemble(Ensemble(frame=frame), attr)
