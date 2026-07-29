#%%
"""
Example: Leap Years and the End of February

Answers two questions about the rolling window that the shipped PVGIS record cannot
demonstrate, because it spans only 2011-2012 and contains exactly one leap day:

1. With a **multi-year** record containing leap years, does a Feb 28 window pool Feb 29
   from the leap years *and* Mar 1 from every year?
2. With a record containing **no leap years at all**, can Feb 29 still be generated from
   its late-February and early-March neighbours?

Both answers are yes. This script shows it rather than asserting it, using two synthetic
records built in-memory: 2011-2020 (leap years 2012, 2016, 2020) and 2021-2023 (none).
No PVGIS fetch, no cached data.

The mechanism is the ``all_leap`` calendar (CF-conventions ``366_day``): every date maps
to a slot against a fixed *leap* reference year, so Feb 29 owns slot 60 and Mar 1 is
always slot 61 regardless of the year. Non-leap years simply never emit slot 60.

    Jan 1 -> 1  ...  Feb 28 -> 59,  Feb 29 -> 60,  Mar 1 -> 61  ...  Dec 31 -> 366

See `docs/design/completed/rolling-day-window.md` and `docs/source/theory.md`.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from meteosynth import DayWindowGenerator, MetDataProcessor, day_slot

LEAP_RECORD = (2011, 2020)      # leap years: 2012, 2016, 2020
LEAPFREE_RECORD = (2021, 2023)  # leap years: none
N_DAYS = 15

#%%

def synthetic_record(start_year: int, end_year: int, seed: int = 0) -> MetDataProcessor:
    """An hourly record with a realistic diurnal cycle and exactly-zero nights.

    Night values are *exactly* zero, as PVGIS supplies them. `np.sin(np.pi)` is 1.22e-16
    rather than 0, so a clipped sine would leave ~1e-14 residue at dusk. That used to
    defeat the exact `std == 0` degeneracy check; detection is scale-aware since
    2026-07-28, so it no longer would. The mask stays explicit anyway, to keep this
    script demonstrating *leap-year windowing* against clean data.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31 23:00", freq="h")
    hour = index.hour.to_numpy()

    daylight = np.zeros(len(index))
    lit = (hour >= 7) & (hour <= 17)
    daylight[lit] = np.sin((hour[lit] - 6) / 12 * np.pi)
    seasonal = 0.5 + 0.5 * np.sin((index.dayofyear.to_numpy() - 80) / 365 * 2 * np.pi)

    df = pd.DataFrame(
        {"year": index.year, "month": index.month, "day": index.day, "hour": hour}
    )
    df["poa_direct"] = 800 * daylight * seasonal + rng.normal(0, 5, len(index)) * daylight
    df["poa_sky_diffuse"] = 100 * daylight + rng.normal(0, 2, len(index)) * daylight
    df["poa_ground_diffuse"] = 0.0
    df["solar_elevation"] = 60 * daylight
    df["temp_air"] = 15 + 10 * seasonal + rng.normal(0, 1, len(index))
    df["wind_speed"] = np.abs(rng.normal(4, 1.5, len(index)))
    df["Int"] = 0
    return MetDataProcessor(df)


def _years_by_day(subset):
    out = {}
    for year, month, day in zip(subset["year"], subset["month"], subset["day"]):
        out.setdefault((month, day), set()).add(year)
    return out


def question_1(mdp: MetDataProcessor):
    """Feb 28 window on a record that has leap years."""
    print("\n" + "=" * 74)
    print("Q1: 10-year record (2011-2020). Ask for Feb 28, +/- 2 days.")
    print("    Does it pick up Feb 29 from the leap years, and Mar 1 from all of them?")
    print("=" * 74)

    by_day = _years_by_day(mdp.get_day_window_subset(2, 28, n_days=2))
    print(f"\n  {'day':7} {'slot':>5} {'years':>6}   contributing years")
    print("  " + "-" * 66)
    for (month, day) in sorted(by_day):
        years = sorted(by_day[(month, day)])
        shown = ", ".join(str(y) for y in years) if len(years) < 10 else "all ten"
        mark = "  <-- leap years only" if (month, day) == (2, 29) else ""
        print(f"  {month:02d}-{day:02d}  {day_slot(month, day):5d} {len(years):6d}   {shown}{mark}")

    print("\n  Yes. Feb 29 is pooled from the 3 years that have one; every other day")
    print("  from all 10. Mar 1 is reached because it is simply the next slot (61).")


