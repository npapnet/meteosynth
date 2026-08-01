# docs/design

**Design notes, specs and brainstorms. Not user documentation.**

This folder is a workspace for thinking: specifications, design proposals, brainstorms,
investigations, and future design patterns. Things land here *before* they are decided,
and stay here after, as the record of why.

## This folder is not part of the published documentation

Sphinx builds from `docs/source/` only (`SOURCEDIR = source` in `docs/Makefile`). This
folder is a sibling of that tree, so Sphinx never sees it — no toctree entry, no
`exclude_patterns` rule, nothing to maintain. It is out by construction.

**Write plain GitHub-flavored Markdown here, not MyST.** These files are read in an
editor or on GitHub, never rendered by Sphinx, so MyST-only constructs do not work:

| don't use | use instead |
|---|---|
| `` ```{note} `` | `> **Note**` blockquote |
| `` ```{mermaid} `` | `` ```mermaid `` (GitHub renders it natively) |
| ``{doc}`page` `` | `[page](page.md)` |
| `$x$` / `$$x$$` maths | fine in prose, but it won't render — keep formulae simple |

User-facing documentation belongs in `docs/source/` instead: `quickstart.md`,
`theory.md`, `examples.md`, `api.rst`.

## Conventions

Each document opens with a status line, so a reader knows what they are holding:

```markdown
Status: proposed · Author: … · Date: YYYY-MM-DD
```

Suggested values: `proposed`, `accepted`, `implemented`, `superseded`, `explainer`,
`brainstorm`. Update the status when reality moves — a stale `proposed` on shipped work
is worse than no status at all.

Where a document makes a quantitative claim, prefer numbers measured against the real
dataset (`data/pvgis_hourly_data.xlsx`) over estimates, and say which is which.

## Contents

Active / Architecture reference:

| document | type | description |
|---|---|---|
| [architecture.md](architecture.md) | architecture reference | Concise overview of package essence, current state (v0.3.1), mathematical foundation, repository tree structure, module responsibilities, and developer/agent onboarding guide. **Synced against the codebase 2026-08-01.** |
| [FEAT-2-FEAT-1-column-resolution-and-provenance.md](FEAT-2-FEAT-1-column-resolution-and-provenance.md) | **superseded** · record only | Superseded by `FEAT-13` the same day, never implemented. Reduced to why the approach was backwards — provenance in the adapter's cache makes a dataset traceable only if you used the fetcher — plus the `DataFrame.attrs` propagation measurements, which `FEAT-13` no longer relies on and which are recorded nowhere else. **Not a live specification.** |



## Completed

Implemented, tested, and moved to [`completed/`](completed/) so this top-level folder
only holds work still in flight. Each retains its own status line plus an archive note
recording when it landed; move a doc here once its feature is implemented and green in
the test suite, not before.

| document | type | implemented | what it is |
|---|---|---|---|
| [completed/FEAT-15-ensemble-generation.md](completed/FEAT-15-ensemble-generation.md) | design spec | 2026-07-30 | `FEAT-15`: generating N synthetic years in one calendar walk instead of N walks — **27 h → 21 min at N = 1000**, measured. Settles the randomness scheme (streams keyed on realisation index and attribute *name*, so a realisation depends on neither how many were asked for nor which other attributes came along), the output format (one long-format parquet file, one row group flushed per calendar day, pivoted `.xlsx` as a lossy export), and why a long `.xlsx` is impossible past ~119 realisations. Closes with a plain-language record of why the draws are **not** batched, deferred to `PERF-16`. Carries an archive note listing four deviations taken during implementation, including a reproducibility defect the LRU cache caused and the corrected headline figure (~77×, not the ~300× first projected). |
| [completed/FEAT-13-met-dataset-format.md](completed/FEAT-13-met-dataset-format.md) | design spec | 2026-07-29 | `MetDataset` as the package's core noun — a strict, versioned, source-agnostic training format with validation at construction, provenance as a field, and lossless parquet round-trip. Supersedes `FEAT-1`; absorbs `FEAT-2 (1)`, `FEAT-5` and `CHORE-3`. Records three measured correctness holes on the core ingestion path, and an archive note listing three deviations taken during implementation. |
| [completed/PERF-1-precomputed-conditional-quantiles.md](completed/PERF-1-precomputed-conditional-quantiles.md) | design note | 2026-07-28 | `PERF-1`: caching the conditional inverse CDF for simulators that are sampled often — 8× on ensemble work, nothing on a year-long walk. Records why the *quantile function* is the thing interpolated rather than the CDF, why node spacing is uniform rather than quantile-based, why the cache is lazy, and what the test suite did **not** catch. |
| [completed/variable-specs-and-initialisation.md](completed/variable-specs-and-initialisation.md) | design spec | 2026-07-22 | An extensible `VariableSpec` registry replacing the fixed column whitelist; sampling truncated to each quantity's physical support; `start_value` replaced by a fitted initial distribution π(x₀) plus a real cross-midnight transition; `generate_series` on the rolling-window path; an optional source-adapter layer. Fixes negative irradiance, out-of-domain crashes and the hour-0 quirk. Carries an archive note recording two claims that did not survive measurement. |
| [completed/rolling-day-window.md](completed/rolling-day-window.md) | design spec | 2026-07-15 | A rolling ±n-day training window as an alternative to the month split, incl. the `all_leap` calendar, Feb 29 handling, and why generators are built lazily rather than persisted. |
| [completed/transition-pair-alignment.md](completed/transition-pair-alignment.md) | explainer | 2026-07-15 | Plain-language account of why `previous`/`current` pairs must be matched by date rather than row position, and how an innocent `sort_values` silently corrupts 26,808 training pairs. |
