"""
Shared data access for the example scripts: sites, cached PVGIS records, output paths.

Every example needs the same three things -- a site, an hourly record for it, and
somewhere to put what it generates -- so they live here once instead of being copied
into each script. Importing this module has **no side effects**: no network call, no
file write. :func:`load_site` is the only thing that touches the network, and only when
the cache is cold.

Layout this module assumes and maintains::

    examples/data/     cached PVGIS downloads   (git-ignored: the repo-wide `data/` rule)
    examples/output/   generated synthetic series and figures  (git-ignored: output/.gitignore)

Run ``python examples/tools/fetch_site_data.py`` to prime the cache up front rather
than paying for the download inside whichever example you run first.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from pvlib.iotools import get_pvgis_hourly

EXAMPLES_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = EXAMPLES_ROOT / "data"
OUTPUT_DIR = EXAMPLES_ROOT / "output"


@dataclass(frozen=True)
class Site:
    """A location the examples fetch data for."""

    key: str
    name: str
    latitude: float
    longitude: float

    def cache_path(self, start_year: int, end_year: int) -> pathlib.Path:
        """Where the hourly record for this site and year range is cached."""
        return DATA_DIR / f"pvgis_hourly_{self.key}_{start_year}_{end_year}.csv"


#: Heraklion, Crete -- the site the use cases are built around. Hot-summer
#: Mediterranean: strong summer irradiance, mild winters, persistent Etesian winds.
HERAKLION = Site("heraklion", "Heraklion, Crete", 35.3387, 25.1442)

#: Paris -- the site the older concept scripts were written against.
PARIS = Site("paris", "Paris", 48.8566, 2.3522)

SITES = {site.key: site for site in (HERAKLION, PARIS)}

#: The record the use cases train on. Eleven full years is enough that a single
#: calendar day has eleven real observations to compare a synthetic day against.
HERAKLION_YEARS = (2010, 2020)

PARIS_YEARS = (2011, 2012)


def add_time_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Add the ``year``/``month``/``day``/``hour`` index columns from a datetime index.

    These four are :data:`meteosynth.INDEX_COLS` -- what
    :class:`~meteosynth.MetDataProcessor` validates on ingestion.
    """
    data["year"] = data.index.year
    data["month"] = data.index.month
    data["day"] = data.index.day
    data["hour"] = data.index.hour
    return data


def add_poa_global(data: pd.DataFrame) -> pd.DataFrame:
    """Add ``poa_global`` as the sum of the three plane-of-array components.

    ``get_pvgis_hourly(components=True)`` returns the components but not their sum,
    and ``components=False`` returns the sum but not the components. The PV use case
    wants total plane-of-array irradiance -- the quantity a module actually sees -- so
    it is reconstructed here rather than fetched twice.

    ``poa_global`` is registered in :mod:`meteosynth.variables` under the same
    :data:`~meteosynth.IRRADIANCE` spec as its parts, so it is modellable with no
    further declaration. The column name is what records that this is the *global*
    component and not the direct one -- see the module docstring of
    ``meteosynth.variables`` on why the names stay distinct.
    """
    parts = ["poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"]
    missing = [col for col in parts if col not in data.columns]
    if missing:
        raise KeyError(
            f"cannot build poa_global: missing {missing}. Fetch with components=True."
        )
    data["poa_global"] = data[parts].sum(axis=1)
    return data


def load_site(
    site: Site = HERAKLION,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Load an hourly PVGIS record for a site, downloading it once and caching it.

    Parameters
    ----------
    site : Site, optional
        Which site. Defaults to :data:`HERAKLION`.
    start_year, end_year : int, optional
        Inclusive year range. Defaults to :data:`HERAKLION_YEARS` for Heraklion and
        :data:`PARIS_YEARS` for Paris.
    refresh : bool, optional
        Re-download even if the cache is warm.

    Returns
    -------
    pd.DataFrame
        Hourly frame with the four calendar index columns and ``poa_global`` added,
        ready for :class:`~meteosynth.MetDataProcessor`.
    """
    default_years = HERAKLION_YEARS if site is HERAKLION else PARIS_YEARS
    start_year = default_years[0] if start_year is None else start_year
    end_year = default_years[1] if end_year is None else end_year

    cache = site.cache_path(start_year, end_year)
    if cache.exists() and not refresh:
        print(f"Loading cached {site.name} {start_year}-{end_year} from {cache.name}...")
        return add_poa_global(pd.read_csv(cache))

    print(
        f"Fetching {site.name} ({site.latitude}, {site.longitude}) "
        f"{start_year}-{end_year} from PVGIS -- one request, then cached..."
    )
    # pvlib returned (data, inputs, metadata) before 0.11 and (data, metadata) after,
    # so index rather than unpack: the examples should not care which is installed.
    result = get_pvgis_hourly(
        latitude=site.latitude,
        longitude=site.longitude,
        start=start_year,
        end=end_year,
        usehorizon=True,
        outputformat="json",
        components=True,
    )
    data = add_time_columns(result[0])

    cache.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(cache, index=False)
    print(f"  cached {len(data)} hourly rows to {cache}")
    return add_poa_global(data)


def load_paris_demo() -> pd.DataFrame:
    """Load the 2011-2012 Paris record the concept scripts use."""
    return load_site(PARIS, *PARIS_YEARS)


def output_path(name: str) -> pathlib.Path:
    """Path inside the git-ignored ``examples/output/`` folder, creating it if needed."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / name


def save_frame(frame: pd.DataFrame, name: str, index: bool = True) -> pathlib.Path:
    """Write a frame to ``examples/output/`` and report where it went."""
    path = output_path(name)
    frame.to_csv(path, index=index)
    print(f"  wrote {frame.shape[0]:6d} rows x {frame.shape[1]} cols -> {path}")
    return path


def save_figure(fig, name: str, dpi: int = 150) -> pathlib.Path:
    """Write a matplotlib figure to ``examples/output/`` and report where it went."""
    path = output_path(name)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"  wrote figure -> {path}")
    return path
