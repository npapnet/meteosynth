"""
The training dataset: a strict, source-agnostic, round-trippable record.

This package's core business is **generating synthetic series from a training record**.
Getting that record is auxiliary -- fetch it, read it from a file, or build the frame by
hand -- and nothing downstream should care which. :class:`MetDataset` is that record: it
owns the schema, validates on construction, carries its own
:class:`~meteosynth.provenance.Provenance`, and round-trips to disk without loss::

    ds = MetDataset(my_frame)              # from anything
    ds.save("heraklion.parquet")
    MetDataset.load("heraklion.parquet") == ds        # True, by construction

Why a format at all
-------------------
A file is optional here -- it always was. But *"optional to use"* does not imply *"not
worth specifying"*, and the package previously drew that inference: with no schema to
version, provenance had nowhere to live except a fetcher's cache, and validation had
nowhere to live except a fetcher's boundary check. So a hand-built frame was never
support-validated at all, and a duplicated calendar row surfaced as a pandas reshape
error deep inside the generator.

Strictness belongs to the format, so it applies however the data arrived.

What is rejected, and what is repaired
--------------------------------------
========================================  ==========================================
condition                                 behaviour
========================================  ==========================================
missing index columns / no variable       raise
duplicate ``(year, month, day, hour)``    raise
invalid calendar (``month=13``)           raise
value outside a spec's physical support   clip to the bound, warn, count it
unregistered columns                      drop
date with fewer than 24 hours             keep, and report in :meth:`describe`
========================================  ==========================================

The two structural rejections were **already fatal** before this class existed -- they
just failed later and less legibly, inside ``pivot`` and inside ``day_slot``. Moving them
to construction changes the error message, not the set of accepted inputs.

Out-of-support values are **clipped rather than rejected** because real station records
routinely carry small negative irradiance at night from sensor noise, and refusing a
19-year record over four ``-2 W/m2`` readings would block real work. The check is also
narrower than it looks: it cannot catch the unit errors it was written for -- 280 K and
20 degF both sit inside support, as the test suite asserts -- so its reach is limited to
violations that happen to cross a bound. Clipping also matches what the model already
does, since sampling is truncated to support by
:meth:`~meteosynth.variables.VariableSpec.clamp_domain`.
"""

from __future__ import annotations

import json
import os
import pathlib
import warnings
from dataclasses import replace
from typing import Any, Dict, Optional, Tuple, Union

import pandas as pd

from .constants import INDEX_COLS
from .day_window import _MONTH_LENGTHS, circular_delta, day_slot, day_slots
from .provenance import Provenance
from .variables import get_spec, registered, resolve_irradiance

__all__ = [
    "SCHEMA_VERSION",
    "MetDataset",
    "validate_columns",
    "trim_columns",
    "convert_to_daily_wide",
]

#: Version of the on-disk schema. Bumped when the *data contract* changes -- column rules,
#: dtypes, row identity -- never for a new provenance field, which readers tolerate.
SCHEMA_VERSION = 1

#: The key parquet key-value metadata is stored under.
_METADATA_KEY = b"meteosynth"

#: Canonical dtype of each calendar column. Normalising these at construction is what makes
#: round-trip identity hold by construction rather than by luck: whatever a source frame
#: arrives with, two datasets built from the same data compare equal.
_INDEX_DTYPES = {"year": "int32", "month": "int8", "day": "int8", "hour": "int8"}

#: Canonical dtype of every modelled variable.
_VALUE_DTYPE = "float64"


def validate_columns(met_data: pd.DataFrame) -> None:
    """
    Check a frame carries the calendar index and at least one modellable column.

    The rule is conditional -- *all* of :data:`~meteosynth.constants.INDEX_COLS`, and
    *any* registered column -- which is why it is a function rather than a flat
    ``REQUIRED_COLS`` tuple: a tuple of things that must all be present cannot express
    "all of these and any of those".

    Requiring only one registered column means a temperature-only source with no
    irradiance at all ingests cleanly. "Is this dataset usable for what you asked?" is a
    different question, answered later by the generator's ``attr_str`` validation, which
    can name the specific column that is missing.

    Raises
    ------
    ValueError
        If an index column is missing, or no registered column is present.
    """
    missing = [col for col in INDEX_COLS if col not in met_data.columns]
    if missing:
        raise ValueError(
            f"met_data is missing required index columns: {missing}. "
            f"Every record needs {INDEX_COLS}."
        )

    known = [col for col in met_data.columns if col in registered()]
    if not known:
        raise ValueError(
            f"met_data has no modellable column. Registered variables are "
            f"{registered()}; the frame has {list(met_data.columns)}. Use "
            f"meteosynth.register() to declare a spec for one of them."
        )


