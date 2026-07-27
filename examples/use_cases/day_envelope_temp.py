#%%
"""
Use case: does a synthetic 21 May look like a real 21 May?  --  air temperature

Same comparison as ``day_envelope_pv.py``, run on ``temp_air``: eleven years of
Heraklion data (2010-2020), an ensemble of synthetic 21 May profiles, held up against
every observed 21 May and the envelope of the surrounding fortnight.

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

The ensemble is written to ``examples/output/`` (git-ignored).

Run with::

    uv run --extra examples python examples/use_cases/day_envelope_temp.py

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

from meteosynth import DayWindowGenerator, MetDataProcessor
from tools.envelope import (
    day_matrix,
    ensemble_frame,
    plot_day_envelope,
    report_day_stats,
    synthetic_ensemble,
)
from tools.site_data import HERAKLION, HERAKLION_YEARS, load_site, save_figure, save_frame

ATTR = "temp_air"
UNIT = "degC"
TARGET = (5, 21)          # 21 May
DATE_LABEL = "21 May"
POOL_DAYS = 7             # observed envelope: every day within a week of the target
WINDOW_DAYS = 15          # training window half-width, +/- 15 days
N_SYNTHETIC = 200
SEED = 42

#%%


def main():
    df = load_site(HERAKLION, *HERAKLION_YEARS)
    mdp = MetDataProcessor(df)
    print(mdp.describe_time_range())

    observed_exact = day_matrix(mdp, ATTR, *TARGET, n_days=0)
    observed_pool = day_matrix(mdp, ATTR, *TARGET, n_days=POOL_DAYS)

    print(f"\nFitting the +/-{WINDOW_DAYS} day window generator for {DATE_LABEL}...")
    generator = DayWindowGenerator(mdp, attr_str=ATTR, n_days=WINDOW_DAYS)
    day_generator = generator.for_day(*TARGET)
    kinds = {sim.kind.name for sim in day_generator.simulators.values()}
    print(f"  training days pooled : {len(day_matrix(mdp, ATTR, *TARGET, n_days=WINDOW_DAYS))}")
    print(f"  transition kinds     : {sorted(kinds)}  -- nothing degenerates")
    print(f"  pi(x0) kind          : {day_generator.initial.kind.name}, fitted to observed "
          f"midnight temperatures spanning "
          f"{observed_pool[0].min():.1f} to {observed_pool[0].max():.1f} {UNIT}")

    print(f"\nDrawing {N_SYNTHETIC} independent synthetic {DATE_LABEL} profiles...")
    synthetic = synthetic_ensemble(generator, *TARGET, n=N_SYNTHETIC, seed=SEED)

    stats = report_day_stats(
        observed_pool, observed_exact, synthetic,
        attr=ATTR, unit=UNIT, date_label=DATE_LABEL, aggregate="mean",
    )

    # Diurnal range is the second thing a temperature series has to get right: a
    # generator can match the daily mean while flattening or exaggerating the swing.
    obs_range = observed_pool.max(axis=1) - observed_pool.min(axis=1)
    syn_range = synthetic.max(axis=1) - synthetic.min(axis=1)
    print(f"\n    4. swing   daily range (max - min, {UNIT}):")
    print(f"               observed pool  mean {obs_range.mean():5.2f}  sd {obs_range.std():5.2f}")
    print(f"               synthetic      mean {syn_range.mean():5.2f}  sd {syn_range.std():5.2f}")
    print(f"               coldest hour: observed {int(np.nanargmin(observed_pool.median()))}:00, "
          f"synthetic {int(np.nanargmin(np.median(synthetic, axis=0)))}:00")

    print("\nSaving...")
    save_frame(ensemble_frame(synthetic), f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}_ensemble.csv")
    save_frame(stats, f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}_stats.csv", index=False)

    fig = plot_day_envelope(
        observed_pool, observed_exact, synthetic,
        attr=ATTR, unit=UNIT, date_label=DATE_LABEL,
        site_label=HERAKLION.name, window_days=POOL_DAYS, aggregate="mean",
    )
    save_figure(fig, f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}.png")

    print("\n  Note how much of the ensemble's spread is set at hour 0 and simply carried")
    print("  through the day. That is persistence doing its job, and it is why pi(x0) has")
    print("  to be a fitted distribution rather than a fixed starting value.")
    return fig


if __name__ == "__main__":
    main()
    plt.show()

# %%
