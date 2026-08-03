# meteosynth

> ## Weather that never happened, from weather that did.

`meteosynth` simulates synthetic hourly environmental time series — solar irradiance, air
temperature, wind speed — as a first-order Markov chain whose transition density is
**re-estimated for every hour of every calendar day**, so the statistics drift with the
season instead of being assumed.

Each transition is fitted by kernel density estimation over the hour-to-hour value pairs
observed in a rolling seasonal window across every year of the record, and sampled by
inverse transform within the variable's declared physical support. Because the model is
generative rather than a resampler, it emits hours that never appear in the historical
record — while remaining physically admissible by construction.

Its primary target is **Monte-Carlo simulation of energy-project output and requirements**,
where many statistically-plausible weather realisations are needed rather than a single
deterministic profile. The package also ships utilities to interface with the PVGIS
(Photovoltaic Geographical Information System) database.

## Features

- **Nonparametric hourly transitions** — a 2D KDE conditional density per hour, estimated from the record rather than assumed (`MarkovChainSimulator2dKDE`).
- **A model per calendar day** — each day is trained on a rolling ±n-day window pooled across every year of the record, so the statistics drift smoothly through the season.
- **A circular `all_leap` calendar** — windows wrap across New Year, and **Feb 29 is an ordinary day**: never discarded, and requestable as a generation target.
- **Physically bounded by construction** — sampling is truncated to each variable's declared support, making out-of-range values impossible rather than merely unlikely.
- **Degeneracy detected, not special-cased** — constant hours such as night-time irradiance collapse to 1D or constant models automatically, judged against the data's own scale.
- **Chained multi-day series** — `generate_series(start, n_days)` runs any span from a single day to a full year, linked across midnight by a cross-midnight model fitted on real consecutive dates.
- **Ensembles in one calendar walk** — `generate_ensemble` fits each day once and passes every realisation through it: **~77× faster** than N separate series at N = 1000.
- **Reproducible realisations** — each is keyed on `(seed, index, attribute)`, so realisation 743 reproduces without generating the other 999, and an ensemble extends from 100 to 200 without invalidating the first 100.
- **Ensembles on disk** — `write_ensemble` streams to a single long-format parquet file, one row group per day, with the full generating parameters and source provenance embedded.
- **A validated training record** — `MetDataset` enforces schema, calendar validity and physical support on construction whatever route the data arrived by, and round-trips to parquet losslessly.
- **A variable registry, not a column whitelist** — a column is modellable if and only if it has a registered `VariableSpec`; `register()` adds your own.
- **Optional PVGIS integration** — `fetch_pvgis` and `fetch_pvgis_tmy` normalise, validate and cache; the contract with the core is an ordinary DataFrame, so a user who already has data never goes through an adapter.
- **Collect once per site** — downloads cache by default and are found again by provenance, not by remembering a filename; a wider record answers a narrower request by narrowing, so one download serves every training period.
- **Alternative simulators** — binned 1D KDE and discrete transition-matrix implementations share the same `get_next_state` / `generate_sequence` interface.

The full release history is in [`CHANGELOG.md`](CHANGELOG.md).

---

## One known limitation, quantified

The generator produces roughly **four times too few heavily overcast days** where a record
holds any. It moves an annual P90 by **0.12 %**, so a yield study cannot see it — but it
matters directly for storage autonomy, worst-case-day and dark-spell questions, and a
daily P10 runs up to 9 % high. Tracked as `FIX-1`, deliberately deferred, and measured in
[`examples/diagnostics-overshoot/`](examples/diagnostics-overshoot/).

---

## Installation & Setup

This package is managed using the `uv` tool. To install the package and its dependencies:

```bash
# Runtime dependencies + the dev group. Enough to run everything, examples included.
uv sync

# Optional: Excel export of an ensemble (`ensemble_to_xlsx`) — the only extra there is
uv sync --extra excel
```

`matplotlib` and `seaborn` are core dependencies (the simulators and plotting helpers expose plotting methods directly).
So is `tqdm`: progress bars are a library feature, not an example one — `generate_series`,
`generate_ensemble` and `write_ensemble` all take `progress=`. **`uv sync` on its own is
therefore enough to run every script under [`examples/`](examples/)**; no extra is needed.
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
from meteosynth import MetDataset, EnvSeriesGenerator

# `df` is a processed PVGIS hourly frame (year, month, day, hour, poa_direct, ...)
mdp = MetDataset(df)
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
from meteosynth import MetDataset, DayWindowGenerator

mdp = MetDataset(df)

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

Fetch real data from PVGIS with `meteosynth.adapters`. **Collect once per site, then
work locally** — the download is cached by default, so only the first call is networked:

```python
from meteosynth.adapters import fetch_pvgis

# First time: downloads every year PVGIS serves for Paris and caches it under ./data/.
ds = fetch_pvgis(48.8566, 2.3522, site="paris")

# Afterwards: no network. The label resolves the coordinates, and the years select a
# view of the record already on disk rather than a new download.
ds = fetch_pvgis(site="paris", start=2011, end=2012)
```

