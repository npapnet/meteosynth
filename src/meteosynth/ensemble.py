"""
Writing, reading and exporting ensembles of synthetic years.

An **ensemble** is N independent synthetic realisations of the same calendar span, for one
or more attributes. :func:`write_ensemble` produces one long-format parquet file, streamed
one calendar day at a time, so peak memory never holds the whole ensemble; and
:func:`read_ensemble` reads it back with its provenance intact.

Long format and one file, deliberately:

* **One file** is easier to move, compress and archive than a folder of N, and a folder can
  always be produced *from* it. The reverse costs a re-read of N files.
* **Long format** is what streams -- day *d* contributes its rows and is then done with --
  and it needs no column-naming scheme. It also matches
  :class:`~meteosynth.dataset.MetDataset`'s own layout, so the same tools read observed and
  synthetic data.

The wide layout is not absent, it is derived: :meth:`Ensemble.to_wide` pivots one attribute
to hours-by-realisations, which is what :func:`ensemble_to_xlsx` writes. That asymmetry is
forced rather than chosen -- see :func:`ensemble_to_xlsx`.

See ``docs/design/FEAT-15-ensemble-generation.md``.
"""

from __future__ import annotations

import json
import os
import pathlib
import warnings
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

import numpy as np
import pandas as pd

from .dataset import MetDataset, _pyarrow
from .generators import DayWindowGenerator, HOURS_PER_DAY, _walk_ensemble, realisation_stream
from .markov_chain_simulator_kde2d import resolve_sampling
from .provenance import Provenance

__all__ = [
    "ENSEMBLE_SCHEMA_VERSION",
    "Ensemble",
    "write_ensemble",
    "read_ensemble",
    "ensemble_to_xlsx",
]

#: Version of the on-disk ensemble schema. Bumped when the *data contract* changes --
#: columns, dtypes, row identity -- never for a new metadata field, which readers tolerate.
ENSEMBLE_SCHEMA_VERSION = 1

#: The key parquet key-value metadata is stored under. Distinct from
#: :data:`~meteosynth.dataset._METADATA_KEY` so a training dataset and an ensemble cannot be
#: mistaken for one another by a reader that only checks for a payload.
_METADATA_KEY = b"meteosynth_ensemble"

#: Hard limits of an ``.xlsx`` worksheet. Not advisory: a writer past them produces a file
#: Excel refuses to open.
_EXCEL_MAX_ROWS = 1_048_576
_EXCEL_MAX_COLS = 16_384

#: What the file says about how its attributes relate to one another. Recorded because a
#: multi-column file *looks* like a weather record, and this one is not one.
_INDEPENDENCE_NOTE = (
    "Attributes were generated independently: within a realisation, a hot hour is not "
    "thereby a sunny one. Cross-attribute correlation is not modelled."
)


@dataclass(frozen=True)
class Ensemble:
    """An ensemble read back from disk: the rows, plus what the file says about itself.

    Parameters
    ----------
    frame : pd.DataFrame
        Long format -- one row per ``(realisation, day_index, hour)``, one column per
        attribute. Row order is as written: ``(day_index, realisation, hour)``.
    meta : dict
        The file's own record of how it was generated -- seed, realisation count, calendar
        span, window half-width, bandwidth, and the provenance of the dataset it was
        trained on. Enough to regenerate it.
    """

    frame: pd.DataFrame
    meta: dict = field(default_factory=dict)

    @property
    def attrs(self) -> tuple[str, ...]:
        """The generated attribute columns, in file order."""
        return tuple(
            c for c in self.frame.columns
            if c not in ("realisation", "day_index", "month", "day", "hour")
        )

    @property
    def n_realisations(self) -> int:
        """How many realisations the file holds."""
        return int(self.frame["realisation"].nunique())

    def realisation(self, index: int) -> pd.DataFrame:
        """One realisation as its own frame, in calendar order.

        The whole point of :func:`~meteosynth.generators.realisation_stream`'s keying is
        that this is a well-defined object: realisation ``index`` is the same series
        whether the file holds 10 of them or 10 000.
        """
        one = self.frame[self.frame["realisation"] == index]
        if one.empty:
            raise KeyError(
                f"no realisation {index} in this ensemble; it holds "
                f"{self.n_realisations} (0..{self.n_realisations - 1})"
            )
        return one.sort_values(["day_index", "hour"]).reset_index(drop=True)

    def to_wide(self, attr: str) -> pd.DataFrame:
        """Pivot one attribute to hours-by-realisations.

        Rows are the calendar span in order (``n_days x 24`` of them), columns are
        realisations. This is the layout most external tools want a time series in, and the
        one :func:`ensemble_to_xlsx` writes.

        Raises
        ------
        KeyError
            If ``attr`` is not one of this ensemble's attributes.
        """
        if attr not in self.attrs:
            raise KeyError(f"{attr!r} is not in this ensemble; it holds {self.attrs}")
        wide = self.frame.pivot(
            index=["day_index", "hour"], columns="realisation", values=attr
        ).sort_index()
        wide.columns = [f"realisation_{c}" for c in wide.columns]
        return wide


