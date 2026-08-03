#%%
"""
Use case: an ensemble of synthetic months, reported as statistics.

Generates ``N_REALISATIONS`` independent synthetic Mays for Heraklion -- each one a
chained 31-day series, hour by hour, across all three attributes -- and reports what
the ensemble says, next to what the eleven observed Mays in the 2010-2020 record say.

This is the shape a real study takes. A single synthetic month tells you nothing you
could not read off the historical data; an *ensemble* of them answers the question the
historical data cannot, because eleven Mays is too few to put a number on the tail:

* **How much does May vary?** The spread across realisations is the generator's answer,
  and comparing it to the spread across observed years is the check on that answer. Too
  narrow and the study will understate risk; too wide and it will overstate it.
* **What is the P90 month?** Energy finance quotes P50 and P90 -- the value exceeded in
  50% and 90% of cases. Eleven observations give a P90 that moves if you add one year;
  a 12-realisation ensemble already gives a steadier one, and 500 gives a usable one.
* **Where does the variability live?** The report separates the mean level from the
  diurnal shape, because a month can be low-yield because every day was dull or because
  a few days were catastrophic, and those are different engineering problems.

On the shipped configuration the first two land close -- monthly irradiance and mean
temperature match the observed years in both level and spread -- while monthly mean
**wind** spreads about 2.5x wider than the eleven real Mays do. That is the script
earning its keep: a wind study built on this ensemble would price a tail that the
record does not support, and no amount of looking at individual days would have shown
it.

Nothing is plotted. Every realisation is written to ``output/`` beside this file (git-ignored)
in long format, along with the statistics table below, so the numbers can be re-derived
or taken into another tool without re-running the generator.

Run with::

    uv run python examples/use_cases/month/monthly_statistics.py

Runtime: ~3 min for 12 realisations of all three attributes. Fitting is paid once --
``CACHE_SIZE`` holds the whole month, so later realisations only pay for sampling.
"""

import calendar
import sys
import time

import numpy as np
import pandas as pd

from meteosynth import workspace

#: This script's own folder. `data/` and `output/` sit beside it, wherever the script
#: is launched from -- so the example is self-contained and can be copied anywhere.
#: `globals().get` rather than `__file__` because this also runs as `#%%` cells, where
#: there is no file and the working directory is the honest answer.
WS = workspace(globals().get("__file__"))
# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_EXAMPLES = next(p for c in (WS.root, *WS.root.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

from meteosynth import DayWindowGenerator, MetDataset
from tools.site_data import HERAKLION, HERAKLION_YEARS, load_site, save_frame

MONTH = 5                 # May
REFERENCE_YEAR = 2023     # non-leap, for hanging timestamps on
N_REALISATIONS = 12
WINDOW_DAYS = 15
SEED = 7

#: How each attribute is aggregated to one number per month, and in what units.
#: Irradiance accumulates (energy); temperature and wind are levels, so they average.
AGGREGATION = {
    "poa_global": ("sum", 1e-3, "kWh/m2 per month"),
    "temp_air": ("mean", 1.0, "degC"),
    "wind_speed": ("mean", 1.0, "m/s"),
}
ATTRS = list(AGGREGATION)

#: Hold the whole month, so realisations 2..N reuse the fitted models rather than
#: refitting all 31 days. ~0.35 MB per day per attribute -- cheap at this size, which
#: is exactly the trade the LRU cache exists to let you make.
CACHE_SIZE = 40

#%%


def month_index(year: int, month: int) -> pd.DatetimeIndex:
    """Hourly timestamps covering one calendar month."""
    n_days = calendar.monthrange(year, month)[1]
    return pd.date_range(f"{year}-{month:02d}-01", periods=n_days * 24, freq="h")


def generate_months(ds: MetDataset, n_days: int) -> dict[str, np.ndarray]:
    """Generate the ensemble: ``{attr: array of shape (N_REALISATIONS, n_days * 24)}``."""
    out = {}
    for attr in ATTRS:
        generator = DayWindowGenerator(
            ds, attr_str=attr, n_days=WINDOW_DAYS, cache_size=CACHE_SIZE
        )
        started = time.perf_counter()
        # One RNG stream across realisations: each call still redraws pi(x0), so the
        # realisations are independent months rather than one long chain.
        rng = np.random.default_rng(SEED + ATTRS.index(attr))
        series = np.vstack([
            generator.generate_series(start=(MONTH, 1), n_days=n_days, rng=rng).ravel()
            for _ in range(N_REALISATIONS)
        ])
        print(f"    {attr:12} {time.perf_counter() - started:5.0f}s   "
              f"{series.shape[0]} x {series.shape[1]} hours   "
              f"finite={np.isfinite(series).all()}")
        out[attr] = series
    return out


def _aggregate(hourly: np.ndarray, how: str, scale: float) -> np.ndarray:
    """Collapse each row of hourly values to one number per month."""
    return (hourly.sum(axis=1) if how == "sum" else hourly.mean(axis=1)) * scale


def describe(values: np.ndarray) -> dict:
    """The summary a monthly report is built from.

    ``p50``/``p90`` follow the energy-finance convention: the value **exceeded** in that
    share of cases, so P90 is the pessimistic one and sits at the 10th percentile.
    """
    values = np.asarray(values, dtype=float)
    return {
        "n": len(values),
        "mean": values.mean(),
        "sd": values.std(ddof=1) if len(values) > 1 else 0.0,
        "cv": values.std(ddof=1) / values.mean() if len(values) > 1 else 0.0,
        "min": values.min(),
        "p90": np.percentile(values, 10),
        "p50": np.percentile(values, 50),
        "p10": np.percentile(values, 90),
        "max": values.max(),
    }