def trim_columns(met_data: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy holding only the index columns and registered variables.

    Unregistered columns are dropped rather than carried through, so nothing downstream
    can come to depend on a provider-specific column -- which is exactly how a PVGIS
    quality flag ended up being treated as a meteorological quantity.

    ``solar_elevation`` and ``Int`` fall out **by this rule**, not by a hardcoded list:
    neither is a stochastic environmental quantity, so neither has a spec. A user who
    genuinely wants to model solar elevation registers a spec for it and it survives.
    Declaring it is the deliberate act.

    Note the caller's original frame is never mutated -- only this processed copy is
    trimmed -- so a dropped column remains available to the caller.
    """
    keep = [col for col in met_data.columns if col in INDEX_COLS or col in registered()]
    return met_data.loc[:, keep].copy()


def _validate_calendar(frame: pd.DataFrame) -> None:
    """Raise if any row is not a real ``all_leap`` calendar instant.

    Checked here rather than left to :func:`~meteosynth.day_window.day_slot`, which only
    sees a frame once a window is requested -- by which point the caller is several calls
    away from the data they need to fix.
    """
    months = frame["month"]
    bad = frame.index[(months < 1) | (months > 12)]
    if len(bad):
        raise ValueError(
            f"month must be in 1..12; {len(bad)} row(s) violate this, first at position "
            f"{int(bad[0])} with month={int(months.iloc[int(bad[0])])}."
        )

    hours = frame["hour"]
    bad = frame.index[(hours < 0) | (hours > 23)]
    if len(bad):
        raise ValueError(
            f"hour must be in 0..23; {len(bad)} row(s) violate this, first at position "
            f"{int(bad[0])} with hour={int(hours.iloc[int(bad[0])])}."
        )

    # Day is validated against the all_leap month lengths, so Feb 29 is an ordinary date
    # -- the same calendar day_slot uses, so the two cannot disagree.
    max_days = months.map(lambda m: _MONTH_LENGTHS[int(m) - 1])
    days = frame["day"]
    bad = frame.index[(days < 1) | (days > max_days)]
    if len(bad):
        pos = int(bad[0])
        raise ValueError(
            f"day is out of range for its month; {len(bad)} row(s) violate this, first "
            f"at position {pos} with month={int(months.iloc[pos])}, "
            f"day={int(days.iloc[pos])}."
        )


def _validate_unique(frame: pd.DataFrame) -> None:
    """Raise if any calendar instant appears twice.

    A duplicate is already fatal -- ``convert_to_daily_wide`` cannot reshape it -- but it
    fails there as ``Index contains duplicate entries``, which names neither the dates
    nor the file they came from.
    """
    dupes = frame.duplicated(subset=list(INDEX_COLS), keep=False)
    if not dupes.any():
        return

    offenders = frame.loc[dupes, list(INDEX_COLS)].drop_duplicates()
    shown = ", ".join(
        f"{int(r.year)}-{int(r.month):02d}-{int(r.day):02d} h{int(r.hour):02d}"
        for r in list(offenders.itertuples())[:3]
    )
    more = "" if len(offenders) <= 3 else f", and {len(offenders) - 3} more"
    raise ValueError(
        f"{int(dupes.sum())} rows share {len(offenders)} duplicate calendar instant(s): "
        f"{shown}{more}. Every (year, month, day, hour) must be unique."
    )


def _clip_to_support(frame: pd.DataFrame) -> Dict[str, int]:
    """Clip every registered column into its spec's support, reporting what moved."""
    clipped: Dict[str, int] = {}
    for col in frame.columns:
        if col not in registered():
            continue
        lower, upper = get_spec(col).support
        values = frame[col]
        out = pd.Series(False, index=frame.index)
        if lower is not None:
            out |= values < lower
        if upper is not None:
            out |= values > upper
        count = int(out.sum())
        if count:
            clipped[col] = count
            frame[col] = values.clip(lower=lower, upper=upper)
    return clipped


class MetDataset:
    """
    A validated, source-agnostic training record.

    Accepts any frame carrying :data:`~meteosynth.constants.INDEX_COLS` plus at least one
    column with a registered :class:`~meteosynth.variables.VariableSpec`. The frame may
    come from :mod:`meteosynth.adapters` or straight from the caller -- adapters are an
    optional collection helper, not a required layer.

    Parameters
    ----------
    met_data : pd.DataFrame
        The record. Never mutated; a canonicalised copy is taken.
    provenance : Provenance, optional
        Where it came from. Defaults to ``Provenance(source="user")``, which invents
        nothing -- it records that nobody claimed a source.

    Attributes
    ----------
    met_data : pd.DataFrame
        The canonical frame: trimmed to registered columns, canonical dtypes, sorted by
        calendar, unique on ``(year, month, day, hour)``, inside physical support.
    provenance : Provenance
        Always present, never ``None``.
    clipped : dict of str to int
        How many values each column had clipped into support **at construction**. A
        report about this build, not a property of the data -- reconstructing from the
        already-clipped frame yields an empty dict, which is why it takes no part in
        :meth:`__eq__`.

    Examples
    --------
    >>> ds = MetDataset(frame)                            # doctest: +SKIP
    >>> ds.irradiance_column                              # doctest: +SKIP
    'poa_global'
    >>> dwg = DayWindowGenerator(ds, ds.irradiance_column)  # doctest: +SKIP
    """

    def __init__(
        self,
        met_data: pd.DataFrame,
        provenance: Optional[Provenance] = None,
    ) -> None:
        validate_columns(met_data)
        frame = trim_columns(met_data)

        index_nulls = [col for col in INDEX_COLS if frame[col].isna().any()]
        if index_nulls:
            raise ValueError(
                f"index columns {index_nulls} contain missing values. The calendar must "
                f"be complete even where a measurement is not."
            )

        for col, dtype in _INDEX_DTYPES.items():
            frame[col] = frame[col].astype(dtype)
        for col in frame.columns:
            if col not in INDEX_COLS:
                frame[col] = frame[col].astype(_VALUE_DTYPE)

        frame = frame.reset_index(drop=True)
        _validate_calendar(frame)
        _validate_unique(frame)

        self.clipped = _clip_to_support(frame)
        if self.clipped:
            detail = ", ".join(
                f"{count} in {col!r} to {get_spec(col).support}"
                for col, count in self.clipped.items()
            )
            warnings.warn(
                f"clipped {detail}. Small excursions are ordinary sensor noise; a large "
                f"count suggests wrong units.",
                stacklevel=2,
            )

        self.met_data = frame.sort_values(list(INDEX_COLS)).reset_index(drop=True)
        self.provenance = provenance if provenance is not None else Provenance()
        self.__slots_cache = None

    # -- what it holds ---------------------------------------------------------------

    @property
    def variables(self) -> Tuple[str, ...]:
        """Every registered column the dataset holds, sorted."""
        return tuple(sorted(c for c in self.met_data.columns if c in registered()))

    @property
    def irradiance_column(self) -> str:
        """
        The one irradiance column to model, chosen by availability.

        Lets a caller stop caring whether the record came from PVGIS hourly
        (``poa_global``) or a TMY (``ghi``). Raises when only components of a total are
        present -- see :func:`~meteosynth.variables.resolve_irradiance`.
        """
        return resolve_irradiance(self.met_data.columns)

    def describe(self) -> Dict[str, Any]:
        """
        What this dataset can say about itself.

        Note ``rows`` is the size of the *whole record*. The size of the set a generator
        actually trains on is a different number, per calendar day, and lives on
        :class:`~meteosynth.generators.DayWindowGenerator` -- e.g. 341 pooled days for a
        +/-15-day window on an 11-year record, against 96 432 rows here. Reporting both,
        each where it is true, beats one number that has to be qualified.
        """
        dates = self.met_data.groupby(["year", "month", "day"], observed=True).size()
        return {
            "schema_version": SCHEMA_VERSION,
            "rows": int(len(self.met_data)),
            "years": (int(self.met_data["year"].min()), int(self.met_data["year"].max())),
            "variables": self.variables,
            "dates": int(len(dates)),
            "incomplete_dates": int((dates != 24).sum()),
            "non_null": {col: int(self.met_data[col].notna().sum()) for col in self.variables},
            "clipped": dict(self.clipped),
            "provenance": self.provenance,
        }

    def describe_time_range(self) -> str:
        """Human-readable summary of the years covered."""
        return (
            f"Data ranges from {self.met_data['year'].min()} "
            f"to {self.met_data['year'].max()}"
        )

    def __eq__(self, other: object) -> bool:
        """Equal when the data and the provenance are equal.

        ``clipped`` is deliberately excluded: it reports what *this construction* had to
        repair, so a dataset reloaded from disk -- already clipped, nothing left to do --
        would otherwise never equal the one that wrote it, and round-trip identity is the
        property the format exists to guarantee.
        """
        if not isinstance(other, MetDataset):
            return NotImplemented
        return self.provenance == other.provenance and self.met_data.equals(other.met_data)

    def __repr__(self) -> str:
        years = f"{self.met_data['year'].min()}-{self.met_data['year'].max()}"
        return (
            f"MetDataset({len(self.met_data)} rows, {years}, "
            f"{list(self.variables)}, source={self.provenance.source!r})"
        )

    # -- I/O -------------------------------------------------------------------------

    def save(self, path: Union[str, os.PathLike]) -> None:
        """
        Write to parquet, losslessly, with provenance embedded.

        Parquet is the canonical format because it is the only one of the three the
        package used to write that satisfies round-trip identity: one file, exact dtypes,
        and metadata carried inside it. CSV widens ``int8`` to ``int64`` and drops
        metadata entirely, which is why :meth:`to_csv` is named as an *export* rather
        than a counterpart to this.

        Provenance travels as explicit parquet key-value metadata rather than through
        ``DataFrame.attrs``. Both were measured to round-trip, but key-value metadata is
        a documented feature of the format while attrs-in-parquet is pandas-internal
        behaviour -- and going through ``pyarrow`` on both sides keeps serialisation
        independent of how a given pandas/pyarrow pair negotiates ``attrs``.

        The result stays readable by anything that speaks parquet: a plain
        ``pd.read_parquet`` returns the columns and ignores the metadata.
        """
        pa, pq = _pyarrow()
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "provenance": self.provenance.to_dict(),
        }
        table = pa.Table.from_pandas(self.met_data, preserve_index=False)
        metadata = dict(table.schema.metadata or {})
        metadata[_METADATA_KEY] = json.dumps(payload).encode("utf-8")
        pq.write_table(table.replace_schema_metadata(metadata), path)

    @classmethod
    def load(cls, path: Union[str, os.PathLike]) -> "MetDataset":
        """
        Read a dataset written by :meth:`save`.

        Raises
        ------
        ValueError
            If the file was written by a **newer** schema version. Today's code cannot
            know whether that version changed the column rules, the dtypes or the row
            identity contract, and guessing yields a plausible-looking wrong dataset --
            the failure this format exists to prevent. Provenance fields are treated the
            opposite way: unknown ones are descriptive, so they are ignored with a
            warning rather than refused.
        """
        pa, pq = _pyarrow()

        table = pq.read_table(path)
        raw = (table.schema.metadata or {}).get(_METADATA_KEY)

        provenance = None
        if raw is None:
            warnings.warn(
                f"{path} carries no meteosynth metadata -- it was probably written by "
                f"something other than MetDataset.save(). Reading it as user data.",
                stacklevel=2,
            )
        else:
            payload = json.loads(raw.decode("utf-8"))
            found = int(payload.get("schema_version", 0))
            if found > SCHEMA_VERSION:
                raise ValueError(
                    f"{path} was written with schema_version {found}, but this "
                    f"meteosynth understands up to {SCHEMA_VERSION}. Upgrade the package "
                    f"-- refusing rather than guessing what changed."
                )
            provenance = Provenance.from_dict(payload.get("provenance", {}))

        return cls(table.to_pandas(), provenance=provenance)

    @classmethod
    def read_csv(
        cls,
        path: Union[str, os.PathLike],
        provenance: Optional[Provenance] = None,
        **kwargs,
    ) -> "MetDataset":
        """
        Import from CSV -- an interchange format, not a counterpart to :meth:`load`.

        A CSV carries no provenance and no dtypes, so both are supplied here: dtypes by
        the schema's canonicalisation, provenance by the caller if they know it.
        """
        return cls(pd.read_csv(path, **kwargs), provenance=provenance)

    def to_csv(self, path: Union[str, os.PathLike], **kwargs) -> None:
        """
        Export to CSV for something else to read. **Lossy, and says so.**

        The asymmetry with :meth:`save` is the point: ``save``/``load`` are a pair that
        round-trips, ``read_csv``/``to_csv`` are two independent conveniences.
        """
        warnings.warn(
            "CSV export is lossy: dtypes widen on read and provenance is not carried. "
            "Use save() for a dataset you intend to load again.",
            stacklevel=2,
        )
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.met_data.to_csv(path, index=False, **kwargs)

    # -- views -----------------------------------------------------------------------

    def get_period_subset(
        self, start: int, end: int, origin: Optional[str] = None
    ) -> "MetDataset":
        """
        The years ``start``-``end`` inclusive, as a dataset in their own right.

        This is what makes **one download per site** enough: a record covering 2005-2023
        answers a request for 2010-2020 by narrowing, so a training period does not have
        to be decided before the data is collected.

        Parameters
        ----------
        start, end : int
            Inclusive year range. Must be fully contained in what this dataset holds.
        origin : str, optional
            Where the wider record came from -- a filename, usually. Recorded in the
            result's provenance notes, so a narrowed dataset still says what it was
            narrowed from.

        Returns
        -------
        MetDataset
            Carrying provenance for **the period it now holds**, not the one it was cut
            from, plus a note naming the origin.

        Raises
        ------
        ValueError
            If the requested period is not fully contained. Returning the overlap would
            answer a different question than the one asked -- silently, and with a
            plausible-looking result -- which is the failure this format exists to
            prevent. Whether a cache is wide enough is
            :func:`meteosynth.store.resolve`'s job, and it applies the same rule.

        Notes
        -----
        Unlike :meth:`get_month_subset` and :meth:`get_day_window_subset`, which return
        bare frames because they are *training slices* consumed immediately by a
        generator, this returns a full :class:`MetDataset`. The difference is that the
        result is still a record of a site over a period -- it can be saved, re-sliced,
        and asked where it came from -- so dropping its provenance would lose exactly
        what the format exists to carry.

        **The narrowing is exact.** Measured on a real 19-year PVGIS record narrowed to
        its middle 11 years against the same 11 years fetched separately: identical row
        count, index columns aligned exactly, ``temp_air`` and ``wind_speed``
        bit-identical, and ``poa_global`` within 0.01 W/m2 -- PVGIS's own two-decimal
        rounding.

        Examples
        --------
        >>> ds.describe_time_range()                       # doctest: +SKIP
        'Data ranges from 2005 to 2023'
        >>> ds.get_period_subset(2010, 2020).describe_time_range()   # doctest: +SKIP
        'Data ranges from 2010 to 2020'
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")

        held_start = int(self.met_data["year"].min())
        held_end = int(self.met_data["year"].max())
        if start < held_start or end > held_end:
            raise ValueError(
                f"this dataset holds {held_start}-{held_end}, which does not contain "
                f"the requested {start}-{end}. Returning the overlap would quietly "
                f"answer a different question -- fetch the missing years instead."
            )

        subset = self.met_data[self.met_data["year"].between(start, end)]

        note = (
            f"subset from {origin}"
            if origin
            else f"subset from a {held_start}-{held_end} record"
        )
        existing = self.provenance.notes
        provenance = replace(
            self.provenance,
            start_year=start,
            end_year=end,
            notes=f"{existing}; {note}" if existing else note,
        )
        return MetDataset(subset.reset_index(drop=True), provenance=provenance)

    def get_month_subset(self, month_ind: int) -> pd.DataFrame:
        """
        Every record in a calendar month, pooled across years.

        Parameters
        ----------
        month_ind : int
            Month index (1-12).

        Returns
        -------
        pd.DataFrame
            The subset, with a ``date_id`` column identifying each unique date.
        """
        month_data = self.met_data[self.met_data["month"] == month_ind].copy()
        return _add_date_id(month_data)

    def get_day_window_subset(
        self, month: int, day: int, n_days: int = 15
    ) -> pd.DataFrame:
        """
        Get a rolling window of the meteorological data centred on a calendar day.

        Selects every record lying within ``n_days`` of ``(month, day)`` on the
        ``all_leap`` calendar, pooled across all years in the dataset. This is the
        seasonal counterpart to :meth:`get_month_subset`: where a month subset is
        centred on the middle of the month (so a May 1 model trains on data centred on
        May 16) and jumps discontinuously at month boundaries, a window is centred on
        the target day and slides smoothly from one day to the next.

        The window wraps across New Year, so a Jan 2 target reaches back into December
        and a Dec 30 target reaches forward into January. Feb 29 needs no special
        handling: it is an ordinary slot, so it is pooled into any nearby window and can
        also be requested as the target.

        Note this is a *climatological* window, not a chronological one -- a Jan 2 2011
        target pools December 2011 as a proxy for "late-December climate".

        Parameters
        ----------
        month : int
            Month of the target day (1-12).
        day : int
            Day of the target month.
        n_days : int, optional
            Half-width of the window in days. Defaults to 15, giving a 31-day window.
            ``n_days=0`` selects the target day alone; any ``n_days >= 183`` selects
            the whole year.

        Returns
        -------
        pd.DataFrame
            Subset of the meteorological data for the window, with the same ``date_id``
            column that :meth:`get_month_subset` adds, plus the ``day_slot`` of each
            record.

        Raises
        ------
        ValueError
            If ``(month, day)`` is not a valid date, or ``n_days`` is negative.
        """
        n_days = int(n_days)
        if n_days < 0:
            raise ValueError(f"n_days must be non-negative, got {n_days}")

        center = day_slot(month, day)
        slots = self._day_slots()

        mask = circular_delta(slots, center) <= n_days
        window_data = self.met_data[mask].copy()
        window_data["day_slot"] = slots[mask]

        return _add_date_id(window_data)

    def get_monthly_attribute_wide_format(
        self, value_col: str, month_id: Optional[int] = None
    ) -> pd.DataFrame:
        """Pivot one attribute to days-by-hours, optionally for a single month."""
        temp_df = (
            self.met_data.copy() if month_id is None else self.get_month_subset(month_id)
        )
        return convert_to_daily_wide(temp_df, value_col=value_col)

    def _day_slots(self):
        """The all_leap calendar slot of every record, computed once and reused.

        The source data does not change over a dataset's lifetime, so caching this keeps
        a 366-day calendar walk from re-mapping all rows on every window.
        """
        if self.__slots_cache is None:
            self.__slots_cache = day_slots(
                self.met_data["month"].values, self.met_data["day"].values
            )
        return self.__slots_cache


def _pyarrow():
    """Import ``pyarrow``, with an error that says what to do about it.

    Imported lazily so ``import meteosynth`` stays cheap for the modelling path, which
    never touches a file.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover -- pyarrow is a declared dependency
        raise ImportError(
            "reading and writing datasets needs pyarrow, which ships as a meteosynth "
            "dependency. Install it with `pip install pyarrow`."
        ) from exc
    return pa, pq


