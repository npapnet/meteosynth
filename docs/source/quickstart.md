# Quickstart

This page gets you from a fresh checkout to a synthetic weather ensemble in a
few minutes.

## Installation

`meteosynth` is managed with [uv](https://docs.astral.sh/uv/).

```bash
# Core install (numpy, pandas, scipy, pvlib, matplotlib)
uv sync

# Add the extra statistical-plotting helpers (seaborn, plotnine)
uv sync --extra plot
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
    A[PVGIS hourly data] --> B[MetDataProcessor<br/>month subset]
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
