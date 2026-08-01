# Examples

`examples/` is organised by purpose:

| Folder | What lives there |
| :--- | :--- |
| `examples/use_cases/` | Applied workflows that produce data — generate, check against the record, write to disk. Heraklion 2010–2020. Split by time scale into `day/`, `month/` and `year/`, each with its own README. |
| `examples/concepts/` | How the package behaves — training windows, leap days, the Markov engine, exploratory plots. Paris 2011–2012. |
| `examples/diagnostics-overshoot/` | A measurement rather than a demonstration: does the generator reproduce the distribution it was fitted to? Four steps behind one `run_all.py`, with the design, the decision rule and the dated findings committed alongside. |
| `examples/tools/` | Shared helpers the scripts import, plus a runnable cache-priming script. Not part of the package. |

Downloads are cached under `examples/data/`; everything generated is written to
the git-ignored `examples/output/`.

```bash
# Optional: prime the cache once, so no script waits on PVGIS
uv run python examples/tools/fetch_site_data.py

# Concepts
uv run python examples/concepts/example_exploratory_analysis.py
uv run python examples/concepts/example_rolling_window.py
uv run python examples/concepts/example_leap_year_windows.py                 # no PVGIS needed

# Use cases
uv run python examples/use_cases/day/day_envelope_pv.py     # also _temp, _wind
uv run python examples/use_cases/month/monthly_statistics.py  # ~3 min
uv run python examples/use_cases/year/synthetic_year.py     # ~4 min

# Diagnostics
uv run python examples/diagnostics-overshoot/run_all.py     # ~5 min
```

Sections 1–4 below walk through the concept scripts; section 5 covers the use
cases, one per time scale; section 6 the diagnostics.

## 1. Exploratory analysis

`examples/concepts/example_exploratory_analysis.py` shows the data-preparation and
visualisation side: fetch hourly data, wrap it in `MetDataset`, subset a
month, reshape to daily-wide format, and produce diagnostic plots via
`sup_plot_lib` (2D KDE contours, hourly boxplots, mean ± error bars, and a
Seaborn faceted line plot).

```python
from meteosynth import MetDataset
import meteosynth.sup_plot_lib as spl

ds = MetDataset(df)
month_data = ds.get_month_subset(5)              # May
wide = ds.get_monthly_attribute_wide_format(     # days x hours
    value_col="poa_direct", month_id=5)

spl.plot_2d_kde_sns(month_data, value_str="poa_direct")
```

## 2. Rolling day windows

`examples/concepts/example_rolling_window.py` contrasts the two training strategies. A
month subset is *off-centre* — a May 1 model trained on all of May inherits May
16's climate — and it *jumps*, since May 31 and June 1 share no training data at
all. A rolling window is centred on its target and slides smoothly.

The script demonstrates the year-boundary wrap, shows that Feb 29 needs no
special handling, and generates profiles for the same target day from each
strategy so the centring bias is visible.

```python
from meteosynth import MetDataset, DayWindowGenerator

ds = MetDataset(df)

# Both pool ~62 days from the 2-year record, around different centres.
may_month = ds.get_month_subset(5)                          # all of May
may_window = ds.get_day_window_subset(5, 1, n_days=15)      # Apr 16 - May 16

# The window wraps across New Year with no special-casing.
new_year = ds.get_day_window_subset(1, 2, n_days=4)         # Dec 29 - Jan 6

# Feb 29 is an ordinary target.
leap = DayWindowGenerator(ds, attr_str="poa_direct").gen_day(2, 29)
```

```{note}
With only two years of data both strategies pool ~62 days, so the window buys
*centring* and *smoothness*, not sample size. See
`docs/design/completed/rolling-day-window.md`.
```

## 3. Leap years and the end of February

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

## 4. A Monte-Carlo sketch for energy output

Putting it together for the target use case — turning synthetic irradiance days
into a distribution of daily energy yield:

