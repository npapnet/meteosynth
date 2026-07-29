# FEAT-2 (1) + FEAT-1 — Column resolution and cache provenance

Status: **superseded, never implemented** · Author: N. Papadakis (with Claude) · Date: 2026-07-29

> **Superseded the same day by [`FEAT-13-met-dataset-format.md`](FEAT-13-met-dataset-format.md).**
> Read that instead — this file is the record of a wrong turn, reduced to the part that is
> still worth having. Nothing here is a live specification.

## Why it was wrong

This plan put provenance inside the adapter's cache: a JSON sidecar beside each cached file,
plus a match predicate in `fetch_pvgis`. It was internally coherent and it answered the two
items as filed.

It was also backwards. Making the sidecar the home of provenance means **a dataset is only
traceable if you happened to use the fetcher** — so the package's auxiliary convenience layer
becomes the only route to a first-class property. For a package whose core business is
generating synthetic series from a *source-agnostic* training record, that inverts the
dependency: the thing that should be central (the dataset) had no representation at all,
while the thing that should be optional (the adapter) owned the metadata.

The root cause was a claim in `adapters.py` that this plan accepted without examining:

> *"It is never a required step, **so** there is no on-disk schema to design or version."*

That `so` does not follow. **"Optional to use" is not "not worth specifying."** `FEAT-13`
rejects the inference, makes `MetDataset` the core noun, and provenance becomes one of its
fields rather than a file beside a cache.

## What survived, and where it went

| From this plan | Now in `FEAT-13` |
| :--- | :--- |
| The irradiance-resolution rule and its four cases | Same rule, simpler membership test — an ordered `IRRADIANCE_COLUMNS` constant instead of spec identity |
| Rejecting `attr_str=None` as an implicit resolver | Recorded in the *Irradiance resolution* section |
| Coordinate matching to 4 decimal places | Recorded in *What shrinks*, where the cache comparison now lives |
| `force_refetch`, not `override` | Unchanged |
| No `irradiance_form` field — the column list answers it | Unchanged |
| JSON sidecar, `CacheMismatchError`, the match predicate | **Dropped.** Provenance is a field on a saved dataset; the comparison is ~15 lines |
| `DataFrame.attrs` as the in-memory carrier | **Dropped.** Superseded by explicit parquet key-value metadata |

## The measurement worth keeping

`DataFrame.attrs` propagation through this repo's real ingestion path — pandas 3.0.3 /
Python 3.13.11. `FEAT-13` no longer relies on `attrs`, so this is recorded here rather than
there, and it is the reason anyone reconsidering a frame-carried metadata scheme does not
have to re-measure:

```text
loc+copy     (trim_columns)  -> survives
boolean mask (day window)    -> survives
rename       (normalise)     -> survives
reset_index  (fetch_pvgis)   -> survives
MetDataProcessor.met_data    -> survives
get_day_window_subset        -> survives
pivot        (_to_wide)      -> LOST
csv roundtrip                -> LOST
```

`attrs` reaches the processor and every window subset intact. It is lost by the wide pivot
and by any CSV round-trip. That is workable — it was the basis of this plan — but it makes
metadata durability depend on a feature pandas documents as experimental, which is why
`FEAT-13` carries provenance on the dataset object and serialises it through parquet's own
key-value metadata instead.
