# %%
"""
Use case: does a synthetic 21 May look like a real 21 May?  --  irradiance (PV)

Trains on the Heraklion record, draws an ensemble of synthetic 21 May profiles of
plane-of-array global irradiance, and holds them up against every 21 May the record
actually contains plus the envelope of the surrounding fortnight.

This is the acceptance test a Monte-Carlo study rests on. A generator whose days look
plausible one at a time can still be systematically wrong in aggregate, so three
things get checked rather than one -- the diurnal *shape*, the *spread* of the
ensemble, and the daily *total*, which is what a PV yield calculation consumes.

What to expect from irradiance specifically, and what makes it the awkward one:

* **The night is degenerate, and correctly so.** Every observed midnight is exactly
  zero, so pi(x0) collapses to a spike at zero (``Kind.CONSTANT``) and every synthetic
  day starts at 0.0 -- read off the data, not hard-coded. The same happens at every
  other night hour. Roughly ten of the day's 24 models are constant in late May at this
  latitude; in December it would be more.
* **The support bound does real work.** Irradiance is truncated to
  ``IRRADIANCE.support = (0.0, None)``, so a dawn hour cannot sample negative, which is
  exactly what an unclamped KDE domain used to do.
* **Daily total is where the known bias would show.** Irradiance piles against a hard
  floor at zero and a renormalised symmetric kernel pushes mass upward, so the
  generator overshoots observed daily totals -- by ~14% on the small Paris record (see
  ``TODOs.md``), and by a few percent on the eleven-year Heraklion one. The printout
  below quantifies it rather than hiding it, which is the point of running the
  comparison at all: treat the shape as sound and the absolute magnitude as something
  you have measured rather than assumed.

The site and the period are in the preamble
-------------------------------------------
Coordinates, site label and year range are constants below, next to ``ATTR`` and
``TARGET``, and go straight to :func:`meteosynth.adapters.fetch_pvgis`. Nothing is
imported from a shared site registry, so this file is the whole statement of what was
run: to move the study, edit four numbers here.

``YEARS = None`` collects **everything PVGIS serves** for the site. A folder that
already holds a narrower record keeps answering with it -- see
:func:`day_study.load_dataset`, and read the period the run prints rather than assuming.

One run per parameter combination
---------------------------------
``POOL_DAYS``, ``WINDOW_DAYS`` and ``N_SYNTHETIC`` are *lists*. ``run_sweep`` walks every
combination of them, calls ``run_case`` once each, and every file it writes carries its
parameters in the name::

    day_21May_poa_global_pool07_win15_n0200_seed42.png

so runs accumulate in ``output/`` instead of overwriting one another, and can be
compared directly. ``output/day_21May_poa_global_sweep_summary.csv`` collects one row per
case. Each figure repeats its own parameters in the bottom-right corner, because a
filename is lost the moment the image is pasted into a document.

Both functions, and everything else the three ``day_envelope_*`` scripts have in common,
live in :mod:`day_study` beside this file. What stays here is the preamble and the two
things peculiar to irradiance.

Run with::

    uv run python examples/use_cases/day/day_envelope_pv.py

Runtime: ~25 s per case on a warm cache (one fetch more on a cold one), plus one
generator fit per distinct ``WINDOW_DAYS``.
"""

import pathlib
import sys
from typing import List, Sequence

import matplotlib.pyplot as plt
import pandas as pd

# `day_study` is this script's sibling, so its folder has to be importable. Found by
# search rather than from `__file__`, because this also runs as `#%%` cells, where there
# is no file and the working directory is the honest starting point.
_FILE = globals().get("__file__")
_HERE = pathlib.Path(_FILE).resolve().parent if _FILE else pathlib.Path.cwd()
_DAY = next(
    p
    for c in (_HERE, *_HERE.parents)
    for p in (c, c / "examples" / "use_cases" / "day")
    if (p / "day_study.py").is_file()
)
if str(_DAY) not in sys.path:
    sys.path.insert(0, str(_DAY))

