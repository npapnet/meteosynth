# Overshoot diagnostics

Does the generated-irradiance bias recorded in [`FIX-1`](../../TODOs.md) depend on how
many years the model was trained on — and is it there at all?

`FIX-1` records +14 % on a two-year Paris record but only +2–3 % on an eleven-year
Heraklion one. Three explanations fit that equally well: the bias is **structural** (a KDE
boundary effect at the zero floor, plus compounding along the 24-step walk), it is a
**small-sample** artefact that decays as the pool grows, or it is a **false positive** —
noise, or an artefact of the reference it was measured against.

This folder measures the bias as a function of training-set size, on the widest record
PVGIS serves for Heraklion (2005–2023, 19 years).

- **[`PLAN.md`](PLAN.md)** — the design, and the reasoning behind each choice. Written and
  reviewed before any code ran; the decision rule is pre-registered there.
- **[`FINDINGS.md`](FINDINGS.md)** — what came out, and which branch of that rule fired.

## Running it

```bash
uv run python examples/diagnostics-overshoot/step1_fetch.py      # probe + download, once
uv run python examples/diagnostics-overshoot/step2_simulate.py   # the simulation
uv run python examples/diagnostics-overshoot/step3_analyse.py    # tests and tables
uv run python examples/diagnostics-overshoot/step4_figures.py    # figures
```

Steps are separate so the simulation is paid once: steps 3 and 4 re-run against the CSVs
in seconds. Every script is import-safe and cell-friendly for an interactive session.

Useful flags on step 2:

```bash
--n 1000     # realisations per configuration (config.py sets the default)
--draws 5    # year-subsets per training size
--resume     # skip configurations already written
```

All knobs live in [`config.py`](config.py) — sizes, calendar days, seeds, bandwidth,
window width. The other three calendar days (21 Jun, 21 Dec, 21 May) are wired and
commented out; enabling them is a one-line edit.

## What lands on disk

`results/raw/` holds every number the conclusions rest on, in tidy long form, so the
analysis can be checked independently rather than taken on trust. `step3` reads **only**
these files — never in-memory state from `step2` — so a check made by hand against them is
a check against exactly what the analysis saw.

| file | one row per |
| :--- | :--- |
| `config_index.csv` | configuration — including `years`, the exact years each draw selected |
| `observed_daily_totals.csv` | configuration × observed day, with `is_centre` and signed `days_from_centre` |
| `synthetic_daily_totals.csv` | configuration × realisation, with a deviation per reference |
| `observed_hourly.csv` | configuration × observed day × hour |
| `synthetic_hourly.csv` | configuration × realisation × hour |
| `references.csv` | configuration × reference, with `m` — how many observed values it rests on |

Hourly values are W/m² as PVGIS supplies them; daily totals are `sum(hourly) / 1000` in
kWh/m²/day. That division is the only arithmetic between the two files.

**To pull the smallest version of the whole experiment**: filter
`observed_daily_totals.csv` on `is_centre` and `config_id == "k19_d0_0321"` for every
21 March in the record, one row per year, and take the same `config_id` from
`synthetic_daily_totals.csv` for the synthetic ones.

`step2` self-checks before you read anything: hourly sums reconcile against daily totals,
centre-day count equals `k`, window count equals `k × 31`, offsets are signed and
symmetric, no observed year appears outside its configuration's declared subset, no
values outside physical support. It prints a pass/fail block and says plainly if
something failed.

`results/summary_*.csv` and `figures/` are derived and can be regenerated from the raw
files at any time. Both `results/raw/` and `figures/` are git-ignored, matching the
repo's rule for `examples/output/`; `FINDINGS.md` and the summary tables are committed,
because they are the evidence `FIX-1` cites.

## What it reuses

`examples/tools/site_data.py` for the site definition, and `examples/tools/envelope.py`
for `day_matrix` and the CVD-validated chart palette. Data is fetched through
`meteosynth.adapters.fetch_pvgis`. No library code is modified by anything here.
