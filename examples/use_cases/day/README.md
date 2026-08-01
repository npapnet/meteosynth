# Day — does a synthetic day look like a real one?

Each script draws **200 independent synthetic 21 Mays** and holds them against the
eleven observed 21 Mays, plus the percentile envelope of the surrounding fortnight.
Independent, not a walk: every call redraws π(x₀), so these are samples of 21 May's
climate rather than 200 consecutive days.

| Script | Attribute | Runtime |
| :--- | :--- | :--- |
| [`day_envelope_pv.py`](day_envelope_pv.py) | `poa_global` — plane-of-array irradiance | ~40 s |
| [`day_envelope_temp.py`](day_envelope_temp.py) | `temp_air` — air temperature | ~60 s |
| [`day_envelope_wind.py`](day_envelope_wind.py) | `wind_speed` — wind speed | ~60 s |

```bash
uv run python examples/use_cases/day/day_envelope_pv.py
uv run python examples/use_cases/day/day_envelope_temp.py
uv run python examples/use_cases/day/day_envelope_wind.py
```

## Three checks, because a generator can pass one and fail another

| Check | What it asks | Where it goes wrong |
| :--- | :--- | :--- |
| **shape** | does the synthetic median trace the observed diurnal cycle? | peak at the wrong hour |
| **spread** | what share of synthetic hours land inside the observed p10–p90? | ~80 % is calibrated; far above means the ensemble is too narrow |
| **quantity** | does the daily total (or mean) land in the right place? | the number an energy model consumes — and the one that can be wrong while the shape looks right |

## Written to `examples/output/`

```
day_21May_<attr>_ensemble.csv    200 synthetic days, one row each, hours as columns
day_21May_<attr>_stats.csv       the numbers printed by the comparison
day_21May_<attr>.png             the envelope figure
```

## Why three scripts and not one loop

The three share one comparison ([`tools/envelope.py`](../../tools/envelope.py)) run on
three quantities, and stay separate files because the quantities behave differently
enough to deserve their own commentary:

- `poa_global` is **degenerate at night** — π(x₀) collapses to a spike at zero and ~10 of
  the day's hourly models are constant — and it sits on its support bound at dawn.
  Magnitudes are calibrated (within 0.7 % of the pool mean, measured 2026-07-28), but the
  ensemble holds **too few heavily overcast days** — see `FIX-1` in `TODOs.md`.
- `temp_air` never degenerates and is **dominated by persistence**, so a day's level is
  largely decided at midnight.
- `wind_speed` **fans out fastest** and is judged on `v³` rather than the mean, where a
  small bias in speed becomes a larger one in power.

The module docstrings are where the interpretation lives — read them alongside the output.
