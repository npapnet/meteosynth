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
import re
import warnings
from dataclasses import replace
from typing import List, Optional, Union

import pandas as pd

from . import store as _store
from .store import COORD_DP, POA_COMPONENTS
from .constants import INDEX_COLS
from .dataset import MetDataset
from .provenance import Provenance
from .variables import get_spec, registered

__all__ = [
    "SOURCE_RENAMES",
    "CacheMismatchError",
    "normalise",
    "validate_support",
    "probe_year_range",
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

#: Decimal places coordinates are compared to when matching a cache. Defined in
#: :mod:`meteosynth.store` so that validating a named file and discovering an unnamed one
#: cannot drift apart on what counts as the same site.
_COORD_DP = COORD_DP


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

    if not _covers_period(cached, wanted):
        reasons.append(
            f"  period    {cached.start_year}-{cached.end_year} does not contain "
            f"requested {wanted.start_year}-{wanted.end_year}"
        )

    return reasons


def _covers_period(cached: Provenance, wanted: Provenance) -> bool:
    """Whether a cached record's period **contains** the requested one.

    Containment rather than equality, because a 2005-2023 record genuinely does answer a
    2010-2020 question -- :meth:`~meteosynth.dataset.MetDataset.get_period_subset` cuts
    it exactly, and that is what lets one download per site serve every training period.
    A record that merely *overlaps* is still a mismatch: returning the intersection would
    answer a narrower question than the one asked, without saying so.

    Delegates to :func:`meteosynth.store.period_contains` so that a file this package
    *finds* and a file it is *handed* are judged wide enough by the same rule.
    """
    return _store.period_contains(
        cached.start_year, cached.end_year, wanted.start_year, wanted.end_year
    )


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

    if not _holds_column(dataset, column):
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

    # Wider than asked for is a match, not an answer: narrow it, so the caller gets the
    # period they requested and its provenance says so.
    if (
        wanted.start_year is not None
        and (dataset.provenance.start_year, dataset.provenance.end_year)
        != (wanted.start_year, wanted.end_year)
    ):
        return dataset.get_period_subset(
            wanted.start_year, wanted.end_year, origin=cache.name
        )
    return dataset


def _holds_column(dataset: MetDataset, column: Optional[str]) -> bool:
    """Whether a dataset holds the requested quantity, or can produce it.

    Asymmetric on purpose: the three POA components sum to ``poa_global``, so a record
    holding them answers a request for the total -- but the total can never be taken
    apart into components, so the reverse does not hold. Mirrors
    :meth:`meteosynth.store.StoredRecord.holds`, which applies the same rule to a footer.
    """
    if column is None:
        return True
    if column in dataset.met_data.columns:
        return True
    return column == "poa_global" and all(
        c in dataset.met_data.columns for c in POA_COMPONENTS
    )


#: Matches the year range PVGIS names in its own error message. Asking for an impossible
#: year is a far more reliable probe than bisecting: one failed request gives both bounds.
_RANGE_RE = re.compile(r"between\s+(\d{4})\s+and\s+(\d{4})")


def probe_year_range(latitude: float, longitude: float, **kwargs) -> tuple:
    """
    Ask PVGIS what year range it serves for a site.

    Deliberately makes a request that *should* fail -- year 1900 -- because the error
    message names both bounds. One round trip, no bisection, and it cannot go stale the
    way a hard-coded range does when the provider extends its coverage.

    Parameters
    ----------
    latitude, longitude : float
        Site coordinates.

    Returns
    -------
    tuple of (int, int)
        First and last year available.

    Raises
    ------
    RuntimeError
        If PVGIS answers with something this cannot parse. Guessing a range here would
        silently truncate a record, so it refuses instead.
    """
    from pvlib.iotools import get_pvgis_hourly

    logging.info("Probing PVGIS for the year range at (%.4f, %.4f)", latitude, longitude)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            get_pvgis_hourly(
                latitude=latitude, longitude=longitude, start=1900, end=1900,
                components=False, **kwargs,
            )
    except Exception as exc:  # noqa: BLE001 -- any failure carries the message we want
        match = _RANGE_RE.search(str(exc))
        if match:
            first, last = int(match.group(1)), int(match.group(2))
            logging.info("PVGIS serves %d-%d (%d years)", first, last, last - first + 1)
            return first, last
        raise RuntimeError(
            f"could not read a year range from PVGIS's reply: {str(exc)[:200]}. "
            f"Pass start= and end= explicitly, or full_range=False."
        ) from exc

    raise RuntimeError(  # pragma: no cover -- PVGIS has never served year 1900
        "PVGIS accepted a request for year 1900, so its range could not be probed. "
        "Pass start= and end= explicitly, or full_range=False."
    )


def _coordinates_for_site(
    site: str, directory: Union[str, pathlib.Path], source: str
) -> tuple:
    """Recover a site's coordinates from a record already cached under that label.

    What makes ``site="heraklion"`` work on every call after the first. The package does
    no geocoding -- a name means whatever the user bound it to, and the binding is the
    first fetch.
    """
    for record in _store.scan(directory):
        if (
            record.provenance.source == source
            and (record.provenance.site or "").strip().lower() == site.strip().lower()
            and record.provenance.latitude is not None
        ):
            return record.provenance.latitude, record.provenance.longitude

    raise ValueError(
        f"no cached {source} record is labelled {site!r} in {directory}, so its "
        f"coordinates are unknown. Give latitude and longitude once, with site={site!r}, "
        f"and the label will resolve on its own from then on."
    )


def fetch_pvgis(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    irradiance: str = "global",
    cache: Union[None, bool, str, pathlib.Path] = None,
    data_dir: Optional[Union[str, pathlib.Path]] = None,
    force_refetch: bool = False,
    site: Optional[str] = None,
    full_range: bool = True,
    components: bool = True,
    **kwargs,
) -> MetDataset:
    """
    Fetch hourly PVGIS data as a :class:`~meteosynth.dataset.MetDataset`.

    **Collect once per site, then work locally.** By default this downloads the widest
    range PVGIS serves, keeps every column it returns, and caches the result -- so a
    later request for any narrower period or any irradiance component is answered from
    disk. ``start``/``end`` select a *view* of that record, not the size of the download.

    Parameters
    ----------
    latitude, longitude : float, optional
        Site coordinates. Optional only when ``site`` names a record already cached, from
        which they are recovered.
    start, end : int, optional
        Inclusive years to **return**. Omit for everything the record holds. The download
        is governed by ``full_range``, not by these.
    irradiance : str, optional
        Which irradiance quantity must be present: ``"global"`` (default), ``"direct"``,
        ``"sky_diffuse"`` or ``"ground_diffuse"``. Each keeps its specific column name,
        so **the name records the quantity**.
    cache : path, ``None`` or ``False``, optional
        ``None`` (default) stores under ``data_dir`` and finds an existing record there by
        provenance. A path names one file explicitly, which is then required to answer the
        request or raise. ``False`` disables the store in both directions -- nothing is
        read, nothing is written.
    data_dir : str or Path, optional
        The project's data store. Defaults to
        :func:`meteosynth.store.default_data_dir` -- ``./data`` under the working
        directory. Ignored when ``cache`` names a file or is ``False``.
    force_refetch : bool, optional
        Ignore any cache, fetch, and overwrite. The explicit way to repurpose a path.
    site : str, optional
        Free label recorded in provenance, e.g. ``"heraklion"``. Never inferred from the
        coordinates -- but once bound, it resolves them.
    full_range : bool, optional
        Download everything PVGIS serves (default), discovered by
        :func:`probe_year_range`. ``False`` downloads only ``start``-``end``, which then
        become required.
    components : bool, optional
        Ask PVGIS for the three plane-of-array components (default) rather than its own
        global total. See the note below -- this is what makes one file per site enough.
    **kwargs
        Forwarded to :func:`pvlib.iotools.get_pvgis_hourly`.

    Returns
    -------
    MetDataset
        :data:`~meteosynth.constants.INDEX_COLS`, every irradiance column the provider
        supplied, ``temp_air`` and ``wind_speed``, with provenance filled in.

    Raises
    ------
    ValueError
        For an unknown ``irradiance``, a non-parquet ``cache`` path, a request the
        provider cannot satisfy, or missing coordinates that no cached label supplies.
    CacheMismatchError
        If a named cache file holds a different site, period or source.
    AmbiguousRecordError
        If several records in the default cache answer the request. Name one.

    Notes
    -----
    **Why components rather than the provider's own total.** PVGIS returns *either*
    ``poa_global`` *or* the three components, never both, so a per-component choice at
    fetch time means a separate download and a separate file for each. Collecting the
    components instead serves every choice from one record, because the total is
    recoverable by summation -- measured on Heraklion 2010 against a fetched
    ``poa_global``, the maximum difference over 8760 hours is **0.01 W/m2**, which is
    PVGIS's own two-decimal rounding.

    A summed total is therefore *derived*, and says so in
    :attr:`~meteosynth.provenance.Provenance.notes`. Pass ``components=False`` for the
    provider's own ``poa_global`` and nothing else.

    Requires ``pvlib``, imported lazily so that the rest of the package does not depend
    on it.

    Examples
    --------
    >>> fetch_pvgis(35.3387, 25.1442, site="heraklion")     # doctest: +SKIP
    >>> fetch_pvgis(site="heraklion", start=2010, end=2020)  # doctest: +SKIP
    """
    if irradiance not in _PVGIS_IRRADIANCE:
        raise ValueError(
            f"irradiance must be one of {tuple(_PVGIS_IRRADIANCE)}, got {irradiance!r}"
        )
    column = _PVGIS_IRRADIANCE[irradiance][0]

    if not components and irradiance != "global":
        raise ValueError(
            f"irradiance={irradiance!r} needs components=True: PVGIS returns either the "
            f"global total or the three components, never both."
        )
    if (start is None) != (end is None):
        raise ValueError(
            f"give both start and end or neither, got start={start}, end={end}"
        )

    explicit_path = cache not in (None, False)
    cache_dir = None
    if explicit_path:
        cache_path = _check_cache_path(cache)
    elif cache is None:
        cache_dir = (
            _store.default_data_dir() if data_dir is None else pathlib.Path(data_dir)
        )
        cache_path = None
    else:
        cache_path = None

    if latitude is None or longitude is None:
        if site is None:
            raise ValueError(
                "give latitude and longitude, or a site= label already cached under them"
            )
        directory = cache_path.parent if explicit_path else cache_dir
        if directory is None:
            raise ValueError(
                "site= can only resolve coordinates from a cache, and cache=False "
                "disabled it. Give latitude and longitude."
            )
        latitude, longitude = _coordinates_for_site(site, directory, "pvgis_hourly")

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

    if not force_refetch and cache is not False:
        if not explicit_path:
            # Nothing was named, so find it. Ambiguity raises rather than choosing --
            # which record a result was trained on is part of the result.
            found = _store.resolve(
                cache_dir,
                source="pvgis_hourly",
                site=site,
                latitude=latitude,
                longitude=longitude,
                start=start,
                end=end,
                column=column,
            )
            if found is not None:
                cached = _use_cache(found, wanted, column)
                if cached is not None:
                    return cached
        else:
            cached = _use_cache(cache_path, wanted, column)
            if cached is not None:
                return cached

    if full_range:
        first, last = probe_year_range(latitude, longitude, **kwargs)
        if start is not None and (start < first or end > last):
            raise ValueError(
                f"PVGIS serves {first}-{last} at ({latitude}, {longitude}), which does "
                f"not contain the requested {start}-{end}."
            )
    elif start is None:
        raise ValueError("full_range=False needs an explicit start and end")
    else:
        first, last = start, end

    from pvlib.iotools import get_pvgis_hourly

    logging.info(
        "Fetching PVGIS hourly data for (%.4f, %.4f), %d-%d, components=%s",
        latitude, longitude, first, last, components,
    )
    # Index rather than unpack, for the same reason fetch_pvgis_tmy does: pvlib has
    # changed the arity of this reader across versions, and `data, _ = ...` silently
    # pins us to whichever one is installed today.
    result = get_pvgis_hourly(
        latitude=latitude,
        longitude=longitude,
        start=first,
        end=last,
        components=components,
        **kwargs,
    )
    data = result[0]

    frame = normalise(_add_index_cols(data), source="pvgis")
    frame, derived = _add_summed_global(frame)

    if column not in frame.columns:
        raise ValueError(
            f"PVGIS returned no {column!r} column (got {list(frame.columns)}). "
            f"This is a mismatch between irradiance={irradiance!r} and what the "
            f"provider supplied."
        )

    # Keep every registered quantity the provider gave, so one record answers every
    # later question about this site. Drop the DatetimeIndex: the calendar is carried by
    # INDEX_COLS, and a canonical record that also depended on its index would not
    # survive a round-trip to disk.
    keep = [c for c in frame.columns if c in registered() or c in INDEX_COLS]
    frame = frame.loc[:, keep].reset_index(drop=True)

    collected = replace(
        wanted,
        start_year=first,
        end_year=last,
        notes="poa_global summed from the three POA components" if derived else None,
    )
    dataset = MetDataset(frame, provenance=collected)

    origin = None
    if cache is not False:
        target = cache_path if explicit_path else _store.record_path_for(collected, cache_dir)
        dataset.save(target)
        logging.info("Cached dataset to %s", target)
        origin = target.name

    # Narrow with the same origin the warm path uses, so that a cold fetch and the
    # cached fetch that follows it produce equal datasets rather than ones differing
    # only in how they describe where they came from.
    if start is not None and (first, last) != (start, end):
        return dataset.get_period_subset(start, end, origin=origin)
    return dataset


def _add_summed_global(frame: pd.DataFrame) -> tuple:
    """Add ``poa_global`` as the sum of its components, when only the components exist.

    Returns the frame and whether anything was derived, so provenance can say so. The
    reconstruction is exact for PVGIS to within its own two-decimal rounding, but "exact
    enough" is a claim about a provider rather than about arithmetic -- so the record
    carries the fact rather than relying on everyone remembering it.
    """
    if "poa_global" in frame.columns:
        return frame, False
    if not all(c in frame.columns for c in POA_COMPONENTS):
        return frame, False

    frame = frame.copy()
    frame["poa_global"] = sum(frame[c] for c in POA_COMPONENTS)
    return frame, True


def fetch_pvgis_tmy(
    latitude: float,
    longitude: float,
    coerce_year: Optional[int] = None,
    cache: Union[None, bool, str, pathlib.Path] = None,
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
        :func:`fetch_pvgis`. **Caching is opt-in here**, unlike :func:`fetch_pvgis` --
        see the note below.
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

    **Caching stays opt-in here, and that asymmetry is deliberate.**
    :func:`fetch_pvgis` can cache by default because a record's identity -- site, period,
    columns -- is fully written into its :class:`~meteosynth.provenance.Provenance`, so a
    file found by searching can be checked against the request. A TMY's identity is
    **not**: ``coerce_year`` and ``roll_utc_offset`` change what comes back (pvlib's
    ``_coerce_and_roll_tmy`` rewrites the year *and can roll the series*), and neither is
    a provenance field. A discovered TMY could therefore answer a different question than
    the one asked, silently -- which is the failure this whole format exists to prevent.
    So a TMY is cached only where the caller names a file, and that file's own contents
    are what say which encoding it holds.

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

    # Caching here stays **opt-in**, unlike fetch_pvgis. See the docstring: a TMY's
    # identity is not fully expressible in provenance, so a record found by searching
    # could answer a different question than the one asked.
    if cache not in (None, False):
        cache = _check_cache_path(cache)
        if not force_refetch:
            cached = _use_cache(cache, wanted, column=None)
            if cached is not None:
                return cached
    else:
        cache = None

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
