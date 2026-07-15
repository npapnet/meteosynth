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

The typical workflow chains 24 hourly simulators into a full day and then draws
an ensemble of days for Monte-Carlo analysis.

```{mermaid}
flowchart LR
    A[PVGIS hourly data] --> B[MetDataProcessor<br/>month subset or<br/>rolling day window]
    B --> C[EnvSeriesGenerator<br/>24 hourly simulators]
    C --> D[generate_ensemble<br/>n_days &times; 24]
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

# One synthetic day (24 hourly values, starting at 0 W/m2 at midnight):
day = gen.gen_day_sequence(start_value=0.0, seed=1)

# An ensemble of 500 independent synthetic days -> shape (500, 24):
ensemble = gen.generate_ensemble(n_days=500, start_value=0.0, seed=1)
daily_energy = ensemble.sum(axis=1)          # crude Wh/m2 per day proxy
print(daily_energy.mean(), daily_energy.std())
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
feb29_day = dwg.gen_day_sequence(2, 29, seed=1)
```

```{note}
With only two years of data both strategies pool ~62 days, so the window buys
*centring* and *smoothness*, not sample size. See {doc}`theory` for the
`all_leap` calendar that makes the wrap and the leap day fall out for free.
```

## Fetching real data from PVGIS

```python
from meteosynth.metdata_pvgis import fetch_pvgis_hourly, SITE_PARIS, save_hourly

df = fetch_pvgis_hourly(start_year=2011, end_year=2012, **SITE_PARIS)
save_hourly(df)   # caches to data/pvgis_hourly_data.xlsx
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
