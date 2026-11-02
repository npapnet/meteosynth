# %%
"""
Use case: does a synthetic 21 May look like a real 21 May?  --  wind speed

Same comparison as ``day_envelope_pv.py``, run on ``wind_speed``: the Heraklion record,
an ensemble of synthetic 21 May profiles, held up against every observed 21 May and the
envelope of the surrounding fortnight.

Wind is the third distinct case, and the one where the daily mean is least sufficient:

* **Never degenerate, and effectively never at the bound.** Every hour is an ordinary 2D
  KDE, and although ``WIND_SPEED.support = (0.0, None)`` forbids negative samples, the
  observed distribution does not pile against zero the way irradiance does, which sits
  exactly on its bound all night. Same spec shape, completely different behaviour.
* **Weak persistence, so the ensemble fans out fast.** The cross-midnight transition
  correlates ~0.98 on the shipped record but hour-to-hour wind wanders far more than
  temperature does, so individual synthetic days criss-cross rather than running
  parallel. The p10-p90 band is wide by lunchtime and stays wide.
* **Power goes as the cube of speed**, so the mean speed is the wrong summary for an
  energy study: an ensemble can match mean speed and still be badly wrong on yield.
  ``extra_report`` below reports mean(v^3) as a power proxy alongside the mean, and the
  two do not agree on how close the generator is.
* **May at this site is pre-Etesian.** The strong northerlies come in July-August, so a
  21 May window is a mild, moderately variable regime -- the ensemble should look
  unremarkable, and a fat upper tail here would be a red flag.

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

    day_21May_wind_speed_pool07_win15_n0200_seed42.png

so runs accumulate in ``output/`` instead of overwriting one another, and can be
compared directly. ``output/day_21May_wind_speed_sweep_summary.csv`` collects one row per
case -- including the v^3 bias, which is the column to read when comparing runs. Each
figure repeats its own parameters in the bottom-right corner, because a filename is lost
the moment the image is pasted into a document.

Both functions, and everything else the three ``day_envelope_*`` scripts have in common,
live in :mod:`day_study` beside this file. What stays here is the preamble and the two
things peculiar to wind.

Run with::

    uv run python examples/use_cases/day/day_envelope_wind.py

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
ATTR = "wind_speed"
UNIT = "m/s"
TARGET = (5, 21)  # 21 May
DATE_LABEL = "21 May"
AGGREGATE = "mean"  # mean speed -- but see extra_report, which is the energy number
AGGREGATE_SCALE = 1.0
AGGREGATE_UNIT = UNIT

# --- the sweep: every combination of these three runs, one figure each ---------
POOL_DAYS = [7,1]  # observed envelope half-width in days, e.g. [7, 1]
WINDOW_DAYS = [15,7]  # training window half-width in days, e.g. [15, 7]
N_SYNTHETIC = [2000]  # ensemble size, e.g. [200, 1000]
SEED = 42

# %%


def describe_fit(day_generator, observed_pool: pd.DataFrame) -> List[str]:
    """What is worth saying about wind's fitted models: nothing degenerates, and how
    close the observed pool comes to the support bound."""
    kinds = {sim.kind.name for sim in day_generator.simulators.values()}
    return [
        f"transition kinds     : {sorted(kinds)}  -- nothing degenerates",
        f"observed minimum     : {np.nanmin(observed_pool.to_numpy()):.2f} {UNIT} "
        f"-- against the 0.0 support bound",
    ]


def extra_report(observed_pool: pd.DataFrame, synthetic: np.ndarray) -> pd.DataFrame:
    """
    The fourth check: the cube of the speed, which is what a turbine is paid for.

    Power is proportional to v^3, so matching the mean speed does not imply matching the
    energy. Both biases are returned, and the cube one is the column to compare across a
    sweep: a wider training window fattens the upper tail, which the mean barely
    registers and the cube does.
    """
    obs_power = np.nanmean(observed_pool.to_numpy() ** 3, axis=1)
    syn_power = np.mean(synthetic**3, axis=1)
    speed_bias = synthetic.mean() / np.nanmean(observed_pool.to_numpy()) - 1
    power_bias = syn_power.mean() / obs_power.mean() - 1

    print("\n    4. energy  daily mean of v^3 (power proxy, m3/s3):")
    print(f"               observed pool  mean {obs_power.mean():7.1f}  sd {obs_power.std():7.1f}")
    print(f"               synthetic      mean {syn_power.mean():7.1f}  sd {syn_power.std():7.1f}")
    print(f"               bias in mean speed : {speed_bias:+6.1%}")
    print(f"               bias in v^3        : {power_bias:+6.1%}   <- the one that costs money")

    return pd.DataFrame(
        {
            "metric": [
                "observed_v3_mean",
                "synthetic_v3_mean",
                "speed_bias_vs_pool",
                "v3_bias_vs_pool",
            ],
            "value": [
                obs_power.mean(),
                syn_power.mean(),
                speed_bias,
                power_bias,
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

    print("\n  A small bias in mean speed becomes a large one in v^3, because cubing")
    print("  weights the windy tail. If you take one number from this script for an")
    print("  energy model, take that one.")
    print("\n  Across cases: compare v3_bias_vs_pool, not speed_bias_vs_pool. A wider")
    print("  window_days pools more of the season and fattens the upper tail, which the")
    print("  mean barely registers and the cube does.")
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
