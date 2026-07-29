# The pipeline, step by step

This page tracks a meteorological record through `meteosynth`: ingestion and validation,
seasonal slicing, the pivot to daily wide format, pair construction, model fitting, and
finally generation. It is the "how it is wired" companion to {doc}`theory` ("why it is
wired that way") and {doc}`quickstart` ("what to type").

---

## High-level overview

```{mermaid}
flowchart TD
    RawData["Raw hourly record (DataFrame)"]
    RawData --> Ingest["MetDataset(df)<br/>schema v1: validate, trim, canonicalise"]

    Ingest --> SliceChoice{"Training subset"}
    SliceChoice -->|"get_day_window_subset(month, day, n_days)"| WindowRoute["Rolling day window<br/>e.g. 21 May +/- 15 days"]
    SliceChoice -->|"get_month_subset(month_ind)"| MonthRoute["Month subset<br/>e.g. all of May"]

    WindowRoute --> Pivot["convert_to_daily_wide<br/>days x hours"]
    MonthRoute --> Pivot

    Pivot --> Init["build_initial_values<br/>&#960;(x&#8320;)"]
    Pivot --> Pairs["build_transition_pairs<br/>h-1 &#8594; h, for h = 1..23"]
    Pivot --> Cross["build_cross_midnight_pairs<br/>23:00(d-1) &#8594; 00:00(d)"]

    Init --> Fit["EnvSeriesGenerator<br/>25 fitted MarkovChainSimulator2dKDE"]
    Pairs --> Fit
    Cross --> Fit

    Fit --> GenDay["gen_day() / gen_day_from()<br/>one 24-hour profile"]
    GenDay --> Series["DayWindowGenerator.generate_series()<br/>chained across midnight"]
```

The full record enters once; each calendar day gets its own 25 models; a day is walked
hour by hour; days are chained across midnight into a month or a year.

---

## 1. Ingestion and validation

```python
from meteosynth import MetDataset

# df is a pandas DataFrame of historical hourly records
ds = MetDataset(df)
```

`MetDataset` is the package's core object: a **strict, source-agnostic training record**.
Whether the frame came from an adapter, a file or your own code, it is checked and
canonicalised the same way, so strictness belongs to the format rather than to whichever
route the data arrived by.

The constructor is driven by the **variable registry** rather than by a fixed column
list. It enforces the schema:

| Rule | Behaviour |
|---|---|
| calendar index present, at least one registered variable | raise (`validate_columns`) |
| unregistered columns | dropped (`trim_columns`) |
| dtypes and row order | canonicalised, so two datasets over the same data are equal |
| duplicate `(year, month, day, hour)` | raise, naming the dates |
| impossible calendar (`month=13`, 31 April) | raise, naming the row |
| value outside a spec's physical support | clipped to the bound, warned, counted in `describe()` |
| a date with fewer than 24 hours | kept, and reported by `describe()` |

The two structural rejections were already fatal before the schema existed — a duplicate
row died inside `pivot`, an impossible month inside `day_slot` — so this changes the error
message rather than what is accepted. Out-of-support values are *repaired* rather than
refused because real records routinely carry small negative irradiance at night from
sensor noise, and the check cannot catch the unit errors it was written for anyway (280 K
and 20 °F both sit inside support).

The two registry-driven checks in more detail:

**`validate_columns`** — the rule is *all* of the calendar index columns
(`INDEX_COLS = year, month, day, hour`) and *any* registered variable. Requiring only one
registered column means a temperature-only source with no irradiance at all ingests
cleanly; "is this frame usable for what you asked?" is a different question, answered
later by the generator's `attr_str` check, which can name the specific column that is
missing.

**`trim_columns`** — returns a copy holding only the index columns and registered
variables. Unregistered columns are dropped rather than carried through, so nothing
downstream can come to depend on a provider-specific column. A PVGIS quality flag (`Int`)
and `solar_elevation` fall out **by this rule**, not by a hardcoded exclusion list:
neither is a stochastic environmental quantity, so neither has a spec. Your original frame
is never mutated — only this processed copy is trimmed.

````{note}
A column is modellable **if and only if it has a registered `VariableSpec`**. Nine ship
registered: `poa_global`, `poa_direct`, `poa_sky_diffuse`, `poa_ground_diffuse`
(plane-of-array), `ghi`, `dni`, `dhi` (horizontal), `temp_air` and `wind_speed`. Add your
own and it becomes modellable with no change to the package:

```python
from meteosynth import register, VariableSpec
register("rel_humidity", VariableSpec((0.0, 100.0), "%", "Relative humidity"))
```

`registered()` is the authoritative answer to "what can I model?"; `SHIPPED_ATTRS` is a
documentation-grade note of the defaults and gates nothing.
````

A spec carries **constraints, not an identity**: `support`, `units`, `long_name`. The
support is what makes an out-of-support sample impossible rather than merely unlikely —
the evaluation domain is clamped to it before any CDF is built.

### What the dataset can tell you

```python
ds.variables            # ('poa_global', 'temp_air', 'wind_speed')
ds.irradiance_column    # 'poa_global' -- or 'ghi' for a horizontal record
ds.describe()           # rows, years, dates, incomplete_dates, clipped, provenance
ds.provenance           # Provenance(source='pvgis_hourly', site='paris', ...)
```

`irradiance_column` is what lets a script stop caring which source produced its data: a
PVGIS hourly record answers `poa_global`, a TMY answers `ghi`. It refuses to guess when
only *components* of a total are present, because a component is a part of a total and
answering with one would be a factor-of-two error.

`describe()["rows"]` is the **whole record**. The number of days a generator actually
trains on is a different quantity, per calendar day — see *Seasonal slicing* below.

### Saving and loading

```python
ds.save("paris.parquet")
MetDataset.load("paris.parquet") == ds       # True: dtypes and provenance included
```

Parquet is the canonical format because it is the only one that round-trips: one file,
exact dtypes, and provenance carried inside it as key-value metadata. CSV remains
available as *interchange* under names that say so — `MetDataset.read_csv` imports and
`ds.to_csv` exports with a warning — because it widens `int8` to `int64` and carries no
provenance at all. `save`/`load` are a pair; `read_csv`/`to_csv` are not.

A file written by a **newer** schema version is refused rather than guessed at, since
today's code cannot know what changed. Unknown *provenance* fields are the opposite: they
are descriptive, so they are ignored with a warning and the dataset still loads.

---

## 2. Seasonal slicing

A first-order Markov chain assumes the days it pools share a climate, so the choice of
subset is a modelling decision. Two routes:

### Route A — rolling day window (`get_day_window_subset`)

```python
window_data = mdp.get_day_window_subset(5, 21, n_days=15)   # 6 May - 5 June, all years
```

1. Every record is mapped to its slot on the circular `all_leap` (366-day) calendar.
   Computed once per processor and cached in `_day_slots()`, so a 366-day calendar walk
   does not re-map all rows on every window.
2. The circular distance from the target slot is taken (period 366).
3. Records within `n_days` are selected — the window wraps across New Year with no
   special-casing, and Feb 29 is an ordinary slot both to pool and to target.
4. A `day_slot` column and a `date_id` column are appended.

The window is **climatological, not chronological**: a Jan 2 2011 target pools December
*2011* as a proxy for late-December climate.

### Route B — calendar month (`get_month_subset`)

```python
may_data = mdp.get_month_subset(5)                          # all of May, all years
```

Selects every record with `month == month_ind` and appends the same `date_id` column, so
the two routes cannot drift apart on the format downstream consumers group by.

Its two defects are why the window exists: it is **off-centre** (a May 1 model trains on
data centred on May 16) and it **jumps** (May 31 and June 1 share no training data at
all).

```{note}
`date_id` is not zero-padded (`'2011-1-2'`), so it does not sort lexicographically — do
not rely on it for ordering. `convert_to_daily_wide` builds its own zero-padded
`date_str` for exactly that reason.
```

---

## 3. Pivoting to daily wide format

```python
from meteosynth import convert_to_daily_wide

wide = convert_to_daily_wide(window_data, value_col="poa_global")
```

The result is indexed by `date_str` (`YYYYMMDD`, so it *does* sort) with hours `0–23` as
columns. `MetDataset.get_monthly_attribute_wide_format(value_col, month_id)` is the
convenience wrapper that slices a month and pivots in one call.

**Why this shape is load-bearing.** Both values of a transition pair are read from the
*same row*, which is what guarantees they come from the same day. Slicing the long frame
into two hour-filtered views and zipping them by position is only correct while both
views happen to share a day ordering; it fails silently — same lengths, no exception,
~27 k mispaired rows — as soon as anything re-sorts the input.

Internally the generators call `_to_wide`, which additionally reindexes the columns to a
full `0–23` set, so a subset missing an hour entirely fails with a clear message rather
than a bare `KeyError`.

---

## 4. Pair construction

A Markov chain is formally **an initial distribution plus a set of transitions**, and a
chained series needs one more model to cross midnight. Three builders, three jobs:

| Function | Builds | From |
| :--- | :--- | :--- |
| `build_initial_values(wide)` | π(x₀), the distribution of hour 0 | the observed 00:00 value of every training day |
| `build_transition_pairs(wide, hour)` | one within-day transition `h-1 → h` | columns `h-1` and `h` of the same row |
| `build_cross_midnight_pairs(wide_full, target_index)` | the 23:00(d−1) → 00:00(d) step | **actual consecutive calendar dates** in the full record |

```python
from meteosynth import build_transition_pairs, build_initial_values

pairs = build_transition_pairs(wide, hour=12)      # 'previous' / 'current' columns
initial = build_initial_values(wide)
```

**`build_transition_pairs` is valid for hours 1–23 only** and raises on hour 0. Hour 0 has
no predecessor within the day, and the chain no longer fakes one. (It used to use
`hour_prev = (hour - 1) % 24`, making hour 0's "previous" hour 23 of the *same* day — a
23-hour backwards jump presented as a one-hour step. On the shipped record those same-day
pairs correlate at 0.360 for `wind_speed` and 0.890 for `temp_air`, against 0.981 and
0.998 for the real cross-midnight step.)

**π(x₀) is returned in `previous`/`current` form with a constant `previous`**, so an
ordinary `MarkovChainSimulator2dKDE` fits it. That is not a trick: a constant `previous`
is exactly the `Kind.KDE_1D` case, which already means "there is no information in the
previous value, sample the marginal". When the 00:00 values are themselves constant — as
they are for irradiance — it degenerates one step further to `Kind.CONSTANT`. *"Irradiance
starts at zero" therefore falls out of the data rather than being hard-coded.*

**Cross-midnight pairs are looked up by real date**, which is why they need the full
record rather than the window: the previous day of a target day may legitimately fall
outside it. Pairing on the calendar *slot* instead would pair Dec 31 **2012** with
Jan 1 **2012** — a 364-day backwards jump presented as a one-hour step.

Days with a missing value at either end of a pair are dropped, and only those days.

---

## 5. Fitting

### `EnvSeriesGenerator` — one day's worth of model, date-blind

```python
from meteosynth import EnvSeriesGenerator

gen = EnvSeriesGenerator(window_data, attr_str="poa_global", bandwidth=0.1)
```

Holds 25 models: π(x₀), 23 within-day transitions, and — when `wide_full=` is supplied —
one cross-midnight transition. It pivots **once** and shares the result: per-hour pivoting
would cost about 12× the KDE fitting it feeds (635 ms against 20 ms, versus 58 ms to fit
all hours). `generate_hr_simulator(met_data, hour, attr_str)` remains as the convenient
single-hour entry point, and does pivot per call.

The class deliberately knows nothing about *which* day it models — the caller chose the
season by choosing the subset. `simulators`, `initial` and `cross_midnight` expose the
fitted models for inspection.

### `DayWindowGenerator` — a generator per calendar day, fitted lazily

```python
from meteosynth import DayWindowGenerator

dwg = DayWindowGenerator(mdp, attr_str="poa_global", n_days=15, cache_size=8)

feb29 = dwg.gen_day(2, 29, seed=1)     # fits 29 Feb's window on first request, then caches
models = dwg.for_day(2, 29)            # the EnvSeriesGenerator itself
```

Holding all 366 fitted days costs ~126 MB for one attribute (~880 MB across seven), while
fitting one costs ~58 ms — a `gaussian_kde` "fit" just stores its points and a 2×2
covariance. Since callers walk the calendar in order, a small LRU cache hits nearly
always. Raise `cache_size` when you will revisit the same days (a month ensemble);
`clear_cache()` releases them.

The full-record pivot that cross-midnight pairs need is computed **once** per generator
and shared across all 366 days.

```{note}
Persisting fitted generators to disk is deliberately not offered: it would write numbers
already present in the source data, ~31× duplicated across overlapping windows, to save
58 ms — and `scipy`'s `gaussian_kde` stores an unpicklable local lambda in
`covariance_factor` at any explicit bandwidth anyway.
```

---

## 6. Generation

### One day

```python
profile = gen.gen_day(seed=42)                  # EnvSeriesGenerator, starts from pi(x0)
profile = dwg.gen_day(5, 21, seed=42)           # DayWindowGenerator, same for a date
continued = gen.gen_day_from(previous_2300=3.4) # continues a chain across midnight
```

1. Hour 0 is drawn from π(x₀) (or from the cross-midnight model, conditioned on the
   previous day's 23:00 value).
2. For each hour `h ∈ [1, 23]`: `simulators[h].get_next_state(value, rng=rng)`.
3. Returns a `(24,)` array.

`gen_day_from` raises if no cross-midnight model was built — construct with `wide_full=`,
or use `DayWindowGenerator`, which supplies it.

### An ensemble of independent days

```python
rng = np.random.default_rng(42)
ensemble = np.vstack([gen.gen_day(rng=rng) for _ in range(1000)])    # (1000, 24)
```

Sharing one `Generator` keeps the whole draw reproducible from a single seed, while π(x₀)
is redrawn for each day so every profile gets its own realistic start.

### A chained series

```python
year = dwg.generate_series(start=(1, 1), n_days=365, seed=42)        # (365, 24)
```

Day 1's hour 0 comes from π(x₀); every later day's hour 0 comes from **that day's**
cross-midnight model. Each calendar day uses models fitted to its own ±`n_days` window, so
the chain is **time-inhomogeneous at daily resolution** and drifts smoothly through the
season.

`start` is required because π(x₀) is a *dated* object — midnight temperature in January
and in July are different distributions. `include_feb29` defaults to `False`, giving a
365-day year; the walk then steps 28 Feb 23:00 → 1 Mar 00:00 using 1 March's
cross-midnight model, which is fitted from real 1 March dates whose actual predecessor was
29 Feb in leap years and 28 Feb otherwise.

---

## 7. Inside `get_next_state`

Every draw dispatches on what the *data* supports, recorded on the simulator as `kind`:

| `Kind` | When | What it does |
| :--- | :--- | :--- |
| `KDE_2D` | previous and current both vary | slice the joint density at `previous`, normalise, inverse-transform sample |
| `KDE_1D` | previous constant | sample the marginal of `current` — there is nothing to condition on |
| `CONSTANT` | current constant | return the constant; consumes no randomness |

"Constant" means constant *to within a tolerance scaled by the simulator's own data*, not
`std == 0` exactly, so a physically-zero night stored as `1e-16` by an interpolated or
unit-converted source is still recognised as night.

The `KDE_2D` path:

1. Clamp the conditioning value into the range the model was fitted over — far outside it
   every kernel evaluates to ~0 and the normalisation is 0/0.
2. Evaluate the joint density along the current-value domain, itself clamped to the
   variable's physical support.
3. Normalise to a conditional pdf, cumulative-sum to a cdf.
4. Draw `u ~ U(0,1)` and interpolate: `x = interp(u, cdf, domain)`.

**Hot simulators cache their answer.** After 64 draws a simulator replaces steps 2–3 with
a precomputed table of conditional *quantile functions* on a 64-node grid of `previous`
values, so a draw costs two interpolations instead of a 1000-point KDE evaluation. Large
ensembles run ~8× faster; a short run never reaches the threshold and is unaffected, which
is why a year-long walk — one sample from each of a day's 24 simulators — never builds a
grid or spends the memory. Call `precompute_grid()` to build it up front when the ensemble
size is known in advance. Both paths consume exactly one number from `rng`, so which one
is taken never perturbs the random stream.

---

## Where to go next

- {doc}`theory` — the mathematics, the `all_leap` calendar, and the assumptions.
- {doc}`examples` — the runnable scripts these steps appear in.
- {doc}`api` — every function and class referenced above.
