#%%
"""
Example: Rolling Day Windows vs. Calendar-Month Subsets

Transition models need a training subset. `meteosynth` offers two strategies, and this
script contrasts them:

* `MetDataset.get_month_subset(5)`      -- every day in May.
* `MetDataset.get_day_window_subset(5, 1, n_days=15)` -- every day within 15 days
  of May 1, pooled across all years.

The month split has two defects the window fixes. It is **off-centre**: a model for
May 1 trains on data whose centre of mass sits on May 16, biased ~15 days late in the
season. And it **jumps**: May 31 and June 1 train on completely disjoint data, so the
generator steps discontinuously at every month boundary.

Note what the window does *not* buy: with only 2 years of data both strategies pool ~62
days, so this is about *centring* and *smoothness*, not sample size.

See `docs/design/completed/rolling-day-window.md` for the full rationale.
"""

import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np

from meteosynth import (
    DayWindowGenerator,
    EnvSeriesGenerator,
    MetDataset,
    convert_to_daily_wide,
    day_slot,
)

# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path.cwd()
_EXAMPLES = next(p for c in (_HERE, *_HERE.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

from tools.site_data import load_paris_demo

ATTR = "poa_direct"


def _observed_daily_total(subset) -> float:
    """Mean observed daily total of ATTR in a subset, in kWh/m2."""
    return convert_to_daily_wide(subset, ATTR).sum(axis=1).mean() / 1000


def compare_subsets(ds: MetDataset):
    """Show that a month subset is really centred on the middle of the month."""
    print("\n1. Centring: both pool the same number of days, around different centres")

    month_data = ds.get_month_subset(5)
    may01 = ds.get_day_window_subset(5, 1, n_days=15)
    may16 = ds.get_day_window_subset(5, 16, n_days=15)

    print(f"   get_month_subset(5)                    -> {month_data['date_id'].nunique():3d} days, all of May")
    print(f"   get_day_window_subset(5, 1, n_days=15) -> {may01['date_id'].nunique():3d} days, Apr 16 - May 16")

    print("\n   Mean OBSERVED daily total in each training set (kWh/m2):")
    print(f"     month subset (all of May)     : {_observed_daily_total(month_data):.2f}")
    print(f"     window centred on May 16      : {_observed_daily_total(may16):.2f}  <- identical")
    print(f"     window centred on May 1       : {_observed_daily_total(may01):.2f}")
    print("   The month subset and the May-16 window contain the same climate. That is the")
    print("   bias precisely: ask for a May 1 model from a month subset and you are handed")
    print("   a May 16 one.")


def show_year_boundary_wrap(ds: MetDataset):
    """The window wraps across New Year; a month subset cannot."""
    print("\n2. The year boundary wraps, with no special-casing")

    for month, day in [(1, 2), (12, 30)]:
        subset = ds.get_day_window_subset(month, day, n_days=4)
        days = sorted({(m, d) for m, d in zip(subset["month"], subset["day"])})
        pretty = ", ".join(f"{m:02d}-{d:02d}" for m, d in days)
        print(f"   target {month:02d}-{day:02d}, n_days=4 -> {pretty}")


def show_leap_day(ds: MetDataset):
    """Feb 29 is an ordinary day: pooled into neighbours, and requestable itself."""
    print("\n3. Feb 29 needs no special handling")

    nearby = ds.get_day_window_subset(2, 27, n_days=3)
    print(f"   Feb 29's data is pooled into the Feb 27 window: "
          f"{'2012-2-29' in set(nearby['date_id'])}")

    leap = ds.get_day_window_subset(2, 29, n_days=15)
    print(f"   Feb 29 is requestable as a target -> {leap['date_id'].nunique()} days pooled "
          f"(slot {day_slot(2, 29)})")
    print("   (61 not 62: only 2012 has a real leap day to contribute)")


def show_smoothness(ds: MetDataset):
    """The month boundary discontinuity, and its absence."""
    print("\n4. Smoothness across a month boundary")

    may31 = ds.get_day_window_subset(5, 31, n_days=15)
    jun01 = ds.get_day_window_subset(6, 1, n_days=15)
    shared = set(may31["day_slot"]) & set(jun01["day_slot"])
    print(f"   window May 31 vs Jun 1 : {len(shared)}/31 days shared  <- slides smoothly")

    month_may = set(ds.get_month_subset(5)["date_id"])
    month_jun = set(ds.get_month_subset(6)["date_id"])
    print(f"   month  May    vs Jun   : {len(month_may & month_jun)} days shared      "
          f"<- a hard jump on June 1")


def plot_comparison(ds: MetDataset, n_profiles: int = 25):
    """Draw synthetic days for the same target from each strategy, and compare."""
    print(f"\n5. Generating {n_profiles} synthetic profiles for May 1 from each strategy...")

    month_gen = EnvSeriesGenerator(ds.get_month_subset(5), attr_str=ATTR)
    window_gen = DayWindowGenerator(ds, attr_str=ATTR, n_days=15).for_day(5, 1)

    # One generator drives both draws, so the comparison differs only in the training
    # data, not in the randomness. An ensemble is now an explicit loop: pi(x0) is
    # redrawn per call, so every profile gets its own realistic start.
    rng = np.random.default_rng(42)
    month_days = np.vstack([month_gen.gen_day(rng=rng) for _ in range(n_profiles)])
    window_days = np.vstack([window_gen.gen_day(rng=rng) for _ in range(n_profiles)])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, days, title in [
        (axes[0], month_days, "Month subset (all of May)\ncentred on May 16"),
        (axes[1], window_days, "Rolling window (May 1, n=15)\ncentred on May 1"),
    ]:
        ax.plot(days.T, color="tab:blue", alpha=0.25, lw=1)
        ax.plot(days.mean(axis=0), color="tab:red", lw=2.5, label="mean")
        ax.set_title(title)
        ax.set_xlabel("Hour of day")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend()
    axes[0].set_ylabel(f"{ATTR} (W/m$^2$)")
    fig.suptitle("Same target day, two training strategies", fontsize=13)
    fig.tight_layout()

    print("                        generated   training data (observed)")
    print(f"   month subset       :   {month_days.sum(axis=1).mean()/1000:5.2f}          "
          f"{_observed_daily_total(ds.get_month_subset(5)):5.2f}   kWh/m2")
    print(f"   rolling window     :   {window_days.sum(axis=1).mean()/1000:5.2f}          "
          f"{_observed_daily_total(ds.get_day_window_subset(5, 1, n_days=15)):5.2f}   kWh/m2")
    print("\n   The month model generates more sun, tracking the sunnier late-May climate")
    print("   it was trained on. Note both generators overshoot their own training data by")
    print("   a similar margin: that is a known open issue (see TODOs.md), unrelated to the")
    print("   choice of window. So these numbers are for comparing the two strategies, not")
    print("   for calibrated absolute yield.")
    return fig


def main():
    ds = load_paris_demo()
    print(ds.describe_time_range())

    compare_subsets(ds)
    show_year_boundary_wrap(ds)
    show_leap_day(ds)
    show_smoothness(ds)
    plot_comparison(ds)

    plt.show()
    print("\nDone.")


if __name__ == "__main__":
    main()

# %%
