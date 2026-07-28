# meteosynth

`meteosynth` is a Python package designed to generate synthetic environmental time-series data (such as solar radiation, air temperature, wind speed) based on historical data. It implements a variety of Markov Chain models and includes utilities to interface with the PVGIS (Photovoltaic Geographical Information System) database.

Its primary target is **Monte-Carlo simulation of energy-project output and requirements**, where many statistically-plausible weather realisations are needed rather than a single deterministic profile.

## Features

- **Markov Chain Simulators** (shared `get_next_state` / `generate_sequence` interface):
  - `MarkovChainSimulator2dKDE`: Continuous state simulation using 2D Kernel Density Estimation, with degenerate data handled via the `Kind` enum (`KDE_2D`, `KDE_1D`, `CONSTANT`) and sampling truncated to each variable's physical support.
  - `ContinuousMarkovChainSimulator`: Binned continuous state simulation using 1D Kernel Density Estimation.
  - `MarkovChainSimulatorDiscrete`: Discrete state transition modeling.
- **Daily Series Generators** (`meteosynth.generators`):
  - `EnvSeriesGenerator`: one day's worth of model — a fitted initial distribution π(x₀) plus 23 hourly transitions — walked into a complete 24-hour profile by `gen_day()`.
  - `DayWindowGenerator`: a generator per calendar day, trained on a rolling window and fitted lazily behind an LRU cache so a whole year never holds all 366 at once. `generate_series(start, n_days)` chains days across midnight.
- **Meteorological Data Processing**:
  - Pivoting hourly data into daily wide formats.
  - Two selectable training strategies: by calendar month (`get_month_subset`) or by a **rolling ±n-day window** centred on a target day (`get_day_window_subset`).
- **Seasonal day windows** (`meteosynth.day_window`):
  - A circular `all_leap` (CF-conventions `366_day`) calendar, so windows wrap across New Year and **Feb 29 is an ordinary day** — never discarded, and requestable as a generation target.
- **PVGIS Integration**:
  - Retrieve hourly or Typical Meteorological Year (TMY) data directly using the `pvlib` API (`meteosynth.metdata_pvgis`).

---

## Installation & Setup

This package is managed using the `uv` tool. To install the package and its dependencies:

```bash
# Sync core dependencies (numpy, pandas, scipy, pvlib, matplotlib, seaborn) + dev group
uv sync

# Add the extras used by the example scripts (tqdm progress bars)
uv sync --extra examples
```

`matplotlib` and `seaborn` are core dependencies (the simulators and plotting helpers expose plotting methods directly).
The `dev` dependency group — installed by default with `uv sync` — provides the
documentation toolchain (Sphinx, furo, Mermaid, MyST) and an interactive
workflow (`jupyter`, `notebook`, `ipykernel`) for VS Code / JupyterLab.
The optional `examples` extra adds `tqdm`, needed only by the longer-running
example scripts; nothing in the package itself requires it.

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
import numpy as np
from meteosynth import MetDataProcessor, EnvSeriesGenerator

# `df` is a processed PVGIS hourly frame (year, month, day, hour, poa_direct, ...)
mdp = MetDataProcessor(df)
may = mdp.get_month_subset(5)                     # train on one month

gen = EnvSeriesGenerator(may, attr_str="poa_direct", bandwidth=0.1)

# 500 independent synthetic days -> shape (500, 24). Hour 0 is drawn from the fitted
# initial distribution pi(x0); there is no start value to supply.
rng = np.random.default_rng(1)
ensemble = np.vstack([gen.gen_day(rng=rng) for _ in range(500)])
daily_energy = ensemble.sum(axis=1)               # per-day yield proxy
print(daily_energy.mean(), daily_energy.std())
```

### Rolling day windows

A month subset is off-centre and jumps: a May 1 model trained on *all of May*
inherits May 16's climate, and May 31 shares no training data with June 1. A
rolling window is centred on its target and slides smoothly.

```python
from meteosynth import MetDataProcessor, DayWindowGenerator

mdp = MetDataProcessor(df)

# Both pool ~62 days from a 2-year record, around different centres:
may_month = mdp.get_month_subset(5)                       # all of May
may_window = mdp.get_day_window_subset(5, 1, n_days=15)   # Apr 16 - May 16

# Wraps across New Year; Feb 29 is an ordinary target needing no special-casing:
new_year = mdp.get_day_window_subset(1, 2, n_days=4)      # Dec 29 - Jan 6

dwg = DayWindowGenerator(mdp, attr_str="poa_direct", n_days=15)
feb29_day = dwg.gen_day(2, 29, seed=1)                    # a synthetic Feb 29

# A chained series needs a start date, and lives only on the window path:
year = dwg.generate_series(start=(1, 1), n_days=365, seed=1)   # (365, 24)
```

> **Note:** with only two years of data both strategies pool ~62 days, so the
> window buys *centring* and *smoothness*, not sample size. See
> [`docs/design/completed/rolling-day-window.md`](docs/design/completed/rolling-day-window.md).

Fetch real data from PVGIS with `meteosynth.metdata_pvgis`:

```python
from meteosynth.metdata_pvgis import fetch_pvgis_hourly, SITE_PARIS, save_hourly

df = fetch_pvgis_hourly(start_year=2011, end_year=2012, **SITE_PARIS)
save_hourly(df)   # caches to data/pvgis_hourly_data.xlsx
```

---

## Examples

`examples/` is split by purpose — `use_cases/` (applied workflows that produce
data), `concepts/` (how the package behaves), and `tools/` (shared helpers).
Downloads are cached under `examples/data/` and everything generated is written
to the git-ignored `examples/output/`. See [`examples/README.md`](examples/README.md)
for the full index.

```bash
# Optional: download the two records the examples use, once, up front
uv run python examples/tools/fetch_site_data.py

# Use cases: Heraklion 2010-2020, grouped by time scale (day / month / year)
uv run --extra examples python examples/use_cases/day/day_envelope_pv.py
uv run --extra examples python examples/use_cases/day/day_envelope_temp.py
uv run --extra examples python examples/use_cases/day/day_envelope_wind.py

# An ensemble of synthetic Mays, reported as statistics against the observed years (~3 min)
uv run --extra examples python examples/use_cases/month/monthly_statistics.py

# A complete 8760-hour synthetic year of all three attributes, written to CSV (~4 min)
uv run --extra examples python examples/use_cases/year/synthetic_year.py

# Concepts: exploratory plots, rolling windows, leap days
uv run python examples/concepts/example_exploratory_analysis.py
uv run python examples/concepts/example_rolling_window.py
uv run python examples/concepts/example_leap_year_windows.py                 # no PVGIS needed
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
