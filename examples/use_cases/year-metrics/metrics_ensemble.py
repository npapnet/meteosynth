"""
A synthetic ensemble for Leros (37.167 N, 26.800 E) across **all three** quantities.

The input the validation work needs. `use_cases/year-leros/` produces the same thing for
``wind_speed`` alone; this produces ``poa_global``, ``temp_air`` and ``wind_speed`` in one
file, on the same calendar, from the same record, under the same seed -- which is what
lets a single analysis pass read all three and what makes the wind column here comparable
to the wind-only file (see step 4).

The metrics this feeds are specified in ``paper/metrics-prompt.md``. Read that before
reading the output: three of its tests need modification for irradiance and temperature,
and the modifications are not cosmetic.

Standalone by design: imports **nothing from `examples/`** -- no `tools.site_data`, no
shared helpers, no `sys.path` bootstrap -- so it can be copied anywhere and run. Written
as Jupyter-style `#%%` cells, so it can equally be stepped through in VS Code or
JupyterLab.

It produces data and nothing else. No plots, no diagnostics, no observed-vs-synthetic
comparison -- the comparison is the point of the metrics work, and it belongs where that
work lives rather than inside the script that generates its input.

Everything lands **beside this file**, whichever directory you launch it from:

    <this folder>/data/pvgis_hourly_leros_2005_2023.parquet   the training record, once
    <this folder>/output/ensemble_leros_2023_n<N>_w<W>_3attr.parquet  the generated ensemble

`data/` for what was collected and `output/` for what was generated, both git-ignored.
The folder is chosen by ``meteosynth.workspace(__file__)`` -- the script's own location,
not the terminal's -- so running this from the repository root and from this directory
give the same answer and neither downloads twice.

**You can skip the download.** `year-leros/data/` already holds the same record (883 KB),
and records are found by provenance rather than by filename, so copying that one parquet
into this folder's `data/` is enough -- `fetch_pvgis` will match it against the request and
make no network call. Re-fetching is also fine; it is one request.

On runtime
----------
Ratios, not seconds -- an absolute time here is a property of the machine as much as of
the code. `year-leros/leros_year_ensemble.py` carries the full analysis; the short version:

* **Cost is days x attributes, and very nearly independent of ``N_REALISATIONS``.** The
  calendar is walked once and each day's fitted models are shared by every realisation, so
  stepping N from 10 to 1000 costs a few per cent. Do not economise on N.
* **The three attributes do not cost the same.** ``temp_air`` and ``wind_speed`` need a
  full 2D KDE for all 23 hourly transitions; ``poa_global`` is constant overnight and needs
  one for well under half, so it runs roughly **three times cheaper** than either.

So expect this run to cost about **2.3x** a ``wind_speed``-only run of the same shape
(1 + 1 + 1/3). Output lands around **200-250 MB** against 90 MB for one attribute -- the
five index columns are shared and compress to almost nothing, so it is the float payload
that triples.

**Size a trial run first** by setting ``N_DAYS = 30``, then multiply by 12.
"""

#%%
from __future__ import annotations

import time

from meteosynth import read_ensemble, workspace
from meteosynth.adapters import fetch_pvgis
from meteosynth.ensemble import write_ensemble

#: This script's own folder. `data/` and `output/` sit beside it, wherever the script is
#: launched from -- so this example is self-contained and can be copied anywhere.
#: `globals().get` rather than `__file__` because this also runs as `#%%` cells, where
#: there is no file and the working directory is the honest answer.
WS = workspace(globals().get("__file__"))

#%%
# --- Configuration -------------------------------------------------------------------
# Every knob this script has. Nothing below here needs editing for an ordinary run.
#

# LATITUDE = 37.167
# LONGITUDE = 26.800
# SITE = "leros"

SITE = "heraklion"  # free label stored in the record's provenance
SITE_NAME = "Heraklion, Crete"  # what the figure is titled with
LATITUDE = 35.3387
LONGITUDE = 25.1442


#: All three quantities, in one file on one calendar. Each is fitted and drawn separately
#: -- they are **not** coupled, and a hot hour in a realisation is not thereby a sunny one.
#: The file records that in its own metadata; any cross-variable claim must not be made
#: from it.
ATTRS = ["poa_global", "temp_air", "wind_speed"]

#: A non-leap calendar to hang the hours on. The generator is climatological and carries
#: no year of its own; this only names the output and fixes the day count at 365.
REFERENCE_YEAR = 2023

#: How many independent synthetic years. The calendar is walked once for all of them.
N_REALISATIONS = 1000

#: Days per realisation. Lower this to size a trial run -- see "On runtime" above.
#: Use 365 for the full run, 30 for a trial.
N_DAYS = 365

