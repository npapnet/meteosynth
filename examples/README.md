# Examples

Runnable scripts, split by what they are for.

| Folder | What lives there |
| :--- | :--- |
| [`use_cases/`](use_cases/) | Applied workflows that produce data, split by time scale into [`day/`](use_cases/day/), [`month/`](use_cases/month/) and [`year/`](use_cases/year/) — each with its own README. |
| [`concepts/`](concepts/) | Demonstrations of how the package behaves — training windows, leap days, the Markov engine, exploratory plots. |
| [`tools/`](tools/) | Shared helpers the scripts import (data loading, the observed-vs-synthetic comparison), plus one runnable cache-priming script. Not part of `meteosynth`. |
| [`diagnostics-overshoot/`](diagnostics-overshoot/) | A measurement rather than a demonstration: does the generator reproduce the distribution it was fitted to? Four steps behind one `run_all.py`, ~20 min, with the design, the pre-registered decision rule and the dated findings alongside. This is what `FIX-1` cites. |
| `data/` | Cached PVGIS downloads. Git-ignored. |
| `output/` | Everything the scripts generate. Git-ignored (see `output/.gitignore`). |

Every script is a `#%%` cell script, so it can be stepped through in an editor as well
as run start to finish.

New to the vocabulary — *ensemble*, *realisation*, *envelope*, *P90*? Read
[`docs/source/concepts.md`](../docs/source/concepts.md) first; it defines every term
these scripts print or plot.

## Before the first run

```bash
uv sync --extra examples
uv run python examples/tools/fetch_site_data.py   # ~10 s, downloads once
```

`fetch_site_data.py` is optional — every script fetches what it needs on a cold cache —
but running it up front separates "waiting for PVGIS" from "waiting for the generator".

## Use cases

All of them train on **Heraklion, Crete, 2010–2020** (eleven full years from PVGIS) and
write their output to `examples/output/`. They are grouped by the **time scale of the
question**, because the scale changes what can be asked — see
[`use_cases/README.md`](use_cases/README.md).

| Script | Question it answers | Runtime |
| :--- | :--- | :--- |
| [`use_cases/day/day_envelope_pv.py`](use_cases/day/day_envelope_pv.py) | Does a synthetic 21 May look like a real one? — plane-of-array **irradiance** | ~40 s |
| [`use_cases/day/day_envelope_temp.py`](use_cases/day/day_envelope_temp.py) | The same, for **air temperature** | ~60 s |
| [`use_cases/day/day_envelope_wind.py`](use_cases/day/day_envelope_wind.py) | The same, for **wind speed** | ~60 s |
| [`use_cases/month/monthly_statistics.py`](use_cases/month/monthly_statistics.py) | What does an ensemble of synthetic Mays say, and does it vary like the real ones? | ~3 min |
| [`use_cases/year/synthetic_year.py`](use_cases/year/synthetic_year.py) | Generate a complete 8760-hour year of all three and write it out | ~4 min |

```bash
uv run --extra examples python examples/use_cases/day/day_envelope_pv.py
uv run --extra examples python examples/use_cases/day/day_envelope_temp.py
uv run --extra examples python examples/use_cases/day/day_envelope_wind.py
uv run --extra examples python examples/use_cases/month/monthly_statistics.py
uv run --extra examples python examples/use_cases/year/synthetic_year.py
```

The three `day_envelope_*` scripts share one comparison (`tools/envelope.py`) run on
three quantities, and are separate files because the three quantities behave
differently enough to deserve their own commentary: irradiance is degenerate at night
and sits on its support bound, temperature is dominated by persistence, wind fans out
fast and is judged on `v³` rather than on the mean. Read the module docstrings — that
is where the interpretation lives.

## Concepts

Paris 2011–2012, the small shipped record, because these scripts are about mechanics
rather than about a site. Each one demonstrates something no use case does; anything
that merely re-ran a use case on a smaller record has been retired.

```bash
uv run python examples/concepts/example_exploratory_analysis.py   # loading & plotting the source data
uv run python examples/concepts/example_rolling_window.py         # rolling window vs calendar month
uv run python examples/concepts/example_leap_year_windows.py      # leap days; needs no PVGIS at all
```

## Output

Everything generated lands in `examples/output/`, which is git-ignored:

```
day_21May_<attr>_ensemble.csv     200 synthetic days, one row each, hours as columns
day_21May_<attr>_stats.csv        the numbers printed by the comparison
day_21May_<attr>.png              the envelope figure
month_heraklion_05_ensemble.csv   12 synthetic Mays, long format
month_heraklion_05_statistics.csv
year_heraklion_2023_r01.csv       8760 hours x 3 attributes
year_heraklion_monthly_summary.csv
year_heraklion_2023_heatmap.png   only when PLOT_HEATMAP is True
```

The `day_` / `month_` / `year_` prefixes are why the three use-case folders can share
one flat output directory.

Delete the folder's contents freely — every file is reproducible by re-running the
script that wrote it, and the seeds are fixed in each script's constants.