def question_2(mdp: MetDataProcessor):
    """Feb 29 target on a record with no leap years."""
    print("\n" + "=" * 74)
    print("Q2: leap-free record (2021-2023). Ask for Feb 29 itself.")
    print("    With no observed Feb 29 anywhere, can we still build a generator?")
    print("=" * 74)

    subset = mdp.get_day_window_subset(2, 29, n_days=N_DAYS)
    days = sorted({(m, d) for m, d in zip(subset["month"], subset["day"])})
    has_real_leap_day = (2, 29) in days

    print(f"\n  get_day_window_subset(2, 29, n_days={N_DAYS})")
    print(f"    pooled days      : {subset['date_id'].nunique()}")
    print(f"    calendar span    : {days[0][0]:02d}-{days[0][1]:02d} .. "
          f"{days[-1][0]:02d}-{days[-1][1]:02d}  ({len(days)} distinct days)")
    print(f"    real Feb 29 in it: {has_real_leap_day}   <-- the record has none to give")
    print(f"    slot 60 present  : {60 in set(subset['day_slot'])}")

    print("\n  Generating a synthetic Feb 29 anyway:")
    for attr in ("poa_direct", "wind_speed", "temp_air"):
        generator = DayWindowGenerator(mdp, attr_str=attr, n_days=N_DAYS)
        # No start value to supply: hour 0 comes from this day's own pi(x0), fitted
        # from the neighbouring days the window pooled.
        profile = generator.gen_day(2, 29, seed=1)
        print(f"    {attr:16} -> 24 values, finite={np.isfinite(profile).all()}, "
              f"peak={np.nanmax(profile):7.2f}")

    print("\n  Yes. Slot 60 contributes nothing, so Feb 29 is interpolated entirely from")
    print("  Feb 14 - Mar 15. That is the intended behaviour, not a fallback.")


def the_boundary(mdp: MetDataProcessor):
    """Exactly when does the leap day enter a window?"""
    print("\n" + "=" * 74)
    print("Where the leap day enters and leaves a window (10-year record)")
    print("=" * 74)
    print(f"\n  Feb 29 is slot {day_slot(2, 29)}. A window reaches it when |slot - centre| <= n.\n")
    print(f"  {'target':8} {'n':>3} {'slot range':>12}   Feb 29 pooled?")
    print("  " + "-" * 50)
    for month, day, n in [(2, 27, 1), (2, 27, 2), (2, 28, 0), (2, 28, 1),
                          (3, 1, 1), (3, 2, 1), (3, 2, 2), (6, 15, 15)]:
        subset = mdp.get_day_window_subset(month, day, n_days=n)
        centre = day_slot(month, day)
        present = (2, 29) in {(m, d) for m, d in zip(subset["month"], subset["day"])}
        print(f"  {month:02d}-{day:02d}    {n:3d} {centre - n:5d}..{centre + n:<5d}   "
              f"{'yes' if present else 'no'}")


