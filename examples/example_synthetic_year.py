#%%
"""
Example: Generate a Full Synthetic Non-Leap Year (wind_speed and poa_direct)

Generates a chained 365-day series per attribute, each day drawn from a generator
trained on the +/- 15 day rolling window centred on that day, and each midnight carried
by that day's cross-midnight model. The result is an 8760-hour series per attribute,
written next to the cached PVGIS data.

Two things this demonstrates:

**Non-leap is the default, not a special case.** We walk a real non-leap reference year
(2023), so Feb 29 is simply never requested -- no filtering, no exclusion list. Ask for a
leap year instead and Feb 29 generates like any other day (see `example_rolling_window.py`).

**Memory stays bounded.** Holding all 366 fitted generators would cost ~126 MB per
attribute. `DayWindowGenerator` fits each day on demand behind a small LRU cache instead,
so a whole year holds a few hundred KB. Fitting is cheap (~58 ms); it is sampling that
dominates the runtime below.

The two attributes behave differently, which is the point of generating both:

* `poa_direct` is zero every night, so ~10 of its hourly models collapse to
  `Kind.CONSTANT`, and its pi(x0) is degenerate.
* `wind_speed` never stops, so all of its models are ordinary 2D KDEs (`Kind.KDE_2D`).

That difference also shows in how each day *starts*. There is no seed value to supply:
hour 0 is drawn from the day's fitted initial distribution pi(x0). For `poa_direct`
every observed midnight is zero, so pi(x0) is a spike at zero and irradiance starts at
0.0 -- from the data, not from a hard-coded default. For `wind_speed` it is a real
distribution over observed midnight wind speeds, a value the old fixed 0.0 default never
took and which used to force the hour-0 model to extrapolate outside its data.

Run with::

    uv run python examples/example_synthetic_year.py

Runtime: ~80 s for both attributes on the shipped 2-year dataset.
"""

import pathlib
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pvlib.iotools import get_pvgis_hourly

from meteosynth import DayWindowGenerator, MetDataProcessor

DATA_DIR = pathlib.Path("./data")
DATA_DIR.mkdir(exist_ok=True)
XLSX_FNAME = DATA_DIR / "pvgis_hourly_data.xlsx"
OUT_FNAME = DATA_DIR / "synthetic_year.csv"

# A non-leap reference year: walking it means Feb 29 is never asked for.
REFERENCE_YEAR = 2023
ATTRS = ["poa_direct", "wind_speed"]
N_DAYS = 15
SEED = 42


def load_or_fetch_data() -> pd.DataFrame:
    """Load PVGIS hourly data from cache, or download it if missing."""
    if XLSX_FNAME.exists():
        print(f"Loading cached weather data from {XLSX_FNAME}...")
        return pd.read_excel(XLSX_FNAME)

    print("No cached data found. Fetching hourly data from PVGIS for Paris...")
    data, _ = get_pvgis_hourly(
        latitude=48.8566, longitude=2.3522, start=2011, end=2012,
        usehorizon=True, outputformat="json", components=True,
    )
    data["year"] = data.index.year
    data["month"] = data.index.month
    data["day"] = data.index.day
    data["hour"] = data.index.hour
    data.to_excel(XLSX_FNAME, index=False)
    print(f"Data saved to {XLSX_FNAME}")
    return data


def generate_year(mdp: MetDataProcessor, attr: str, n_days_out: int) -> np.ndarray:
    """Generate a chained synthetic year.

    This used to be a hand-rolled loop right here: walk the calendar, call
    ``gen_day_sequence(start_value=previous_value)``, then set
    ``previous_value = profile[-1]`` to chain across midnight -- seeding the first day
    with ``climatological_start``, the mean observed 23:00 value nearby. That was a
    single number standing in for a distribution, read off the wrong hour, and fed into
    an hour-0 transition that paired midnight with 23:00 of the *same* day.

    ``generate_series`` replaces all of it and does it properly: day 1 starts from that
    day's fitted initial distribution pi(x0), and every later midnight uses that day's
    own cross-midnight model, fitted from real consecutive-day pairs.

    Returns an array of shape (n_days_out, 24).
    """
    print(f"\nGenerating {n_days_out} days of '{attr}'...")
    generator = DayWindowGenerator(mdp, attr_str=attr, n_days=N_DAYS, cache_size=4)

    started = time.perf_counter()
    # include_feb29=False is the default, so a 365-day walk never visits Feb 29.
    days = generator.generate_series(start=(1, 1), n_days=n_days_out, seed=SEED)

    print(f"  done in {time.perf_counter() - started:.0f}s")
    print(f"  hour 0 of Jan 1, drawn from pi(x0): {days[0, 0]:.2f}")
    print(f"  cached generators still held: {len(generator._cache)} "
          f"-- memory stays flat however long the walk")
    return days


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def compare_to_observed(frame: pd.DataFrame, source: pd.DataFrame, attr: str, unit: str):
    """Check the generated climatology against the data it was trained on.

    A synthetic year is only useful if its seasonal shape is the real one, so this is
    worth looking at rather than trusting the generator blindly.
    """
    observed = source.groupby("month")[attr].mean()
    synthetic = frame[attr].groupby(frame.index.month).mean()

    print(f"\n  {attr} monthly mean ({unit}) -- generated vs the data it learned from:")
    print("           " + "".join(f"{m:>7}" for m in MONTH_NAMES))
    print("  observed " + "".join(f"{observed[m]:7.1f}" for m in range(1, 13)))
    print("  synthetic" + "".join(f"{synthetic[m]:7.1f}" for m in range(1, 13)))

    correlation = np.corrcoef(observed.to_numpy(), synthetic.to_numpy())[0, 1]
    bias = synthetic.mean() / observed.mean() - 1
    print(f"  seasonal shape correlation: {correlation:.3f}   "
          f"overall bias: {bias:+.0%}   "
          f"peak month: observed {MONTH_NAMES[observed.idxmax() - 1]}, "
          f"synthetic {MONTH_NAMES[synthetic.idxmax() - 1]}")


