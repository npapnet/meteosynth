"""
Optional helpers for collecting data from providers.

Adapters are an **auxiliary tool for getting data in easily**, not a required layer. The
contract between them and the rest of the package is a
:class:`~meteosynth.dataset.MetDataset`, which serves both use cases without forcing
either through the other's path::

    # A -- no data for the site; fetch it.
    ds = fetch_pvgis(48.86, 2.35, 2011, 2012, cache="data/paris.parquet")

    # B -- the user already has data. No adapter involved at all.
    register("rel_humidity", VariableSpec((0.0, 100.0), "%"))
    ds = MetDataset(my_df)

Both routes produce the same object, validated the same way. That is the point: a fetched
record is no more trustworthy than a hand-built one, so the schema checks live in the
dataset rather than here, and apply however the data arrived.

What a column name says, and what it cannot
-------------------------------------------
``poa_global`` and ``poa_direct`` are different columns, and a frame always says which one
it holds: **the column name is the quantity**, which is why nothing here records an
"irradiance form". What a name cannot say is *which site*, *which years*, and *which of a
provider's mutually exclusive fetch modes* produced the record -- so each fetch stamps a
:class:`~meteosynth.provenance.Provenance` onto the dataset it returns, and
:meth:`~meteosynth.dataset.MetDataset.save` carries it into the file.

That is what lets a warm cache answer *"are you the answer to what I am asking?"* instead
of being trusted on the strength of its path alone.

Two PVGIS entry points
----------------------
:func:`fetch_pvgis` collects a real multi-year hourly record on the **plane of array**;
:func:`fetch_pvgis_tmy` collects a Typical Meteorological Year on the **horizontal**.
They are not interchangeable, and again the column names say so -- ``poa_global`` from
one, ``ghi`` / ``dni`` / ``dhi`` from the other.

Note that a TMY is what this package is an alternative *to*: it is built to be typical,
so it has no bad years in it and offers one profile and one answer. It is here as a
baseline to generate against, not as an input the generator is meant to be trained on.

Provider naming
---------------
``SOURCE_RENAMES`` maps a provider's column names onto canonical ones. It is keyed
**per source** rather than being one flat alias map, because two providers can use the
same label for different quantities and a flat map would resolve that silently.

Note it is nearly empty for PVGIS: ``pvlib.iotools.get_pvgis_hourly`` already renames
the raw API's ``T2m`` / ``WS10m`` / ``G(i)`` into ``temp_air`` / ``wind_speed`` /
``poa_global`` before this package sees anything. The mapping earns its keep for
providers ``pvlib`` does not cover.
"""

from __future__ import annotations

import datetime as _dt
import logging
import pathlib
from typing import List, Optional, Union

import pandas as pd

from .constants import INDEX_COLS
from .dataset import MetDataset
from .provenance import Provenance
from .variables import get_spec, registered

__all__ = [
    "SOURCE_RENAMES",
    "CacheMismatchError",
    "normalise",
    "validate_support",
    "fetch_pvgis",
    "fetch_pvgis_tmy",
]

#: Provider column name -> canonical name, keyed by source.
#:
#: PVGIS is empty because ``pvlib`` has already done the renaming; it is present so the
#: source is a known one rather than an error, and as the place a raw-CSV mapping would
#: go if this package ever ingested one.
SOURCE_RENAMES: dict[str, dict[str, str]] = {
    "pvgis": {},
    "open_meteo": {
        "temperature_2m": "temp_air",
        "windspeed_10m": "wind_speed",
        "wind_speed_10m": "wind_speed",
        "shortwave_radiation": "poa_global",
    },
}

#: Which irradiance component each choice collects, and whether PVGIS must be asked for
#: components to produce it.
_PVGIS_IRRADIANCE = {
    "global": ("poa_global", False),
    "direct": ("poa_direct", True),
    "sky_diffuse": ("poa_sky_diffuse", True),
    "ground_diffuse": ("poa_ground_diffuse", True),
}

#: Decimal places coordinates are compared to when matching a cache. ~11 m: finer than
#: any provider's grid, coarser than float noise, so 35.3387 and 35.33870000001 are the
#: same site. A false miss is not a correctness bug, but it does cost a silent
#: re-download.
_COORD_DP = 4


class CacheMismatchError(Exception):
    """A cached dataset does not answer the request that was made of it.

    Raised rather than silently refetching, because the caller chose the path: a mismatch
    means a Paris request was pointed at a Heraklion file, which is a mistake to surface,
    not a stale entry to evict. Overwriting would destroy a record that may have taken a
    long download to produce -- so repurposing a path is spelled ``force_refetch=True``.
    """