```python
import numpy as np
from meteosynth import MetDataset, DayWindowGenerator

ds = MetDataset(df)
generator = DayWindowGenerator(ds, attr_str="poa_global", n_days=15)

# 1000 synthetic 21 Junes -> (1000, 24) array of hourly irradiance. Fit once with
# for_day, then draw repeatedly from one RNG stream.
june21 = generator.for_day(6, 21)
rng = np.random.default_rng(42)
ensemble = np.vstack([june21.gen_day(rng=rng) for _ in range(1000)])

# Convert to a simple daily-energy proxy (W/m2 summed over hours -> Wh/m2)
module_area_m2 = 1.6
module_eff = 0.20
daily_wh = ensemble.sum(axis=1) * module_area_m2 * module_eff

print(f"P50 daily yield : {np.percentile(daily_wh, 50):8.1f} Wh")
print(f"P90 daily yield : {np.percentile(daily_wh, 10):8.1f} Wh")  # exceeded 90% of the time
```

The percentile spread across the ensemble is exactly the quantity an energy
Monte-Carlo consumes: a distribution of outcomes rather than a single number.

```{note}
P50/P90 here follow the **energy-finance convention**: the value *exceeded* in
that share of cases. P90 is therefore the pessimistic figure — the one a lender
asks about — and it sits at the 10th percentile.
```

## 5. Use cases: a day, a month, a year

`examples/use_cases/` runs the sketch above for real, on eleven full years of
Heraklion, Crete data (2010–2020, PVGIS). Each script writes what it generates to
the git-ignored `examples/output/`.

They are grouped by the **time scale of the question** — `day/`, `month/`, `year/` —
because the scale changes what can be asked, and each folder carries a README saying
what its scripts answer, what they write and how long they take. All three build on the
same rolling-window base:

```python
import numpy as np
import pandas as pd
from meteosynth import DayWindowGenerator, MetDataset

ds = MetDataset(df)                                  # Heraklion 2010-2020
generator = DayWindowGenerator(ds, attr_str="poa_global", n_days=15)
```

| Scale | Call | What it can be checked against |
| :--- | :--- | :--- |
| **Day** | `gen_day` / `for_day`, looped | eleven observed 21 Mays, and the percentile envelope of the surrounding fortnight |
| **Month** | `generate_series((5, 1), 31)`, looped | eleven observed Mays — level, spread, P50/P90 |
| **Year** | `generate_series((1, 1), 365)` | the observed climatology: monthly means, seasonal shape, annual total |

### Day — does a synthetic day look like a real one?

`day/day_envelope_pv.py`, `day_envelope_temp.py` and `day_envelope_wind.py` each draw
200 independent synthetic 21 Mays and hold them against the eleven observed
21 Mays plus the percentile envelope of the surrounding fortnight. Three checks,
because a generator can pass one and fail another:

| Check | What it asks | Where it can go wrong |
| :--- | :--- | :--- |
| **shape** | does the synthetic median trace the observed diurnal cycle? | peak at the wrong hour |
| **spread** | what share of synthetic hours land inside the observed p10–p90? | ~80 % is calibrated; far above means the ensemble is too narrow |
| **quantity** | does the daily total (or mean) land in the right place? | the number an energy model consumes, and the one that can be wrong while the shape looks right |

```python
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

### Month — an ensemble of Mays

`month/monthly_statistics.py` generates 12 synthetic Mays and reports them against the
eleven observed ones: level, spread, P50/P90, and the diurnal shape. A month is a
*chained* series, because a month is about order — streaks of dull days, a monthly total,
a battery's state of charge.

```python
generator = DayWindowGenerator(ds, attr_str="poa_global", n_days=15, cache_size=40)

