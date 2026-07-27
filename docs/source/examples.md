# Examples

`examples/` is organised by purpose:

| Folder | What lives there |
| :--- | :--- |
| `examples/use_cases/` | Applied workflows that produce data — generate, check against the record, write to disk. Heraklion 2010–2020. |
| `examples/concepts/` | How the package behaves — training windows, leap days, the Markov engine, exploratory plots. Paris 2011–2012. |
| `examples/tools/` | Shared helpers the scripts import, plus a runnable cache-priming script. Not part of the package. |

Downloads are cached under `examples/data/`; everything generated is written to
the git-ignored `examples/output/`.

```bash
# Optional: prime the cache once, so no script waits on PVGIS
uv run python examples/tools/fetch_site_data.py

# Concepts
uv run python examples/concepts/example_exploratory_analysis.py
uv run python examples/concepts/example_markov_generation.py
uv run python examples/concepts/example_rolling_window.py
uv run --extra examples python examples/concepts/example_synthetic_year.py   # ~80 s
uv run python examples/concepts/example_leap_year_windows.py                 # no PVGIS needed

# Use cases
uv run --extra examples python examples/use_cases/day_envelope_pv.py         # also _temp, _wind
uv run --extra examples python examples/use_cases/synthetic_year.py          # ~4 min
uv run --extra examples python examples/use_cases/monthly_statistics.py      # ~3 min
```

Sections 1–6 below walk through the concept scripts; section 7 covers the use
cases.

## 1. Exploratory analysis

`examples/concepts/example_exploratory_analysis.py` shows the data-preparation and
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

`examples/concepts/example_markov_generation.py` builds an `EnvSeriesGenerator` for
plane-of-array direct irradiance and plots several synthetic daily profiles.

```{mermaid}
flowchart LR
    L["load_or_fetch_data()"] --> M["MetDataProcessor"]
    M --> May["get_month_subset(5)"]
    May --> G["EnvSeriesGenerator(attr_str='poa_direct')"]
    G --> P["gen_day() &times; 10"]
    P --> Plot["plot 24-hour profiles"]
```

```python
from meteosynth import MetDataProcessor, EnvSeriesGenerator

mdp = MetDataProcessor(df)
may = mdp.get_month_subset(5)

generator = EnvSeriesGenerator(may, attr_str="poa_direct")
rng = np.random.default_rng(42)
profiles = [generator.gen_day(rng=rng) for _ in range(10)]
```

## 3. Rolling day windows

`examples/concepts/example_rolling_window.py` contrasts the two training strategies. A
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
leap = DayWindowGenerator(mdp, attr_str="poa_direct").gen_day(2, 29)
```

```{note}
With only two years of data both strategies pool ~62 days, so the window buys
*centring* and *smoothness*, not sample size. See `docs/design/completed/rolling-day-window.md`.
```

## 4. A full synthetic year

`examples/concepts/example_synthetic_year.py` walks a 365-day non-leap calendar and draws
one synthetic day per date for both `poa_direct` and `wind_speed`, writing an
8760-hour series to `examples/output/concepts_synthetic_year_paris.csv`.

Walking a real non-leap year means Feb 29 is simply never requested — there is no
filtering or exclusion list. `DayWindowGenerator` fits each day on demand behind
a small LRU cache, so the year holds a few hundred KB rather than the ~126 MB all
366 fitted generators would cost.

```python
import pandas as pd
from meteosynth import MetDataProcessor, DayWindowGenerator

mdp = MetDataProcessor(df)
generator = DayWindowGenerator(mdp, attr_str="wind_speed", n_days=15, cache_size=4)