You get a `MetDataset` directly: the four calendar columns plus every irradiance quantity
PVGIS supplied, `temp_air` and `wind_speed`, canonicalised and validated. Each column
keeps its specific name, so **the name records the quantity**.

`start`/`end` select a *view*, not the size of the download. The default fetch takes the
provider's widest range and keeps all three plane-of-array components, so one file per
site answers every later question about it — `poa_global` is derived from the components
by summation, which for PVGIS is exact to **0.01 W/m²** (its own two-decimal rounding)
and is recorded as derived in the dataset's provenance. Pass `components=False` for the
provider's own total instead, or `full_range=False` to download only the years asked for.

What a column name *cannot* record is which site and which years produced it, so each
dataset also carries a `Provenance`. That is what a cache is matched against — both when
you name a file and when the package finds one for you:

```python
ds.provenance          # Provenance(source='pvgis_hourly', latitude=48.8566, ...)
ds.irradiance_column   # 'poa_global' -- resolved, so a TMY record answers 'ghi' instead

# Pointing a different request at the same file is an error, not a silent wrong answer.
fetch_pvgis(35.3387, 25.1442, 2011, 2012, cache="data/paris_2011_2012.parquet")
# CacheMismatchError: site (48.8566, 2.3522) != requested (35.3387, 25.1442)
```

**The store is project-local.** It is `data/` under a *workspace root*, and nothing else —
no user-level location, no environment variable, no global setting. Two projects side by
side keep two independent stores.

The root is `./` — the folder you are working in — unless you say otherwise, which is
what a command line means. **A script pins its own folder instead**, so it reads and
writes beside itself however it was launched:

```python
from meteosynth import workspace

WS = workspace(__file__)                        # this script's folder
fetch_pvgis(48.8566, 2.3522, site="paris", data_dir=WS.data_dir)
WS.output("ensemble.parquet")                   # generated files go in output/
```

Say otherwise per call with `data_dir="inputs"` (another folder — a **relative** path is
read from the working directory, like any path you type), `cache="exact/file.parquet"`
(one named file) or `cache=False` (nothing read, nothing written).

To see what you have collected:

```python
import meteosynth
print(meteosynth.store.describe_store())
# data: 2 cached dataset(s)
#   pvgis_hourly_heraklion_2005_2023.parquet  [2005-2023]  poa_global, temp_air, wind_speed
#   pvgis_hourly_paris_2011_2012.parquet      [2011-2012]  poa_direct, ..., wind_speed
```

If two collected records could both answer a request, the package **refuses and lists
them** rather than choosing — which record a result was trained on is part of the result,
and picking for you would make that depend on what else is in the folder.

Any dataset saves and loads losslessly, whatever built it:

```python
ds.save("data/paris.parquet")
MetDataset.load("data/paris.parquet") == ds     # True, dtypes and provenance included
```

A Typical Meteorological Year is `fetch_pvgis_tmy(48.8566, 2.3522, coerce_year=2023)`.
Note it supplies *horizontal* irradiance (`ghi`, `dni`, `dhi`), not plane-of-array — a
different quantity, which is why it gets different column names.

---

## Examples

`examples/` is split by purpose — `use_cases/` (applied workflows that produce
data), `concepts/` (how the package behaves), `tools/` (shared helpers), and
`diagnostics-overshoot/` (a measurement rather than a demonstration). **Each script
folder is self-contained**: it collects its record into a `data/` folder beside itself and
writes what it generates into an `output/` folder beside itself, both git-ignored. See
[`examples/README.md`](examples/README.md) for the full index.

```bash
# Use cases: Heraklion 2010-2020, grouped by time scale (day / month / year)
uv run python examples/use_cases/day/day_envelope_pv.py
uv run python examples/use_cases/day/day_envelope_temp.py
uv run python examples/use_cases/day/day_envelope_wind.py

# An ensemble of synthetic Mays, reported as statistics against the observed years (~3 min)
uv run python examples/use_cases/month/monthly_statistics.py

# A complete 8760-hour synthetic year of all three attributes, written to CSV (~4 min)
uv run python examples/use_cases/year/synthetic_year.py

# Concepts: exploratory plots, rolling windows, leap days
uv run python examples/concepts/example_exploratory_analysis.py
uv run python examples/concepts/example_rolling_window.py
uv run python examples/concepts/example_leap_year_windows.py                 # no PVGIS needed

# Diagnostics: does the generator reproduce the distribution it was fitted to? (~5 min)
uv run python examples/diagnostics-overshoot/run_all.py
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

439 tests across 19 modules, about eight minutes — most of it fitting KDEs. No environment
variables are needed: `tests/conftest.py` selects a headless matplotlib backend at import,
so the suite is headless by construction under `pytest`, an IDE runner or CI alike. (This
used to require setting `MPLBACKEND=Agg` by hand; that instruction is obsolete for the
suite. It is still worth setting to run an *example script* unattended, since several end
in `plt.show()`, which blocks under an interactive backend.)

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
