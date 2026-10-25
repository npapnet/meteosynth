# Day — does a synthetic day look like a real one?

Each script draws **200 independent synthetic 21 Mays** and holds them against every
21 May the record contains, plus the percentile envelope of the surrounding fortnight.
Independent, not a walk: every call redraws π(x₀), so these are samples of 21 May's
climate rather than 200 consecutive days.

| File | Attribute | Runtime per case |
| :--- | :--- | :--- |
| [`day_envelope_pv.py`](day_envelope_pv.py) | `poa_global` — plane-of-array irradiance | ~25 s |
| [`day_envelope_temp.py`](day_envelope_temp.py) | `temp_air` — air temperature | ~45 s |
| [`day_envelope_wind.py`](day_envelope_wind.py) | `wind_speed` — wind speed | ~45 s |
| [`day_study.py`](day_study.py) | the machinery all three share — not run directly | — |

```bash
uv run python examples/use_cases/day/day_envelope_pv.py
uv run python examples/use_cases/day/day_envelope_temp.py
uv run python examples/use_cases/day/day_envelope_wind.py
```

## Each script states its own site, period and parameters

Nothing is imported from a shared site registry: coordinates, label and year range are
constants in each script's preamble, next to the attribute and the target date, and go
straight to `fetch_pvgis`. The file is the whole statement of what was run.

```python
SITE_NAME = "Heraklion, Crete"
LATITUDE, LONGITUDE = 35.3387, 25.1442
YEARS = None              # every year PVGIS serves for this site
# YEARS = (2010, 2020)    # the eleven-year record the scripts were written against
```

`YEARS = None` asks for the provider's whole record — **but only on a cold folder.** A
request for no particular period means "whatever you have", so a `data/` that already
holds 2010–2020 keeps answering with it. Each run prints the period it actually loaded;
to widen the folder, delete the narrow parquet first (`refresh=True` on its own leaves
both records behind, and two records answering one request is refused rather than
guessed).

The three sweep axes are **lists**, so one launch can run several configurations:

```python
POOL_DAYS   = [7, 1]    # observed envelope half-width — the blue band only
WINDOW_DAYS = [15, 7]   # training window half-width — this is what changes the synthetic days
N_SYNTHETIC = [200]     # ensemble size
```

`run_case(...)` does one combination and returns its figure and stats; `run_sweep(...)`
walks every combination of the three lists, fitting once per distinct `WINDOW_DAYS`
(fitting depends on the training window alone) and reusing that fit across the
`POOL_DAYS` beneath it. Both take the script's `STUDY` — site, attribute, date and the
two variable-specific report hooks. In an interactive session, load the record once and
drive them directly:

```python
ds = load_dataset(STUDY)
result = run_case(STUDY, ds, pool_days=7, window_days=15, n_synthetic=200)
summary, results = run_sweep(STUDY, ds, pool_days=[7, 1], window_days=[15, 7])
```

## Three checks, because a generator can pass one and fail another

| Check | What it asks | Where it goes wrong |
| :--- | :--- | :--- |
| **shape** | does the synthetic median trace the observed diurnal cycle? | peak at the wrong hour |
| **spread** | what share of synthetic hours land inside the observed p10–p90? | ~80 % is calibrated; far above means the ensemble is too narrow |
| **quantity** | does the daily total (or mean) land in the right place? | the number an energy model consumes — and the one that can be wrong while the shape looks right |

## Written to `output/`, beside these scripts

Every filename carries the parameters that produced it, so runs accumulate instead of
overwriting one another and can be compared directly:

```
day_21May_<attr>_pool07_win15_n0200_seed42_ensemble.csv   the synthetic days, one row each, hours as columns
day_21May_<attr>_pool07_win15_n0200_seed42_stats.csv      the numbers printed by the comparison, with its parameters
day_21May_<attr>_pool07_win15_n0200_seed42.png            the envelope figure, captioned with the same tag
day_21May_<attr>_sweep_summary.csv                        one row per case of the last sweep, every metric as a column
```

`pool07` is `POOL_DAYS`, `win15` is `WINDOW_DAYS`, `n0200` is `N_SYNTHETIC`; numbers are
zero-padded so a directory listing sorts the way they do. The figure repeats the tag in
its bottom-right corner, because an image pasted into a document has left its filename
behind. The summary CSV is the one to plot when comparing configurations — note that
`window_days` changes the synthetic days while `pool_days` changes only the observed
band they are judged against, so coverage moving with `pool_days` alone is the band
changing width, not the generator changing behaviour.

## Why three scripts and not one loop

Everything that does not depend on which quantity is being modelled lives in
[`day_study.py`](day_study.py) — collecting the record, fitting, drawing the ensemble,
naming files after their parameters, and the sweep. The comparison itself is
[`tools/envelope.py`](../../tools/envelope.py), which stays there because
`diagnostics-overshoot/` imports it too.

What is left in each script is its preamble and the two things genuinely specific to its
variable, handed to `DayStudy` as functions: `describe_fit`, the lines printed about the
fitted models, and `extra_report`, the fourth check after shape, spread and quantity.
They stay separate files because the quantities behave differently enough to deserve
their own commentary:

- `poa_global` is **degenerate at night** — π(x₀) collapses to a spike at zero and ~10 of
  the day's hourly models are constant — and it sits on its support bound at dawn.
  Magnitudes are calibrated (within 0.7 % of the pool mean, measured 2026-07-28), but the
  ensemble holds **too few heavily overcast days** — see `FIX-1` in `TODOs.md`.
- `temp_air` never degenerates and is **dominated by persistence**, so a day's level is
  largely decided at midnight.
- `wind_speed` **fans out fastest** and is judged on `v³` rather than the mean, where a
  small bias in speed becomes a larger one in power.

The module docstrings are where the interpretation lives — read them alongside the output.