def validate_support(met_data: pd.DataFrame) -> None:
    """
    Check every registered column lies inside its spec's physical support.

    Parameters
    ----------
    met_data : pd.DataFrame
        A canonical frame.

    Raises
    ------
    ValueError
        Naming the column, the offending extreme, and the bound it violates.

    Notes
    -----
    **This is an opt-in hard check, not the ingestion rule.**
    :class:`~meteosynth.dataset.MetDataset` *clips* out-of-support values and reports the
    count instead, because real station records routinely carry small negative irradiance
    at night from sensor noise, and refusing a 19-year record over four of them blocks
    real work. Call this when you would rather be stopped than repaired.

    Validation is **one-sided by nature** either way: support is a necessary condition,
    not a sufficient one. 20 degC mislabelled from 20 degF is 20 either way and passes
    cleanly. This catches gross errors that happen to cross a bound; it is not a unit
    check, and unit *conversion* is deliberately not attempted here.
    """
    for col in met_data.columns:
        if col not in registered():
            continue
        spec = get_spec(col)
        lower, upper = spec.support
        values = met_data[col].dropna()
        if values.empty:
            continue

        if lower is not None and values.min() < lower:
            raise ValueError(
                f"column {col!r} has minimum {values.min():.4g}, below its physical "
                f"lower bound of {lower:.4g} ({spec.long_name}, expected units "
                f"{spec.units!r}). Check the source's units."
            )
        if upper is not None and values.max() > upper:
            raise ValueError(
                f"column {col!r} has maximum {values.max():.4g}, above its physical "
                f"upper bound of {upper:.4g} ({spec.long_name}, expected units "
                f"{spec.units!r}). Check the source's units."
            )


