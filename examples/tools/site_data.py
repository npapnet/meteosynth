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

from meteosynth import MetDataset
from meteosynth.adapters import fetch_pvgis

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
        """Where the hourly record for this site and year range is cached.

        Note the site and period are still in the *filename*, which is convenient for a
        human browsing the folder -- but it is no longer what identifies the file. The
        dataset's own :class:`~meteosynth.Provenance` is, and it is checked on load, so
        a renamed or mistyped file cannot quietly answer the wrong question.
        """
        return DATA_DIR / f"pvgis_hourly_{self.key}_{start_year}_{end_year}.parquet"


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


def load_site(
    site: Site = HERAKLION,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    refresh: bool = False,
) -> MetDataset:
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
    MetDataset
        Holding all three plane-of-array components **and** their sum ``poa_global``,
        with provenance recording the site and period.

    Notes
    -----
    Thin over :func:`meteosynth.adapters.fetch_pvgis`, which now collects the components
    and derives ``poa_global`` itself -- so this module no longer reimplements either.
    The examples need both forms: the use cases model ``poa_global``, the concept scripts
    model ``poa_direct``.

    **The cache path is named explicitly rather than discovered**, which is the one thing
    this does not delegate. ``examples/data/`` holds two overlapping Heraklion records
    (2005-2023 for the diagnostics, 2010-2020 for the use cases), and letting the default
    discovery choose between them would raise
    :exc:`~meteosynth.cache.CacheAmbiguityError` -- correctly, since the two are genuinely
    different training records. Naming the file says which is wanted.
    """
    default_years = HERAKLION_YEARS if site is HERAKLION else PARIS_YEARS
    start_year = default_years[0] if start_year is None else start_year
    end_year = default_years[1] if end_year is None else end_year

    cache = site.cache_path(start_year, end_year)
    if not cache.exists():
        print(
            f"Fetching {site.name} ({site.latitude}, {site.longitude}) "
            f"{start_year}-{end_year} from PVGIS -- one request, then cached..."
        )

    dataset = fetch_pvgis(
        latitude=site.latitude,
        longitude=site.longitude,
        start=start_year,
        end=end_year,
        site=site.key,
        cache=cache,
        force_refetch=refresh,
        full_range=False,
        usehorizon=True,
        outputformat="json",
    )
    print(
        f"Loaded {site.name} {start_year}-{end_year} "
        f"({len(dataset.met_data)} hourly rows) from {cache.name}"
    )
    return dataset


def load_paris_demo() -> MetDataset:
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
