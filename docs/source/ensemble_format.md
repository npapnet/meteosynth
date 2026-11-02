# The ensemble file format

Scripts like `examples/use_cases/year/synthetic_year.py` do not print their results —
they **write a file**, and that file is the input to whatever comes next: a PV yield
model, a battery sizing run, a demand simulation. This page describes that file, so you
can read it from your own code without needing `meteosynth` installed at all.

The writer is {func}`~meteosynth.ensemble.write_ensemble`; the matching reader is
{func}`~meteosynth.ensemble.read_ensemble`. If you have `meteosynth` available, use the
reader — {ref}`jump to it <reading-with-meteosynth>`. If you would rather treat the file
as plain data, everything you need is below.

---

## At a glance

| | |
| :--- | :--- |
| **Format** | Apache Parquet, a single file, snappy-compressed |
| **Layout** | Long (tidy): one row per `(realisation, day, hour)` |
| **Row count** | `n_realisations × n_days × 24` |
| **Row groups** | One per calendar day |
| **Self-describing** | Generating parameters and source provenance embedded as parquet key-value metadata |
| **Dependencies to read** | Any parquet reader — pandas, polars, DuckDB, Arrow, Spark |

A run of `synthetic_year.py` with its shipped defaults (10 realisations, 365 days, three
attributes) produces 87 600 rows across 365 row groups.

## Columns

Five index columns, then **one `float64` column per generated attribute**, named exactly
as the attribute is (`poa_global`, `temp_air`, `wind_speed`, …).

| column | dtype | meaning |
| :--- | :--- | :--- |
| `realisation` | `int32` | Which independent series this row belongs to. **0-based**, `0 … n_realisations-1`. |
| `day_index` | `int16` | Position in the generated span. **1-based**, `1 … n_days`. This is what orders the file. |
| `month` | `int8` | Calendar month, 1–12. |
| `day` | `int8` | Day of month. |
| `hour` | `int8` | Hour of day, **0–23**. |
| *(attribute)* | `float64` | The generated value, in the variable's registered units. |

There is **no `year` column and no timestamp column** — see
{ref}`attaching-timestamps` for why, and what to do about it.

### Why `day_index` as well as `month`/`day`

They answer different questions, and one cannot replace the other.

`month` and `day` say *where in the calendar* a row sits. `day_index` says *where in the
series* it sits — and a span may wrap past New Year, so the calendar alone does not order
it. An ensemble starting on 30 December runs `12/30, 12/31, 1/1, 1/2, …`; sorting that by
`(month, day)` puts January first and silently reverses the year boundary.

**Sort by `(day_index, hour)`. Filter by `(month, day)`.**

## Row order and row groups

Rows are written in `(day_index, realisation, hour)` order, because that is the order the
generator produces them: the calendar is walked once, and each day emits all of its
realisations before the walk moves on. Within a day the block is realisation-major,
hour-minor.

Each calendar day is flushed as its own **row group**. Two consequences worth knowing:

- Writing never holds the whole ensemble in memory, which is why realisation count is
  limited by disk rather than by RAM.
- Reading *one day* is cheap — a reader can skip whole row groups. Reading *one
  realisation* touches every row group, because realisations are interleaved. Parquet's
  column statistics make that fast rather than free.

If your access pattern is realisation-major, sort once after reading rather than fighting
the layout.

## The metadata block

The file records how it was generated, under the parquet key-value metadata key
`meteosynth_ensemble`, as a UTF-8 JSON object.

