# Examples

Runnable scripts, split by what they are for.

| Folder | What lives there |
| :--- | :--- |
| [`use_cases/`](use_cases/) | Applied workflows that produce data: generate something, check it against the record, write it to disk. |
| [`concepts/`](concepts/) | Demonstrations of how the package behaves — training windows, leap days, the Markov engine, exploratory plots. |
| [`tools/`](tools/) | Shared helpers the scripts import (data loading, the observed-vs-synthetic comparison), plus one runnable cache-priming script. Not part of `meteosynth`. |
| `data/` | Cached PVGIS downloads. Git-ignored. |
| `output/` | Everything the scripts generate. Git-ignored (see `output/.gitignore`). |

Every script is a `#%%` cell script, so it can be stepped through in an editor as well
as run start to finish.

## Before the first run

```bash
uv sync --extra examples
uv run python examples/tools/fetch_site_data.py   # ~10 s, downloads once
```

`fetch_site_data.py` is optional — every script fetches what it needs on a cold cache —
but running it up front separates "waiting for PVGIS" from "waiting for the generator".

## Use cases

All four train on **Heraklion, Crete, 2010–2020** (eleven full years from PVGIS) and
write their output to `examples/output/`.

| Script | Question it answers | Runtime |
| :--- | :--- | :--- |
| [`use_cases/day_envelope_pv.py`](use_cases/day_envelope_pv.py) | Does a synthetic 21 May look like a real one? — plane-of-array **irradiance** | ~40 s |
| [`use_cases/day_envelope_temp.py`](use_cases/day_envelope_temp.py) | The same, for **air temperature** | ~60 s |
| [`use_cases/day_envelope_wind.py`](use_cases/day_envelope_wind.py) | The same, for **wind speed** | ~60 s |
| [`use_cases/synthetic_year.py`](use_cases/synthetic_year.py) | Generate a complete 8760-hour year of all three and write it out | ~4 min |
| [`use_cases/monthly_statistics.py`](use_cases/monthly_statistics.py) | What does an ensemble of synthetic Mays say, and does it vary like the real ones? | ~3 min |

```bash
uv run --extra examples python examples/use_cases/day_envelope_pv.py
uv run --extra examples python examples/use_cases/day_envelope_temp.py
uv run --extra examples python examples/use_cases/day_envelope_wind.py
uv run --extra examples python examples/use_cases/synthetic_year.py
uv run --extra examples python examples/use_cases/monthly_statistics.py
```

The three `day_envelope_*` scripts share one comparison (`tools/envelope.py`) run on
three quantities, and are separate files because the three quantities behave
differently enough to deserve their own commentary: irradiance is degenerate at night
and sits on its support bound, temperature is dominated by persistence, wind fans out
fast and is judged on `v³` rather than on the mean. Read the module docstrings — that
is where the interpretation lives.

## Concepts

Paris 2011–2012, the small shipped record, because these scripts are about mechanics
rather than about a site.

```bash
uv run python examples/concepts/example_exploratory_analysis.py   # loading & plotting the source data
uv run python examples/concepts/example_markov_generation.py      # EnvSeriesGenerator, one month, one attribute
uv run python examples/concepts/example_rolling_window.py         # rolling window vs calendar month
uv run --extra examples python examples/concepts/example_synthetic_year.py  # ~80 s, chained year + heatmap
uv run python examples/concepts/example_leap_year_windows.py      # leap days; needs no PVGIS at all
```

## Output

Everything generated lands in `examples/output/`, which is git-ignored:

```
day_21May_<attr>_ensemble.csv     200 synthetic days, one row each, hours as columns
day_21May_<attr>_stats.csv        the numbers printed by the comparison
day_21May_<attr>.png              the envelope figure
year_heraklion_2023_r01.csv       8760 hours x 3 attributes
year_heraklion_monthly_summary.csv
month_heraklion_05_ensemble.csv   12 synthetic Mays, long format
month_heraklion_05_statistics.csv
```

Delete the folder's contents freely — every file is reproducible by re-running the
script that wrote it, and the seeds are fixed in each script's constants.
