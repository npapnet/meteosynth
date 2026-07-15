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

| document | status | what it is |
|---|---|---|
| [rolling-day-window.md](rolling-day-window.md) | implemented | A rolling ±n-day training window as an alternative to the month split, incl. the `all_leap` calendar, Feb 29 handling, and why generators are built lazily rather than persisted. |
| [transition-pair-alignment.md](transition-pair-alignment.md) | explainer | Plain-language account of why `previous`/`current` pairs must be matched by date rather than row position, and how an innocent `sort_values` silently corrupts 26,808 training pairs. |
