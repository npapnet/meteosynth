"""
A synthetic wind-speed ensemble for Leros (37.167 N, 26.800 E). Data only.

Standalone by design: imports **nothing from `examples/`** -- no `tools.site_data`, no
shared helpers, no `sys.path` bootstrap -- so it can be copied anywhere and run. Written
as Jupyter-style `#%%` cells, so it can equally be stepped through in VS Code or
JupyterLab.

It produces data and nothing else. No plots, no diagnostics, no observed-vs-synthetic
comparison: those live in `use_cases/year/` and `diagnostics-overshoot/`. Run this when
you want the file a yield model, a storage-sizing run or a demand simulation consumes.

Everything lands in the **default data store**, `./data/` under the directory you run
from:

    data/pvgis_hourly_leros_2005_2023.parquet     the training record, fetched once
    data/ensemble_leros_2023_n<N>.parquet         the generated ensemble

The training record holds every quantity PVGIS returned, so switching ``ATTRS`` to
another variable needs no refetch -- it is already on disk.

Both are parquet and both sit in one folder, but they cannot be confused: a training
record and an ensemble carry different parquet metadata keys, so `meteosynth.store` lists
only the former and `read_ensemble` accepts only the latter.

On runtime -- and what does *not* drive it
-----------------------------------------
Absolute times belong to whatever machine you are on, so what follows is deliberately in
ratios. Run ``leros_timing_benchmark.py`` for the numbers on yours; it writes them to
``benchmarks/``.

**The number of realisations is very nearly free.** Stepping N over two orders of
magnitude -- ten realisations to a thousand -- costs a **few per cent** more time, and the
run-to-run scatter is the same size as the effect. Per realisation-day the cost falls by
about a hundredfold, exactly as if N were not in the equation. Output grows in proportion
and still does not register, so even parquet writing, the one component that genuinely
scales with N, is lost in the noise.

**What does drive it: days x transitions needing a full 2D KDE x training pairs.** Nearly
all the time goes into building each simulator's cached quantile grid, and that is paid
per calendar day per attribute *regardless of N*.

That is also what sets the gap between attributes. Each has 23 hourly transitions to
model, but only those that are not degenerate need a full 2D KDE: ``poa_global`` is
constant through the night and so needs a full fit for fewer than half of them, while
``temp_air`` and ``wind_speed`` need all 23. Irradiance therefore comes out **roughly
three times cheaper** than either of the other two, which cost about the same as each
other -- and it is the cheapest of the three despite being the headline quantity.

So the levers are, in order of effect:

===============================  ==========================================
lever                            effect
===============================  ==========================================
fewer ``ATTRS``                  ~proportional to their 2D-KDE counts above
``WINDOW_DAYS`` 15 -> 7          ~halves it, by halving the pooled pairs
raising ``N_REALISATIONS``       **costs almost nothing -- do not economise here**
===============================  ==========================================

Narrowing the window is a **modelling** decision, not just a speed one -- see ``CHORE-1``
in ``TODOs.md``, which measures what a window costs in seasonal contamination. Do not
change it purely to go faster.

**Runtime is linear in ``N_DAYS`` and independent of ``N_REALISATIONS``**, which is all
you need to size a run: time a short one, multiply. A full 365-day year at a single
non-degenerate attribute lands in the **low hours** on a current desktop, at any
realisation count.

**Size a trial run first** by lowering ``N_DAYS``.
"""

#%%
from __future__ import annotations

import time

from meteosynth import read_ensemble, store
from meteosynth.adapters import fetch_pvgis
from meteosynth.ensemble import write_ensemble

#%%
# --- Configuration -------------------------------------------------------------------
# Every knob this script has. Nothing below here needs editing for an ordinary run.

#: The site. A label is not a lookup -- it is a name bound to these coordinates by the
#: first fetch, and resolved from the store's provenance on every later one.
LATITUDE = 37.167
LONGITUDE = 26.800
SITE = "leros"

#: Quantities to generate. Each needs a registered VariableSpec, is fitted and drawn
#: separately, and costs roughly in proportion to how many of its 23 hourly transitions
#: need a full 2D KDE. ``wind_speed`` and ``temp_air`` need all of them and cost about the
#: same; ``poa_global`` is constant overnight, needs a full fit for well under half, and
#: so runs roughly three times cheaper than either -- the cheapest of the three despite
#: being the headline quantity.
# ATTRS = ["poa_global", "temp_air", "wind_speed"]
ATTRS = ["wind_speed"]

#: A non-leap calendar to hang the hours on. The generator is climatological and carries
#: no year of its own; this only names the output and fixes the day count at 365.
REFERENCE_YEAR = 2023

#: How many independent synthetic years. The calendar is walked once for all of them.
N_REALISATIONS = 1000

#: Days per realisation. Lower this to size a trial run -- see "On runtime" above.
# use 365 for full run, or 30 for a test run
N_DAYS = 365

#: Half-width of each day's rolling training window, in days. A modelling choice.
WINDOW_DAYS = 15

#: Root entropy. Realisation *i* of attribute *a* is a fixed function of (SEED, i, a),
#: so realisation 0 does not change when you ask for more, and temp_air does not change
#: when you add wind_speed alongside it.
SEED = 2026

#: Build each simulator's cached quantile grid up front rather than letting the package
#: decide. Left as ``None`` it switches on above 64 realisations, which means two runs
#: either side of that boundary differ by *which sampling path ran* and not only by size.
#: Forcing it True keeps every run on one path, and is the right setting for any ensemble
#: large enough to want one -- below ~64 realisations it is pure overhead.
PRECOMPUTE = True

#: Re-download the training record even when one is already stored.
FORCE_REFETCH = False

#: Show a tqdm bar over the calendar walk. Worth leaving on for a run this long.
PROGRESS = True

#%%
# --- 1. The training record ----------------------------------------------------------
# No cache= and no data_dir=, so this uses the default store: ./data/ under the working
# directory. The first run downloads every year PVGIS serves for the site; later runs
# find that same record by provenance and never touch the network.

print(f"Training record for {SITE} ({LATITUDE}, {LONGITUDE})")
print(f"  store: {store.default_data_dir()}")

dataset = fetch_pvgis(LATITUDE, LONGITUDE, site=SITE, force_refetch=FORCE_REFETCH)
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

#%%
# --- 2. Generate the ensemble --------------------------------------------------------
# Streamed one calendar day at a time, so peak memory holds a day rather than the whole
# ensemble. This is the long step.

ensemble_path = store.default_data_dir() / (
    f"ensemble_{SITE}_{REFERENCE_YEAR}_n{N_REALISATIONS}.parquet"
)

print(
    f"\nGenerating {N_REALISATIONS} realisations x {N_DAYS} days x {len(ATTRS)} "
    f"attributes\n  -> {ensemble_path}"
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
    precompute=PRECOMPUTE,
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

print(
    "\nRead it elsewhere with `meteosynth.read_ensemble(path)`, or as plain parquet --\n"
    "the format is documented in docs/source/ensemble_format.md and needs no meteosynth."
)

#%%