def the_deficit(leap_mdp: MetDataProcessor, free_mdp: MetDataProcessor):
    """Non-leap years contribute one day fewer to any window spanning slot 60."""
    print("\n" + "=" * 74)
    print("The non-leap deficit: why a late-February window pools fewer days")
    print("=" * 74)
    print(f"\n  {'record':12} {'target':8} {'slots':>6} {'days':>6}   note")
    print("  " + "-" * 62)
    for label, mdp, n_years in [("2011-2020", leap_mdp, 10), ("2021-2023", free_mdp, 3)]:
        for month, day, note in [(6, 15, "unaffected (nowhere near slot 60)"),
                                 (2, 29, "spans slot 60")]:
            subset = mdp.get_day_window_subset(month, day, n_days=N_DAYS)
            slots = subset["day_slot"].nunique()
            days = subset["date_id"].nunique()
            print(f"  {label:12} {month:02d}-{day:02d}    {slots:6d} {days:6d}   {note}")
        ref = leap_mdp if label == "2011-2020" else free_mdp
        full = ref.get_day_window_subset(6, 15, n_days=N_DAYS)["date_id"].nunique()
        span = ref.get_day_window_subset(2, 29, n_days=N_DAYS)["date_id"].nunique()
        n_leap = sum(1 for y in range(*( (2011, 2021) if label == "2011-2020" else (2021, 2024)))
                     if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0)
        print(f"  {'':12} {'':8} {'':6} {full - span:6d}   deficit == non-leap years "
              f"({n_years} - {n_leap} = {n_years - n_leap})\n")

    print("  Faithful to the calendar rather than a defect: those days do not exist.")

    subset = leap_mdp.get_day_window_subset(2, 29, n_days=N_DAYS)
    total = subset["date_id"].nunique()
    real = subset[(subset["month"] == 2) & (subset["day"] == 29)]["date_id"].nunique()
    print(f"\n  Worth knowing: even WITH leap years, only {real} of {total} pooled days "
          f"({real / total:.1%}) are")
    print("  real Feb 29 observations. A 'synthetic Feb 29' is overwhelmingly built from")
    print("  its neighbours -- by design.")


def plot_window_membership(leap_mdp, free_mdp):
    """Which (year, calendar-day) cells feed a Feb 29 generator?"""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharex=True)

    for ax, (mdp, label, years) in zip(
        axes,
        [(leap_mdp, "2011-2020 (leap: 2012, 2016, 2020)", range(2011, 2021)),
         (free_mdp, "2021-2023 (no leap years)", range(2021, 2024))],
    ):
        subset = mdp.get_day_window_subset(2, 29, n_days=N_DAYS)
        present = {(y, s) for y, s in zip(subset["year"], subset["day_slot"])}
        slots = range(day_slot(2, 29) - N_DAYS, day_slot(2, 29) + N_DAYS + 1)

        grid = np.array([[1.0 if (y, s) in present else 0.0 for s in slots] for y in years])
        # Mark the leap slot distinctly where it is present.
        for i, y in enumerate(years):
            if (y, 60) in present:
                grid[i][list(slots).index(60)] = 2.0

        ax.imshow(grid, aspect="auto", cmap="YlGnBu", vmin=0, vmax=2,
                  extent=[min(slots) - 0.5, max(slots) + 0.5, max(years) + 0.5, min(years) - 0.5])
        ax.axvline(60, color="crimson", lw=1.5, ls="--", label="slot 60 = Feb 29")
        ax.set_yticks(list(years))
        ax.set_title(f"Feb 29 window (n={N_DAYS})\n{label}", fontsize=10)
        ax.set_xlabel("all_leap slot  (60 = Feb 29)")
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_ylabel("year")
    fig.suptitle("Which observations feed a synthetic Feb 29?  "
                 "(dark = leap day, mid = ordinary day, blank = does not exist)",
                 fontsize=11)
    fig.tight_layout()
    return fig
#%%


print("Building synthetic records in memory (no PVGIS fetch needed)...")
leap_mdp = synthetic_record(*LEAP_RECORD)
free_mdp = synthetic_record(*LEAPFREE_RECORD)
#%%
print(f"  {LEAP_RECORD[0]}-{LEAP_RECORD[1]}: {len(leap_mdp.met_data):6d} hourly rows")
print(f"  {LEAPFREE_RECORD[0]}-{LEAPFREE_RECORD[1]}: {len(free_mdp.met_data):6d} hourly rows")
#%%
question_1(leap_mdp)
#%%
question_2(free_mdp)
the_boundary(leap_mdp)
the_deficit(leap_mdp, free_mdp)

plot_window_membership(leap_mdp, free_mdp)
plt.show()
print("\nDone.")

# Note: this file is a `#%%` cell script -- everything above runs at import time so the
# cells can be stepped through in an editor. There is deliberately no main() to call.

# %%