def _ensemble_schema(pa, attrs: Sequence[str], metadata: dict):
    """The parquet schema, with the file's self-description attached.

    Built once, before the walk, because a streaming writer fixes its schema at creation
    and every row group must match it.
    """
    fields = [
        pa.field("realisation", pa.int32()),
        pa.field("day_index", pa.int16()),
        pa.field("month", pa.int8()),
        pa.field("day", pa.int8()),
        pa.field("hour", pa.int8()),
    ] + [pa.field(attr, pa.float64()) for attr in attrs]
    return pa.schema(
        fields, metadata={_METADATA_KEY: json.dumps(metadata).encode("utf-8")}
    )


def _day_table(pa, schema, step, attrs: Sequence[str], n_realisations: int):
    """One calendar day as a row group: ``n_realisations x 24`` rows.

    Row order within the group is realisation-major, hour-minor, which is exactly C order
    of the ``(n_realisations, 24)`` arrays the walk produces -- so the values need no
    transposition, only a ``ravel``.
    """
    n_rows = n_realisations * HOURS_PER_DAY
    columns = [
        pa.array(np.repeat(np.arange(n_realisations, dtype=np.int32), HOURS_PER_DAY)),
        pa.array(np.full(n_rows, step.day_index, dtype=np.int16)),
        pa.array(np.full(n_rows, step.month, dtype=np.int8)),
        pa.array(np.full(n_rows, step.day, dtype=np.int8)),
        pa.array(np.tile(np.arange(HOURS_PER_DAY, dtype=np.int8), n_realisations)),
    ] + [pa.array(step.values[attr].ravel()) for attr in attrs]
    return pa.Table.from_arrays(columns, schema=schema)


