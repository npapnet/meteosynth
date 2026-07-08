# meteosynth

`meteosynth` is a Python package designed to generate synthetic environmental time-series data (such as solar radiation, air temperature, wind speed) based on historical data. It implements a variety of Markov Chain models and includes utilities to interface with the PVGIS (Photovoltaic Geographical Information System) database.

Its primary target is **Monte-Carlo simulation of energy-project output and requirements**, where many statistically-plausible weather realisations are needed rather than a single deterministic profile.

## Features

- **Markov Chain Simulators** (shared `get_next_state` / `generate_sequence` interface):
  - `MarkovChainSimulator2dKDE`: Continuous state simulation using 2D Kernel Density Estimation with handling for various singularity cases (CC, CN, NC, NN).
  - `ContinuousMarkovChainSimulator`: Binned continuous state simulation using 1D Kernel Density Estimation.
  - `MarkovChainSimulatorDiscrete`: Discrete state transition modeling.
- **Daily Series Generators** (`meteosynth.generators`):
  - `EnvSeriesGenerator`: chains 24 hourly simulators into complete 24-hour profiles and draws Monte-Carlo ensembles via `generate_ensemble`.
- **Meteorological Data Processing**:
  - Pivoting hourly data into daily wide formats.
  - Subsetting and filtering datasets by month/year.
- **PVGIS Integration**:
  - Retrieve hourly or Typical Meteorological Year (TMY) data directly using the `pvlib` API (`meteosynth.metdata_pvgis`).

---

## Installation & Setup

This package is managed using the `uv` tool. To install the package and its dependencies:

```bash
# Sync core dependencies (numpy, pandas, scipy, pvlib, matplotlib) + dev group
uv sync

# Add the extra statistical-plotting helpers (seaborn, plotnine)
uv sync --extra plot
```

`matplotlib` is a core dependency (the simulators expose plotting helpers directly).
The `dev` dependency group — installed by default with `uv sync` — provides the
documentation toolchain (Sphinx, furo, Mermaid, MyST) and an interactive
workflow (`jupyter`, `notebook`, `ipykernel`) for VS Code / JupyterLab.

---

## Usage Example

Draw a single transition or a full Markov trajectory:

```python
import pandas as pd
from meteosynth import MarkovChainSimulator2dKDE

# Load your historical training data (containing 'previous' and 'current' columns)
data = pd.DataFrame({
    'previous': [1.2, 1.5, 1.8, 2.1],
    'current': [1.5, 1.9, 2.0, 2.3]
})

# Initialize the 2D KDE simulator
simulator = MarkovChainSimulator2dKDE(data)

# Generate the next state from a current value of 1.7 ...
next_state = simulator.get_next_state(1.7, seed=42)
print("Next state:", next_state)

# ... or a whole reproducible sequence
print(simulator.generate_sequence(start_state=1.7, length=10, seed=42))
```

### Monte-Carlo daily ensemble

Chain 24 hourly simulators into synthetic days and draw an ensemble for
downstream energy analysis:

```python
from meteosynth import MetDataProcessor, EnvSeriesGenerator

# `df` is a processed PVGIS hourly frame (year, month, day, hour, poa_direct, ...)
mdp = MetDataProcessor(df)
may = mdp.get_month_subset(5)                     # train on one month

gen = EnvSeriesGenerator(may, attr_str="poa_direct", bandwidth=0.1)

# 500 independent synthetic days -> shape (500, 24)
ensemble = gen.generate_ensemble(n_days=500, start_value=0.0, seed=1)
daily_energy = ensemble.sum(axis=1)               # per-day yield proxy
print(daily_energy.mean(), daily_energy.std())
```

Fetch real data from PVGIS with `meteosynth.metdata_pvgis`:

```python
from meteosynth.metdata_pvgis import fetch_pvgis_hourly, SITE_PARIS, save_hourly

df = fetch_pvgis_hourly(start_year=2011, end_year=2012, **SITE_PARIS)
save_hourly(df)   # caches to data/pvgis_hourly_data.xlsx
```

---

## Examples

Two runnable scripts live under `examples/`. On first run they fetch data from
PVGIS and cache it to `data/pvgis_hourly_data.xlsx`, so subsequent runs are
offline and fast.

```bash
# Exploratory analysis: fetch, process, and plot PVGIS data
uv run python examples/example_exploratory_analysis.py

# Synthetic generation: build hourly simulators and plot synthetic daily profiles
uv run python examples/example_markov_generation.py
```

See the **Examples** page in the documentation for a full walk-through.

---

## Running Tests

Verify the installation by running the test suite (`MPLBACKEND=Agg` keeps
matplotlib headless):

```bash
# Linux/macOS
MPLBACKEND=Agg uv run pytest

# Windows (PowerShell)
$env:MPLBACKEND = "Agg"; uv run pytest
```

---

## Building Documentation

The documentation uses the standard Sphinx layout (`docs/source/` for sources,
`docs/build/` for output, with `Makefile`/`make.bat` at the `docs/` root) and
the `furo` theme, with Mermaid diagrams and Markdown (MyST) support.

```bash
# From the docs/ directory (Windows)
cd docs
uv run .\make.bat html

# ...or on Linux/macOS
cd docs && uv run make html

# ...or invoke sphinx-build directly from the project root
uv run sphinx-build -b html docs/source docs/build/html
```

Open `docs/build/html/index.html` in your web browser to view it. The docs
include a **Quickstart**, a **Theory** section explaining the KDE Markov method
(with diagrams), an **Examples** walk-through, and the full **API reference**.