def plot_year(frame: pd.DataFrame):
    """A heatmap per attribute: day of year across, hour of day down."""
    fig, axes = plt.subplots(len(ATTRS), 1, figsize=(13, 7), squeeze=False)
    axes = axes.ravel()
    for ax, attr in zip(axes, ATTRS):
        grid = frame[attr].to_numpy().reshape(-1, 24).T  # (24 hours, 365 days)
        im = ax.imshow(grid, aspect="auto", origin="lower", cmap="viridis",
                       extent=[1, len(grid[0]), 0, 24])
        ax.set_ylabel("Hour of day")
        ax.set_title(f"Synthetic {REFERENCE_YEAR} (non-leap): {attr}")
        fig.colorbar(im, ax=ax, label=attr)
    axes[-1].set_xlabel("Day of year")
    fig.tight_layout()
    return fig


def main():
    df = load_or_fetch_data()
    mdp = MetDataProcessor(df)
    print(mdp.describe_time_range())

    calendar = pd.date_range(f"{REFERENCE_YEAR}-01-01", f"{REFERENCE_YEAR}-12-31", freq="D")
    assert len(calendar) == 365, "reference year must not be a leap year"
    print(f"\nTarget calendar: {REFERENCE_YEAR}, {len(calendar)} days (no Feb 29).")

    hourly_index = pd.date_range(
        f"{REFERENCE_YEAR}-01-01", f"{REFERENCE_YEAR}-12-31 23:00", freq="h"
    )
    frame = pd.DataFrame(index=hourly_index)
    frame.index.name = "timestamp"

    for attr in ATTRS:
        frame[attr] = generate_year(mdp, attr, len(calendar)).ravel()

    print(f"\nGenerated series: {frame.shape[0]} hours x {frame.shape[1]} attributes")
    print(f"  all finite: {np.isfinite(frame.to_numpy()).all()}")
    print(f"  Feb 29 present: {((frame.index.month == 2) & (frame.index.day == 29)).any()}")

    compare_to_observed(frame, df, "poa_direct", "W/m2")
    compare_to_observed(frame, df, "wind_speed", "m/s")

    observed_annual = df.groupby("year")["poa_direct"].sum().mean() / 1000
    print(f"\n  annual poa_direct total : {frame['poa_direct'].sum() / 1000:.0f} kWh/m2 "
          f"(observed: {observed_annual:.0f})")
    print(f"  mean wind speed         : {frame['wind_speed'].mean():.2f} m/s "
          f"(observed: {df['wind_speed'].mean():.2f})")
    print("\n  The seasonal shape is learned from the data, including the sunny May and")
    print("  cloudy June this particular 2011-2012 Paris record happens to contain -- it")
    print("  is not a smooth idealised curve.")
    print("\n  The poa_direct overshoot is a known open issue (see TODOs.md), and it is")
    print("  not the rolling window: a month-based generator overshoots by the same")
    print("  margin. Nor is it simply the bandwidth -- the bias survives every bandwidth,")
    print("  including Scott's rule. Treat absolute magnitudes as uncalibrated; the")
    print("  seasonal shape is sound.")

    frame.to_csv(OUT_FNAME)
    print(f"\nWritten to {OUT_FNAME}")

    plot_year(frame)
    plt.show()
    print("\nDone.")


if __name__ == "__main__":
    main()

# %%