def _add_date_id(subset: pd.DataFrame) -> pd.DataFrame:
    """
    Add the ``date_id`` column identifying each unique date, in place.

    Shared by :meth:`MetDataset.get_month_subset` and
    :meth:`MetDataset.get_day_window_subset` so the two slicing strategies cannot drift
    apart on the format downstream consumers group by.

    Note the id is not zero-padded (``'2011-1-2'``), so it does not sort
    lexicographically -- do not rely on it for ordering. :func:`convert_to_daily_wide`
    builds its own zero-padded ``date_str`` for that reason.
    """
    subset["date_id"] = (
        subset["year"].astype(str)
        + "-"
        + subset["month"].astype(str)
        + "-"
        + subset["day"].astype(str)
    )
    return subset


def convert_to_daily_wide(met_data: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """
    Reshape one attribute to one row per day and one column per hour.

    Parameters
    ----------
    met_data : pd.DataFrame
        A long frame carrying the calendar index columns and ``value_col``.
    value_col : str
        The column to spread across hours.

    Returns
    -------
    pd.DataFrame
        Days-by-hours. Both values of a transition pair are read from the same row,
        which is what guarantees they come from the same day.
    """
    tmp_df = met_data.loc[:, [value_col, "year", "month", "day", "hour"]]
    # A zero-padded date string, so the index sorts chronologically -- date_id does not.
    tmp_df["date_str"] = pd.to_datetime(tmp_df[["year", "month", "day"]]).dt.strftime(
        "%Y%m%d"
    )
    return tmp_df.pivot(index=["date_str"], columns="hour", values=value_col)
