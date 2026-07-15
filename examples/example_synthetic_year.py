#%%
"""
Example: Generate a Full Synthetic Non-Leap Year (wind_speed and poa_direct)

Walks a 365-day calendar and, for each day, draws a synthetic 24-hour profile from a
generator trained on the +/- 15 day rolling window centred on that day. The result is an
8760-hour series per attribute, written next to the cached PVGIS data.

Two things this demonstrates:

**Non-leap is the default, not a special case.** We walk a real non-leap reference year
(2023), so Feb 29 is simply never requested -- no filtering, no exclusion list. Ask for a
leap year instead and Feb 29 generates like any other day (see `example_rolling_window.py`).

**Memory stays bounded.** Holding all 366 fitted generators would cost ~126 MB per
attribute. `DayWindowGenerator` fits each day on demand behind a small LRU cache instead,
so a whole year holds a few hundred KB. Fitting is cheap (~58 ms); it is sampling that
dominates the runtime below.

The two attributes behave differently, which is the point of generating both:

* `poa_direct` is zero every night, so ~10 of its 24 hourly models collapse to the
  constant-value (CC) singularity case.
* `wind_speed` never stops, so all 24 of its models are ordinary 2D KDEs (NN).

That difference also drives how a day is seeded. Rather than starting every day at a
fixed 0.0 -- correct for irradiance at midnight, but a value wind *never* takes, which
would ask the hour-0 model to extrapolate outside its data -- each day is chained from
the previous day's 23:00 value. For irradiance that reduces to 0.0 automatically.

Requires
--------
`tqdm`, for the progress bars over the two 365-day generation loops. It ships in the
``examples`` extra rather than as a package dependency, since nothing in ``meteosynth``
itself needs it::

    uv sync --extra examples
    uv run --extra examples python examples/example_synthetic_year.py

    # or, outside uv:
    pip install "meteosynth[examples]"

Runtime: ~80 s for both attributes on the shipped 2-year dataset.
"""

import pathlib
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pvlib.iotools import get_pvgis_hourly
from tqdm import tqdm

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


def climatological_start(mdp: MetDataProcessor, attr: str, month: int, day: int) -> float:
    """A sensible hour-0 seed: the mean observed 23:00 value near this day.

    Only used for the very first day of the year; every later day is chained from the
    day before it.
    """
    window = mdp.get_day_window_subset(month, day, n_days=N_DAYS)
    return float(window[window["hour"] == 23][attr].mean())


def generate_year(mdp: MetDataProcessor, attr: str, calendar: pd.DatetimeIndex) -> np.ndarray:
    """Generate one synthetic day per calendar date, chaining across midnight.

    Returns an array of shape (len(calendar), 24).
    """
    print(f"\nGenerating {len(calendar)} days of '{attr}'...")
    generator = DayWindowGenerator(mdp, attr_str=attr, n_days=N_DAYS, cache_size=4)

    first = calendar[0]
    previous_value = climatological_start(mdp, attr, first.month, first.day)
    print(f"  seeding hour 0 of {first:%b %d} at {previous_value:.2f} "
          f"(mean observed 23:00 value nearby)")

    days = np.empty((len(calendar), 24))
    started = time.perf_counter()
    progress = tqdm(calendar, desc=f"  {attr}", unit="day")
    for i, date in enumerate(progress):
        profile = generator.for_day(date.month, date.day).gen_day_sequence(
            start_value=previous_value, seed=SEED + i
        )
        days[i] = profile
        # Chain: tomorrow's hour 0 is conditioned on tonight's 23:00.
        previous_value = profile[-1]
        # Memory stays flat: the cache never grows past cache_size, however long we walk.
        progress.set_postfix(cached=len(generator._cache), refresh=False)

    print(f"  done in {time.perf_counter() - started:.0f}s")
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
        frame[attr] = generate_year(mdp, attr, calendar).ravel()

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
