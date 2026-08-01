"""
The project's data store: collected records, kept beside the work that uses them.

A project folder accumulates source records -- two sites, three year ranges, a TMY -- and
this module answers *"which of these is the one I asked for?"* without opening any of
them. It is what lets an analysis be re-run without re-downloading, and what lets a
script say *"train on Heraklion"* rather than naming a file.

Why "store" and not "cache"
---------------------------
A cache is expendable, transparent and usually shared: delete it and you lose only time.
This is none of those things.

* **It is not expendable.** Delete a record and you lose the exact input a result was
  built on. Providers revise their archives, so a refetch may not return the same
  numbers -- the file *is* part of the analysis, not an accelerator for it.
* **It is not transparent.** You name sites, list what you hold, and get an error rather
  than a silent choice when two records could answer the same question.
* **It is not shared.** :func:`default_data_dir` is ``./data`` under the working
  directory and nothing else. Two projects side by side keep two independent stores;
  there is no user-level location, and **no environment variable or global setting** by
  which one could reach into the other.

Discovery, as distinct from validation
--------------------------------------
:class:`~meteosynth.dataset.MetDataset` already answers *"are you the answer to what I am
asking?"* -- a saved dataset carries its :class:`~meteosynth.provenance.Provenance`
inside the file, and :func:`meteosynth.adapters.fetch_pvgis` checks it before trusting a
record it was handed. That is **validation**: you name a file, and it either answers your
question or raises.

This module is the other half: **discovery**. Given a folder and a question, which file
answers it?

Why a scan rather than an index
-------------------------------
The obvious implementation is a manifest listing what the folder holds. It is also the
wrong one: a manifest is a second source of truth that drifts from the files it
describes, and the whole point of ``FEAT-13`` was to put provenance *inside* the record
so it cannot be separated from it.

A scan is honest instead, and it is affordable because parquet stores its metadata in a
**footer**. Reading provenance costs one seek; reading the data costs megabytes.
Measured over three real cached records:

======================================  =========
operation                               cost
======================================  =========
provenance via ``pq.read_schema``       1.3 ms/file
full ``MetDataset.load``                113 ms/file
======================================  =========

So a folder of a hundred datasets is discoverable in ~130 ms, and nothing has to be
maintained alongside the files.

Containment, not equality
-------------------------
A record covering 2005-2023 **does** answer a request for 2010-2020 -- subsetting it is
exact, and it is what lets one download per site serve every training period. So the
period rule here is containment, and :meth:`~meteosynth.dataset.MetDataset.get_period_subset`
does the narrowing.

The same reasoning does *not* extend to picking between candidates. When two records both
contain a request, this module **refuses and lists them** rather than choosing: which file
a result was trained on is part of the result, and a rule like "the widest wins" makes
that depend on what else happens to be in the folder. Ambiguity is rare by construction --
one file per site -- and when it happens it is worth a sentence from the user.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

from .constants import INDEX_COLS
from .dataset import _METADATA_KEY, _pyarrow
from .provenance import Provenance

__all__ = [
    "COORD_DP",
    "DATA_DIR_NAME",
    "StoredRecord",
    "AmbiguousRecordError",
    "record_filename",
    "default_data_dir",
    "read_provenance",
    "resolve",
    "scan",
]

#: Folder the store lives in, relative to the working directory. A plain constant, not a
#: setting: where a project's data sits is a property of the project, so it is chosen by
#: where you run rather than by anything ambient.
DATA_DIR_NAME = "data"

#: Decimal places coordinates are compared to. ~11 m: finer than any provider's grid,
#: coarser than float noise, so 35.3387 and 35.33870000001 are the same site. A false
#: miss is not a correctness bug, but it does cost a silent re-download.
COORD_DP = 4

#: The three plane-of-array components whose sum is ``poa_global``. A record holding all
#: three can answer a ``poa_global`` request, because the reconstruction is exact for
#: PVGIS -- measured at 0.01 W/m2 maximum difference over 8760 hours, which is the
#: provider's own two-decimal rounding.
POA_COMPONENTS = ("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse")


def period_contains(
    held_start: Optional[int],
    held_end: Optional[int],
    wanted_start: Optional[int],
    wanted_end: Optional[int],
) -> bool:
    """
    Whether a record covering ``held_start``-``held_end`` answers a request for
    ``wanted_start``-``wanted_end``, inclusive on both.

    **The single definition of "wide enough."** Both the discovery path here and the
    validation path in :func:`meteosynth.adapters._use_cache` call this, because the two
    disagreeing is a bug that shows up as a covering cache being refused -- which it did,
    once, during implementation.

    Two edge cases, and they are not symmetric:

    * **No period requested** means *"whatever you have"*, so anything covers it.
    * **No period held** is a TMY, which genuinely has no single year. It covers nothing
      but the no-period request above. What keeps a TMY from answering an hourly request
      is the ``source`` check, not this one.
    """
    if wanted_start is None and wanted_end is None:
        return True
    if held_start is None or held_end is None:
        return False
    lo = held_start if wanted_start is None else wanted_start
    hi = held_end if wanted_end is None else wanted_end
    return held_start <= lo and held_end >= hi


class AmbiguousRecordError(Exception):
    """Several cached records answer the same request.

    Distinct from :exc:`~meteosynth.adapters.CacheMismatchError`, which means *"the file
    you named is the wrong file"*. This one means *"you did not name a file, and more
    than one would do"* -- so the fix is to say which, not to overwrite anything.
    """


@dataclass(frozen=True)
class StoredRecord:
    """One stored record, identified without being read.

    Parameters
    ----------
    path : pathlib.Path
        Where it is.
    provenance : Provenance
        What it says about itself, read from the parquet footer.
    columns : tuple of str
        Column names, also from the footer. Enough to answer *"does this record hold the
        quantity I want to model?"* without loading a single row.
    """

    path: pathlib.Path
    provenance: Provenance
    columns: tuple

    def covers(self, start: Optional[int], end: Optional[int]) -> bool:
        """Whether this record's period contains ``start``-``end`` inclusive."""
        return period_contains(
            self.provenance.start_year, self.provenance.end_year, start, end
        )

    def holds(self, column: Optional[str]) -> bool:
        """Whether the requested column is present, or derivable from what is."""
        if column is None:
            return True
        if column in self.columns:
            return True
        # A total is reconstructible from its parts; a part is never reconstructible
        # from the total, which is why this is not symmetric.
        return column == "poa_global" and all(c in self.columns for c in POA_COMPONENTS)


