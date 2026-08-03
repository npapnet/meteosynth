# Overshoot diagnostics

Does the generator reproduce the distribution it was fitted to?

This folder answers that for the code as it ships, on the widest record PVGIS serves for
Heraklion (2005–2023, 19 years). It began as an investigation of the generated-irradiance
overshoot recorded in [`FIX-1`](../../TODOs.md) and **ended by retiring it**: the mean is
calibrated, and the defect is elsewhere.

- **[`PLAN.md`](PLAN.md)** — the design: *why* it is measured this way and *how* it runs,
  with the decision rule pre-registered before any code ran.
- **[`FINDINGS-2026-07-28.md`](FINDINGS-2026-07-28.md)** — what came out. **One dated file
  per run**; a later run adds a file rather than editing this one, so a result always keeps
  the date it was measured on.

## The result in three lines

- **No overshoot** at any of four dates through the year: mean daily total within 0.7 % of
  the pool the model was fitted to, on an instrument that detects an injected +10 % in 9 of
  9 configurations.
- **Too few overcast days**, at every date where the record contains any — 0.2 % against
  1.4 % observed below 1 kWh/m² at 21 March. This is what `FIX-1` now records.
- **Scott's rule is worse than the shipped `bandwidth=0.1`** on every statistic measured.

## How the comparison works

One configuration is a *(calendar date, window half-width, bandwidth)*. For each, the
generator is fitted to the pooled ±`n_days` window across all 19 years, and 1000
independent synthetic days are drawn from it.

**The same pool is both the training data and the reference.** That is the design's one
important property: the model was fitted to exactly those observed days, so the comparison
target is a known quantity rather than an estimate of one. Run 1 found that the choice of
reference could move an answer by more than the effect being measured; this removes the
choice rather than managing it.

Both samples are reduced to two per-day numbers — the daily **sum** and the daily
**maximum** — and compared statistic by statistic, each with a 95 % bootstrap interval from
resampling the synthetic side only.

## Running it

```bash
uv run python examples/diagnostics-overshoot/run_all.py
```

That runs all four steps in order — about **5 minutes** cold, most of it the PVGIS fetch —
announcing what each is about to do and roughly how long it will take, with a progress bar
per configuration and per draw inside it. It says up front whether the fetch will hit the
network or read the cache.

```bash
--n 100           # fewer realisations: a quick pass to check the pipeline
--from analyse    # start partway: fetch | simulate | analyse | figures
--resume          # skip configurations already written
--skip-figures    # stop after the tables
```

The four steps are also runnable on their own, and are import-safe and cell-friendly for an
interactive session:

```bash
uv run python examples/diagnostics-overshoot/step1_fetch.py      # probe + download, once
uv run python examples/diagnostics-overshoot/step2_simulate.py   # ~2 min
uv run python examples/diagnostics-overshoot/step3_analyse.py    # tables, seconds
uv run python examples/diagnostics-overshoot/step4_figures.py    # figures, seconds
```

Progress bars need `tqdm`, which is a core dependency — `uv sync` is enough.
They disable themselves automatically when output is not a terminal, so a redirected log
holds the printed results rather than several thousand redraws of a bar.

Interrupting is safe: step 2 writes incrementally, so a stopped run picks up with
`--resume`, and the analysis and figures re-derive from the CSVs in seconds.

All knobs live in [`config.py`](config.py) — dates, window half-width, the bandwidth
factor, seeds, thresholds. 21 May sits in `DAYS_BACKLOG` and is a one-line edit to enable.

## What lands on disk

`results/raw/` holds every number the conclusions rest on, in tidy long form. `step3` reads
**only** these files — never in-memory state from `step2` — so a check made by hand against
them is a check against exactly what the analysis saw.

| file | one row per |
| :--- | :--- |
| `config_index.csv` | configuration, with the KDE factor each bandwidth level actually chose |
| `observed_daily.csv` | configuration × observed day, with signed `days_from_centre` |
| `synthetic_daily.csv` | configuration × realisation |
| `observed_hourly.csv` | configuration × observed day × hour |
| `synthetic_hourly.csv` | configuration × realisation × hour |

Hourly values are W/m² as PVGIS supplies them; daily sums are `sum(hourly) / 1000` in
kWh/m²/day, and daily maxima are `max(hourly)` in W/m². That is the only arithmetic between
the hourly and daily files, so both are directly checkable.

**The smallest version of the whole experiment**: take one `config_id`, read its
`sum_kwh_m2` column from `observed_daily.csv` and from `synthetic_daily.csv`, and compare
the two distributions. Everything else is elaboration on that.

## What guards it

`step2` self-checks before anything is read: hourly values reconcile against both daily
sums and daily maxima, the observed row count matches years × (2n+1), offsets are signed
and symmetric, every year of the record is present, nothing falls outside physical support,
and no `config_id` appears twice. It prints a pass/fail block and says plainly if something
failed. A PID lockfile refuses to start while another run is writing the same files.

`step3` adds three controls, all reported before any result:

- a **null control** — the observed pool resampled in place of the synthetic sample, which
  must show no difference;
- a **positive control** — the synthetic sample inflated 10 %, which must be detected;
- an **anchor cell** — run 1's exact configuration, which must return run 1's numbers.

The first two catch a harness that reports differences that are not there, or misses ones
that are. The anchor catches a rewrite that quietly changed what is computed.

`results/summary_*.csv` and `figures/` are derived and regenerate from the raw files in
seconds. `results/raw/` and `figures/` are git-ignored, matching the repo's rule for
the examples' `output/` folders; the dated `FINDINGS-*.md` and the summary tables are committed, because
they are the evidence `FIX-1` cites.

## What it reuses

`examples/tools/site_data.py` for the site definition, and `examples/tools/envelope.py` for
`day_matrix` and the CVD-validated chart palette. Data is fetched through
`meteosynth.adapters.fetch_pvgis`. **No library code is modified by anything here.**
