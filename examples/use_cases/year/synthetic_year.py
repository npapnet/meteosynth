#%%
"""
Use case: generate an ensemble of synthetic years and write it to disk.

``N_REALISATIONS`` independent 8760-hour series per attribute for Heraklion, each chained
day by day across midnight, trained on the +/-15 day rolling window around each calendar
day of the 2010-2020 record. This script exists to *produce data*: the file it writes is
the input to whatever comes next (a PV yield model, a battery sizing run, a demand
simulation).

Plots are **off by default** for that reason. Set ``PLOT_HEATMAP = True`` for a
year-at-a-glance figure of the first realisation -- day of year across, hour of day down,
one panel per attribute -- which is the quickest way to see that the seasonal envelope and
the lengthening summer day are both there.

What the output is, and is not:

* Each realisation **is** one plausible year at this site. Every hour is drawn, not copied;
  no series repeats a historical year.
* No realisation is a forecast of any particular year. The **spread between them** is the
  quantity the whole exercise is for, which is why the ensemble rather than the single
  series is the useful object.
* Attributes are generated **independently**. Within a realisation a hot hour is not
  thereby a sunny one -- cross-attribute correlation is not modelled. The file records
  this in its own metadata.

Mechanics worth knowing while it runs:

* **The calendar is walked once, not once per realisation.** ``write_ensemble`` fits each
  day's models a single time and advances every realisation through them, which is what
  makes hundreds of realisations affordable. Generating them one at a time refits every day
  for every realisation, because an ordered walk never revisits a calendar slot and so the
  LRU cache never hits.
* **Memory stays flat regardless of N.** One day's generators are alive at a time, and the
  ensemble is streamed to parquet one calendar day per row group rather than accumulated.
* **Non-leap is the default.** The walk covers 365 days from 1 January with
  ``include_feb29=False``, so Feb 29 is never requested -- no filtering step, no exclusion
  list. Ask for a leap year instead and Feb 29 generates like any other day.
* **Every midnight is a real transition.** Day 1 starts from 1 January's fitted pi(x0);
  every later day's hour 0 comes from that day's cross-midnight model, conditioned on *that
  realisation's own* previous 23:00 value.
* **Reproducibility is per realisation and per attribute.** Realisation *i* of attribute *a*
  depends on ``(SEED, i, a)`` and nothing else, so realisation 3 is the same series whether
  you generate 10 or 10 000, and ``temp_air`` does not change when you add ``wind_speed``
  alongside it. (One caveat, documented on ``generate_ensemble``: the sampler switches above
  64 realisations, so pass ``precompute=`` explicitly if you need two *differently sized*
  ensembles to agree to the last digit.)

Output lands in ``examples/output/`` (git-ignored): one parquet ensemble, a monthly summary
table checking the generated climatology against the observed one, and -- if asked for --
an ``.xlsx`` copy and the heatmap.

Run with::

    uv run --extra examples python examples/use_cases/year/synthetic_year.py

Runtime: roughly 21 min per attribute for a 1000-realisation year, against ~27 h to
generate the same thing one series at a time -- a 77x reduction, measured.
"""

import pathlib
import sys
import time

import numpy as np
import pandas as pd

# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path.cwd()
_EXAMPLES = next(p for c in (_HERE, *_HERE.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

from meteosynth import MetDataset, read_ensemble, write_ensemble
from tools.site_data import (HERAKLION, HERAKLION_YEARS, load_site, output_path,
                             save_figure, save_frame)

ATTRS = ["poa_global", "temp_air", "wind_speed"]
REFERENCE_YEAR = 2023     # a non-leap calendar to hang timestamps on
N_REALISATIONS = 10       # the point of the ensemble; raise to hundreds for a real study
N_DAYS = 365              # lower it to try the script out without waiting for a full year
WINDOW_DAYS = 15
SEED = 2026
PLOT_HEATMAP = False      # True writes year_<site>_<year>_heatmap.png alongside the data
WRITE_XLSX = False        # True also writes an .xlsx (needs `uv sync --extra excel`)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

#%%


def hourly_index(year: int, n_days: int = N_DAYS) -> pd.DatetimeIndex:
    """Hourly timestamps for the generated span, on a non-leap reference calendar."""
    full = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    if len(full) != 8760:
        raise ValueError(f"{year} is a leap year; pick a non-leap REFERENCE_YEAR")
    return full[: n_days * 24]


def realisation_frame(ensemble, index: pd.DatetimeIndex, i: int) -> pd.DataFrame:
    """One realisation as a timestamped wide frame, the shape downstream tools expect.

    The ensemble file is long by design -- that is what let it stream -- so pulling a
    single realisation out is a view rather than a different product.
    """
    one = ensemble.realisation(i)
    frame = pd.DataFrame({attr: one[attr].to_numpy() for attr in ATTRS}, index=index)
    frame.index.name = "timestamp"
    return frame


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
    print("  exercise exists to sample.")


def ensemble_spread(ensemble) -> pd.DataFrame:
    """Annual totals and means per realisation -- the reason to generate more than one.

    A single series cannot show this. The spread across realisations is the model's
    statement about year-to-year variability, and it is what a P50/P90 is computed from.
    """
    rows = []
    for attr in ATTRS:
        wide = ensemble.to_wide(attr)                       # 8760 hours x N realisations
        annual = wide.sum(axis=0) if attr == "poa_global" else wide.mean(axis=0)
        rows.append({
            "attr": attr,
            "statistic": "annual total (kWh/m2)" if attr == "poa_global" else "annual mean",
            "value": annual.mean() / (1000 if attr == "poa_global" else 1),
            "p10": annual.quantile(0.10) / (1000 if attr == "poa_global" else 1),
            "p90": annual.quantile(0.90) / (1000 if attr == "poa_global" else 1),
            "cv_percent": 100 * annual.std() / annual.mean(),
        })
    return pd.DataFrame(rows)


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
    print(f"Generating an ensemble of {N_REALISATIONS} synthetic year(s) of {ATTRS} "
          f"on a {REFERENCE_YEAR} (non-leap) calendar.")
    print("One calendar walk for the whole ensemble: each day's models are fitted once "
          "and shared by every realisation.\n")

    index = hourly_index(REFERENCE_YEAR, N_DAYS)
    path = output_path(
        f"ensemble_{HERAKLION.key}_{REFERENCE_YEAR}_n{N_REALISATIONS}.parquet"
    )

    started = time.perf_counter()
    meta = write_ensemble(
        ds, ATTRS, path,
        start=(1, 1), n_days=N_DAYS, n_realisations=N_REALISATIONS,
        seed=SEED, n_days_window=WINDOW_DAYS, include_feb29=False, progress=True,
    )
    elapsed = time.perf_counter() - started
    size_mb = path.stat().st_size / 1024**2
    print(f"\n  wrote {path.name}: {size_mb:.1f} MB, {elapsed/60:.1f} min "
          f"({elapsed/max(N_REALISATIONS, 1):.0f}s per realisation for all "
          f"{len(ATTRS)} attributes)")
    print(f"  embedded metadata: seed={meta['seed']}, "
          f"n_realisations={meta['n_realisations']}, window=+/-{meta['window_n_days']}d")

    ensemble = read_ensemble(path)
    first = realisation_frame(ensemble, index, 0)

    # The climatology checks below compare against *annual* observed statistics, so they
    # only mean anything for a full year. A shortened N_DAYS is for trying the script out.
    if N_DAYS == 365:
        summary = monthly_summary(first, ds.met_data)
        print_summary(summary, first, ds.met_data)
        save_frame(summary, f"year_{HERAKLION.key}_monthly_summary.csv", index=False)

        if N_REALISATIONS > 1:
            spread = ensemble_spread(ensemble)
            print(f"\n  spread across {N_REALISATIONS} realisations "
                  f"-- the quantity a single series cannot give you:")
            print(spread.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
            save_frame(spread, f"year_{HERAKLION.key}_ensemble_spread.csv", index=False)
    else:
        print(f"\n  N_DAYS={N_DAYS} rather than 365, so the monthly and annual checks are "
              f"skipped -- they compare against annual observed statistics.")

    # A single realisation as CSV, for anything that would rather read one series than an
    # ensemble. The parquet file remains the record: it carries the provenance.
    save_frame(first, f"year_{HERAKLION.key}_{REFERENCE_YEAR}_r01.csv")

    if WRITE_XLSX:
        from meteosynth import ensemble_to_xlsx
        xlsx = path.with_suffix(".xlsx")
        ensemble_to_xlsx(ensemble, xlsx)
        print(f"  wrote {xlsx.name} (one sheet per attribute, hours x realisations)")

    if PLOT_HEATMAP:
        save_figure(plot_year(first),
                    f"year_{HERAKLION.key}_{REFERENCE_YEAR}_heatmap.png")

    print(f"\n  Feb 29 present in the output: "
          f"{((index.month == 2) & (index.day == 29)).any()}")
    print(f"\nDone. Ensemble at {path}")
    return path


if __name__ == "__main__":
    main()

# %%