def default_data_dir() -> pathlib.Path:
    """
    Where collected records go when the caller does not say: ``./data``.

    Returns
    -------
    pathlib.Path
        :data:`DATA_DIR_NAME` under the **current working directory**.

    Notes
    -----
    **There is deliberately no environment variable and no global setting.** Where a
    project's data sits is a property of that project, so it is decided by the folder you
    work in and by nothing else. Ambient configuration would mean a script could read a
    different store depending on which shell launched it, which is precisely the class of
    surprise a provenance-checked format exists to remove. To use another folder, say so
    at the call: ``fetch_pvgis(..., data_dir="inputs")``.

    The working directory rather than the calling script's folder, because a library
    cannot reliably find its caller's file -- it would have to walk the call stack, which
    breaks in a REPL, in a notebook and in anything frozen. A script that wants its own
    folder regardless of where it is run from can be explicit::

        fetch_pvgis(..., data_dir=pathlib.Path(__file__).parent / "data")
    """
    return pathlib.Path.cwd() / DATA_DIR_NAME


def record_filename(provenance: Provenance) -> str:
    """
    The conventional filename for a record, from what it says about itself.

    ``<source>_<site>_<start>_<end>.parquet``, with coordinates standing in for a missing
    site label and the period omitted when there is none (a TMY).

    Notes
    -----
    **The name is a convenience, not an identity.** Provenance inside the file is what
    identifies it and what :func:`resolve` matches on, so a renamed file still answers
    honestly and a mistyped one still fails honestly. The name exists so that a human
    listing the folder can see what they have.

    Examples
    --------
    >>> record_filename(Provenance(source="pvgis_hourly", site="heraklion",
    ...                           start_year=2005, end_year=2023))
    'pvgis_hourly_heraklion_2005_2023.parquet'
    """
    if provenance.site:
        who = str(provenance.site).strip().lower().replace(" ", "-")
    elif provenance.latitude is not None and provenance.longitude is not None:
        who = f"{round(float(provenance.latitude), COORD_DP)}_{round(float(provenance.longitude), COORD_DP)}"
    else:
        who = "unknown"

    parts = [provenance.source, who]
    if provenance.start_year is not None and provenance.end_year is not None:
        parts += [str(provenance.start_year), str(provenance.end_year)]
    return "_".join(parts) + ".parquet"