from day_study import (  # noqa: E402  (needs the sys.path insert above)
    DayStudy,
    load_dataset,
    run_case,
    run_sweep,
)

# --- the site and the record: hardcoded here, not imported ---------------------
SITE_KEY = "heraklion"  # free label stored in the record's provenance
SITE_NAME = "Heraklion, Crete"  # what the figure is titled with
LATITUDE = 35.3387
LONGITUDE = 25.1442
YEARS = None  # None = every year PVGIS serves for this site
# YEARS = (2010, 2020)  # eleven full years: eleven real 21 Mays to compare against

# --- what is being modelled ----------------------------------------------------
ATTR = "poa_global"
UNIT = "W/m2"
TARGET = (5, 21)  # 21 May
DATE_LABEL = "21 May"
AGGREGATE = "sum"  # the daily total is what a PV yield calculation consumes
AGGREGATE_SCALE = 1e-3  # W/m2 summed over 24 h -> kWh/m2
AGGREGATE_UNIT = "kWh/m2"

# --- the sweep: every combination of these three runs, one figure each ---------
POOL_DAYS = [7,1]  # observed envelope half-width in days, e.g. [7, 1]
WINDOW_DAYS = [15,7]  # training window half-width in days, e.g. [15, 7]
N_SYNTHETIC = [2000]  # ensemble size, e.g. [200, 1000]
SEED = 42

# %%


def describe_fit(day_generator, observed_pool: pd.DataFrame) -> List[str]:
    """What is worth saying about irradiance's fitted models: where they degenerate."""
    degenerate = [h for h, sim in day_generator.simulators.items() if sim.is_degenerate]
    return [
        f"degenerate hours     : {degenerate}",
        f"pi(x0) kind          : {day_generator.initial.kind.name} "
        f"-- every observed midnight is 0 {UNIT}, so every synthetic day starts there",
    ]


#: Everything :mod:`day_study` needs in order to run this question. The constants above
#: stay separate so the preamble is still the one place to edit.
STUDY = DayStudy(
    site_key=SITE_KEY,
    site_name=SITE_NAME,
    latitude=LATITUDE,
    longitude=LONGITUDE,
    years=YEARS,
    attr=ATTR,
    unit=UNIT,
    target=TARGET,
    date_label=DATE_LABEL,
    aggregate=AGGREGATE,
    aggregate_scale=AGGREGATE_SCALE,
    aggregate_unit=AGGREGATE_UNIT,
    describe_fit=describe_fit,
)

# %%


def main(
    pool_days: Sequence[int] = POOL_DAYS,
    window_days: Sequence[int] = WINDOW_DAYS,
    n_synthetic: Sequence[int] = N_SYNTHETIC,
    seed: int = SEED,
):
    """Load the record once, then run every case the preamble asks for."""
    ds = load_dataset(STUDY)
    print(ds.describe_time_range())

    summary, results = run_sweep(
        STUDY,
        ds,
        pool_days=pool_days,
        window_days=window_days,
        n_synthetic=n_synthetic,
        seed=seed,
    )

    print("\n  Read the left panel as: the synthetic band should sit inside the observed")
    print("  one and peak at the same hour. Read the right panel as: the orange mass")
    print("  should overlie the blue. A shift to the right there is the known daily-total")
    print("  overshoot, and it is visible even when the shapes agree.")
    print("\n  Across cases: window_days changes the synthetic days, pool_days only the")
    print("  observed band they are judged against. Coverage moving when only pool_days")
    print("  moved is the band changing width, not the generator changing behaviour.")
    return summary, results


if __name__ == "__main__":
    main()
    plt.show()

# %%
# One case on its own, for an interactive session:
#
#     ds = load_dataset(STUDY)
#     result = run_case(STUDY, ds, pool_days=7, window_days=15, n_synthetic=200)
#     result["figure"]
