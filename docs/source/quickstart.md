# Quickstart

This page gets you from a fresh checkout to a synthetic weather ensemble in a
few minutes.

## Installation

`meteosynth` is managed with [uv](https://docs.astral.sh/uv/).

```bash
# Install core dependencies (numpy, pandas, scipy, pvlib, matplotlib, seaborn)
uv sync

# Add the extras used by the example scripts (tqdm progress bars)
uv sync --extra examples
```

This installs `meteosynth` in editable mode, so edits under `src/meteosynth/`
take effect immediately.

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
print(sim.get_next_state(0.7, seed=42))

# ... or a whole Markov trajectory.
print(sim.generate_sequence(start_state=0.7, length=10, seed=42))
```

## End-to-end: a synthetic daily ensemble

The typical workflow fits an initial distribution plus 23 hourly transitions, walks
them into a full day, and draws either independent days or a chained series.

```{mermaid}
flowchart LR
    A[hourly data] --> B[MetDataProcessor<br/>month subset or<br/>rolling day window]
    B --> C["EnvSeriesGenerator<br/>&#960;(x&#8320;) + 23 transitions"]
    C --> D["gen_day()<br/>or generate_series()"]
    D --> E[Energy Monte-Carlo]
```

```python
import numpy as np
import pandas as pd
from meteosynth import MetDataProcessor, EnvSeriesGenerator

# `df` is a processed PVGIS hourly frame with columns:
#   year, month, day, hour, poa_direct, temp_air, wind_speed, ...
# (see the Examples page for how to fetch it from PVGIS)
mdp = MetDataProcessor(df)

# Train on a single month so the diurnal statistics are consistent.
may = mdp.get_month_subset(5)

gen = EnvSeriesGenerator(may, attr_str="poa_direct", bandwidth=0.1)

# One synthetic day (24 hourly values). There is no start value to pass: hour 0 is
# drawn from the fitted initial distribution pi(x0). For irradiance every observed
# midnight is zero, so pi(x0) is a spike at zero and the day starts at 0.0 -- read
# off the data rather than hard-coded.
day = gen.gen_day(seed=1)

# An ensemble of 500 independent days is an explicit loop. Share one Generator so the
# whole draw is reproducible from a single seed, and pi(x0) is redrawn for each day.
rng = np.random.default_rng(1)
ensemble = np.vstack([gen.gen_day(rng=rng) for _ in range(500)])   # (500, 24)
daily_energy = ensemble.sum(axis=1)          # crude Wh/m2 per day proxy
print(daily_energy.mean(), daily_energy.std())
```

```{note}
For `temp_air` and `wind_speed` this is a substantive change, not a cosmetic one. The
old `start_value=0.0` default was *outside the observed midnight range* of both, so
every day in an ensemble began at an impossible value -- and far enough out the KDE
returned zero density and the next hour raised
`ValueError: array must not contain infs or NaNs`.
```

## Choosing a training subset: month or rolling window

`get_month_subset` is not the only option, and usually not the best one. A model
for May 1 trained on *all of May* inherits May 16's climate, and May 31 shares no
training data at all with June 1. A **rolling day window** is centred on its
target and slides smoothly across month boundaries.

```python
from meteosynth import MetDataProcessor, DayWindowGenerator

mdp = MetDataProcessor(df)

# Both pool ~62 days from a 2-year record, around different centres:
may_month = mdp.get_month_subset(5)                       # all of May
may_window = mdp.get_day_window_subset(5, 1, n_days=15)   # Apr 16 - May 16

# The window wraps across New Year, and Feb 29 is an ordinary target:
new_year = mdp.get_day_window_subset(1, 2, n_days=4)      # Dec 29 - Jan 6
leap = mdp.get_day_window_subset(2, 29)                   # centred on Feb 29

# Either subset drops into EnvSeriesGenerator unchanged. For a whole calendar,
# DayWindowGenerator fits each day on demand behind a small LRU cache, so you
# never hold all 366 at once (~126 MB per attribute if you did).
dwg = DayWindowGenerator(mdp, attr_str="poa_direct", n_days=15)
feb29_day = dwg.gen_day(2, 29, seed=1)

# A *chained* series lives here and only here -- it needs a start date, because each
# day uses its own models and each midnight uses that day's cross-midnight transition.
year = dwg.generate_series(start=(1, 1), n_days=365, seed=1)      # (365, 24)
```

```{note}
`generate_series` is deliberately not available on `EnvSeriesGenerator`. A month
subset has one pooled initial distribution and one set of transitions shared by every
generated day, so there is no honest answer to "what does day 32 look like". Chaining
months by hand would step discontinuously twelve times a year in a quantity that
varies smoothly.
```

```{note}
With only two years of data both strategies pool ~62 days, so the window buys
*centring* and *smoothness*, not sample size. See {doc}`theory` for the
`all_leap` calendar that makes the wrap and the leap day fall out for free.
```

## Fetching real data from PVGIS

```python
from meteosynth import MetDataProcessor
from meteosynth.adapters import fetch_pvgis

# Paris, 2011-2012. The cache file is written on the first call and read on every
# later one, so collection happens once.
df = fetch_pvgis(48.8566, 2.3522, 2011, 2012, cache="data/paris_2011_2012.csv")
mdp = MetDataProcessor(df)
```

You get a canonical frame — the four calendar columns plus `poa_global`, `temp_air` and
`wind_speed` — already validated against each column's physical support, so a unit error
at the boundary (kW/m² read as W/m², °F as °C) raises here rather than surfacing months
later as a plausible-looking synthetic series.

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
DataFrame, so if you already have data, hand it straight to `MetDataProcessor` and no
adapter is involved at all. Register a spec for any column you want to model that the
package does not ship — see {doc}`workflow`.
```

## Running the test suite

```bash
# MPLBACKEND=Agg keeps matplotlib headless
MPLBACKEND=Agg uv run pytest
```

## Next steps

- {doc}`theory` — how the KDE Markov chain works and why.
- {doc}`examples` — the full scripts under `examples/`.
- {doc}`api` — the complete API reference.