| key | meaning |
| :--- | :--- |
| `ensemble_schema_version` | Contract version of the columns and row identity. Currently `1`. |
| `meteosynth_version` | The package version that wrote the file. |
| `attrs` | The generated attribute columns, in file order. |
| `start` | `[month, day]` of the first day of the span. |
| `n_days` | Number of consecutive days per realisation. |
| `n_realisations` | How many independent series the file holds. |
| `include_feb29` | Whether the walk visited 29 February. |
| `seed` | Root entropy, or `null` if the run was not seeded. |
| `window_n_days` | Half-width of the rolling training window, in days. |
| `bandwidth` | KDE bandwidth used for the fits. |
| `sampling` | Which path answered each draw: `"exact"` (live density) or `"grid"` (cached quantile grid). Never `"auto"` — the file records what happened, not what was asked for. |
| `source_provenance` | Where the *training* data came from: source, site, coordinates, period, fetch date. |
| `notes` | A statement that attributes were generated independently. Read it. |

Everything except `notes` and `meteosynth_version` is what you would need to **regenerate
the file bit-for-bit**. That is the point of embedding it: a synthetic series with no
record of what produced it is not reproducible science.

Read the metadata without touching the data at all:

```python
import json
import pyarrow.parquet as pq

meta = json.loads(pq.read_schema(path).metadata[b"meteosynth_ensemble"])

print(meta["n_realisations"], "realisations of", meta["n_days"], "days")
print("seed:", meta["seed"], "window: ±", meta["window_n_days"], "days")
print("trained on:", meta["source_provenance"]["site"])
```

---

## Reading it with pandas alone

No `meteosynth` required — `pandas` and `pyarrow` are enough.

```python
import pandas as pd

frame = pd.read_parquet("ensemble_heraklion_2023_n10.parquet")

frame.head()
#    realisation  day_index  month  day  hour  poa_global   temp_air  wind_speed
# 0            0          1      1    1     0         0.0  15.061336    3.212...
# 1            0          1      1    1     1         0.0  14.171513    3.049...
```

(attaching-timestamps)=
### Attaching timestamps

The file deliberately carries no year. Each realisation is **one plausible year at this
site**, not a particular one — stamping it `2023` would assert a claim the model never
made. So the calendar year is yours to choose, and you attach it on read.

The span is a contiguous run of days from `start`, skipping 29 February unless
`include_feb29` is set. That makes the mapping a direct offset:

```python
import pandas as pd

REFERENCE_YEAR = 2023          # any non-leap year, unless meta["include_feb29"]

start = pd.Timestamp(year=REFERENCE_YEAR, month=meta["start"][0], day=meta["start"][1])
days = pd.date_range(start, periods=meta["n_days"], freq="D")

one = frame[frame["realisation"] == 0].sort_values(["day_index", "hour"])
timestamps = (days.to_numpy()[one["day_index"].to_numpy() - 1]
              + pd.to_timedelta(one["hour"].to_numpy(), unit="h"))

series = one.set_index(pd.DatetimeIndex(timestamps, name="timestamp"))[meta["attrs"]]
#                      poa_global   temp_air  wind_speed
# timestamp
# 2023-01-01 00:00:00         0.0  15.061336    3.212...
```

:::{warning}
Pick a **non-leap** reference year when `include_feb29` is `False`, which is the default.
A 365-day span laid onto a leap year silently shifts every date after 28 February by one
day.
:::

### One attribute as hours × realisations

The layout most external tools want a time series in:

```python
wide = frame.pivot(index=["day_index", "hour"],
                   columns="realisation",
                   values="poa_global").sort_index()
# (8760, 10) — 8760 hours down, one column per realisation
```

### Statistics across realisations

The spread between realisations is the quantity the ensemble exists for — a single series
cannot give you a P90.

```python
annual = (frame.groupby("realisation")["poa_global"].sum() / 1000)   # kWh/m² per year

print(f"P50 {annual.quantile(0.50):.0f}   P90 {annual.quantile(0.90):.0f}"
      f"   CV {100 * annual.std() / annual.mean():.1f}%")
```

### Reading only part of the file

Column and row-group pruning both work, and matter once the file is large:

