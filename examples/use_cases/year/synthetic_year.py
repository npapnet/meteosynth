#%%
"""
Use case: generate a complete synthetic year and write it to disk.

One 8760-hour series per attribute for Heraklion, chained day by day across midnight,
trained on the +/-15 day rolling window around each calendar day of the 2010-2020
record. This script exists to *produce data*: the file it writes is the input to
whatever comes next (a PV yield model, a battery sizing run, a demand simulation).

Plots are **off by default** for that reason. Set ``PLOT_HEATMAP = True`` for a
year-at-a-glance figure -- day of year across, hour of day down, one panel per
attribute -- which is the quickest way to see that the seasonal envelope and the
lengthening summer day are both there.

What the output is, and is not:

* It **is** one plausible realisation of a year at this site. Every hour is drawn, not
  copied; the series never repeats a historical year.
* It is **not** a forecast of any particular year, and one realisation is not a
  Monte-Carlo study. Raise ``N_REALISATIONS`` for that -- each one is an independent
  draw, and the spread between them is the quantity the whole exercise is for.

Mechanics worth knowing while it runs:

* **Non-leap is the default.** ``generate_series`` walks 365 days from 1 January with
  ``include_feb29=False``, so Feb 29 is simply never requested. There is no filtering
  step and no exclusion list; ask for a leap year instead and Feb 29 generates like any
  other day.
* **Memory stays flat.** Holding all 366 fitted generators would cost ~126 MB per
  attribute. ``DayWindowGenerator`` fits each day on demand behind a small LRU cache,
  so the walk holds a few hundred KB however long it runs. Fitting dominates the
  runtime, which is why a second realisation is nearly free if you raise
  ``CACHE_SIZE`` to 366 and pay the memory instead.
* **Every midnight is a real transition.** Day 1 starts from 1 January's fitted pi(x0);
  every later day's hour 0 comes from that day's cross-midnight model, conditioned on
  the previous day's 23:00 value.

Output lands in ``examples/output/`` (git-ignored): one CSV per realisation, plus a
monthly summary table checking the generated climatology against the observed one, and
the heatmap if it was asked for.

Run with::

    uv run --extra examples python examples/use_cases/year/synthetic_year.py

Runtime: ~4 min per realisation for all three attributes.
"""

