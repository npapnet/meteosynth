# MetDataProcessor Workflow

This page provides a detailed explanation of the core pipeline in `meteosynth`. It tracks the flow of meteorological data from raw import, through seasonal slicing, conversion into daily wide formats, transition pair alignment, model fitting, and finally synthetic daily profile generation.

---

## High-Level Workflow Overview

The following diagram maps the lifecycle of meteorological data as it moves through the class methods and functions of `meteosynth`:

```{mermaid}
flowchart TD
    RawData["Raw Meteorological Data (Pandas DataFrame)"]
    RawData --> Ingest["Ingestion & Validation: MetDataProcessor(df)"]
    
    Ingest --> SliceChoice{"Select Slicing Strategy"}
    
    SliceChoice -->|"get_month_subset(month_ind)"| MonthRoute["Month Subset Route: e.g., all of May"]
    SliceChoice -->|"get_day_window_subset(month, day, n_days)"| WindowRoute["Rolling Day Window Route: e.g., May 1 +/- 15 days"]
    
    MonthRoute --> AddDateId["Add date_id column via _add_date_id"]
    WindowRoute --> AddDateId
    
    AddDateId --> Pivot["Pivot to Daily Wide Format: convert_to_daily_wide"]
    
    Pivot --> PairAlign["Build Transition Pairs: build_transition_pairs"]
    
    PairAlign --> FitKDE["Fit 23 Hourly Simulators: MarkovChainSimulator2dKDE"]
    
    PairAlign --> FitInit["Fit Initial Distribution: build_initial_values"]

    FitKDE --> GenDay["Generate Daily Profile: gen_day"]
    FitInit --> GenDay

    GenDay -->|"Loop hours 1-23"| GenDay

    GenDay --> Series["Chain Across Midnight: generate_series"]
```

---

## 1. Data Ingestion and Validation

