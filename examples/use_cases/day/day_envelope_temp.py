# %%
"""
Use case: does a synthetic 21 May look like a real 21 May?  --  air temperature

Same comparison as ``day_envelope_pv.py``, run on ``temp_air``: the Heraklion record, an
ensemble of synthetic 21 May profiles, held up against every observed 21 May and the
envelope of the surrounding fortnight.

Temperature behaves nothing like irradiance, and that is why it is worth its own file:

* **Nothing is degenerate.** Temperature never stands still, so all 23 within-day
  transitions and pi(x0) are ordinary 2D KDEs (``Kind.KDE_2D``) -- no constant hours,
  no spike at midnight. Hour 0 is drawn from the real distribution of observed midnight
  temperatures on this date, which is a genuinely informative starting point.
* **The support bound never binds.** ``TEMP_AIR.support = (-273.15, None)`` is a
  statement about physics, not a constraint that does anything here; a May night in
  Crete is nowhere near it. Contrast irradiance, where the lower bound is load-bearing
  at dawn and dusk.
* **Persistence is very strong.** Consecutive hourly temperatures correlate ~0.998, so
  each day's trajectory stays close to wherever pi(x0) started it. The visible
  consequence in the plot: the synthetic band is a bundle of near-parallel curves rather
  than the criss-crossing spaghetti wind produces. Level is set at midnight; shape is
  the diurnal cycle on top of it.
* **The daily mean is the aggregate that matters** -- for heating/cooling demand and
  for PV module derating, where a hot day costs efficiency.

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

    day_21May_temp_air_pool07_win15_n0200_seed42.png

so runs accumulate in ``output/`` instead of overwriting one another, and can be
compared directly. ``output/day_21May_temp_air_sweep_summary.csv`` collects one row per
case -- including the diurnal-swing numbers, which is where a wider training window shows
up first. Each figure repeats its own parameters in the bottom-right corner, because a
filename is lost the moment the image is pasted into a document.

Both functions, and everything else the three ``day_envelope_*`` scripts have in common,
live in :mod:`day_study` beside this file. What stays here is the preamble and the two
things peculiar to temperature.

Run with::

    uv run python examples/use_cases/day/day_envelope_temp.py

Runtime: ~45 s per case on a warm cache, plus one generator fit per distinct
``WINDOW_DAYS``.
"""

import pathlib
import sys
from typing import List, Sequence

import matplotlib.pyplot as plt
import numpy as np
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
ATTR = "temp_air"
UNIT = "degC"
TARGET = (5, 21)  # 21 May
DATE_LABEL = "21 May"
AGGREGATE = "mean"  # the daily mean is what demand and derating models consume
AGGREGATE_SCALE = 1.0
AGGREGATE_UNIT = UNIT

# --- the sweep: every combination of these three runs, one figure each ---------
POOL_DAYS = [7,1 ]  # observed envelope half-width in days, e.g. [7, 1]
WINDOW_DAYS = [15,7]  # training window half-width in days, e.g. [15, 7]
N_SYNTHETIC = [2000]  # ensemble size, e.g. [200, 1000]
SEED = 42

# %%


def describe_fit(day_generator, observed_pool: pd.DataFrame) -> List[str]:
    """What is worth saying about temperature's fitted models: that none degenerate."""
    kinds = {sim.kind.name for sim in day_generator.simulators.values()}
    return [
        f"transition kinds     : {sorted(kinds)}  -- nothing degenerates",
        f"pi(x0) kind          : {day_generator.initial.kind.name}, fitted to observed "
        f"midnight temperatures spanning "
        f"{observed_pool[0].min():.1f} to {observed_pool[0].max():.1f} {UNIT}",
    ]


def extra_report(observed_pool: pd.DataFrame, synthetic: np.ndarray) -> pd.DataFrame:
    """
    The fourth check: diurnal swing.

    A generator can match the daily mean while flattening or exaggerating the day's
    range, so the range is worth its own comparison -- and worth carrying into the sweep
    summary, where a wider training window shows up here before it shows up in coverage.
    """
    obs_range = observed_pool.max(axis=1) - observed_pool.min(axis=1)
    syn_range = synthetic.max(axis=1) - synthetic.min(axis=1)
    obs_coldest = int(np.nanargmin(observed_pool.median()))
    syn_coldest = int(np.nanargmin(np.median(synthetic, axis=0)))

    print(f"\n    4. swing   daily range (max - min, {UNIT}):")
    print(f"               observed pool  mean {obs_range.mean():5.2f}  sd {obs_range.std():5.2f}")
    print(f"               synthetic      mean {syn_range.mean():5.2f}  sd {syn_range.std():5.2f}")
    print(f"               coldest hour: observed {obs_coldest}:00, synthetic {syn_coldest}:00")

    return pd.DataFrame(
        {
            "metric": [
                "observed_daily_range_mean",
                "synthetic_daily_range_mean",
                "daily_range_bias_vs_pool",
                "observed_coldest_hour",
                "synthetic_coldest_hour",
            ],
            "value": [
                obs_range.mean(),
                syn_range.mean(),
                syn_range.mean() / obs_range.mean() - 1,
                obs_coldest,
                syn_coldest,
            ],
        }
    )


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
    extra_report=extra_report,
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

    print("\n  Note how much of the ensemble's spread is set at hour 0 and simply carried")
    print("  through the day. That is persistence doing its job, and it is why pi(x0) has")
    print("  to be a fitted distribution rather than a fixed starting value.")
    print("\n  Across cases: a wider window_days pools more of the season into one day's")
    print("  models, which widens pi(x0) and inflates the spread before it touches the")
    print("  swing. Compare daily_range_bias_vs_pool in the summary, not just coverage.")
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