import pathlib
import sys
import time

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path.cwd()
_EXAMPLES = next(p for c in (_HERE, *_HERE.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

from meteosynth import DayWindowGenerator, MetDataset
from tools.site_data import HERAKLION, HERAKLION_YEARS, load_site, save_figure, save_frame

ATTRS = ["poa_global", "temp_air", "wind_speed"]
REFERENCE_YEAR = 2023     # a non-leap calendar to hang timestamps on
N_REALISATIONS = 1
WINDOW_DAYS = 15
CACHE_SIZE = 8            # raise towards 366 to make extra realisations cheap
SEED = 2026
PLOT_HEATMAP = False      # True writes year_<site>_<year>_heatmap.png alongside the CSV

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

#%%


def hourly_index(year: int) -> pd.DatetimeIndex:
    """The 8760 hourly timestamps of a non-leap reference year."""
    index = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    if len(index) != 8760:
        raise ValueError(f"{year} is a leap year; pick a non-leap REFERENCE_YEAR")
    return index


def generate_year(ds: MetDataset, attr: str, seed: int) -> np.ndarray:
    """One chained 365-day series for one attribute. Returns shape ``(365, 24)``.

    The progress bar is worth having here because the walk is slow for a reason worth
    seeing: each calendar day fits its own generators on first visit, so the bar moves
    steadily rather than stalling, and a run that has stopped moving is a real signal
    rather than ordinary patience.
    """
    generator = DayWindowGenerator(
        ds, attr_str=attr, n_days=WINDOW_DAYS, cache_size=CACHE_SIZE
    )
    started = time.perf_counter()
    days = generator.generate_series(start=(1, 1), n_days=365, seed=seed, progress=True)
    tqdm.write(f"    {attr:12} {time.perf_counter() - started:5.0f}s   "
               f"finite={np.isfinite(days).all()}  "
               f"range {days.min():8.2f} .. {days.max():8.2f}  "
               f"cached generators held: {len(generator._cache)}")
    return days


def monthly_summary(frame: pd.DataFrame, observed: pd.DataFrame) -> pd.DataFrame:
    """Monthly means, generated against the record they were learned from.

    A synthetic year is only useful if its seasonal shape is the real one. This is the
    cheapest check that it is, and the first thing to look at before using the file.
    """
    rows = []
    for attr in ATTRS:
        obs = observed.groupby("month")[attr].mean()
        syn = frame[attr].groupby(frame.index.month).mean()
        for month in range(1, 13):
            rows.append({"attr": attr, "month": month, "month_name": MONTHS[month - 1],
                         "observed_mean": obs[month], "synthetic_mean": syn[month]})
    return pd.DataFrame(rows)


def print_summary(summary: pd.DataFrame, frame: pd.DataFrame, observed: pd.DataFrame) -> None:
    for attr in ATTRS:
        block = summary[summary["attr"] == attr]
        obs = block["observed_mean"].to_numpy()
        syn = block["synthetic_mean"].to_numpy()
        print(f"\n  {attr} -- monthly mean, generated vs observed:")
        print("           " + "".join(f"{m:>7}" for m in MONTHS))
        print("  observed " + "".join(f"{v:7.1f}" for v in obs))
        print("  synthetic" + "".join(f"{v:7.1f}" for v in syn))
        print(f"  seasonal shape correlation {np.corrcoef(obs, syn)[0, 1]:.3f}   "
              f"overall bias {syn.mean() / obs.mean() - 1:+.1%}   "
              f"peak month observed {MONTHS[int(np.argmax(obs))]}, "
              f"synthetic {MONTHS[int(np.argmax(syn))]}")

    observed_annual = observed.groupby("year")["poa_global"].sum().mean() / 1000
    print(f"\n  annual poa_global total : {frame['poa_global'].sum() / 1000:7.0f} kWh/m2 "
          f"(observed mean year: {observed_annual:.0f})")
    print(f"  mean air temperature    : {frame['temp_air'].mean():7.2f} degC "
          f"(observed: {observed['temp_air'].mean():.2f})")
    print(f"  mean wind speed         : {frame['wind_speed'].mean():7.2f} m/s "
          f"(observed: {observed['wind_speed'].mean():.2f})")
    print("\n  Individual months wander by a degree or two, and should: this is one draw,")
    print("  not a climatology. It is the annual totals and the shape correlation that")
    print("  have to hold up, and the month-to-month scatter is the variability the whole")
    print("  exercise exists to sample. Average N realisations and it flattens out.")
    print("  Treat absolute irradiance magnitudes as uncalibrated -- the generator")
    print("  overshoots observed daily totals (see TODOs.md); the seasonal shape is sound.")


def plot_year(frame: pd.DataFrame):
    """A heatmap per attribute: day of year across, hour of day down.

    The whole year on one axis, which the monthly table cannot show: the seasonal
    envelope, and the summer day widening at both ends rather than just getting
    brighter. Imported lazily so the default data-only run needs no matplotlib.
    """
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(ATTRS), 1, figsize=(13, 3 * len(ATTRS)), squeeze=False)
    for ax, attr in zip(axes.ravel(), ATTRS):
        grid = frame[attr].to_numpy().reshape(-1, 24).T          # (24 hours, 365 days)
        image = ax.imshow(grid, aspect="auto", origin="lower", cmap="viridis",
                          extent=[1, grid.shape[1], 0, 24])
        ax.set_ylabel("Hour of day")
        ax.set_title(f"Synthetic {REFERENCE_YEAR} (non-leap), {HERAKLION.name}: {attr}")
        fig.colorbar(image, ax=ax, label=attr)
    axes.ravel()[-1].set_xlabel("Day of year")
    fig.tight_layout()
    return fig


def main():
    ds = load_site(HERAKLION, *HERAKLION_YEARS)
    print(ds.describe_time_range())
    print(f"Generating {N_REALISATIONS} synthetic year(s) of {ATTRS} "
          f"on a {REFERENCE_YEAR} (non-leap) calendar.\n")

    index = hourly_index(REFERENCE_YEAR)
    written = []

    # Outer bar over the whole run, inner bar over each attribute's 365-day walk. Two
    # levels because the two questions are different: "how far through the job am I"
    # and "is the current series still moving".
    overall = tqdm(
        total=N_REALISATIONS * len(ATTRS),
        desc="synthetic years",
        unit="series",
        position=0,
    )
    for realisation in range(N_REALISATIONS):
        tqdm.write(f"  realisation {realisation + 1}/{N_REALISATIONS}:")
        frame = pd.DataFrame(index=index)
        frame.index.name = "timestamp"
        for attr in ATTRS:
            # A distinct seed per (realisation, attribute): the attributes are modelled
            # independently, so sharing one stream would not couple them anyway -- but a
            # distinct seed makes each series reproducible on its own.
            frame[attr] = generate_year(ds, attr, seed=SEED + 1000 * realisation
                                        + ATTRS.index(attr)).ravel()
            overall.update(1)

        name = f"year_{HERAKLION.key}_{REFERENCE_YEAR}_r{realisation + 1:02d}.csv"
        written.append(save_frame(frame, name))

        if realisation == 0:
            summary = monthly_summary(frame, ds.met_data)
            print_summary(summary, frame, ds.met_data)
            save_frame(summary, f"year_{HERAKLION.key}_monthly_summary.csv", index=False)
            if PLOT_HEATMAP:
                save_figure(plot_year(frame),
                            f"year_{HERAKLION.key}_{REFERENCE_YEAR}_heatmap.png")

    overall.close()

    print(f"\n  Feb 29 present in the output: "
          f"{((index.month == 2) & (index.day == 29)).any()}")
    print(f"\nDone. {len(written)} synthetic year(s) written to {written[0].parent}")
    return written


if __name__ == "__main__":
    main()

# %%
