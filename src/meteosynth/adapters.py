"""
Optional helpers for collecting data from providers.

Adapters are an **auxiliary tool for getting data in easily**, not a required layer.
The contract between them and the rest of the package is an ordinary canonical
DataFrame, which serves both use cases without forcing either through the other's path::

    # A -- no data for the site; fetch it.
    df  = fetch_pvgis(48.86, 2.35, 2011, 2012, cache="data/paris.csv")
    mdp = MetDataProcessor(df)

    # B -- the user already has data. No adapter involved at all.
    register("rel_humidity", VariableSpec((0.0, 100.0), "%"))
    mdp = MetDataProcessor(my_df)

A file is a convenience for case A, where collection is slow and networked. It is never
a required step, so there is no on-disk schema to design or version, and no metadata
sidecar: the **column name is the provenance**. ``poa_global`` and ``poa_direct`` are
different columns, and a frame always says which one it holds.

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

import logging
import pathlib
from typing import Optional, Union

import pandas as pd

from .constants import INDEX_COLS
from .variables import get_spec, registered

__all__ = ["SOURCE_RENAMES", "normalise", "validate_support", "fetch_pvgis"]

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


def validate_support(met_data: pd.DataFrame) -> None:
    """
    Check every registered column lies inside its spec's physical support.

    This is what turns a class of silent ingestion bug -- kW/m2 read as W/m2, kelvin
    read as degC -- into an error at the boundary rather than a plausible-looking
    synthetic series months later.

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
    Validation is **one-sided by nature**: support is a necessary condition, not a
    sufficient one. 20 degC mislabelled from 20 degF is 20 either way and passes
    cleanly. This catches the gross errors, which are the ones that reach production;
    it is not a unit check, and unit *conversion* is deliberately not attempted here.
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
    Rename a provider's columns to canonical names, then validate the result.

    Parameters
    ----------
    met_data : pd.DataFrame
        Raw frame as the provider supplied it.
    source : str
        Key into :data:`SOURCE_RENAMES`.

    Returns
    -------
    pd.DataFrame
        A renamed copy. Column *selection* is left to
        :class:`~meteosynth.met_data_processor.MetDataProcessor`, which trims to the
        registered set on ingestion.

    Raises
    ------
    KeyError
        If ``source`` is unknown. An unknown source is an error rather than a silent
        no-op, since passing data through unrenamed would look like it worked.
    ValueError
        If the renamed data violates a spec's support.
    """
    if source not in SOURCE_RENAMES:
        raise KeyError(
            f"unknown source {source!r}. Known: {tuple(sorted(SOURCE_RENAMES))}."
        )

    renamed = met_data.rename(columns=SOURCE_RENAMES[source])
    validate_support(renamed)
    return renamed


def _add_index_cols(data: pd.DataFrame) -> pd.DataFrame:
    """Derive ``year``/``month``/``day``/``hour`` from a DatetimeIndex."""
    data = data.copy()
    data["year"] = data.index.year
    data["month"] = data.index.month
    data["day"] = data.index.day
    data["hour"] = data.index.hour
    return data


def fetch_pvgis(
    latitude: float,
    longitude: float,
    start: int,
    end: int,
    irradiance: str = "global",
    cache: Optional[Union[str, pathlib.Path]] = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch hourly PVGIS data as a canonical frame.

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
        -- so **the name records the choice** and no metadata is needed to know what a
        frame holds.
    cache : str or Path, optional
        If given and the file exists, read from it instead of the network. If given and
        it does not, write the fetched frame there. Collection is slow and networked;
        modelling is not, and the two are often run at different times.
    **kwargs
        Forwarded to :func:`pvlib.iotools.get_pvgis_hourly`.

    Returns
    -------
    pd.DataFrame
        Canonical frame with :data:`~meteosynth.constants.INDEX_COLS`, the chosen
        irradiance column, ``temp_air`` and ``wind_speed``.

    Raises
    ------
    ValueError
        If ``irradiance`` is not one of the four components, or the fetched data
        violates a spec's support.

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

    if cache is not None:
        cache = pathlib.Path(cache)
        if cache.exists():
            logging.info("Reading cached PVGIS data from %s", cache)
            frame = _read_cache(cache)
            validate_support(frame)
            return frame

    from pvlib.iotools import get_pvgis_hourly

    logging.info(
        "Fetching PVGIS hourly data for (%.4f, %.4f), %d-%d, irradiance=%s",
        latitude, longitude, start, end, irradiance,
    )
    data, _ = get_pvgis_hourly(
        latitude=latitude,
        longitude=longitude,
        start=start,
        end=end,
        components=needs_components,
        **kwargs,
    )

    frame = normalise(_add_index_cols(data), source="pvgis")

    if column not in frame.columns:
        raise ValueError(
            f"PVGIS returned no {column!r} column (got {list(frame.columns)}). "
            f"This is a mismatch between irradiance={irradiance!r} and what the "
            f"provider supplied."
        )

    # Drop the DatetimeIndex: the calendar is carried by INDEX_COLS, and a canonical
    # frame that also depended on its index would not survive a cache round-trip
    # through CSV.
    frame = frame.loc[:, [column, "temp_air", "wind_speed", *INDEX_COLS]].reset_index(
        drop=True
    )

    if cache is not None:
        _write_cache(frame, cache)
        logging.info("Cached PVGIS data to %s", cache)

    return frame


def _read_cache(path: pathlib.Path) -> pd.DataFrame:
    """Read a cached canonical frame, by extension."""
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _write_cache(frame: pd.DataFrame, path: pathlib.Path) -> None:
    """Write a canonical frame, by extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        frame.to_excel(path, index=False)
    elif path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)