```python
import pyarrow.parquet as pq

# One attribute, one realisation — never materialises the rest.
subset = pq.read_table(
    path,
    columns=["realisation", "day_index", "hour", "temp_air"],
    filters=[("realisation", "=", 2)],
).to_pandas()

# Or one calendar day, which maps onto a single row group.
july = pq.read_table(path, filters=[("month", "=", 7), ("day", "=", 15)]).to_pandas()
```

DuckDB reads it directly, which is often the shortest path to an aggregate:

```sql
SELECT realisation, sum(poa_global) / 1000 AS annual_kwh
FROM read_parquet('ensemble_heraklion_2023_n10.parquet')
GROUP BY realisation
ORDER BY annual_kwh;
```

---

(reading-with-meteosynth)=
## Reading it with meteosynth

{func}`~meteosynth.ensemble.read_ensemble` returns an
{class}`~meteosynth.ensemble.Ensemble`: the same rows, plus the parsed metadata and two
views.

```python
from meteosynth import read_ensemble

ens = read_ensemble(path)

ens.attrs                  # ('poa_global', 'temp_air', 'wind_speed')
ens.n_realisations         # 10
ens.meta["seed"]           # 2026
ens.meta["source_provenance"].site      # a parsed Provenance, not a dict

ens.realisation(0)         # one series, sorted (day_index, hour), index reset
ens.to_wide("poa_global")  # (n_days*24, n_realisations), columns realisation_0…
ens.frame                  # the raw long frame, if you want it
```

Two behaviours worth knowing:

- **A file from a newer schema version is refused, not guessed at.** If
  `ensemble_schema_version` exceeds what your installed `meteosynth` understands,
  `read_ensemble` raises `ValueError` telling you to upgrade. A reader that guessed would
  produce a plausible-looking wrong answer.
- **A file with no metadata warns and still reads.** You get the columns as they are, and
  an empty `meta`.

## What the format does not carry

Four absences, all deliberate — plan around them rather than looking for a flag.

**Cross-attribute correlation is not modelled.** Each attribute is generated from its own
independent random stream, so within a realisation a hot hour is not thereby a sunny one.
A multi-column file *looks* like a weather record, and this one is not one; the
`notes` metadata field says so in the file itself. If your downstream model couples
irradiance and temperature — panel derating, for instance — that coupling is not in this
data.

**No realisation is a forecast.** Realisation 3 is not a prediction of any particular
year. The spread *between* realisations is the model's statement, and the individual
series is only a way of carrying it.

**No timestamps, no timezone, no year.** As above: the span is a climatological calendar
position, not a dated one. Hours are local standard time in whatever convention the
training record used — for PVGIS data, UTC.

**The `.xlsx` export is not this file.** {func}`~meteosynth.ensemble.ensemble_to_xlsx`
writes a pivoted, one-sheet-per-attribute copy with **no metadata at all**, for software
that cannot read parquet. It is lossy and one-way. Keep the parquet file as the record.

## Reproducing a file you were given

Because a realisation is keyed on `(seed, realisation index, attribute name)` and nothing
else, the metadata is enough to regenerate any part of an ensemble — including a single
realisation, without generating the others:

```python
from meteosynth import MetDataset, DayWindowGenerator

ds = MetDataset.load("training_record.parquet")     # matching source_provenance
dwg = DayWindowGenerator(ds, attr_str="poa_global",
                         n_days=meta["window_n_days"],
                         bandwidth=meta["bandwidth"])

again = dwg.generate_ensemble(
    start=tuple(meta["start"]), n_days=meta["n_days"],
    n_realisations=meta["n_realisations"], seed=meta["seed"],
    include_feb29=meta["include_feb29"], sampling=meta["sampling"],
)
```

Passing `sampling` back, as above, is what makes the regeneration exact even at a
**different** realisation count from the original: left on `"auto"` the path is chosen
from the count, and two runs either side of 64 would use different samplers. See
{meth}`~meteosynth.generators.DayWindowGenerator.generate_ensemble`.