The process begins by loading historical hourly meteorological data into a Pandas DataFrame and initializing the [MetDataProcessor](file:///c:/_sandbox/research/meteosynth/src/meteosynth/met_data_processor.py#L6-L15) class:

```python
from meteosynth import MetDataProcessor

# df is a pandas DataFrame of historical weather records
mdp = MetDataProcessor(df)
```

### Ingestion Requirements
To ensure downstream methods run successfully, the constructor validates that the input DataFrame contains a specific set of required columns:
* **Environmental attributes to simulate**: `poa_direct`, `poa_sky_diffuse`, `poa_ground_diffuse`, `temp_air`, `wind_speed`, `Int`.
* **Context/sorting attributes**: `solar_elevation`.
* **Chronological indices**: `year`, `month`, `day`, `hour`.

Validation is enforced via assertion:
```python
assert all(col in met_data.columns for col in self.__met_data_columns), "Missing columns in met_data"
```

---

## 2. Seasonal Slicing Strategies (The Slicing Routes)

A first-order Markov chain assumes that the data within a training subset is *stationary* (i.e., shares the same climate characteristics). To model a specific time of year, `MetDataProcessor` offers two primary slicing routes:

### Route A: By Calendar Month (`get_month_subset`)
Filters the dataset for a single month index (1–12):
```python
may_data = mdp.get_month_subset(5)
```
* **How it works**: Selects all records where `month == month_ind` across all years in the record.
* **Date identification**: Applies the internal helper [_add_date_id](file:///c:/_sandbox/research/meteosynth/src/meteosynth/met_data_processor.py#L140-L159), which formats a unique `date_id` column as `'YYYY-M-D'` to let downstream functions group rows by calendar day.
* **Limitations**: Centered on the middle of the month (meaning a May 1 simulation is trained on mid-May climate) and introduces discontinuous jumps at month boundaries.

### Route B: By Rolling Day Window (`get_day_window_subset`)
Filters a rolling window centered on a specific target day `(month, day)` spanning `±n_days` (default `15`, giving a 31-day window):
```python
window_data = mdp.get_day_window_subset(5, 1, n_days=15)
```
* **How it works**:
  1. Maps every record in the dataset to its slot index on a circular `all_leap` (366-day) calendar. This is computed once and cached in `_day_slots()` to optimize performance.
  2. Calculates the circular delta between the target day's slot and every record's slot.
  3. Masks and extracts all records that fall within the `n_days` radius (wrapping around the New Year boundary seamlessly).
  4. Appends the `day_slot` and the unique `date_id` column.
* **Benefits**: Avoids artificial month-boundary jumps and aligns the training data precisely to the target day's season.

---

## 3. Pivoting to Daily Wide Format

Once a seasonal subset is selected, it must be converted from long format (one row per hour) to a daily wide format before transitions can be analyzed. This step is handled by [convert_to_daily_wide](file:///c:/_sandbox/research/meteosynth/src/meteosynth/met_data_processor.py#L162-L183):

```python
wide_df = convert_to_daily_wide(may_data, value_col="poa_direct")
```

### Why Pivoting is Critical
1. **Hour Alignment**: The wide format has days as the index (`date_str` formatted as `YYYYMMDD` for correct lexicographical sorting) and hours `0-23` as the columns.
2. **Safe Transition Mapping**: Zipping raw hourly rows is fragile because a single missing hour or row-reordering would silently pair incorrect days together. Pivoting keys the alignment on the date, guaranteeing that transition pairs always come from the same calendar day.

---

## 4. Transition Pair Construction and Simulator Fitting

### Building Transition Pairs
The function [build_transition_pairs](file:///c:/_sandbox/research/meteosynth/src/meteosynth/generators.py#L52-L112) builds `(previous, current)` transition pairs for a target hour from the pivoted wide DataFrame:
```python
pairs = build_transition_pairs(wide_df, hour=12)
```
* For a target hour `h`, the `previous` value is read from column `h-1` and the `current` value is read from column `h` of the *same row*.
* **Cross-Midnight Step**: For hour `0`, the previous hour is `23` of the *same* day index (rather than the day before). This is pinned by tests to preserve legacy behavior.
* **Handling Missing Data**: Any row containing a `NaN` at either hour is dropped using `.dropna()`, preventing incomplete transitions from corrupting the density estimation.

### Fitting the Simulators
An [EnvSeriesGenerator](file:///c:/_sandbox/research/meteosynth/src/meteosynth/generators.py#L182-L224) is initialized by providing a sliced subset, an attribute, and optionally a bandwidth parameter:
```python
from meteosynth import EnvSeriesGenerator

gen = EnvSeriesGenerator(may_data, attr_str="poa_direct", bandwidth=0.1)
```
Under the hood, the generator:
1. Converts the long subset to the daily wide format once (`_to_wide`).
2. Iterates over all 24 hours of the day.
3. Calls `build_transition_pairs` and fits a `MarkovChainSimulator2dKDE` for each transition `hour-1 -> hour`.

### Lazy Loading with DayWindowGenerator
When generating a full calendar walk, initializing 366 daily generators at once would consume significant memory (~126 MB per attribute). To prevent this, the [DayWindowGenerator](file:///c:/_sandbox/research/meteosynth/src/meteosynth/generators.py#L294-L342) wraps the `MetDataProcessor` and constructs `EnvSeriesGenerator` instances on demand, caching them in a small Least-Recently Used (LRU) cache (default size `8`):
```python
from meteosynth import DayWindowGenerator

dwg = DayWindowGenerator(mdp, attr_str="poa_direct", n_days=15)
# Generates a sequence for Feb 29, fitting and caching the model on the fly
feb29_day = dwg.gen_day(2, 29, seed=1)
```

---

## 5. Synthetic Generation

Once the simulators are fitted, they are ready to produce new synthetic weather series:

### Single Day Generation (`gen_day`)
Generates a 24-hour profile. There is no initial state to supply — hour 0 is drawn from the fitted initial distribution $\pi(x_0)$:
```python
profile = gen.gen_day(seed=42)
```
* **Step-by-Step Transition**:
  1. Draws hour 0 from $\pi(x_0)$, fitted to the observed 00:00 values of the training subset. For irradiance every observed midnight is zero, so this degenerates to a constant 0.0.
  2. For each hour $h \in [1, 23]$:
     * Takes the hourly simulator `self._dic_simulator[h]`.
     * Calls `sim.get_next_state(current_val, rng=rng)`.
     * Update `current_val` with the sampled output.
  3. Returns a numpy array of shape `(24,)`.

* **KDE Conditional Sampling**:
  Inside `get_next_state(v)` of the `MarkovChainSimulator2dKDE`:
  1. Slices the fitted 2D joint density at the previous value $x_t = v$.
  2. Normalizes the slice into a conditional PDF.
  3. Integrates the PDF into a cumulative CDF.
  4. Draws a random number $u \sim \mathcal{U}(0,1)$.
  5. Interpolates the CDF to find the next state $x_{t+1}$ (Inverse-Transform Sampling).

### Ensemble Generation
To support Monte-Carlo studies, draw many independent days by looping. Sharing one `Generator` keeps the whole draw reproducible from a single seed, while $\pi(x_0)$ is redrawn for each day so every profile gets its own realistic start:
```python
rng = np.random.default_rng(42)
ensemble = np.vstack([gen.gen_day(rng=rng) for _ in range(1000)])
# Returns a numpy array of shape (1000, 24)
```

### Continuous Series (`generate_series`)
A *chained* series links midnights instead of resetting them. It lives on `DayWindowGenerator` and requires a start date, because each day uses its own models and $\pi(x_0)$ is a dated object:
```python
year = dwg.generate_series(start=(1, 1), n_days=365, seed=42)
# Returns a numpy array of shape (365, 24)
```
Day 1's hour 0 comes from $\pi(x_0)$; every later day's hour 0 comes from **that day's** cross-midnight model, conditioned on the previous day's 23:00 value.
