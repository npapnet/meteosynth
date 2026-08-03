"""
Shared data access for the example scripts: sites, their records, and where output goes.

Every example needs the same three things -- a site, an hourly record for it, and
somewhere to put what it generates -- so they live here once instead of being copied into
each script. Importing this module has **no side effects**: no network call, no file
write. :func:`load_site` is the only thing that touches the network, and only when the
folder holds no answer yet.

Where the files go is not decided here
--------------------------------------
It is decided by the script, and handed in as a
:class:`~meteosynth.paths.Workspace`::

    from meteosynth import workspace
    from tools.site_data import HERAKLION, load_site, save_frame

    WS = workspace(globals().get("__file__"))     # this script's own folder
    dataset = load_site(WS, HERAKLION)            # -> <script folder>/data/
    save_frame(WS, summary, "monthly.csv")        # -> <script folder>/output/

This module used to name the folders itself (``examples/data``, ``examples/output``),
which meant every script wrote to the same two places regardless of which one you ran.
Each example now owns its data and its output, so it is self-contained: copy the folder
anywhere and it still runs. The rule is ``FEAT-21``; the mechanism is
:func:`meteosynth.paths.workspace`.

Records are found, not named
----------------------------
:func:`load_site` passes ``data_dir`` and lets :func:`~meteosynth.adapters.fetch_pvgis`
match on what each record says about itself. It used to name the exact file, because the
one shared folder held two overlapping Heraklion records and discovery would rightly
refuse to choose between them. One folder per script means one record per site, so the
collision is gone and these scripts now show the package's ordinary path.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from meteosynth import MetDataset, Workspace
from meteosynth.adapters import fetch_pvgis


@dataclass(frozen=True)
class Site:
    """A location the examples fetch data for.

    Note there is no path on this: a site is *what* to collect, and a
    :class:`~meteosynth.paths.Workspace` is *where* it goes. Keeping them apart is what
    lets the same site definition serve six example folders.
    """

    key: str
    name: str
    latitude: float
    longitude: float


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
    workspace: Workspace,
    site: Site = HERAKLION,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    refresh: bool = False,
) -> MetDataset:
    """
    Load an hourly PVGIS record for a site, downloading it once into this workspace.

    Parameters
    ----------
    workspace : Workspace
        Whose ``data/`` folder holds the record. Typically
        ``workspace(globals().get("__file__"))`` -- the running script's own folder.
    site : Site, optional
        Which site. Defaults to :data:`HERAKLION`.
    start_year, end_year : int, optional
        Inclusive year range. Defaults to :data:`HERAKLION_YEARS` for Heraklion and
        :data:`PARIS_YEARS` for Paris.
    refresh : bool, optional
        Re-download even when the folder already holds an answer.

    Returns
    -------
    MetDataset
        Holding all three plane-of-array components **and** their sum ``poa_global``,
        with provenance recording the site and period.

    Notes
    -----
    Thin over :func:`meteosynth.adapters.fetch_pvgis`, which collects the components and
    derives ``poa_global`` itself -- so this module reimplements neither. The examples need
    both forms: the use cases model ``poa_global``, the concept scripts model
    ``poa_direct``.

    ``full_range=False`` is deliberate. The default downloads every year PVGIS serves
    (2005-2023 for these sites); these examples train on a fixed shorter period, and there
    is no reason for a first run to pay for eight years nobody reads.
    """
    default_years = HERAKLION_YEARS if site is HERAKLION else PARIS_YEARS
    start_year = default_years[0] if start_year is None else start_year
    end_year = default_years[1] if end_year is None else end_year

    if not _holds_a_record(workspace.data_dir):
        print(
            f"Fetching {site.name} ({site.latitude}, {site.longitude}) "
            f"{start_year}-{end_year} from PVGIS -- one request, then stored in "
            f"{workspace.data_dir}..."
        )

    dataset = fetch_pvgis(
        latitude=site.latitude,
        longitude=site.longitude,
        start=start_year,
        end=end_year,
        site=site.key,
        data_dir=workspace.data_dir,
        force_refetch=refresh,
        full_range=False,
        usehorizon=True,
        outputformat="json",
    )
    print(
        f"Loaded {site.name} {start_year}-{end_year} "
        f"({len(dataset.met_data)} hourly rows) from {workspace.data_dir}"
    )
    return dataset


def _holds_a_record(data_dir: pathlib.Path) -> bool:
    """Whether anything is stored yet -- for the message only, not for the decision.

    ``fetch_pvgis`` decides whether to download by reading provenance, which is the
    trustworthy answer. This is just so a cold run says so before spending a minute.
    """
    return data_dir.is_dir() and any(data_dir.glob("*.parquet"))


def load_paris_demo(workspace: Workspace) -> MetDataset:
    """Load the 2011-2012 Paris record the concept scripts use."""
    return load_site(workspace, PARIS, *PARIS_YEARS)


def save_frame(
    workspace: Workspace, frame: pd.DataFrame, name: str, index: bool = True
) -> pathlib.Path:
    """Write a frame to the workspace's ``output/`` and report where it went."""
    path = workspace.output(name)
    frame.to_csv(path, index=index)
    print(f"  wrote {frame.shape[0]:6d} rows x {frame.shape[1]} cols -> {path}")
    return path


def save_figure(workspace: Workspace, fig, name: str, dpi: int = 150) -> pathlib.Path:
    """Write a matplotlib figure to the workspace's ``output/`` and report where it went."""
    path = workspace.output(name)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"  wrote figure -> {path}")
    return path
