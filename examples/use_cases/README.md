# Use cases

Applied workflows, grouped by the **time scale of the question they answer**. All of
them train on the same record — Heraklion, Crete, 2010–2020, eleven full years from
PVGIS — and all of them write to the git-ignored `examples/output/`.

| Folder | The question | Runtime |
| :--- | :--- | :--- |
| [`day/`](day/) | Does a synthetic *day* look like a real one? | ~40–60 s each |
| [`month/`](month/) | Does an ensemble of synthetic *months* vary like the real ones? | ~3 min |
| [`year/`](year/) | Produce a complete 8760-hour *year* to feed something downstream. | **~45–50 min** |

Each folder's `README.md` says what its scripts answer, what they write, and how long
they take. Read those before the scripts.

The scale is not a presentation detail — it changes what can be asked. A single day can
be held against eleven real ones, so shape and spread are checkable directly. A month
only becomes meaningful as an ensemble, because one synthetic May is a draw and not a
climatology. A year is not checked at all here; it is *produced*, and the checking is
whatever consumes it.

```bash
# Optional: prime the download cache once, so no script waits on PVGIS
uv run python examples/tools/fetch_site_data.py

uv run python examples/use_cases/day/day_envelope_pv.py
uv run python examples/use_cases/month/monthly_statistics.py
uv run python examples/use_cases/year/synthetic_year.py
```

New to *ensemble*, *realisation*, *envelope*, *P90*? Read
[`docs/source/concepts.md`](../../docs/source/concepts.md) first — it defines every term
these scripts print.
