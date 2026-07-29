# Year — produce a complete 8760-hour series

| Script | What it does | Runtime |
| :--- | :--- | :--- |
| [`synthetic_year.py`](synthetic_year.py) | One 8760-hour series per attribute, chained day by day across midnight, written to CSV | ~4 min per realisation |

```bash
uv run --extra examples python examples/use_cases/year/synthetic_year.py
```

This script exists to **produce data**, not to make a point: the file it writes is the
input to whatever comes next — a PV yield model, a battery sizing run, a demand
simulation. Set `PLOT_HEATMAP = True` for a year-at-a-glance figure (day of year across,
hour of day down, one panel per attribute), which shows what the monthly table cannot:
the seasonal envelope, and the summer day widening at both ends rather than merely
getting brighter.

## What the output is, and is not

- It **is** one plausible realisation of a year at this site. Every hour is drawn, not
  copied; the series never repeats a historical year.
- It is **not** a forecast of any particular year, and one realisation is not a
  Monte-Carlo study. Raise `N_REALISATIONS` for that — the spread between draws is the
  quantity the whole exercise is for.

## Mechanics worth knowing while it runs

- **Non-leap is the default.** `generate_series` walks 365 days from 1 January with
  `include_feb29=False`, so Feb 29 is never requested — no filtering, no exclusion list.
  Ask for a leap year instead and Feb 29 generates like any other day.
- **Memory stays flat.** All 366 fitted generators would cost ~126 MB per attribute.
  `DayWindowGenerator` fits each day on demand behind a small LRU cache, so the walk
  holds a few hundred KB however long it runs. Raise `CACHE_SIZE` towards 366 to make
  extra realisations nearly free and pay the memory instead.
- **Every midnight is a real transition.** Day 1 starts from 1 January's fitted π(x₀);
  every later day's hour 0 comes from that day's cross-midnight model, conditioned on
  the previous day's 23:00 value.

## Written to `examples/output/`

```
year_heraklion_2023_r01.csv           8760 hours x 3 attributes
year_heraklion_monthly_summary.csv    generated vs observed monthly means
year_heraklion_2023_heatmap.png       only when PLOT_HEATMAP is True
```

The monthly summary is the first thing to look at before using the file: individual
months wander by a degree or two and should, since this is one draw and not a
climatology. It is the **annual totals** and the **shape correlation** that have to hold
up. Absolute irradiance magnitudes **are** calibrated — measured 2026-07-28, the mean daily
total sits within 0.7 % of the pool the generator was fitted to, and an annual P90 is within
0.12 %. The known defect is the **overcast tail**, under-produced about fourfold (`FIX-1` in
`TODOs.md`), so a synthetic year holds fewer very dark days than the record does. That is
immaterial to annual energy and material to anything sizing storage against a dark spell.