def read_provenance(path: Union[str, os.PathLike]) -> Optional[StoredRecord]:
    """
    Read one record's provenance and column names, without reading its data.

    Parameters
    ----------
    path : str or Path
        A ``.parquet`` file.

    Returns
    -------
    StoredRecord or None
        ``None`` when the file carries no meteosynth metadata -- an ordinary parquet
        file someone else wrote. That is not an error here: this function's job is to
        report what a folder holds, and a folder is allowed to hold other things.

    Notes
    -----
    Deliberately does **not** check ``schema_version``. A future-versioned file cannot be
    *loaded* by this package -- :meth:`~meteosynth.dataset.MetDataset.load` refuses it --
    but it can still be listed, and hiding it would make a folder's contents depend on
    which version was doing the looking.
    """
    _, pq = _pyarrow()
    path = pathlib.Path(path)

    try:
        schema = pq.read_schema(path)
    except Exception as exc:  # noqa: BLE001 -- an unreadable file is not our failure
        logging.debug("skipping %s: %s", path, exc)
        return None

    raw = (schema.metadata or {}).get(_METADATA_KEY)
    if raw is None:
        return None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):  # pragma: no cover -- corrupt metadata
        logging.debug("skipping %s: unreadable meteosynth metadata", path)
        return None

    return StoredRecord(
        path=path,
        provenance=Provenance.from_dict(payload.get("provenance", {})),
        columns=tuple(schema.names),
    )


def scan(directory: Union[str, os.PathLike]) -> List[StoredRecord]:
    """
    Every meteosynth record in a folder, identified from its footer.

    Parameters
    ----------
    directory : str or Path
        Searched non-recursively. A missing folder is an empty result, not an error --
        "nothing is cached yet" is the normal first-run state.

    Returns
    -------
    list of StoredRecord
        Sorted by path, so output is stable across filesystems.
    """
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        return []

    found = [read_provenance(p) for p in sorted(directory.glob("*.parquet"))]
    return [record for record in found if record is not None]


def _matches(
    record: StoredRecord,
    *,
    source: str,
    site: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    start: Optional[int],
    end: Optional[int],
    column: Optional[str],
) -> bool:
    """Whether one record answers the request. Site identity first, then coverage."""
    if record.provenance.source != source:
        return False

    if site is not None:
        # A label the user chose, compared as they would say it.
        if (record.provenance.site or "").strip().lower() != site.strip().lower():
            return False
    elif latitude is not None and longitude is not None:
        here = (record.provenance.latitude, record.provenance.longitude)
        if None in here:
            return False
        if (round(float(here[0]), COORD_DP), round(float(here[1]), COORD_DP)) != (
            round(float(latitude), COORD_DP),
            round(float(longitude), COORD_DP),
        ):
            return False

    return record.covers(start, end) and record.holds(column)


def candidates(
    directory: Union[str, os.PathLike],
    *,
    source: str,
    site: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    column: Optional[str] = None,
) -> List[StoredRecord]:
    """Every cached record that answers this request. See :func:`resolve`."""
    return [
        record
        for record in scan(directory)
        if _matches(
            record,
            source=source,
            site=site,
            latitude=latitude,
            longitude=longitude,
            start=start,
            end=end,
            column=column,
        )
    ]


