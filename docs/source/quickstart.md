# Quickstart

This page gets you from a fresh checkout to a synthetic weather ensemble in a
few minutes.

## Installation

`meteosynth` is managed with [uv](https://docs.astral.sh/uv/).

```bash
# Runtime dependencies + the dev group. Enough to run everything, examples included.
uv sync

# Optional: Excel export of an ensemble (`ensemble_to_xlsx`) -- the only extra there is
uv sync --extra excel
```

This installs `meteosynth` in editable mode, so edits under `src/meteosynth/`
take effect immediately. `uv sync` on its own is enough to run every script under
`examples/` — `tqdm` is a core dependency, because progress bars are a library
feature rather than an example one.

```{note}
The dev dependency group (`uv sync` installs it by default) also brings in
Jupyter, `notebook` and `ipykernel`, so you can drive the package from an
interactive session in VS Code or JupyterLab.
```

## The 30-second version

```python
import numpy as np
import pandas as pd
from meteosynth import MarkovChainSimulator2dKDE

# A transition sample: each row pairs a value with the value that followed it.
rng = np.random.default_rng(0)
previous = rng.normal(0, 1, 1000)
current = 0.8 * previous + rng.normal(0, 0.5, 1000)
data = pd.DataFrame({"previous": previous, "current": current})

sim = MarkovChainSimulator2dKDE(data)

# Draw the next state given a current value ...
print(sim.get_next_state(0.7, rng=42))

# ... or a whole Markov trajectory.
print(sim.generate_sequence(start_state=0.7, length=10, rng=42))
```

That is the engine. Everything below wraps it in a calendar.

## Getting data for a day, a month, a year

`DayWindowGenerator` is the entry point for all three, and the one to reach for by
default. It wraps a `MetDataset` and hands out a model for **any calendar day**,
trained on the rolling ±`n_days` window centred on that day, fitted on demand behind a
small LRU cache.

```{mermaid}
flowchart LR
    A[hourly record] --> B["MetDataset(df)"]
    B --> C["DayWindowGenerator<br/>attr_str, n_days"]
    C --> D["gen_day(month, day)<br/><b>one day</b>"]
    C --> E["generate_series(start, n_days)<br/><b>a month, a year</b>"]
    D --> F[Energy Monte-Carlo]
    E --> F
```

One setup serves all three scales:

```python
import numpy as np
import pandas as pd
from meteosynth import MetDataset, DayWindowGenerator

# `df` is an hourly frame with columns: year, month, day, hour, and at least one
# registered variable (poa_global, temp_air, wind_speed, ...). See "Fetching real
# data from PVGIS" below, or hand over a frame you already have.
mdp = MetDataset(df)

generator = DayWindowGenerator(mdp, attr_str="poa_global", n_days=15)
```

`n_days=15` gives a 31-day window: a 21 May model trains on 6 May – 5 June pooled
across every year in the record.

### A day

`gen_day(month, day)` returns 24 hourly values. Hour 0 is drawn from that date's fitted
initial distribution π(x₀) — there is no start value to pass.

```python
day = generator.gen_day(5, 21, seed=42)          # (24,) hourly W/m2
print(day.sum() / 1000, "kWh/m2")
```

A single day is one roll of the dice. The question worth asking is what 21 May *can*
look like, which is an **ensemble** — fit once with `for_day`, then draw repeatedly from
one RNG stream so the whole draw is reproducible from a single seed:

```python
may21 = generator.for_day(5, 21)                 # fit the models once
rng = np.random.default_rng(42)
ensemble = np.vstack([may21.gen_day(rng=rng) for _ in range(200)])   # (200, 24)

daily = ensemble.sum(axis=1) / 1000              # kWh/m2 per day
print(f"mean {daily.mean():.2f}   P50 {np.percentile(daily, 50):.2f}   "
      f"P90 {np.percentile(daily, 10):.2f}")     # P90 = exceeded in 90% of cases
```

Every call redraws π(x₀), so these are 200 independent samples of 21 May's climate
rather than one 200-day walk.

```{note}
Measured on Heraklion 2010–2020 (11 years), `poa_global`, `n_days=15`: the 200-draw
ensemble gives a mean daily total of **7.20 kWh/m²** against **7.19** for the 341
observed days in the same window, and a median of 7.71 against 7.75. Fitting plus one
day costs ~1.4 s; the 200-day ensemble ~18 s.
```

### A month

A month is a **chained** series — `generate_series(start, n_days)` — because a month is
about *order*: streaks of overcast days, a battery's state of charge, a monthly total.
Day 1 starts from π(x₀); every later day's midnight comes from that day's cross-midnight
model, conditioned on the previous day's 23:00 value.

```python
# Hold the whole month in the cache so repeated realisations do not refit.
generator = DayWindowGenerator(mdp, attr_str="poa_global", n_days=15, cache_size=40)

may = generator.generate_series(start=(5, 1), n_days=31, seed=42)    # (31, 24)
print(may.sum() / 1000, "kWh/m2 over the month")
```

One synthetic May tells you little that the record does not. An **ensemble of months**
is the shape a real study takes — the spread *between* realisations is the answer, and
comparing it to the spread between observed years is the check on that answer:

```python
rng = np.random.default_rng(7)
months = np.vstack([
    generator.generate_series((5, 1), 31, rng=rng).ravel() for _ in range(12)
])                                               # (12, 744) hours

totals = months.sum(axis=1) / 1000
print(f"{totals.mean():.1f} +/- {totals.std(ddof=1):.1f} kWh/m2 per May")
```

```{note}
Same record, same settings: **218.3 ± 9.8 kWh/m²** across twelve synthetic Mays against
**219.5 ± 10.6** across the eleven observed ones. The first realisation costs ~12 s
(fitting 31 days); with `cache_size=40` the eleven that follow cost ~4.6 s each, since
only sampling is left to pay for.
```

### A year

Same call, 365 days. `include_feb29` defaults to `False`, so the walk simply never
requests Feb 29 — there is no filtering step and no exclusion list.

```python
generator = DayWindowGenerator(mdp, attr_str="poa_global", n_days=15, cache_size=8)

year = generator.generate_series(start=(1, 1), n_days=365, seed=2026)   # (365, 24)

# 8760 hourly values, ready to hang on a calendar and hand to a downstream model.
index = pd.date_range("2023-01-01", periods=365 * 24, freq="h")
series = pd.Series(year.ravel(), index=index, name="poa_global")
series.to_csv("synthetic_year.csv")
```

Memory stays flat whatever the length of the walk: `DayWindowGenerator` fits each day on
demand and keeps `cache_size` of them, so a year holds a few hundred KB rather than the
~126 MB all 366 fitted generators would cost.

```{note}
Same record: the generated year totals **1918 kWh/m²** against observed annual totals
ranging 1803–1938 (mean 1880), and takes ~2 min for one attribute — nearly all of it
fitting. A leap year is `n_days=366, include_feb29=True`.
```

### Which call answers which question

| You want | Call | Shape |
| :--- | :--- | :--- |
| One synthetic 21 May | `gen_day(5, 21)` | `(24,)` |
| 200 independent 21 Mays | `for_day(5, 21)` then loop `gen_day(rng=rng)` | `(200, 24)` |
| One synthetic May, in order | `generate_series((5, 1), 31)` | `(31, 24)` |
| 12 independent synthetic Mays | loop `generate_series((5, 1), 31, rng=rng)`, `np.stack` | `(12, 31, 24)` |
| One synthetic year | `generate_series((1, 1), 365)` | `(365, 24)` |

```{note}
**The boundary of a call is the reset.** Within one `generate_series` call the days are
chained across midnight; between two calls nothing is carried over. So "500 independent
days" is 500 calls with `n_days=1` (or 500 `gen_day` calls), *not* one call with
`n_days=500`.
```

## Choosing a training subset: window or month

The rolling window is not the only option, but it is usually the right one. A model for
May 1 trained on *all of May* inherits May 16's climate, and May 31 shares no training
data at all with June 1. A rolling window is centred on its target and slides smoothly
across month boundaries.

```python
from meteosynth import MetDataset, EnvSeriesGenerator

mdp = MetDataset(df)

# Two ways to cut the same record:
may_month = mdp.get_month_subset(5)                       # all of May
may_window = mdp.get_day_window_subset(5, 1, n_days=15)   # Apr 16 - May 16

# The window wraps across New Year, and Feb 29 is an ordinary target:
new_year = mdp.get_day_window_subset(1, 2, n_days=4)      # Dec 29 - Jan 6
leap = mdp.get_day_window_subset(2, 29)                   # centred on Feb 29

# Either subset drops into EnvSeriesGenerator unchanged. It is date-blind: the caller
# chose the season by choosing the subset.
gen = EnvSeriesGenerator(may_month, attr_str="poa_global", bandwidth=0.1)
day = gen.gen_day(seed=1)                                 # (24,)
```

```{note}
`generate_series` is deliberately **not** available on `EnvSeriesGenerator`. A month
subset has one pooled initial distribution and one set of transitions shared by every
generated day, so there is no honest answer to "what does day 32 look like". Chaining
months by hand would step discontinuously twelve times a year in a quantity that varies
smoothly. Chained series live on `DayWindowGenerator`, which knows the calendar.
```

```{note}
The window buys **centring and smoothness, not sample size**. On the 11-year Heraklion
record both a May month subset and a 21 May ±15 window pool 341 days. See {doc}`theory`
for the `all_leap` calendar that makes the New Year wrap and the leap day fall out for
free.
```

## Fetching real data from PVGIS

```python
from meteosynth.adapters import fetch_pvgis

# Paris, 2011-2012. The cache file is written on the first call and read on every
# later one, so collection happens once.
ds = fetch_pvgis(48.8566, 2.3522, 2011, 2012, cache="data/paris_2011_2012.parquet")
```

You get a `MetDataset` directly — the four calendar columns plus `poa_global`,
`temp_air` and `wind_speed` — canonicalised and validated on construction, and carrying
a `Provenance` recording the site, the period and the source.

The cache is matched against that provenance rather than trusted on its path, so
requesting a different site or period from the same file raises `CacheMismatchError`
instead of quietly returning the wrong record. Pass `force_refetch=True` to repurpose a
path deliberately.

PVGIS returns *either* global plane-of-array irradiance *or* its three components, never
both. `irradiance="global"` is the default; pass `"direct"`, `"sky_diffuse"` or
`"ground_diffuse"` for a component. The emitted column keeps its specific name, so the
name itself records what was collected.

```{note}
`fetch_pvgis_tmy` fetches a Typical Meteorological Year instead. Its irradiance is
**horizontal** (`ghi`, `dni`, `dhi`), not plane-of-array — a different quantity, hence
different column names. Pass `coerce_year=` for a clean single-year calendar; a TMY
stitches each month from a different real year, so otherwise the `year` column jumps.
```

```{note}
Adapters are optional. The contract with the rest of the package is an ordinary
DataFrame, so if you already have data, hand it straight to `MetDataset` and no
adapter is involved at all. Register a spec for any column you want to model that the
package does not ship — see {doc}`workflow`.
```

## Running the test suite

```bash
uv run pytest
```

No environment variables are needed: `tests/conftest.py` selects a headless matplotlib
backend at import, so the suite is headless under `pytest`, an IDE runner or CI alike.
Expect about nine minutes — most of it fitting KDEs.

## Next steps

- {doc}`concepts` — the vocabulary, in plain language.
- {doc}`workflow` — the pipeline, step by step.
- {doc}`theory` — how the KDE Markov chain works and why.
- {doc}`examples` — the full scripts under `examples/`.
- {doc}`api` — the complete API reference.
