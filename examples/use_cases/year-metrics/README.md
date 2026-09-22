# `year-metrics/` — the three-variable ensemble the validation work reads

One script, one output: **1 000 synthetic years of `poa_global`, `temp_air` and
`wind_speed` for Leros**, on one calendar, from one training record, under one seed.

```bash
uv run python examples/use_cases/year-metrics/leros_metrics_ensemble.py
```

It generates data and checks that the data round-trips. It computes no metrics — those
are specified in [`paper/metrics-prompt.md`](../../../paper/metrics-prompt.md), and the
split is deliberate: generation is expensive and runs once, analysis is cheap and runs
many times.

## Why this exists alongside `year-leros/`

[`year-leros/`](../year-leros/) produces the same thing for **`wind_speed` alone**, and its
output is what the validation work is currently being built against. This folder is the
three-variable version, so the two can run independently: one is being analysed while the
other generates.

Every constant is matched between the two — site, seed (2026), window (±15 days),
realisation count (1 000), calendar, sampling path. That is not tidiness. Randomness is
keyed on `(seed, realisation index, attribute name)` and never on the attribute's position
in the requested list, so **the wind column here should reproduce the wind-only file
rather than merely resemble it**. Step 4 of the script checks exactly that, on one calendar
day, and prints the result. If it holds, every wind finding derived from the
single-attribute file carries over unchanged.

A mismatch would most likely mean the two files were written by different package
versions — the existing wind-only file records `precompute: True`, an older spelling of
today's `sampling: "grid"`. The script prints both versions when they disagree.

## What it writes

```
year-metrics/
    leros_metrics_ensemble.py
    data/     pvgis_hourly_leros_2005_2023.parquet   the training record, 883 KB
    output/   ensemble_leros_2023_n1000_3attr.parquet   ~200–250 MB
```

Both git-ignored. `data/` is an input a result was built on; `output/` is a product —
delete it freely, the seed is fixed and it regenerates.

**You can skip the download.** `year-leros/data/` already holds the identical record, and
records are found by reading provenance rather than by filename, so copying that one
parquet into `year-metrics/data/` is enough — `fetch_pvgis` will match it and make no
network call.

## Runtime and size

Read ratios, not seconds — an absolute time is a property of the machine as much as of the
code.

Cost is **days × attributes** and very nearly independent of the realisation count, because
the calendar is walked once and each day's fitted models are shared by every realisation.
The three attributes do not cost the same: `temp_air` and `wind_speed` need a full 2D KDE
for all 23 hourly transitions, while `poa_global` is constant overnight and needs one for
well under half. So:

| | relative cost |
| :--- | :--- |
| `wind_speed` alone (the `year-leros` run) | 1.0 |
| `temp_air` alone | ~1.0 |
| `poa_global` alone | ~0.33 |
| **all three, this run** | **~2.3** |

Output is ~200–250 MB against 90 MB for one attribute: the five index columns are shared
and compress to almost nothing, so it is the float payload that triples.

**Size a trial first.** Set `N_DAYS = 30`, time it, multiply by 12.

## Two things to know before using the output

**Attributes are generated independently.** Within a realisation, a hot hour is not thereby
a sunny one. The file says so in its own metadata. No cross-variable claim can be made from
it — not correlation, not coincident extremes, not joint droughts.

**The calendars differ by four days.** The observed record holds Feb 29 in each of its
leap years; the ensemble is generated with `include_feb29=False` and holds none. Drop those
days from the observed side before comparing. The script counts and prints them so the
discrepancy is visible rather than discovered later.