# One call. Day 1 starts from pi(x0); every later midnight uses that day's own
# cross-midnight model. include_feb29 defaults to False, giving a 365-day year.
year = generator.generate_series(start=(1, 1), n_days=365, seed=42)   # (365, 24)
```

```{note}
`generate_series` replaces what used to be a hand-rolled loop in this example:
walk the calendar, pass the previous day's 23:00 as `start_value`, repeat. Day 1 now
starts from the fitted initial distribution π(x₀) instead of a guessed seed, and each
midnight uses that day's own cross-midnight model — fitted from real consecutive-day
pairs, rather than the hour-0 transition that actually paired midnight with 23:00 of
the *same* day.
```

The script checks itself against the data it learned from. On the shipped
2011–2012 Paris record the seasonal shape tracks closely (correlation 0.95 for
`poa_direct`, peak month May in both), while absolute irradiance overshoots by
~14%.

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

`examples/concepts/example_leap_year_windows.py` answers two questions the shipped record
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
rng = np.random.default_rng(42)
ensemble = np.vstack([gen.gen_day(rng=rng) for _ in range(1000)])

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

## 7. Use cases

`examples/use_cases/` runs the sketch above for real, on eleven full years of
Heraklion, Crete data (2010–2020, PVGIS). Each script writes what it generates to
the git-ignored `examples/output/`.

### Does a synthetic day look like a real one?

`day_envelope_pv.py`, `day_envelope_temp.py` and `day_envelope_wind.py` each draw
200 independent synthetic 21 Mays and hold them against the eleven observed
21 Mays plus the percentile envelope of the surrounding fortnight. Three checks,
because a generator can pass one and fail another:

| Check | What it asks | Where it can go wrong |
| :--- | :--- | :--- |
| **shape** | does the synthetic median trace the observed diurnal cycle? | peak at the wrong hour |
| **spread** | what share of synthetic hours land inside the observed p10–p90? | ~80 % is calibrated; far above means the ensemble is too narrow |
| **quantity** | does the daily total (or mean) land in the right place? | the number an energy model consumes, and the one that can be wrong while the shape looks right |

```python
from meteosynth import DayWindowGenerator, MetDataProcessor

mdp = MetDataProcessor(df)                                    # Heraklion 2010-2020
generator = DayWindowGenerator(mdp, attr_str="poa_global", n_days=15)

# 200 independent draws of the same date: each call redraws pi(x0), so these are
# samples of 21 May's climate rather than one 200-day walk.
rng = np.random.default_rng(42)
may21 = generator.for_day(5, 21)
ensemble = np.vstack([may21.gen_day(rng=rng) for _ in range(200)])   # (200, 24)
```

The three quantities are separate scripts because they behave differently:
`poa_global` is degenerate at night (π(x₀) collapses to a spike at zero and ~10 of
the day's models are constant) and sits on its support bound at dawn;
`temp_air` never degenerates and is dominated by persistence, so a day's level is
largely set at midnight; `wind_speed` fans out fastest and is judged on `v³`,
where a small bias in mean speed becomes a larger one in power.

### A whole synthetic year

`synthetic_year.py` writes an 8760-hour series of all three attributes and checks
the generated climatology against the observed one — monthly means, seasonal
shape correlation, annual totals. No plots; the point is the file.

### An ensemble of months

`monthly_statistics.py` generates 12 synthetic Mays and reports them against the
eleven observed ones: level, spread, P50/P90 (energy-finance convention — the
value *exceeded* in that share of cases), and the diurnal shape.

```{note}
Read the **spread** row first: the ratio of synthetic to observed standard
deviation across months. On the shipped configuration irradiance and temperature
land near 1, while monthly mean wind spreads ~2.5× wider than the eleven real
Mays do — a study built on that ensemble would price a wind tail the record does
not support. It is the kind of thing only an ensemble reveals; no amount of
looking at individual days shows it.
```

## Interactive use

Every snippet above runs cleanly in a Jupyter notebook or a VS Code interactive
window (the dev environment ships Jupyter, `notebook` and `ipykernel`). Because
each simulator exposes plotting helpers (`plot_joint_distribution`,
`plot_conditional_densities`, `plot_transition_slice`), it is convenient to
explore the fitted densities cell-by-cell.
```