# One RNG stream across realisations: each call still redraws pi(x0), so these are
# twelve independent Mays rather than one long chain.
rng = np.random.default_rng(7)
months = np.vstack([
    generator.generate_series(start=(5, 1), n_days=31, rng=rng).ravel()
    for _ in range(12)
])                                                             # (12, 744) hours
```

`cache_size=40` holds the whole month, so fitting is paid once and the eleven realisations
after the first only pay for sampling.

```{note}
Read the **spread** row first: the ratio of synthetic to observed standard
deviation across months. On the shipped configuration irradiance and temperature
land near 1, while monthly mean wind spreads ~2.5× wider than the eleven real
Mays do — a study built on that ensemble would price a wind tail the record does
not support. It is the kind of thing only an ensemble reveals; no amount of
looking at individual days shows it.
```

### Year — a complete 8760-hour series

`year/synthetic_year.py` writes an 8760-hour series of all three attributes and checks
the generated climatology against the observed one — monthly means, seasonal shape
correlation, annual totals. The point is the file, so plots are off by default; set
`PLOT_HEATMAP = True` for a year-at-a-glance figure.

```python
generator = DayWindowGenerator(ds, attr_str="wind_speed", n_days=15, cache_size=8)

# One call. Day 1 starts from pi(x0); every later midnight uses that day's own
# cross-midnight model. include_feb29 defaults to False, giving a 365-day year.
year = generator.generate_series(start=(1, 1), n_days=365, seed=42)   # (365, 24)

index = pd.date_range("2023-01-01", periods=365 * 24, freq="h")
series = pd.Series(year.ravel(), index=index, name="wind_speed")
```

Walking a 365-day year means Feb 29 is simply never requested — there is no filtering
step and no exclusion list. `DayWindowGenerator` fits each day on demand behind a small
LRU cache, so the walk holds a few hundred KB rather than the ~126 MB all 366 fitted
generators would cost.

```{note}
Seasonal shape tracks the observed record closely, and so do absolute magnitudes: measured
against the pooled window the generator is fitted to, on a 19-year Heraklion record, the
mean daily total comes out within 0.7 % of observed at four dates through the year.

What *is* off is the **overcast tail** — the model produces roughly four times too few
heavily overcast days (`FIX-1` in `TODOs.md`). Irradiance piles against a hard floor at
zero, and a symmetric kernel cannot put enough mass near the bound without putting some
below it.

How much that matters depends entirely on what you are asking. It moves an **annual P90 by
0.12 %**, so a yield study cannot see it. It does affect anything that reads the dark end
directly — **storage autonomy, worst-case days, a daily P10** (up to 9 % high). Deferred
rather than fixed for exactly that reason.
```

## 6. Diagnostics: settling a claim about accuracy

`examples/diagnostics-overshoot/` is how a claim about generator accuracy gets settled in
this repo. Four separately-runnable steps behind one `run_all.py` (~5 min): fetch a
19-year record, draw 1000 synthetic days at each of four dates against two bandwidths,
score them, and plot.

What makes it evidence rather than a demonstration is the design:

- **The training pool is the reference.** Each configuration compares the 285 observed
  days in a date's window against 1000 synthetic days drawn from the generator fitted to
  those same 285 — so the comparison target is a known quantity, not an estimate of one,
  and there is no choice of reference to defend.
- **A null control** — the observed pool resampled in place of the synthetic sample —
  covers 88 of 90 statistics, against the 5% a 95% interval permits.
- **A positive control** — the synthetic sample inflated 10% — is recovered as a lift of
  1.100 in 9 of 9 configurations. So a negative result means "there is no effect", not
  "the instrument cannot see one".
- **An anchor cell** reproduces an earlier pass's numbers with a different harness.

Its findings are committed alongside the code (`FINDINGS-2026-07-28.md`), and they are
what the accuracy statements elsewhere in this documentation cite: no overshoot at the
shipped bandwidth at any of four dates, an under-produced overcast tail, and Scott's rule
rejected as the irradiance default.

## Interactive use

Every snippet above runs cleanly in a Jupyter notebook or a VS Code interactive
window (the dev environment ships Jupyter, `notebook` and `ipykernel`). Because
each simulator exposes plotting helpers (`plot_joint_distribution`,
`plot_conditional_densities`, `plot_transition_slice`), it is convenient to
explore the fitted densities cell-by-cell.