def write_ensemble(
    dataset: MetDataset,
    attrs: Sequence[str],
    path: Union[str, os.PathLike],
    start: tuple,
    n_days: int,
    n_realisations: int,
    seed: Optional[int] = None,
    n_days_window: int = 15,
    bandwidth: Optional[float] = 0.1,
    include_feb29: bool = False,
    progress: bool = False,
    sampling: str = "auto",
    compression: str = "snappy",
) -> dict:
    """
    Generate an ensemble and stream it to one long-format parquet file.

    Walks the calendar **once**, fitting each day's models once per attribute and letting
    every realisation use them, then flushes that day's rows as a parquet row group before
    moving on. Peak memory therefore holds one day's generators plus one day's values, not
    the whole ensemble -- and not the 366 fitted generators that amortising the fit any
    other way would require.

    Measured on Heraklion 2010-2020, ``poa_global``, a 365-day year: 1000 realisations drop
    from ~26.9 h to ~20.9 min (**77x**) against calling
    :meth:`~meteosynth.generators.DayWindowGenerator.generate_series` 1000 times. Multiply by
    the number of attributes -- each is fitted and drawn separately.

    Parameters
    ----------
    dataset : MetDataset
        The training data. One :class:`~meteosynth.generators.DayWindowGenerator` is built
        per attribute -- fitting stays strictly per-attribute.
    attrs : sequence of str
        Attributes to generate. Each must have a registered
        :class:`~meteosynth.variables.VariableSpec`.
    path : str or path-like
        Destination ``.parquet`` file. Parent directories are created.
    start : tuple of (int, int)
        ``(month, day)`` of the first day.
    n_days : int
        Number of consecutive days per realisation.
    n_realisations : int
        How many independent series to generate.
    seed : int, optional
        Root entropy. Realisation *i* of attribute *a* is a fixed function of
        ``(seed, i, a)`` -- see :func:`~meteosynth.generators.realisation_stream` -- so
        realisation 0 does not change when you ask for more realisations, and ``temp_air``
        does not change when you add ``wind_speed`` alongside it.
    n_days_window : int, optional
        Half-width of each day's training window. Defaults to 15.
    bandwidth : float, optional
        KDE bandwidth. Defaults to ``0.1``.
    include_feb29 : bool, optional
        Whether the walk visits Feb 29. Defaults to ``False``, giving a 365-day year.
    progress : bool, optional
        Show a ``tqdm`` bar over the day walk.
    sampling : {"auto", "exact", "grid"}, optional
        Which path answers each draw. ``"auto"`` (default) decides from ``n_realisations``
        before drawing starts. The **resolved** value -- never ``"auto"`` -- is recorded in
        the file's metadata, since it is part of what would be needed to regenerate the
        ensemble bit-for-bit. See
        :data:`~meteosynth.markov_chain_simulator_kde2d.SAMPLING_PATHS`.
    compression : str, optional
        Parquet codec. Defaults to ``"snappy"`` for the widest reader compatibility, since
        these files are written to be read by other software.

    Returns
    -------
    dict
        The metadata embedded in the file, so a caller can log or assert on it without
        re-reading.

    Raises
    ------
    ValueError
        If ``attrs`` is empty or contains duplicates, or the walk request is malformed.

    Notes
    -----
    **Row order is** ``(day_index, realisation, hour)``, because that is the order a
    streamed walk produces. A reader wanting one realisation therefore touches every row
    group; parquet's column statistics make that cheap rather than free. Sort after reading
    if the access pattern warrants it -- :meth:`Ensemble.realisation` does.

    Attributes are generated **independently**; the file records that in its metadata
    ``notes``. See ``FEAT-2``.
    """
    pa, pq = _pyarrow()

    attrs = tuple(attrs)
    if not attrs:
        raise ValueError("attrs must name at least one attribute to generate")
    if len(set(attrs)) != len(attrs):
        raise ValueError(f"attrs contains duplicates: {attrs}")
    if n_realisations < 1:
        raise ValueError(f"n_realisations must be at least 1, got {n_realisations}")

    from . import __version__

    # cache_size=1 deliberately: a calendar walk never revisits a slot, so a larger cache
    # would only retain fitted models -- and any quantile grids they built -- that nothing
    # will ask for again. At ensemble scale those grids are the memory that matters.
    generators = {
        attr: DayWindowGenerator(
            dataset, attr_str=attr, n_days=n_days_window,
            bandwidth=bandwidth, cache_size=1,
        )
        for attr in attrs
    }
    streams = {
        attr: [realisation_stream(seed, r, attr) for r in range(n_realisations)]
        for attr in attrs
    }

    metadata = {
        "ensemble_schema_version": ENSEMBLE_SCHEMA_VERSION,
        "meteosynth_version": __version__,
        "attrs": list(attrs),
        "start": [int(start[0]), int(start[1])],
        "n_days": int(n_days),
        "n_realisations": int(n_realisations),
        "include_feb29": bool(include_feb29),
        "seed": None if seed is None else int(seed),
        "window_n_days": int(n_days_window),
        "bandwidth": None if bandwidth is None else float(bandwidth),
        # The path that actually ran, not the one requested: "auto" tells a later reader
        # nothing, and a file records what happened.
        "sampling": resolve_sampling(sampling, n_expected_draws=n_realisations),
        "source_provenance": dataset.provenance.to_dict(),
        "notes": _INDEPENDENCE_NOTE,
    }

    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = _ensemble_schema(pa, attrs, metadata)

    with pq.ParquetWriter(path, schema, compression=compression) as writer:
        for step in _walk_ensemble(
            generators,
            start=start,
            n_days=n_days,
            streams=streams,
            include_feb29=include_feb29,
            progress=progress,
            sampling=sampling,
        ):
            writer.write_table(_day_table(pa, schema, step, attrs, n_realisations))

    return metadata


