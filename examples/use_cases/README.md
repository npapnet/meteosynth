# Use cases

Applied workflows, grouped by the **time scale of the question they answer**. The first
three train on the same record — Heraklion, Crete, 2010–2020, eleven full years from
PVGIS; the two Leros folders train on 2005–2023, nineteen years. Each writes to its own
folder's git-ignored `output/`, having collected its record into its own `data/`.

| Folder | The question | Runtime |
| :--- | :--- | :--- |
| [`day/`](day/) | Does a synthetic *day* look like a real one? | ~40–60 s each |
| [`month/`](month/) | Does an ensemble of synthetic *months* vary like the real ones? | ~3 min |
| [`year/`](year/) | Produce a complete 8760-hour *year* to feed something downstream. | **~45–50 min** |
| [`year-leros/`](year-leros/) | Generate 1 000 synthetic years of `wind_speed` at Leros — then ask whether they are faithful, on two axes. | **hours** to generate; ~2 min per metric |
| [`year-metrics/`](year-metrics/) | The same generation, widened to all three quantities in one file. Data only. | **~2.3×** `year-leros` |

`year-leros/` is the only folder here that both generates and *measures*: one script writes
the ensemble, and two read it back against the 19-year record — `leros_metric_marginal.py`
for distributional fidelity (Wasserstein-1 per month × hour, against a year-split control
band) and `leros_metric_temporal.py` for persistence (autocorrelation to 10 days, against
the observed year-to-year spread). Both are specified in
[`paper/metrics-prompt.md`](../../paper/metrics-prompt.md), and both stream the 90 MB
ensemble rather than loading it.

Each folder's `README.md` says what its scripts answer, what they write, and how long
they take. Read those before the scripts.

The scale is not a presentation detail — it changes what can be asked. A single day can
be held against eleven real ones, so shape and spread are checkable directly. A month
only becomes meaningful as an ensemble, because one synthetic May is a draw and not a
climatology. A year is not checked at all here; it is *produced*, and the checking is
whatever consumes it.

```bash
uv run python examples/use_cases/day/day_envelope_pv.py
uv run python examples/use_cases/month/monthly_statistics.py
uv run python examples/use_cases/year/synthetic_year.py
```

New to *ensemble*, *realisation*, *envelope*, *P90*? Read
[`docs/source/concepts.md`](../../docs/source/concepts.md) first — it defines every term
these scripts print.
