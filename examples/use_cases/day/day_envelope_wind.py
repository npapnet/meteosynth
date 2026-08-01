#%%
"""
Use case: does a synthetic 21 May look like a real 21 May?  --  wind speed

Same comparison as ``day_envelope_pv.py``, run on ``wind_speed``: eleven years of
Heraklion data (2010-2020), an ensemble of synthetic 21 May profiles, held up against
every observed 21 May and the envelope of the surrounding fortnight.

Wind is the third distinct case, and the one where the daily mean is least sufficient:

* **Never degenerate, never at the bound.** Every hour is an ordinary 2D KDE, and
  although ``WIND_SPEED.support = (0.0, None)`` forbids negative samples, the observed
  minimum never reaches zero -- unlike irradiance, which sits exactly on its bound all
  night. Same spec shape, completely different behaviour.
* **Weak persistence, so the ensemble fans out fast.** The cross-midnight transition
  correlates ~0.98 on the shipped record but hour-to-hour wind wanders far more than
  temperature does, so individual synthetic days criss-cross rather than running
  parallel. The p10-p90 band is wide by lunchtime and stays wide.
* **Power goes as the cube of speed**, so the mean speed is the wrong summary for an
  energy study: an ensemble can match mean speed and still be badly wrong on yield.
  The extra block below reports mean(v^3) as a power proxy alongside the mean, and the
  two do not agree on how close the generator is.
* **May at this site is pre-Etesian.** The strong northerlies come in July-August, so a
  21 May window is a mild, moderately variable regime -- the ensemble should look
  unremarkable, and a fat upper tail here would be a red flag.

The ensemble is written to ``examples/output/`` (git-ignored).

Run with::

    uv run python examples/use_cases/day/day_envelope_wind.py

Runtime: ~60 s on a warm cache.
"""

import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np

# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path.cwd()
_EXAMPLES = next(p for c in (_HERE, *_HERE.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

from meteosynth import DayWindowGenerator, MetDataset
from tools.envelope import (
    day_matrix,
    ensemble_frame,
    plot_day_envelope,
    report_day_stats,
    synthetic_ensemble,
)
from tools.site_data import HERAKLION, HERAKLION_YEARS, load_site, save_figure, save_frame

ATTR = "wind_speed"
UNIT = "m/s"
TARGET = (5, 21)          # 21 May
DATE_LABEL = "21 May"
POOL_DAYS = 7             # observed envelope: every day within a week of the target
WINDOW_DAYS = 15          # training window half-width, +/- 15 days
N_SYNTHETIC = 200
SEED = 42

#%%


def main():
    ds = load_site(HERAKLION, *HERAKLION_YEARS)
    print(ds.describe_time_range())

    observed_exact = day_matrix(ds, ATTR, *TARGET, n_days=0)
    observed_pool = day_matrix(ds, ATTR, *TARGET, n_days=POOL_DAYS)

    print(f"\nFitting the +/-{WINDOW_DAYS} day window generator for {DATE_LABEL}...")
    generator = DayWindowGenerator(ds, attr_str=ATTR, n_days=WINDOW_DAYS)
    day_generator = generator.for_day(*TARGET)
    kinds = {sim.kind.name for sim in day_generator.simulators.values()}
    print(f"  training days pooled : {len(day_matrix(ds, ATTR, *TARGET, n_days=WINDOW_DAYS))}")
    print(f"  transition kinds     : {sorted(kinds)}  -- nothing degenerates")
    print(f"  observed minimum     : {np.nanmin(observed_pool.to_numpy()):.2f} {UNIT} "
          f"-- above the 0.0 support bound, so the bound never binds")

    print(f"\nDrawing {N_SYNTHETIC} independent synthetic {DATE_LABEL} profiles...")
    synthetic = synthetic_ensemble(generator, *TARGET, n=N_SYNTHETIC, seed=SEED, show_progress=True)

    stats = report_day_stats(
        observed_pool, observed_exact, synthetic,
        attr=ATTR, unit=UNIT, date_label=DATE_LABEL, aggregate="mean",
    )

    # Mean speed is not what a turbine sees. Power is proportional to v^3, so compare
    # the cube-mean too: matching one does not imply matching the other.
    obs_power = np.nanmean(observed_pool.to_numpy() ** 3, axis=1)
    syn_power = np.mean(synthetic ** 3, axis=1)
    speed_bias = synthetic.mean() / np.nanmean(observed_pool.to_numpy()) - 1
    power_bias = syn_power.mean() / obs_power.mean() - 1
    print(f"\n    4. energy  daily mean of v^3 (power proxy, m3/s3):")
    print(f"               observed pool  mean {obs_power.mean():7.1f}  sd {obs_power.std():7.1f}")
    print(f"               synthetic      mean {syn_power.mean():7.1f}  sd {syn_power.std():7.1f}")
    print(f"               bias in mean speed : {speed_bias:+6.1%}")
    print(f"               bias in v^3        : {power_bias:+6.1%}   <- the one that costs money")

    print("\nSaving...")
    save_frame(ensemble_frame(synthetic), f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}_ensemble.csv")
    save_frame(stats, f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}_stats.csv", index=False)

    fig = plot_day_envelope(
        observed_pool, observed_exact, synthetic,
        attr=ATTR, unit=UNIT, date_label=DATE_LABEL,
        site_label=HERAKLION.name, window_days=POOL_DAYS, aggregate="mean",
    )
    save_figure(fig, f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}.png")

    print("\n  A small bias in mean speed becomes a large one in v^3, because cubing")
    print("  weights the windy tail. If you take one number from this script for an")
    print("  energy model, take that one.")
    return fig


if __name__ == "__main__":
    main()
    plt.show()

# %%