def read_ensemble(path: Union[str, os.PathLike]) -> Ensemble:
    """
    Read a file written by :func:`write_ensemble`.

    Parameters
    ----------
    path : str or path-like
        The ``.parquet`` file.

    Returns
    -------
    Ensemble

    Raises
    ------
    ValueError
        If the file was written by a **newer** schema version. Today's code cannot know
        whether that version changed the columns or the row identity, and guessing yields a
        plausible-looking wrong answer -- the same rule
        :meth:`~meteosynth.dataset.MetDataset.load` applies.
    """
    pa, pq = _pyarrow()

    table = pq.read_table(path)
    raw = (table.schema.metadata or {}).get(_METADATA_KEY)

    meta: dict = {}
    if raw is None:
        warnings.warn(
            f"{path} carries no meteosynth ensemble metadata -- it was probably written "
            f"by something other than write_ensemble(). Reading the columns as they are.",
            stacklevel=2,
        )
    else:
        meta = json.loads(raw.decode("utf-8"))
        found = int(meta.get("ensemble_schema_version", 0))
        if found > ENSEMBLE_SCHEMA_VERSION:
            raise ValueError(
                f"{path} was written with ensemble_schema_version {found}, but this "
                f"meteosynth understands up to {ENSEMBLE_SCHEMA_VERSION}. Upgrade the "
                f"package -- refusing rather than guessing what changed."
            )
        if "source_provenance" in meta:
            # Round-tripped through the same tolerant reader the training format uses, so an
            # unknown field from a newer writer is a warning rather than a failure.
            meta["source_provenance"] = Provenance.from_dict(meta["source_provenance"])

    return Ensemble(frame=table.to_pandas(), meta=meta)


def ensemble_to_xlsx(
    ensemble: Union[Ensemble, str, os.PathLike],
    path: Union[str, os.PathLike],
    attrs: Optional[Sequence[str]] = None,
) -> None:
    """
    Export an ensemble to ``.xlsx``, **pivoted to wide**, one sheet per attribute.

    Lossy and one-way, in the same sense as
    :meth:`~meteosynth.dataset.MetDataset.to_csv`: the metadata does not survive, so this is
    an export for other software to read rather than a counterpart to
    :func:`write_ensemble`.

    **The pivot is forced, not a preference.** A worksheet holds 1 048 576 rows; a
    long-format ensemble of 1000 realisations x 8760 hours is 8.76 million, so long format
    caps out at about 119 realisations. Wide -- ``n_days x 24`` rows by ``n_realisations``
    columns -- fits to N ~ 16 000 instead, which covers the range this package is for.

    Parameters
    ----------
    ensemble : Ensemble or path-like
        An in-memory ensemble, or the path to one written by :func:`write_ensemble`.
    path : str or path-like
        Destination ``.xlsx``.
    attrs : sequence of str, optional
        Which attributes to export. Defaults to all of them, one sheet each.

    Raises
    ------
    ImportError
        If no ``.xlsx`` writer is installed. This is the one path in the package that needs
        a dependency the core does not.
    ValueError
        If the export would exceed a worksheet's limits. It refuses rather than truncating:
        silently dropping realisations from an ensemble is exactly the kind of quiet wrong
        answer that is impossible to notice downstream.
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "writing .xlsx needs an Excel writer, which is not a core meteosynth "
            "dependency. Install it with `pip install meteosynth[excel]` (or "
            "`pip install openpyxl`). The parquet file written by write_ensemble() needs "
            "no extra package."
        ) from exc

    if not isinstance(ensemble, Ensemble):
        ensemble = read_ensemble(ensemble)

    selected = tuple(attrs) if attrs is not None else ensemble.attrs
    unknown = [a for a in selected if a not in ensemble.attrs]
    if unknown:
        raise KeyError(f"{unknown} not in this ensemble; it holds {ensemble.attrs}")

    n_rows = len(ensemble.frame) // max(ensemble.n_realisations, 1)
    n_cols = ensemble.n_realisations
    if n_cols > _EXCEL_MAX_COLS - 2:
        raise ValueError(
            f"{n_cols} realisations exceeds the {_EXCEL_MAX_COLS}-column worksheet limit. "
            f"Keep the parquet file, or export a subset via the attrs/realisation "
            f"selection -- refusing rather than truncating the ensemble."
        )
    if n_rows > _EXCEL_MAX_ROWS - 1:
        raise ValueError(
            f"{n_rows} hours exceeds the {_EXCEL_MAX_ROWS}-row worksheet limit. "
            f"Refusing rather than truncating the series."
        )

    warnings.warn(
        "xlsx export is lossy: the ensemble's metadata (seed, provenance, calendar span) "
        "is not carried. Keep the parquet file as the record.",
        stacklevel=2,
    )

    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for attr in selected:
            # Sheet names are capped at 31 characters by the format; no shipped attribute
            # name comes close, but a user-registered one could.
            ensemble.to_wide(attr).to_excel(writer, sheet_name=attr[:31])
