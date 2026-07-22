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

Active — proposed or in progress:

*(none — everything currently designed has landed.)*


## Completed

Implemented, tested, and moved to [`completed/`](completed/) so this top-level folder
only holds work still in flight. Each retains its own status line plus an archive note
recording when it landed; move a doc here once its feature is implemented and green in
the test suite, not before.

| document | type | implemented | what it is |
|---|---|---|---|
| [completed/variable-specs-and-initialisation.md](completed/variable-specs-and-initialisation.md) | design spec | 2026-07-22 | An extensible `VariableSpec` registry replacing the fixed column whitelist; sampling truncated to each quantity's physical support; `start_value` replaced by a fitted initial distribution π(x₀) plus a real cross-midnight transition; `generate_series` on the rolling-window path; an optional source-adapter layer. Fixes negative irradiance, out-of-domain crashes and the hour-0 quirk. Carries an archive note recording two claims that did not survive measurement. |
| [completed/rolling-day-window.md](completed/rolling-day-window.md) | design spec | 2026-07-15 | A rolling ±n-day training window as an alternative to the month split, incl. the `all_leap` calendar, Feb 29 handling, and why generators are built lazily rather than persisted. |
| [completed/transition-pair-alignment.md](completed/transition-pair-alignment.md) | explainer | 2026-07-15 | Plain-language account of why `previous`/`current` pairs must be matched by date rather than row position, and how an innocent `sort_values` silently corrupts 26,808 training pairs. |
