#%%
"""
Use case: does a synthetic 21 May look like a real 21 May?  --  irradiance (PV)

Trains on eleven years of Heraklion data (2010-2020), draws an ensemble of synthetic
21 May profiles of plane-of-array global irradiance, and holds them up against every
21 May the record actually contains plus the envelope of the surrounding fortnight.

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
  ``TODOs.md``), and by a few percent on this eleven-year one. The printout below
  quantifies it rather than hiding it, which is the point of running the comparison at
  all: treat the shape as sound and the absolute magnitude as something you have
  measured rather than assumed.

The ensemble is written to ``examples/output/`` (git-ignored).

Run with::

    uv run --extra examples python examples/use_cases/day_envelope_pv.py

Runtime: ~40 s (one fetch on a cold cache, then ~15 s of sampling).
"""

import pathlib
import sys

import matplotlib.pyplot as plt

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

ATTR = "poa_global"
UNIT = "W/m2"
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

    # The observed cloud: the exact date, and the fortnight around it.
    observed_exact = day_matrix(mdp, ATTR, *TARGET, n_days=0)
    observed_pool = day_matrix(mdp, ATTR, *TARGET, n_days=POOL_DAYS)

    print(f"\nFitting the +/-{WINDOW_DAYS} day window generator for {DATE_LABEL}...")
    generator = DayWindowGenerator(mdp, attr_str=ATTR, n_days=WINDOW_DAYS)
    day_generator = generator.for_day(*TARGET)
    degenerate = [h for h, sim in day_generator.simulators.items() if sim.is_degenerate]
    print(f"  training days pooled : {len(day_matrix(mdp, ATTR, *TARGET, n_days=WINDOW_DAYS))}")
    print(f"  degenerate hours     : {degenerate}")
    print(f"  pi(x0) kind          : {day_generator.initial.kind.name} "
          f"-- every observed midnight is 0 W/m2, so every synthetic day starts there")

    print(f"\nDrawing {N_SYNTHETIC} independent synthetic {DATE_LABEL} profiles...")
    synthetic = synthetic_ensemble(generator, *TARGET, n=N_SYNTHETIC, seed=SEED)

    stats = report_day_stats(
        observed_pool, observed_exact, synthetic,
        attr=ATTR, unit=UNIT, date_label=DATE_LABEL,
        aggregate="sum", aggregate_scale=1e-3, aggregate_unit="kWh/m2",
    )

    print("\nSaving...")
    save_frame(ensemble_frame(synthetic), f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}_ensemble.csv")
    save_frame(stats, f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}_stats.csv", index=False)

    fig = plot_day_envelope(
        observed_pool, observed_exact, synthetic,
        attr=ATTR, unit=UNIT, date_label=DATE_LABEL,
        site_label=HERAKLION.name, window_days=POOL_DAYS,
        aggregate="sum", aggregate_scale=1e-3, aggregate_unit="kWh/m2",
    )
    save_figure(fig, f"day_{DATE_LABEL.replace(' ', '')}_{ATTR}.png")

    print("\n  Read the left panel as: the synthetic band should sit inside the observed")
    print("  one and peak at the same hour. Read the right panel as: the orange mass")
    print("  should overlie the blue. A shift to the right there is the known daily-total")
    print("  overshoot, and it is visible even when the shapes agree.")
    return fig


if __name__ == "__main__":
    main()
    plt.show()

# %%
