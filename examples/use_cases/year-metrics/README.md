# `year-metrics/` — generate a three-variable ensemble, then measure it

One script **generates** 1 000 synthetic years of `poa_global`, `temp_air` and
`wind_speed` — one calendar, one training record, one seed, one file. Four scripts
**measure** that file against the record it was trained on, through `meteosynth.metrics`.

| Script | What it does | Writes to |
| :--- | :--- | :--- |
| [`metrics_ensemble.py`](metrics_ensemble.py) | Generates the ensemble and checks it round-trips. Computes no metrics. | `output/` |
| [`metrics-marginal_basic.py`](metrics-marginal_basic.py) | ECDF of one variable, reference vs synthetic. Plain pandas read. | `output/` |
| [`metrics-temporal_basic.py`](metrics-temporal_basic.py) | Autocorrelation to 10 days for one variable, against the reference years' spread. | `output/` |
| [`metrics-marginal_adv.py`](metrics-marginal_adv.py) | `MarginalFidelity` — Wasserstein-1 per (month, hour) cell against a year-split control band, every variable, heatmaps and a summary CSV. | `output_adv/marginal/` |
| [`metrics-temporal_adv.py`](metrics-temporal_adv.py) | `TemporalFidelity` — raw and anomaly ACF and decorrelation time, every variable, streamed row group by row group. | `output_adv/temporal/` |

```bash
uv run python examples/use_cases/year-metrics/metrics_ensemble.py        # hours
uv run python examples/use_cases/year-metrics/metrics-marginal_adv.py    # minutes
uv run python examples/use_cases/year-metrics/metrics-temporal_adv.py
```

Generation and measurement are separate scripts on purpose: generation is expensive and
runs once, measurement is cheap and runs many times. What each metric means, and how well
it suits this package, is in the documentation's
[*Validating synthetic data*](../../../docs/source/metrics/index.md) section; the package
design is [`FEAT-23`](../../../docs/design/completed/FEAT-23-metrics-package.md).

## Basic and advanced

The `_basic` scripts are written to be read: one variable (chosen by `ATTR_IDX`), laid out
as constants, functions and invocation cells, the ensemble read with pandas. They resolve
`data/` and `output/` against the **working directory**, so run them from this folder or
step through them as `#%%` cells.

The `_adv` scripts are written to be run: every variable in one pass, the ensemble streamed
into a preallocated `(N, 8760)` array (~70 MB at N = 1 000, against ~276 MB+ for a full
pandas read), and a summary CSV per ensemble. They find their folders through
`meteosynth.workspace(__file__)`, so they behave the same from any directory.

Both tiers drop Feb 29 from the reference — the ensemble is generated without it — and
name every output after the ensemble it measured, so runs at different training windows
(`_w7_`, `_w15_`) sit side by side.

## What it writes

```
year-metrics/
    data/        pvgis_hourly_<site>_2005_2023.parquet             the training record
                 ensemble_<site>_2023_n1000_w<W>_3attr.parquet     input to the metric scripts
    output/      ensemble_<site>_2023_n<N>_w<W>_3attr.parquet      what metrics_ensemble.py writes
                 <ensemble stem>-<attr>_ecdf.png, …_temporal_acf.png   basic-tier figures
    output_adv/  marginal/<attr>/<ensemble stem>-<attr>_marginal_w1.csv  and  .png
                 marginal/<ensemble stem>_marginal_summary.csv
                 temporal/<attr>/<ensemble stem>-<attr>_temporal_acf.csv  and  .png
                 temporal/<ensemble stem>_temporal_summary.csv
```

All three folders are git-ignored. **The metric scripts read the ensemble from `data/`, not
`output/`**: move (or copy) a finished ensemble across before measuring it, and set
`SYNTHETIC_DATA_PARQUET` at the top of each script to the file you want measured. The
site is set in `metrics_ensemble.py` (`SITE`, `LATITUDE`, `LONGITUDE`) — currently
Heraklion, with Leros commented out alongside.

**You can skip the download** when a sibling folder already holds the record: records are
found by reading provenance rather than by filename, so copying the parquet into this
folder's `data/` is enough — `fetch_pvgis` will match it and make no network call.

## Relation to `year-leros/`

[`year-leros/`](../year-leros/) produces the same kind of ensemble for **`wind_speed`
alone** and measures it with self-contained scripts that predate `meteosynth.metrics`.
Generation constants are matched between the two — seed (2026), window, realisation count
(1 000), calendar, sampling path. Randomness is keyed on `(seed, realisation index,
attribute name)` and never on the attribute's position in the list, so at the same site
and window **the wind column here should reproduce the wind-only file rather than merely
resemble it**. (The script no longer checks this itself; compare one calendar day of the
two files if you rely on it.)

## Runtime and size

Read ratios, not seconds. Cost is **days × attributes** and very nearly independent of the
realisation count, because the calendar is walked once and each day's fitted models are
shared by every realisation. `poa_global` is constant overnight and needs a 2D KDE for well
under half its transitions, so:

| | relative cost |
| :--- | :--- |
| `wind_speed` alone (the `year-leros` run) | 1.0 |
| `temp_air` alone | ~1.0 |
| `poa_global` alone | ~0.33 |
| **all three, this run** | **~2.3** |

Output is ~200–250 MB against 90 MB for one attribute. **Size a trial first:** set
`N_DAYS = 30`, time it, multiply by 12.

## Two things to know before using the output

**Attributes are generated independently.** Within a realisation, a hot hour is not thereby
a sunny one. The file says so in its own metadata. No cross-variable claim can be made from
it — not correlation, not coincident extremes, not joint droughts.

**The calendars differ by the leap days.** The observed record holds Feb 29 in each leap
year; the ensemble holds none. Every metric script here drops them from the reference
before comparing.
