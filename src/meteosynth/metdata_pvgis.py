# -*- coding: utf-8 -*-
"""
PVGIS data-retrieval helpers.

Thin wrappers around :mod:`pvlib.iotools` for fetching hourly and Typical
Meteorological Year (TMY) data from the PVGIS (Photovoltaic Geographical
Information System) service, plus small utilities to prepare the returned
frames for the rest of :mod:`meteosynth`.

Importing this module has **no side effects** (no network calls, no file
writes, no plots). Run it as a script (``python -m meteosynth.metdata_pvgis``)
to execute the small demonstration in ``__main__``.
"""

import pathlib
from typing import Optional, Tuple

import pandas as pd
from pvlib.iotools import get_pvgis_hourly, get_pvgis_tmy

# Default cache location for downloaded hourly data.
DATA_DIR = pathlib.Path("data")
XLSX_FNAME = DATA_DIR / "pvgis_hourly_data.xlsx"

# A couple of convenience example sites.
SITE_CRETE = {"latitude": 35.3387, "longitude": 25.1442}
SITE_PARIS = {"latitude": 48.8566, "longitude": 2.3522}


def add_time_columns(data: pd.DataFrame) -> pd.DataFrame:
    """
    Add ``year``, ``month``, ``day`` and ``hour`` columns from a datetime index.

    Parameters
    ----------
    data : pd.DataFrame
        A frame indexed by a :class:`~pandas.DatetimeIndex` (as returned by
        :func:`pvlib.iotools.get_pvgis_hourly`).

    Returns
    -------
    pd.DataFrame
        The same frame with the four calendar columns added (in place and
        returned for convenience).
    """
    data["year"] = data.index.year
    data["month"] = data.index.month
    data["day"] = data.index.day
    data["hour"] = data.index.hour
    return data


def fetch_pvgis_hourly(
    latitude: float,
    longitude: float,
    start_year: int,
    end_year: int,
    usehorizon: bool = True,
    components: bool = True,
) -> pd.DataFrame:
    """
    Fetch hourly irradiance / weather data from PVGIS for a site.

    Parameters
    ----------
    latitude, longitude : float
        Site coordinates in decimal degrees.
    start_year, end_year : int
        Inclusive range of years to retrieve.
    usehorizon : bool
        Whether to account for the local horizon (default ``True``).
    components : bool
        Whether to return separate irradiance components (default ``True``).

    Returns
    -------
    pd.DataFrame
        Hourly data with ``year``, ``month``, ``day`` and ``hour`` columns
        added.
    """
    data, _inputs, _metadata = get_pvgis_hourly(
        latitude=latitude,
        longitude=longitude,
        start=start_year,
        end=end_year,
        usehorizon=usehorizon,
        outputformat="json",
        components=components,
    )
    return add_time_columns(data)


def fetch_pvgis_tmy(
    latitude: float,
    longitude: float,
    coerce_year: Optional[int] = None,
) -> Tuple[pd.DataFrame, dict]:
    """
    Fetch a Typical Meteorological Year (TMY) dataset from PVGIS.

    Parameters
    ----------
    latitude, longitude : float
        Site coordinates in decimal degrees.
    coerce_year : int, optional
        If given, all timestamps are coerced to this year.

    Returns
    -------
    tuple of (pd.DataFrame, dict)
        The TMY weather frame and the associated site metadata.
    """
    tmy_data, _months, _inputs, tmy_meta = get_pvgis_tmy(
        latitude,
        longitude,
        coerce_year=coerce_year,
        outputformat="json",
    )
    return tmy_data, tmy_meta


def save_hourly(data: pd.DataFrame, path: pathlib.Path = XLSX_FNAME) -> pathlib.Path:
    """Save an hourly frame to Excel, creating the parent directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_excel(path, index=False)
    return path


if __name__ == "__main__":
    # Small demonstration: fetch two years for Paris and cache to Excel.
    df = fetch_pvgis_hourly(start_year=2010, end_year=2011, **SITE_PARIS)
    print(df.head())
    out = save_hourly(df)
    print(f"Saved {len(df)} rows to {out}")
