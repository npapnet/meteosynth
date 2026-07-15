# Examples

Five runnable scripts live under `examples/`. All but the last fetch data from
PVGIS on first run and cache it to `data/pvgis_hourly_data.xlsx`, so subsequent
runs are offline and fast.

```bash
uv run python examples/example_exploratory_analysis.py
uv run python examples/example_markov_generation.py
uv run python examples/example_rolling_window.py
uv run --extra examples python examples/example_synthetic_year.py   # ~80 s
uv run python examples/example_leap_year_windows.py                 # no PVGIS needed
```

## 1. Exploratory analysis

`examples/example_exploratory_analysis.py` shows the data-preparation and
visualisation side: fetch hourly data, wrap it in `MetDataProcessor`, subset a
month, reshape to daily-wide format, and produce diagnostic plots via
`sup_plot_lib` (2D KDE contours, hourly boxplots, mean ± error bars, and a
Seaborn faceted line plot).

```python
from meteosynth import MetDataProcessor
import meteosynth.sup_plot_lib as spl

mdp = MetDataProcessor(df)
month_data = mdp.get_month_subset(5)              # May
wide = mdp.get_monthly_attribute_wide_format(     # days x hours
    value_col="poa_direct", month_id=5)

spl.plot_2d_kde_sns(month_data, value_str="poa_direct")
```

## 2. Synthetic generation

`examples/example_markov_generation.py` builds an `EnvSeriesGenerator` for
plane-of-array direct irradiance and plots several synthetic daily profiles.

```{mermaid}
flowchart LR
    L["load_or_fetch_data()"] --> M["MetDataProcessor"]
    M --> May["get_month_subset(5)"]
    May --> G["EnvSeriesGenerator(attr_str='poa_direct')"]
    G --> P["gen_day_sequence() &times; 10"]
    P --> Plot["plot 24-hour profiles"]
```

```python
from meteosynth import MetDataProcessor, EnvSeriesGenerator

mdp = MetDataProcessor(df)
may = mdp.get_month_subset(5)

generator = EnvSeriesGenerator(may, attr_str="poa_direct")
profiles = [generator.gen_day_sequence(start_value=0.0) for _ in range(10)]
```

## 3. Rolling day windows

`examples/example_rolling_window.py` contrasts the two training strategies. A
month subset is *off-centre* — a May 1 model trained on all of May inherits May
16's climate — and it *jumps*, since May 31 and June 1 share no training data at
all. A rolling window is centred on its target and slides smoothly.

The script demonstrates the year-boundary wrap, shows that Feb 29 needs no
special handling, and generates profiles for the same target day from each
strategy so the centring bias is visible.

```python
from meteosynth import MetDataProcessor, DayWindowGenerator

mdp = MetDataProcessor(df)

# Both pool ~62 days from the 2-year record, around different centres.
may_month = mdp.get_month_subset(5)                          # all of May
may_window = mdp.get_day_window_subset(5, 1, n_days=15)      # Apr 16 - May 16

# The window wraps across New Year with no special-casing.
new_year = mdp.get_day_window_subset(1, 2, n_days=4)         # Dec 29 - Jan 6

# Feb 29 is an ordinary target.
leap = DayWindowGenerator(mdp, attr_str="poa_direct").gen_day_sequence(2, 29)
```

```{note}
With only two years of data both strategies pool ~62 days, so the window buys
*centring* and *smoothness*, not sample size. See `docs/design/rolling-day-window.md`.
```

## 4. A full synthetic year

`examples/example_synthetic_year.py` walks a 365-day non-leap calendar and draws
one synthetic day per date for both `poa_direct` and `wind_speed`, writing an
8760-hour series to `data/synthetic_year.csv`.

Walking a real non-leap year means Feb 29 is simply never requested — there is no
filtering or exclusion list. `DayWindowGenerator` fits each day on demand behind
a small LRU cache, so the year holds a few hundred KB rather than the ~126 MB all
366 fitted generators would cost.

