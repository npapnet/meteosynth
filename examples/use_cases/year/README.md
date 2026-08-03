# Year — produce a complete 8760-hour series

| Script | What it does | Runtime |
| :--- | :--- | :--- |
| [`synthetic_year.py`](synthetic_year.py) | An **ensemble of 10** 8760-hour years, each attribute chained day by day across midnight, written to one parquet file | **~45–50 min** (measured; see below) |

```bash
uv run python examples/use_cases/year/synthetic_year.py
```

> **In a hurry?** Lower `N_DAYS` from 365 — the script is built to be tried out that way,
> and skips the annual climatology checks when you do, since those only mean anything for
> a full year. `N_DAYS = 20` finishes in under three minutes.

This script exists to **produce data**, not to make a point: the file it writes is the
input to whatever comes next — a PV yield model, a battery sizing run, a demand
simulation. Set `PLOT_HEATMAP = True` for a year-at-a-glance figure (day of year across,
hour of day down, one panel per attribute), which shows what the monthly table cannot:
the seasonal envelope, and the summer day widening at both ends rather than merely
getting brighter.

## What the output is, and is not

- It **is** ten plausible realisations of a year at this site. Every hour is drawn, not
  copied; no series repeats a historical year.
- Each one is **not** a forecast of any particular year. The **spread between them** is
  the quantity the whole exercise is for — `year_heraklion_ensemble_spread.csv` is that
  number, and a single series cannot give it to you.
- Ten is a demonstration size. Raise `N_REALISATIONS` towards hundreds for a real
  Monte-Carlo study; it costs far less than it looks (see below).

## Where the runtime goes, and why more realisations are nearly free

**The calendar is walked once for the whole ensemble**, not once per realisation
(`write_ensemble`, `FEAT-15`). Each day's models are fitted once and every realisation is
passed through them, so the cost is **per calendar day**, essentially independent of
`N_REALISATIONS`.

Measured on this configuration — Heraklion 2010–2020, ±15-day window, three attributes:

| | |
| :--- | ---: |
| per calendar day, all three attributes | **~7.5–8 s** |
| 365 days | **~45–50 min** |
| going from 10 realisations to 100 | almost nothing extra |

Most of that per-day cost is **building each simulator's cached quantile grid**, not
drawing values — about 79 % of it at large *N*. That is `PERF-16` in `TODOs.md`, and it
is why "make the ensemble bigger" is cheap while "make the year longer" is not.

## Mechanics worth knowing while it runs

- **Non-leap is the default.** The walk covers 365 days from 1 January with
  `include_feb29=False`, so Feb 29 is never requested — no filtering, no exclusion list.
  Ask for a leap year instead and Feb 29 generates like any other day.
- **Memory stays flat.** All 366 fitted generators would cost ~126 MB per attribute.
  `DayWindowGenerator` fits each day on demand and holds only a few at a time, so the
  walk stays at a few hundred KB however long it runs. Note the LRU cache does **not**
  speed this script up: an ordered walk visits each calendar slot exactly once and never
  returns, so the hit rate is zero at any cache size. It earns its keep only for repeated
  requests for the *same* day (`gen_day`).
- **Every midnight is a real transition.** Day 1 starts from 1 January's fitted π(x₀);
  every later day's hour 0 comes from that day's cross-midnight model, conditioned on
  the previous day's 23:00 value.
- **Reproducibility.** Realisation *i* is keyed on `(seed, i, attribute)`, so it does not
  depend on how many realisations were requested — with one documented exception, the
  sampler switch above 64 realisations, noted in `generate_ensemble`'s docstring.

## Written to `examples/output/`

```
ensemble_heraklion_2023_n10.parquet   the record: 10 realisations x 8760 h x 3 attributes,
                                      with seed, window and source provenance embedded
year_heraklion_2023_r01.csv           realisation 0 alone, 8760 hours x 3 attributes
year_heraklion_monthly_summary.csv    generated vs observed monthly means
year_heraklion_ensemble_spread.csv    annual totals across realisations: value, P10, P90, CV
year_heraklion_2023_heatmap.png       only when PLOT_HEATMAP is True
```

**The parquet is the record**, not the CSV: it carries the generating parameters and the
source dataset's provenance, and it is documented in
[`docs/source/ensemble_format.md`](../../../docs/source/ensemble_format.md) so it can be
read without `meteosynth` installed. The CSV is there for anything that would rather read
one series than an ensemble. `WRITE_XLSX = True` adds a pivoted spreadsheet (needs
`uv sync --extra excel`).

The monthly summary is the first thing to look at before using the file: individual
months wander by a degree or two and should, since one realisation is one draw and not a
climatology. It is the **annual totals** and the **shape correlation** that have to hold
up. Absolute irradiance magnitudes **are** calibrated — measured 2026-07-28, the mean daily
total sits within 0.7 % of the pool the generator was fitted to, and an annual P90 is within
0.12 %. The known defect is the **overcast tail**, under-produced about fourfold (`FIX-1` in
`TODOs.md`), so a synthetic year holds fewer very dark days than the record does. That is
immaterial to annual energy and material to anything sizing storage against a dark spell.