#: Half-width of each day's rolling training window, in days. A modelling choice, not a
#: speed one -- ``CHORE-1`` in ``TODOs.md`` measures what a window costs in seasonal
#: contamination. Matched to the wind-only run so the two are comparable.
WINDOW_DAYS = 15

#: Root entropy. Realisation *i* of attribute *a* is a fixed function of (SEED, i, a) and
#: of nothing else -- not of how many realisations were asked for, and not of which other
#: attributes were. That last property is what step 4 exercises.
SEED = 2026

#: Which path answers each draw. Named rather than left on ``"auto"`` so every run sits on
#: one sampling path regardless of realisation count, and two runs differ only by size.
SAMPLING = "grid"


#: Re-download the training record even when one is already stored.
FORCE_REFETCH = False

#: Show a tqdm bar over the calendar walk. Worth leaving on for a run this long.
PROGRESS = True

#%%
# --- 1. The training record ----------------------------------------------------------
# `data_dir=` names the folder, not the file: the first run downloads every year PVGIS
# serves for the site, and later runs find that same record by reading the provenance
# inside it. No filename is constructed here, and none needs to be.

print(f"Training record for {SITE} ({LATITUDE}, {LONGITUDE})")
print(f"  {WS.describe()}")

dataset = fetch_pvgis(
    LATITUDE, LONGITUDE, site=SITE, data_dir=WS.data_dir, force_refetch=FORCE_REFETCH
)

#%%
print(f"  {dataset.describe_time_range()}, {len(dataset.met_data):,} hourly rows")
print(f"  columns: {list(dataset.variables)}")
if dataset.provenance.notes:
    print(f"  note: {dataset.provenance.notes}")

missing = [a for a in ATTRS if a not in dataset.met_data.columns]
if missing:
    raise ValueError(
        f"the record does not hold {missing}. Available: {list(dataset.variables)}."
    )

# The observed record contains Feb 29 in leap years; the ensemble below is generated with
# include_feb29=False and does not. Anything comparing the two has to drop those days from
# the observed side first, or the calendars silently disagree. Stated here because it is
# easy to miss and cheap to count.
leap_rows = dataset.met_data.query("month == 2 and day == 29")
print(
    f"  observed holds {len(leap_rows) // 24} Feb-29 days ({len(leap_rows)} rows); "
    f"the ensemble will hold none -- drop them before comparing."
)

#%%
# --- 2. Generate the ensemble --------------------------------------------------------
# Streamed one calendar day at a time, so peak memory holds a day rather than the whole
# ensemble. This is the long step.

ensemble_path = WS.output(
    f"ensemble_{SITE}_{REFERENCE_YEAR}_n{N_REALISATIONS}_w{WINDOW_DAYS}_{len(ATTRS)}attr.parquet"
)

print(
    f"\nGenerating {N_REALISATIONS} realisations x {N_DAYS} days x {len(ATTRS)} "
    f"attributes ({', '.join(ATTRS)})\n  -> {ensemble_path}"
)

started = time.perf_counter()
meta = write_ensemble(
    dataset, ATTRS, ensemble_path,
    start=(1, 1),
    n_days=N_DAYS,
    n_realisations=N_REALISATIONS,
    seed=SEED,
    n_days_window=WINDOW_DAYS,
    include_feb29=False,
    progress=PROGRESS,
    sampling=SAMPLING,
)
elapsed = time.perf_counter() - started

print(f"\nDone in {elapsed / 60:.1f} min ({elapsed / max(N_DAYS, 1):.1f} s per day).")

#%%
# --- 3. Confirm what was written -----------------------------------------------------
# Reading it back is the only check here: the file either round-trips or it does not.

size_mb = ensemble_path.stat().st_size / 1024**2
print(f"{ensemble_path.name}: {size_mb:.1f} MB")
print(
    f"  embedded: seed={meta['seed']}, n_realisations={meta['n_realisations']}, "
    f"window=+/-{meta['window_n_days']}d, attrs={list(meta['attrs'])}"
)

ensemble = read_ensemble(ensemble_path)
print(f"  reads back: {ensemble.n_realisations} realisations, attrs {ensemble.attrs}")
print(f"  realisation 0: {len(ensemble.realisation(0)):,} rows "
      f"(= {N_DAYS} days x 24 h)")

#%%
print(
    "\nRead it elsewhere with `meteosynth.read_ensemble(path)`, or as plain parquet --\n"
    "the format is documented in docs/source/ensemble_format.md and needs no meteosynth.\n"
    "It is one row group per calendar day, so stream it: the whole frame is ~26M rows and\n"
    "expands to well over a gigabyte in pandas."
)

#%%