```python
import pandas as pd
from meteosynth import MetDataProcessor, DayWindowGenerator

mdp = MetDataProcessor(df)
generator = DayWindowGenerator(mdp, attr_str="wind_speed", n_days=15, cache_size=4)

calendar = pd.date_range("2023-01-01", "2023-12-31", freq="D")   # 365 days
previous = 3.9                                                   # hour-0 seed
for date in calendar:
    profile = generator.for_day(date.month, date.day).gen_day_sequence(
        start_value=previous)
    previous = profile[-1]        # chain: tomorrow's 00:00 follows tonight's 23:00
```

```{note}
Each day is chained from the previous day's 23:00 value rather than started at a
fixed `0.0`. Zero is right for irradiance at midnight, but it is a value wind
*never* takes — it sits outside the hour-0 model's domain, forcing it to
extrapolate. Chaining reduces to `0.0` automatically for irradiance.
```

The script checks itself against the data it learned from. On the shipped
2011–2012 Paris record the seasonal shape tracks closely (correlation 0.95 for
`poa_direct`, peak month May in both), while absolute irradiance overshoots by
~13%.

```{note}
That overshoot is a known open issue (see `TODOs.md`), and it is not the rolling
window — a month-based generator overshoots by the same margin. Nor is it simply
the bandwidth: the bias survives every bandwidth, including Scott's rule.
Irradiance piles against a hard floor at zero, and a symmetric kernel
renormalised onto a `[0, max]` domain pushes mass upward. Treat absolute
magnitudes as uncalibrated for zero-floored variables; the seasonal shape is
sound.
```

## 5. Leap years and the end of February

`examples/example_leap_year_windows.py` answers two questions the shipped record
cannot demonstrate, because it spans only 2011–2012 and holds one leap day. It
builds synthetic records in memory instead — 2011–2020 (leap: 2012, 2016, 2020)
and 2021–2023 (none) — so it needs no PVGIS fetch.

**Does a Feb 28 window pick up Feb 29 from the leap years, and Mar 1 from all of
them?** Yes:

```text
  day      slot  years   contributing years
  02-26     57     10   all ten
  02-27     58     10   all ten
  02-28     59     10   all ten
  02-29     60      3   2012, 2016, 2020  <-- leap years only
  03-01     61     10   all ten
```

**With no leap year in the record at all, can Feb 29 still be generated?** Also
yes — slot 60 contributes nothing, and the day is interpolated from Feb 14 –
Mar 15:

```text
  get_day_window_subset(2, 29, n_days=15)
    pooled days      : 90
    calendar span    : 02-14 .. 03-15  (30 distinct days)
    real Feb 29 in it: False   <-- the record has none to give
```

The script also prints exactly where the leap day enters and leaves a window as
`n_days` grows, and the non-leap deficit. See {doc}`theory` for the `all_leap`
calendar behind it.

## 6. A Monte-Carlo sketch for energy output

Putting it together for the target use case — turning synthetic irradiance days
into a distribution of daily energy yield:

```python
import numpy as np
from meteosynth import MetDataProcessor, EnvSeriesGenerator

mdp = MetDataProcessor(df)
june = mdp.get_month_subset(6)

gen = EnvSeriesGenerator(june, attr_str="poa_direct", bandwidth=0.1)

# 1000 synthetic June days -> (1000, 24) array of hourly irradiance
ensemble = gen.generate_ensemble(n_days=1000, start_value=0.0, seed=42)

# Convert to a simple daily-energy proxy (W/m2 summed over hours -> Wh/m2)
module_area_m2 = 1.6
module_eff = 0.20
daily_wh = ensemble.sum(axis=1) * module_area_m2 * module_eff

print(f"P50 daily yield : {np.percentile(daily_wh, 50):8.1f} Wh")
print(f"P90 daily yield : {np.percentile(daily_wh, 90):8.1f} Wh")
print(f"P10 daily yield : {np.percentile(daily_wh, 10):8.1f} Wh")
```

The percentile spread across the ensemble is exactly the quantity an energy
Monte-Carlo consumes: a distribution of outcomes rather than a single number.

## Interactive use

Every snippet above runs cleanly in a Jupyter notebook or a VS Code interactive
window (the dev environment ships Jupyter, `notebook` and `ipykernel`). Because
each simulator exposes plotting helpers (`plot_joint_distribution`,
`plot_conditional_densities`, `plot_transition_slice`), it is convenient to
explore the fitted densities cell-by-cell.
```