def resolve(
    directory: Union[str, os.PathLike],
    *,
    source: str,
    site: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    column: Optional[str] = None,
) -> Optional[pathlib.Path]:
    """
    The one cached record that answers this request.

    Parameters
    ----------
    directory : str or Path
        Folder to search, non-recursively.
    source : str
        Must match exactly: ``"pvgis_hourly"``, ``"pvgis_tmy"``, ...
    site : str, optional
        Site label, compared case-insensitively against
        :attr:`~meteosynth.provenance.Provenance.site`. When given, coordinates are not
        consulted -- a name the user chose is a stronger statement of intent than a pair
        of floats.
    latitude, longitude : float, optional
        Used when ``site`` is not given, compared at :data:`COORD_DP` decimal places.
    start, end : int, optional
        Inclusive period. A record matches if its own period **contains** this one.
    column : str, optional
        A quantity the record must hold, or be able to produce -- all three POA
        components answer a ``poa_global`` request.

    Returns
    -------
    pathlib.Path or None
        ``None`` when nothing matches, which tells the caller to fetch.

    Raises
    ------
    AmbiguousRecordError
        When more than one record answers, listing every candidate. Choosing for the
        caller would make a result depend on what else is in the folder.

    Examples
    --------
    >>> resolve("data", source="pvgis_hourly", site="heraklion",
    ...         start=2011, end=2012)                        # doctest: +SKIP
    PosixPath('data/pvgis_hourly_heraklion_2005_2023.parquet')
    """
    found = candidates(
        directory,
        source=source,
        site=site,
        latitude=latitude,
        longitude=longitude,
        start=start,
        end=end,
        column=column,
    )

    if not found:
        return None
    if len(found) == 1:
        return found[0].path

    raise AmbiguousRecordError(
        f"{len(found)} stored records answer this request "
        f"({_describe_request(source, site, latitude, longitude, start, end, column)}):\n"
        + "\n".join(_describe(record) for record in found)
        + "\nName one explicitly, or remove the ones you do not want."
    )


def _describe_request(
    source: str,
    site: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    start: Optional[int],
    end: Optional[int],
    column: Optional[str],
) -> str:
    """The request, as a short phrase for an error message."""
    who = site if site is not None else f"({latitude}, {longitude})"
    parts = [f"source={source}", f"site={who}"]
    if start is not None or end is not None:
        parts.append(f"period={start}-{end}")
    if column is not None:
        parts.append(f"column={column}")
    return ", ".join(parts)


def _describe(record: StoredRecord) -> str:
    """One candidate, as an indented line naming what distinguishes it."""
    prov = record.provenance
    period = (
        f"{prov.start_year}-{prov.end_year}"
        if prov.start_year is not None
        else "no period"
    )
    modelled = ", ".join(c for c in record.columns if c not in INDEX_COLS)
    return f"  {record.path.name}  [{period}]  {modelled}"


def record_path_for(
    provenance: Provenance, directory: Optional[Union[str, os.PathLike]] = None
) -> pathlib.Path:
    """
    Full path a record should be written to.

    Parameters
    ----------
    provenance : Provenance
        What the record says about itself; supplies the filename.
    directory : str or Path, optional
        Where to put it. Defaults to :func:`default_data_dir`.
    """
    base = default_data_dir() if directory is None else pathlib.Path(directory)
    return base / record_filename(provenance)


def describe_store(directory: Optional[Union[str, os.PathLike]] = None) -> str:
    """
    A human-readable listing of what a cache folder holds.

    Intended for a ``--list`` style command and for error messages; the machine-readable
    form is :func:`scan`.
    """
    directory = default_data_dir() if directory is None else pathlib.Path(directory)
    records = scan(directory)
    if not records:
        return f"{directory}: nothing cached"
    lines = [f"{directory}: {len(records)} record(s)"]
    lines += [_describe(record) for record in records]
    return "\n".join(lines)