def observed_months(ds: MetDataset, attr: str) -> pd.Series:
    """One aggregated value per observed year -- the eleven real Mays."""
    how, scale, _ = AGGREGATION[attr]
    subset = ds.met_data[ds.met_data["month"] == MONTH]
    return subset.groupby("year")[attr].agg(how) * scale


def diurnal_shape(hourly: np.ndarray) -> np.ndarray:
    """Mean value by hour of day, over every day of every realisation."""
    return hourly.reshape(-1, 24).mean(axis=0)


def report(ds: MetDataset, ensemble: dict[str, np.ndarray]) -> pd.DataFrame:
    """Print the statistics table and return it as a frame."""
    rows = []
    month_name = calendar.month_name[MONTH]
    n_years = ds.met_data["year"].nunique()

    for attr in ATTRS:
        how, scale, unit = AGGREGATION[attr]
        observed = observed_months(ds, attr)
        synthetic = _aggregate(ensemble[attr], how, scale)

        obs_stats = describe(observed.to_numpy())
        syn_stats = describe(synthetic)

        print(f"\n{'=' * 78}")
        print(f"{attr}  --  monthly {how} ({unit}),  {month_name}")
        print("=" * 78)
        print(f"  {'':10}{'n':>4}{'mean':>9}{'sd':>8}{'cv':>7}"
              f"{'min':>9}{'P90':>9}{'P50':>9}{'P10':>9}{'max':>9}")
        for label, stats in [("observed", obs_stats), ("synthetic", syn_stats)]:
            print(f"  {label:10}{stats['n']:4d}{stats['mean']:9.2f}{stats['sd']:8.2f}"
                  f"{stats['cv']:7.2f}{stats['min']:9.2f}{stats['p90']:9.2f}"
                  f"{stats['p50']:9.2f}{stats['p10']:9.2f}{stats['max']:9.2f}")

        level_bias = syn_stats["mean"] / obs_stats["mean"] - 1
        spread_ratio = syn_stats["sd"] / obs_stats["sd"] if obs_stats["sd"] else np.nan
        obs_shape = (ds.met_data[ds.met_data["month"] == MONTH]
                     .groupby("hour")[attr].mean().to_numpy())
        syn_shape = diurnal_shape(ensemble[attr])
        shape_corr = float(np.corrcoef(obs_shape, syn_shape)[0, 1])

        print(f"\n  level  : synthetic mean is {level_bias:+.1%} against the observed years")
        print(f"  spread : synthetic sd / observed sd = {spread_ratio:.2f}   "
              f"(1.0 = the ensemble varies like the weather does)")
        print(f"  shape  : mean diurnal profile correlation = {shape_corr:.3f}")
        print(f"  years observed: " + ", ".join(f"{y}:{v:.1f}" for y, v in observed.items()))

        rows.append({
            "attr": attr, "aggregation": how, "unit": unit,
            **{f"observed_{k}": v for k, v in obs_stats.items()},
            **{f"synthetic_{k}": v for k, v in syn_stats.items()},
            "level_bias": level_bias, "spread_ratio": spread_ratio,
            "diurnal_shape_correlation": shape_corr,
        })

    print(f"\n{'=' * 78}")
    print("  Read `spread` first -- it is the number that decides whether the ensemble is")
    print("  usable, and the one most likely to be wrong. Below 1 the synthetic months")
    print("  vary less than real ones and every risk figure downstream is optimistic;")
    print("  above 1 the study overstates the tail and oversizes whatever it is sizing.")
    print("  Expect the three attributes to disagree here: month-to-month irradiance and")
    print("  temperature are largely set by the seasonal cycle the model is fitted to,")
    print("  while monthly mean wind is nearly constant between real years, so the daily")
    print("  independence between synthetic days has much more room to accumulate.")
    print(f"  Note the observed sd rests on {n_years} years, so it is itself uncertain --")
    print("  do not chase a ratio of exactly 1.")
    return pd.DataFrame(rows)


def long_frame(ensemble: dict[str, np.ndarray], index: pd.DatetimeIndex) -> pd.DataFrame:
    """All realisations in one long frame: realisation, timestamp, one column per attribute."""
    frames = []
    for realisation in range(N_REALISATIONS):
        frame = pd.DataFrame(
            {attr: ensemble[attr][realisation] for attr in ATTRS}, index=index
        )
        frame.index.name = "timestamp"
        frame.insert(0, "realisation", realisation + 1)
        frames.append(frame)
    return pd.concat(frames)


def main():
    ds = load_site(WS, HERAKLION, *HERAKLION_YEARS)
    print(ds.describe_time_range())

    index = month_index(REFERENCE_YEAR, MONTH)
    n_days = len(index) // 24
    print(f"\nGenerating {N_REALISATIONS} synthetic {calendar.month_name[MONTH]}s "
          f"({n_days} days, {len(index)} hours each) for {HERAKLION.name}:")
    ensemble = generate_months(ds, n_days)

    stats = report(ds, ensemble)

    print("\nSaving...")
    save_frame(WS, long_frame(ensemble, index),
               f"month_{HERAKLION.key}_{MONTH:02d}_ensemble.csv")
    save_frame(WS, stats, f"month_{HERAKLION.key}_{MONTH:02d}_statistics.csv", index=False)
    return stats


if __name__ == "__main__":
    main()

# %%
