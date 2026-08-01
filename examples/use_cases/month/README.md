# Month — does an ensemble of synthetic months vary like the real ones?

| Script | What it does | Runtime |
| :--- | :--- | :--- |
| [`monthly_statistics.py`](monthly_statistics.py) | 12 independent synthetic Mays, all three attributes, reported against the eleven observed Mays | ~3 min |

```bash
uv run python examples/use_cases/month/monthly_statistics.py
```

Nothing is plotted — the output is a statistics table.

## Why an ensemble, and not one month

A single synthetic May tells you nothing you could not read off the record. An
*ensemble* answers what the record cannot, because eleven Mays is too few to put a
number on a tail:

- **How much does May vary?** The spread across realisations is the generator's answer;
  the spread across observed years is the check on it.
- **What is the P90 month?** Energy finance quotes P50/P90 — the value *exceeded* in
  50 % and 90 % of cases. Eleven observations give a P90 that moves when you add a year.
- **Where does the variability live?** Mean level and diurnal shape are reported
  separately, because a dull month and a month with a few catastrophic days are
  different engineering problems.

## Read the spread row first

On the shipped configuration irradiance and temperature land near 1 on the
synthetic-to-observed standard-deviation ratio, while monthly mean **wind spreads about
2.5× wider** than the eleven real Mays do. A wind study built on this ensemble would
price a tail the record does not support. It is the kind of thing only an ensemble
reveals; no amount of looking at individual days shows it.

## Written to `examples/output/`

```
month_heraklion_05_ensemble.csv     every realisation, long format
month_heraklion_05_statistics.csv   the statistics table
```
