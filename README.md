# meteosynth

`meteosynth` is a Python package designed to generate synthetic environmental time-series data (such as solar radiation, air temperature, wind speed) based on historical data. It implements a variety of Markov Chain models and includes utilities to interface with the PVGIS (Photovoltaic Geographical Information System) database.

Its primary target is **Monte-Carlo simulation of energy-project output and requirements**, where many statistically-plausible weather realisations are needed rather than a single deterministic profile.

## Features

- **Markov Chain Simulators** (shared `get_next_state` / `generate_sequence` interface):
  - `MarkovChainSimulator2dKDE`: Continuous state simulation using 2D Kernel Density Estimation, with degenerate data handled via the `Kind` enum (`KDE_2D`, `KDE_1D`, `CONSTANT`) and sampling truncated to each variable's physical support. A simulator that turns out to be sampled often **caches its conditional inverse CDF**, making large ensembles ~8× faster without changing what a short run produces.
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
- **PVGIS Integration** (`meteosynth.adapters`):
  - `fetch_pvgis` retrieves a real multi-year hourly record on the plane of array; `fetch_pvgis_tmy` retrieves a Typical Meteorological Year on the horizontal. Both normalise to the canonical schema, validate against each column's physical support, and optionally cache to disk.
  - Adapters are optional. The contract with the rest of the package is an ordinary DataFrame, so a user who already has data never goes through one.
- **A variable registry, not a column whitelist** (`meteosynth.variables`):
  - A column is modellable if and only if it has a registered `VariableSpec` carrying its physical `support`, `units` and `long_name`. Plane-of-array irradiance, **horizontal irradiance** (`ghi`, `dni`, `dhi`), air temperature and wind speed ship registered; `register()` adds your own.

---

## What has changed since 0.2.0

The full record is in [`CHANGELOG.md`](CHANGELOG.md); these are the changes that alter
what the package does rather than how it is arranged.

| | |
| :--- | :--- |
| **Ensemble sampling is ~8× faster** | `get_next_state` used to evaluate a 1000-point KDE grid on *every* call — ~97 % of generation runtime. Hot simulators now cache their conditional inverse CDF. A short run is bit-for-bit unchanged; a large ensemble shifts by ~0.2 % on a daily total, an order of magnitude below anything the package can resolve. Argued in [`docs/design/precomputed-conditional-quantiles.md`](docs/design/precomputed-conditional-quantiles.md). |
| **Degeneracy detection is scale-aware** | Night used to be recognised only when a source stored it as an exact `0.0`. Any resampled, interpolated or unit-converted record storing it as `1e-16` fell through to a 2D KDE fitted across a catastrophically ill-conditioned covariance. The test is now against the data's own scale. |
| **A singular covariance no longer crashes** | Perfectly collinear `previous`/`current` degrades to the 1D path with a warning instead of dying several steps later on `np.sum(None)`. |
| **Horizontal irradiance is a first-class quantity** | `ghi`, `dni` and `dhi` are registered against their own spec, so a TMY frame validates rather than being silently dropped at ingestion. |
| **PVGIS fetching works again** | `pvlib` changed the arity of its PVGIS return value; both call sites were unpacking the old shape. |
| **Absolute magnitudes are calibrated** | `FIX-1` recorded generated irradiance as "systematically too high" (+14 %). Measured against the pool the model is fitted to, on 19 years at four dates, the mean lands within 0.7 % and the claim does not reproduce. What is real is a **deficit of heavily overcast days** — see below. |

### One known limitation, quantified

The generator produces roughly **four times too few heavily overcast days** where a record
holds any. It moves an annual P90 by **0.12 %**, so a yield study cannot see it — but it
matters directly for storage autonomy, worst-case-day and dark-spell questions, and a
daily P10 runs up to 9 % high. Tracked as `FIX-1`, deliberately deferred, and measured in
[`examples/diagnostics-overshoot/`](examples/diagnostics-overshoot/).

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
next_state = simulator.get_next_state(1.7, rng=42)
print("Next state:", next_state)

# ... or a whole reproducible sequence
print(simulator.generate_sequence(start_state=1.7, length=10, rng=42))
```

> **`rng=` at the simulator level, `rng=` or `seed=` at the generator level.** Every
> stochastic path takes an explicit source of randomness rather than touching the global
> `np.random` state. `rng=` accepts `None`, an `int` seed, or a `Generator` — pass a
> `Generator` to draw a whole ensemble from one advancing stream, which is what the
> day generators do internally.

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

Fetch real data from PVGIS with `meteosynth.adapters`:

```python
from meteosynth import MetDataProcessor
from meteosynth.adapters import fetch_pvgis

# Paris, 2011-2012. Pass `cache=` and the file is written on the first call and
# read on every later one -- collection is slow and networked, modelling is not.
df = fetch_pvgis(48.8566, 2.3522, 2011, 2012, cache="data/paris_2011_2012.csv")
mdp = MetDataProcessor(df)
```

The frame comes back canonical: the four calendar columns plus `poa_global`, `temp_air`
and `wind_speed`, validated against each column's physical support. Ask for a different
irradiance component with `irradiance="direct"` — the emitted column keeps its specific
name, so **the name records the choice** and no metadata sidecar is needed.

A Typical Meteorological Year is `fetch_pvgis_tmy(48.8566, 2.3522, coerce_year=2023)`.
Note it supplies *horizontal* irradiance (`ghi`, `dni`, `dhi`), not plane-of-array — a
different quantity, which is why it gets different column names.

---

## Examples

`examples/` is split by purpose — `use_cases/` (applied workflows that produce
data), `concepts/` (how the package behaves), `tools/` (shared helpers), and
`diagnostics-overshoot/` (a measurement rather than a demonstration). Downloads are
cached under `examples/data/` and everything generated is written to the git-ignored
`examples/output/`. See [`examples/README.md`](examples/README.md) for the full index.

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

# Diagnostics: does the generator reproduce the distribution it was fitted to? (~5 min)
uv run --extra examples python examples/diagnostics-overshoot/run_all.py
```

See the **Examples** page in the documentation for a full walk-through.

The diagnostics folder is worth knowing about separately: it is how a claim about the
generator's accuracy gets settled in this repo. It fits on a 19-year record, draws a
thousand synthetic days at four dates, and scores them against the pool they were fitted
to — with a null control, a positive control and an anchor cell, so a negative result is
worth as much as the demonstration that a positive would have been detected. Its design
and its findings are committed alongside the code.

---

## Running Tests

Verify the installation by running the test suite:

```bash
uv run pytest
```

280 tests across 16 modules, about nine minutes — most of it fitting KDEs. No environment
variables are needed: `tests/conftest.py` selects a headless matplotlib backend at import,
so the suite is headless by construction under `pytest`, an IDE runner or CI alike. (This
used to require setting `MPLBACKEND=Agg` by hand; that instruction is obsolete.)

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