def normalise(met_data: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    Rename a provider's columns to canonical names.

    Parameters
    ----------
    met_data : pd.DataFrame
        Raw frame as the provider supplied it.
    source : str
        Key into :data:`SOURCE_RENAMES`.

    Returns
    -------
    pd.DataFrame
        A renamed copy. Column *selection* and schema validation are left to
        :class:`~meteosynth.dataset.MetDataset`, which trims to the registered set and
        enforces the schema on construction -- for every route in, not only this one.

    Raises
    ------
    KeyError
        If ``source`` is unknown. An unknown source is an error rather than a silent
        no-op, since passing data through unrenamed would look like it worked.
    """
    if source not in SOURCE_RENAMES:
        raise KeyError(
            f"unknown source {source!r}. Known: {tuple(sorted(SOURCE_RENAMES))}."
        )

    return met_data.rename(columns=SOURCE_RENAMES[source])


def _add_index_cols(data: pd.DataFrame) -> pd.DataFrame:
    """Derive ``year``/``month``/``day``/``hour`` from a DatetimeIndex."""
    data = data.copy()
    data["year"] = data.index.year
    data["month"] = data.index.month
    data["day"] = data.index.day
    data["hour"] = data.index.hour
    return data


def _today() -> str:
    """Today's date in UTC, ISO-8601."""
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _package_version() -> Optional[str]:
    from . import __version__

    return __version__


def _check_cache_path(cache: Union[str, pathlib.Path]) -> pathlib.Path:
    """A cache is parquet, because only parquet carries provenance and exact dtypes."""
    cache = pathlib.Path(cache)
    if cache.suffix.lower() != ".parquet":
        raise ValueError(
            f"cache must be a .parquet path, got {cache.name!r}. A cache has to carry "
            f"provenance and exact dtypes so a later request can be matched against it, "
            f"and CSV carries neither -- use MetDataset.to_csv() for interchange."
        )
    return cache


def _mismatches(cached: Provenance, wanted: Provenance) -> List[str]:
    """Every field on which a cached record fails to answer the request."""
    reasons: List[str] = []

    if cached.source != wanted.source:
        reasons.append(f"  source    {cached.source!r} != requested {wanted.source!r}")

    def _coord(value):
        return None if value is None else round(float(value), _COORD_DP)

    if (_coord(cached.latitude), _coord(cached.longitude)) != (
        _coord(wanted.latitude),
        _coord(wanted.longitude),
    ):
        reasons.append(
            f"  site      ({cached.latitude}, {cached.longitude}) != requested "
            f"({wanted.latitude}, {wanted.longitude})"
        )

    if (cached.start_year, cached.end_year) != (wanted.start_year, wanted.end_year):
        reasons.append(
            f"  period    {cached.start_year}-{cached.end_year} != requested "
            f"{wanted.start_year}-{wanted.end_year}"
        )

    return reasons


def _use_cache(
    cache: pathlib.Path, wanted: Provenance, column: Optional[str]
) -> Optional[MetDataset]:
    """Return the cached dataset if it answers this request, else raise.

    ``None`` means "there is no cache to consider". Anything present either matches or is
    an error: a file the caller pointed at is an assertion about what they want.
    """
    if not cache.exists():
        return None

    dataset = MetDataset.load(cache)
    reasons = _mismatches(dataset.provenance, wanted)

    if column is not None and column not in dataset.met_data.columns:
        reasons.append(
            f"  columns   {list(dataset.variables)} does not hold requested {column!r}"
        )

    if reasons:
        raise CacheMismatchError(
            f"{cache} does not answer this request:\n"
            + "\n".join(reasons)
            + "\nPass force_refetch=True to overwrite it, or use a different path."
        )

    logging.info("Reading cached dataset from %s", cache)
    return dataset


def fetch_pvgis(
    latitude: float,
    longitude: float,
    start: int,
    end: int,
    irradiance: str = "global",
    cache: Optional[Union[str, pathlib.Path]] = None,
    force_refetch: bool = False,
    site: Optional[str] = None,
    **kwargs,
) -> MetDataset:
    """
    Fetch hourly PVGIS data as a :class:`~meteosynth.dataset.MetDataset`.

    Parameters
    ----------
    latitude, longitude : float
        Site coordinates.
    start, end : int
        First and last year to fetch.
    irradiance : str, optional
        Which irradiance component to collect: ``"global"`` (default), ``"direct"``,
        ``"sky_diffuse"`` or ``"ground_diffuse"``. PVGIS returns *either* global *or*
        the three components depending on one flag, so global is the default and the
        components are opted into.

        The emitted column keeps its specific name -- ``poa_global`` or ``poa_direct``
        -- so **the name records the choice**.
    cache : str or Path, optional
        A ``.parquet`` path. If it exists and its provenance matches this request it is
        read instead of the network; if it exists and does not match,
        :exc:`CacheMismatchError` is raised. Collection is slow and networked; modelling
        is not, and the two are often run at different times.
    force_refetch : bool, optional
        Ignore any existing cache, fetch, and overwrite it. The explicit way to repurpose
        a cache path.
    site : str, optional
        Free label recorded in provenance, e.g. ``"heraklion"``. Never inferred from the
        coordinates.
    **kwargs
        Forwarded to :func:`pvlib.iotools.get_pvgis_hourly`.

    Returns
    -------
    MetDataset
        Carrying :data:`~meteosynth.constants.INDEX_COLS`, the chosen irradiance column,
        ``temp_air`` and ``wind_speed``, with provenance filled in.

    Raises
    ------
    ValueError
        If ``irradiance`` is not one of the four components, or ``cache`` is not a
        ``.parquet`` path.
    CacheMismatchError
        If a cache exists at ``cache`` but holds a different site, period or source.

    Notes
    -----
    Requires ``pvlib``, imported lazily so that the rest of the package does not depend
    on it.
    """
    if irradiance not in _PVGIS_IRRADIANCE:
        raise ValueError(
            f"irradiance must be one of {tuple(_PVGIS_IRRADIANCE)}, got {irradiance!r}"
        )
    column, needs_components = _PVGIS_IRRADIANCE[irradiance]

    wanted = Provenance(
        source="pvgis_hourly",
        site=site,
        latitude=latitude,
        longitude=longitude,
        start_year=start,
        end_year=end,
        fetched=_today(),
        meteosynth_version=_package_version(),
    )

    if cache is not None:
        cache = _check_cache_path(cache)
        if not force_refetch:
            cached = _use_cache(cache, wanted, column)
            if cached is not None:
                return cached

    from pvlib.iotools import get_pvgis_hourly

    logging.info(
        "Fetching PVGIS hourly data for (%.4f, %.4f), %d-%d, irradiance=%s",
        latitude, longitude, start, end, irradiance,
    )
    # Index rather than unpack, for the same reason fetch_pvgis_tmy does: pvlib has
    # changed the arity of this reader across versions, and `data, _ = ...` silently
    # pins us to whichever one is installed today.
    result = get_pvgis_hourly(
        latitude=latitude,
        longitude=longitude,
        start=start,
        end=end,
        components=needs_components,
        **kwargs,
    )
    data = result[0]

    frame = normalise(_add_index_cols(data), source="pvgis")

    if column not in frame.columns:
        raise ValueError(
            f"PVGIS returned no {column!r} column (got {list(frame.columns)}). "
            f"This is a mismatch between irradiance={irradiance!r} and what the "
            f"provider supplied."
        )

    # Drop the DatetimeIndex: the calendar is carried by INDEX_COLS, and a canonical
    # record that also depended on its index would not survive a round-trip to disk.
    frame = frame.loc[:, [column, "temp_air", "wind_speed", *INDEX_COLS]].reset_index(
        drop=True
    )

    dataset = MetDataset(frame, provenance=wanted)

    if cache is not None:
        dataset.save(cache)
        logging.info("Cached dataset to %s", cache)

    return dataset


def fetch_pvgis_tmy(
    latitude: float,
    longitude: float,
    coerce_year: Optional[int] = None,
    cache: Optional[Union[str, pathlib.Path]] = None,
    force_refetch: bool = False,
    site: Optional[str] = None,
    **kwargs,
) -> MetDataset:
    """
    Fetch a PVGIS Typical Meteorological Year as a
    :class:`~meteosynth.dataset.MetDataset`.

    Parameters
    ----------
    latitude, longitude : float
        Site coordinates.
    coerce_year : int, optional
        Force every timestamp into this year. Defaults to ``None``, matching
        ``pvlib`` -- see the note below on what that means for the ``year`` column.
    cache : str or Path, optional
        A ``.parquet`` path, matched against this request exactly as in
        :func:`fetch_pvgis`.
    force_refetch : bool, optional
        Ignore any existing cache, fetch, and overwrite it.
    site : str, optional
        Free label recorded in provenance.
    **kwargs
        Forwarded to :func:`pvlib.iotools.get_pvgis_tmy`.

    Returns
    -------
    MetDataset
        Carrying :data:`~meteosynth.constants.INDEX_COLS` and every *registered* column
        PVGIS supplied -- ordinarily ``ghi``, ``dni``, ``dhi``, ``temp_air`` and
        ``wind_speed``.

    Raises
    ------
    ValueError
        If the provider returns no registered column, or ``cache`` is not a ``.parquet``
        path.
    CacheMismatchError
        If a cache exists at ``cache`` but holds a different site or source.

    Notes
    -----
    **The irradiance is horizontal, not plane-of-array.** TMY supplies ``ghi`` / ``dni``
    / ``dhi``, which is a different quantity from the ``poa_*`` columns
    :func:`fetch_pvgis` returns -- they differ by however much the array is tilted.
    Transposing onto a plane is the caller's job; this function does not do it, and the
    column names are what keep the two from being confused.

    **A TMY has no single year**, so its provenance records no period at all rather than
    a fabricated one. Each month is taken from a different real year, so with the default
    ``coerce_year=None`` the ``year`` column jumps between months. Measured on Heraklion
    (35.34, 25.14), the twelve months came from nine distinct years::

        month  1     2     3     4     5     6     7     8     9    10    11    12
        year  2019  2015  2017  2008  2014  2020  2010  2006  2020  2017  2014  2009

    That is harmless for the rolling-window training this package does -- it pools by
    month and day, never by year -- but it makes
    :meth:`~meteosynth.dataset.MetDataset.describe_time_range` report a span that looks
    wrong. Pass a year for a clean single-year calendar.

    Rewriting the year silently was considered and rejected: it would destroy the record
    of which real year each month came from, and this package declares rather than
    infers.

    Unlike :func:`fetch_pvgis` there is no component flag to choose -- TMY returns all
    three irradiance columns at once, so every registered column is kept and PVGIS's
    unregistered extras (``pressure``, ``wind_direction``, ``IR(h)``, ...) fall out by
    rule.

    Requires ``pvlib``, imported lazily so the rest of the package does not depend on it.
    """
    wanted = Provenance(
        source="pvgis_tmy",
        site=site,
        latitude=latitude,
        longitude=longitude,
        fetched=_today(),
        meteosynth_version=_package_version(),
    )

    if cache is not None:
        cache = _check_cache_path(cache)
        if not force_refetch:
            cached = _use_cache(cache, wanted, column=None)
            if cached is not None:
                return cached

    from pvlib.iotools import get_pvgis_tmy

    logging.info(
        "Fetching PVGIS TMY for (%.4f, %.4f), coerce_year=%s",
        latitude, longitude, coerce_year,
    )
    # Index rather than unpack. pvlib has returned (data, months, inputs, metadata),
    # (data, inputs, metadata) and (data, metadata) across versions; indexing works
    # against every one of them and needs no version check.
    result = get_pvgis_tmy(
        latitude=latitude,
        longitude=longitude,
        coerce_year=coerce_year,
        **kwargs,
    )
    data = result[0]

    frame = normalise(_add_index_cols(data), source="pvgis")

    keep = [col for col in frame.columns if col in registered()]
    if not keep:
        raise ValueError(
            f"PVGIS TMY returned no registered columns (got {list(frame.columns)}). "
            f"Registered: {registered()}."
        )

    frame = frame.loc[:, [*keep, *INDEX_COLS]].reset_index(drop=True)

    dataset = MetDataset(frame, provenance=wanted)

    if cache is not None:
        dataset.save(cache)
        logging.info("Cached TMY dataset to %s", cache)

    return dataset
