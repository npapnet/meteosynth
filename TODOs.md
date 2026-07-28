# TODOs

**Open work only.** When an item lands it is folded into [`CHANGELOG.md`](CHANGELOG.md)
and removed from here, so this file never grows a "done" section. Design rationale lives
in [`docs/design/`](docs/design/README.md).

Each item records **what was measured**, so nobody has to re-derive it, and carries a
**stable ID** — cross-references elsewhere in the repo point at `FIX-2`, not at "item 7",
so re-ordering this file breaks nothing. Groups are ordered by how much they block real
use; within a group, most significant first.

## ID allocation

> **Next ID: 10.**

IDs come from **one counter shared by every category**. The prefix says what an item
*is*; the number says *which* item it is. Only the number is the identity.

1. **Allocate from the single counter, then bump it.** The next item is `#10`, written
   `FIX-10`, `FEAT-10` or `CHORE-10` depending on what it turns out to be — never all
   three. No two items ever share a number, whatever their prefixes.
2. **Numbers are never reused.** Landing, dropping or superseding an item does not free
   its number. `FIX-2` and `FIX-3` are burned permanently.
3. **Reclassification changes the prefix, never the number.** A feature that turns out to
   be a defect becomes `FIX-14`, not a new ID. This is why the category is not part of the
   identity: a stale `FEAT-14` in a commit message or design doc still resolves
   unambiguously to item 14.
4. **Triage preserves the number.** An `INBOX-n` graduates by swapping its prefix —
   `INBOX-8` becomes `FEAT-8` — so the link across triage survives without an annotation.
   The ID only becomes citable at that point — see
   [the record-keeping rules](docs/design/architecture.md#the-rules-this-implies).
5. **IDs below 10 are legacy** and predate this scheme, so several categories reuse the
   same low numbers (`FIX-1`, `PERF-1`, `FEAT-1` are three different items). For those the
   full `PREFIX-N` string is the identity. They are **not** renumbered — 97 citations
   across the repo and the git history point at them. From `#10` up, the number alone is
   unambiguous.

**Retired numbers** — burned, and where they went: `FIX-2`, `FIX-3` → [`CHANGELOG.md`](CHANGELOG.md)
0.2.0 · `INBOX-1` … `INBOX-7` → triaged 2026-07-27, see the table at the end of this file.

| ID                                                                              | Item                                            | Status                |
| :------------------------------------------------------------------------------ | :---------------------------------------------- | :-------------------- |
| [FIX-1](#fix-1--generated-irradiance-is-systematically-too-high)                | Generated irradiance is systematically too high | open · **start here** |
| [PERF-1](#perf-1--sampling-re-evaluates-the-kde-on-every-call)                  | Sampling re-evaluates the KDE on every call     | open                  |
| [PERF-2](#perf-2--four-copies-of-the-same-data-in-every-simulator)              | Four copies of the same data in every simulator | open · low priority   |
| [PERF-3](#perf-3--fitted-generators-cannot-be-pickled-at-the-default-bandwidth) | Fitted generators cannot be pickled             | open · low priority   |
| [FEAT-1](#feat-1--cached-data-metadata-and-cache-match-check)                   | Cached data metadata and cache-match check      | open                  |
| [FEAT-2](#feat-2--irradiance-pick-one-column-by-availability)                   | Irradiance: pick one column by availability     | decision partly taken |
| [FEAT-3](#feat-3--chained-series-between-two-dates)                             | Chained series between two dates                | open · shape decided  |
| [FEAT-4](#feat-4--downloads-cache-by-default-keyed-by-sourcesiteperiod)         | Downloads cache by default                      | open · needs FEAT-1   |
| [FEAT-5](#feat-5--metdataprocessor-metadata-dict)                               | `MetDataProcessor` metadata dict                | open · needs FEAT-1   |
| [VISION-1](#vision-1--ingest-sources-other-than-pvgis)                          | Ingest sources other than PVGIS                 | future                |
| [CHORE-1](#chore-1--default-window-half-width-needs-a-real-evaluation)          | Default window half-width needs evaluating      | open                  |
| [CHORE-2](#chore-2--date_id-is-not-zero-padded)                                 | `date_id` is not zero-padded                    | open · breaking       |
| [CHORE-3](#chore-3--document-the-on-disk-format)                                | Document the on-disk format                     | open · needs FEAT-1   |
| [CHORE-4](#chore-4--bring-docssource-back-in-line-with-the-repo)                | Bring `docs/source/` back in line with the repo | open · do last        |

The [Inbox](#inbox--not-yet-triaged) is empty. `INBOX-1` … `INBOX-7` were triaged on
2026-07-27: two landed (see [`CHANGELOG.md`](CHANGELOG.md)), one merged into the former
`FIX-3`, the rest became `FEAT-3`, `FEAT-4`, `FEAT-5`, `CHORE-3` and `CHORE-4`.

## Order of work

Groups are ordered by how much they block real use; this is the order to *take them in*,
which is not the same thing.

1. **FIX-1 with CHORE-1 folded in** — one investigation, not two: the Paris-vs-Heraklion
   gap *is* the sample-size question CHORE-1 asks. Land the calibration test first, or
   no attempted fix is measurable.
2. **PERF-1** — after FIX-1, not before: a precomputed CDF grid has to encode whatever
   boundary correction FIX-1 lands, so doing it first means doing it twice.
3. **FEAT-2 (1)**, then **FEAT-1**, then **FEAT-4** and **FEAT-5**, which both need it.
4. **CHORE-3**, then **CHORE-4** last, so the docs pass is one edit rather than three.

**FEAT-3** is independent of all of it and can slot in anywhere.

*Landed 2026-07-28, both folded into [`CHANGELOG.md`](CHANGELOG.md): `FIX-3` (stale
`pvlib` unpacking) — which shrank `CHORE-4`, since the broken quickstart snippet went
with it — and `FIX-2` (exact-float degeneracy detection), which **unblocks VISION-1**.*

---

# Fixes — known defects

## FIX-1 — Generated irradiance is systematically too high

**Status:** open · **Impact:** absolute yield figures are not calibrated

Seasonal *shape* is faithful, so this affects magnitudes, not the climatology. Anyone
using this package for P50/P90 yield estimates needs it fixed first.

**The size of it depends on the record**, which is itself a clue:

| record                      | variable                      | measured               | against                        |
| :-------------------------- | :---------------------------- | :--------------------- | :----------------------------- |
| Paris 2011–2012 (2 yr)      | `poa_direct`, synthetic year  | 678 kWh/m² (**+14 %**) | 594 observed                   |
| Heraklion 2010–2020 (11 yr) | `poa_global`, 21 May ensemble | **+3.2 %**             | ±7-day observed pool           |
| Heraklion 2010–2020 (11 yr) | `poa_global`, synthetic year  | **+2.0 %**             | 1880 kWh/m² observed mean year |

`wind_speed` on the same 11-year record comes out at +1.1 % (mean speed) and +2.7 % on
`v³`. So the defect is real but not a fixed +14 %: a thin two-year training sample makes
it much worse.

### It is not simply the bandwidth

Originally attributed to `bandwidth=0.1`. That is wrong — the bias survives every
bandwidth, including Scott's rule. Measured on the May subset, 300-day ensemble, observed
3.27 kWh/m²:

| bandwidth     | generated | bias  |
| ------------- | --------- | ----- |
| 0.05          | 3.56      | +9 %  |
| 0.1 (default) | 3.62      | +11 % |
| 0.2           | 3.71      | +14 % |
| 0.3           | 3.75      | +15 % |
| 0.5           | 3.72      | +14 % |
| None (Scott)  | 3.71      | +14 % |

Smaller bandwidths help but do not remove it. Contrast `wind_speed`, where bandwidth *is*
the whole story — 0.05 gives +12 %, Scott's rule gives **0 %**.

### Two coupled causes

**(a) KDE boundary bias at the zero floor.** Every biased hour has `min == 0.0`: the data
piles against a hard physical bound. The evaluation domain spans exactly `[0, max]`, so
Gaussian mass that should fall below zero is renormalised back *into* the domain, pushing
the conditional mean up. This is the classic KDE boundary problem, and it explains why
`wind_speed` is unaffected — its distribution (min 0.07) does not sit against a bound. It
also explains the bandwidth trend: boundary bias scales with kernel width.

**(b) The error compounds along the 24-step walk.** One step from *true* observed values
is only +6 %; the full chain from midnight reaches +18 % by hour 12:

|                                 | hour 12 mean | bias  |
| ------------------------------- | ------------ | ----- |
| observed                        | 398.7        | —     |
| 1 step from true hour-11 values | 422.3        | +6 %  |
| 24-step chain from midnight     | 469.7        | +18 % |

Per-hour bias grows through the day (hour 6 +9 % → hour 12 +18 % → hour 18 +13 %), the
signature of accumulation rather than a constant offset.

### Already tried — do not repeat

**Removing the ±10 % domain padding, both sides.** Landed in 0.2.0. It was expected to
move the total in both directions at once (the lower pad let mass escape below zero, the
upper pad added headroom); the measured net was the **wrong** way, 670 → 678 kWh/m²
(+13 % → +14 %). It did fix generated negatives — 1.29 % → 0.00 % — which was its actual
purpose. The padding is gone from both the 1D and 2D paths, so there is nothing left to
measure separately here.

### Candidate fixes

- Boundary correction for the bounded-below case: reflection at zero, a log/sqrt transform
  before fitting, or beta/gamma kernels near the bound. This is the main line of attack
  now that padding is ruled out.
- Investigate whether `_calc_domain` taking `min`/`max` across *both* `previous` and
  `current` widens the domain for hours where the two ranges differ, leaking mass.
- Quantify the compounding separately: it may be inherent to the first-order chain rather
  than fixable in the kernel.
- Add a calibration test pinning generated-vs-observed bias per attribute, so any fix is
  measurable and cannot silently regress. The 11-year figures in the table above are the
  natural baseline.

---

# Performance & internals

## PERF-1 — Sampling re-evaluates the KDE on every call

**Status:** open · **Impact:** ~97 % of generation runtime

`get_next_state` re-evaluates a 1000-point grid through `gaussian_kde.evaluate` on every
single call — 53.5 ms per generated day, against 58 ms to *fit* all 24 hourly models.
Fitting is not the bottleneck; sampling is. On the 11-year record this is what makes a
full synthetic year take ~4 minutes for three attributes.

Precomputing the conditional CDF on a grid of `previous` values in `__init__` would make
sampling two interpolations. This is the module's own long-standing TODO
(`markov_chain_simulator_kde2d.py`). It trades memory for speed: a 200×1000 grid per
simulator is ~1.6 MB, or ~38 MB per generator.

---

## PERF-2 — Four copies of the same data in every simulator

**Status:** open · low priority

`MarkovChainSimulator2dKDE` holds `self.data`, `self.previous_values`,
`self.current_values` *and* `joint_kde.dataset` — ~15× overhead (992 bytes of payload held
as ~14.6 KB). Trimming touches that class's golden tests.

---

## PERF-3 — Fitted generators cannot be pickled at the default bandwidth

**Status:** open · low priority

```text
bandwidth=0.1  -> AttributeError: Can't get local object
                  'gaussian_kde.set_bandwidth.<locals>.<lambda>'
bandwidth=None -> pickles fine, 262 KB
```

`scipy` stores a local lambda in `covariance_factor`. This blocks any disk-caching or
multiprocessing of fitted generators. A custom `__reduce__` would fix it.

Not blocking anything today: generators are built lazily behind an LRU cache precisely
because persisting them buys ~58 ms and duplicates data already on disk — a decision
recorded in `CHANGELOG.md` 0.2.0 and argued in
[`rolling-day-window.md`](docs/design/completed/rolling-day-window.md). It would start to
matter if PERF-1 lands, since a precomputed CDF grid *is* worth persisting.

---

# Features — planned work

## FEAT-1 — Cached data metadata and cache-match check

**Status:** open · **Impact:** prevents redundant network fetches and cached-file
mismatches

Saved datasets carry no embedded metadata identifying their origin, so a warm cache can
silently answer a question it was not asked.

- **Metadata tracking** — record the source provider (`"PVGIS"`), coordinates
  (`latitude`, `longitude`), period (`start_year`, `end_year`), and (per FEAT-2) which
  irradiance form was fetched.
- **Automatic cache-match check** — on fetch, use an existing cached file only if it
  matches the requested site, period and source; otherwise fetch.
- **Force flag** — a `force_refetch` / `override` parameter so a fresh request can be
  demanded explicitly.

Note the examples currently encode site and period in the *filename*
(`pvgis_hourly_heraklion_2010_2020.csv`), which is a working stopgap and not a substitute:
it cannot express which irradiance form the file holds.

---

## FEAT-2 — Irradiance: pick one column by availability

**Status:** decision partly taken · **Needed before VISION-1**

> **Settled (2026-07-27): one irradiance column is modelled, and it is chosen by what the
> source supplies.** Components are *not* modelled separately and summed. What remains is
> **selection and provenance** — how the package chooses between `poa_global` and
> `poa_direct` when only one is available, and how it records which it used.

PVGIS returns **either** the global plane-of-array irradiance **or** its three components,
never both — one boolean, two mutually exclusive column sets:

```text
components=False -> poa_global
components=True  -> poa_direct, poa_sky_diffuse, poa_ground_diffuse
```

`adapters.fetch_pvgis` handles this by making the caller choose via
`irradiance="global"|"direct"|…`. The examples need both forms, so
`examples/tools/site_data.py:add_poa_global` fetches the components and reconstructs the
total by summation.

**That reconstruction is exact.** Measured on Heraklion 2010, fetched `poa_global` against
the summed components over 8760 hours: max absolute difference **0.01 W/m²** (PVGIS's own
two-decimal rounding), mean **0.0003 W/m²**, annual totals 1914.6 vs 1914.6 kWh/m². It is
sound for *observed* data, before any fitting.

### Why summing synthetic components is ruled out

Recorded so it is not re-litigated. Fitting the three components independently and summing
the *generated* series is not equivalent to fitting `poa_global`: each component gets its
own KDE and its own draw, so the physical anticorrelation between direct and diffuse — a
cloud moves one down and the other up — is destroyed. The sum is then under-dispersed at
the day scale, over-dispersed hour to hour, and can produce hours no sky could.

The accepted consequence: a user needing internally consistent components — to re-transpose
onto a different tilt, say — cannot get them from this package. That is a limitation of the
one-attribute-at-a-time engine, not a bug.

### Still to decide

1. **How is the column selected?** The rule wanted is *by availability*: use whichever
   irradiance column the source supplies rather than making every caller name one. Today
   `adapters.fetch_pvgis` requires an explicit `irradiance=`, and a user-supplied frame
   gets no help at all — `EnvSeriesGenerator` takes an `attr_str` and fails if that exact
   column is absent. What is missing is a resolver: given a frame, return the one
   irradiance column to model, following a documented preference order (`poa_global`
   first, as the quantity a plane actually receives), erroring only when none is present
   and naming what it looked for. It must **not** silently substitute a different quantity
   when one *was* named — preference order applies only when nothing was asked for.
2. **What does a cache hold?** One PVGIS fetch cannot carry both forms. Feeds FEAT-1.
3. **Is a derived column distinguishable from a fetched one?** Today it is not.
   `adapters.py` states the position — *"the column name is the provenance… no metadata
   sidecar"* — and a summed `poa_global` sits byte-for-byte alongside a fetched one.
   Options: a `source` field on the frame (`DataFrame.attrs`, lost on CSV round-trip), a
   sidecar keyed to the cache file (FEAT-1), a naming convention, or accepting that the
   summation is exact enough for PVGIS. It will matter for a provider where the identity
   does not hold exactly.
4. **What does a saved synthetic series carry?** Whatever answers (1) and (3) for observed
   data should ride along with generated data, or a result cannot be audited later.

---

## FEAT-3 — Chained series between two dates

**Status:** open · **Shape decided (2026-07-27)** · **Independent of everything else**

Explicit *start* dates already work: `gen_day(5, 21)`, `for_day(month, day)`,
`generate_series(start=(1, 1), n_days=365)`. What is missing is the **end**: `n_days` is
a count, and the model carries **no year at all** — it is climatological by construction
— so "1 Jan → 31 Mar" and "2030-01-01 → 2030-12-31" are different asks.

> **Settled: `end=(month, day)` alongside `n_days`.** The smallest change, and it stays
> calendar-only. Real dates in / timestamped frame out was rejected: it puts a year into
> a model that has none, and leap years would then have to mean something.

### Fix

Add `end: Optional[tuple] = None` to `generate_series`
(`generators.py:605`), mutually exclusive with `n_days`. Convert `end` to a day count
against the existing slot arithmetic — `day_slot(month, day)`, `DAYS_IN_YEAR`,
`FEB29_SLOT` — the walk at `generators.py:666-676` already uses.

Three things the implementation has to settle, all visible in that loop:

- **`end` is inclusive**, and wraps: `start=(12, 30), end=(1, 2)` is four days, not an
  error. The walk is already circular (`slot % DAYS_IN_YEAR + 1`).
- **`include_feb29=False` shortens the count**, since the walk skips slot 60. Deriving
  `n_days` must skip it the same way or the series overshoots by a day.
- **`end=(2, 29)` with `include_feb29=False`** should raise, mirroring the existing
  guard on `start=(2, 29)` at `generators.py:660-664`.

*(Was INBOX-4.)*

---

## FEAT-4 — Downloads cache by default, keyed by source/site/period

**Status:** open · **Needs:** FEAT-1 · **Impact:** the user-facing half of caching

FEAT-1 is the *record* — what a cached file says about itself, and the match predicate.
This is the **policy**: for any fetch, not only the examples,

- write to a cache subfolder **by default**, rather than only when handed an explicit
  path,
- **skip the download** when a matching file already exists,
- unless a `force_refetch` / `override` says otherwise.

Tracked separately from FEAT-1 because the two fail differently: a wrong record is a
correctness bug, a wrong default location is an ergonomics one, and they can land in
either order once FEAT-1 defines the match.

**Assessment.** Only the examples cache by default today (`examples/tools/site_data.py`,
keyed by filename via `Site.cache_path`). `adapters.fetch_pvgis` caches solely when
handed an explicit `cache=` path (`adapters.py:222-228`) and records nothing about what
the file holds — on a warm cache it re-validates support and returns, without ever
checking the file answers the question asked.

**Question, still open:** default location — `./data/<source>/` relative to the working
directory (matches the examples, visible, easy to git-ignore) or a user-level cache
directory (survives moving between projects, but invisible from any of them)? **Decide
this before FEAT-1 starts**, since it shapes the API surface both share.

*(Was INBOX-5, kept separate from FEAT-1 by decision on 2026-07-27.)*

---

## FEAT-5 — `MetDataProcessor` metadata dict

**Status:** open · **Needs:** FEAT-1 for the provenance half

Add a `.metadata` dict reporting what the processor can see: row count, years covered,
date range, columns kept and dropped, non-null count per attribute — plus provenance
(source, coordinates, period) when an adapter can supply it.

**Two cautions, carried over from the triage.**

1. **"Size of training set" has two meanings, in two homes.** The processor holds the
   *whole record*; the actual training subset is per calendar day and belongs on
   `DayWindowGenerator` / `EnvSeriesGenerator` — e.g. 341 pooled days for a ±15-day
   window on the 11-year record, against 96 432 rows in the record itself. Reporting
   both, each where it is true, is more useful than one number that has to be qualified.
2. **Provenance cannot be invented.** A hand-built DataFrame has none, and `adapters.py`
   deliberately supports that path (case B in its module docstring). The field must be
   optional and **absent, never an error**.

> **Settled: derived fields, plus an optional provenance passthrough the adapter fills.**
> Derived-only would mean the one thing a user most wants to audit — where did this come
> from — is the one thing the dict cannot say.

The derived half needs nothing from FEAT-1 and could land first; the passthrough needs
FEAT-1 to have defined what provenance *is*.

*(Was INBOX-7.)*

---

# Direction — where the package is going

## VISION-1 — Ingest sources other than PVGIS

**Status:** future · **Unblocked** (FIX-2 landed 2026-07-28) · **Shapes:** FEAT-1, FEAT-2

Support other providers (Open-Meteo, ERA5, local station data) via a thin **adapter
layer** that normalises each source into the canonical schema the core consumes
(`year, month, day, hour` plus the modelled columns), so the Markov code never learns a
provider's quirks.

The `VariableSpec` registry is the natural seam: an adapter maps provider columns to
registered spec names, converts units into each spec's declared `units`, and validates
against each spec's `support` — turning silent ingestion bugs (kW/m² read as W/m², °F as
°C) into an error at the boundary. `adapters.py` already has the shape of this; what is
missing is a second real provider to prove it.

**Both prerequisites are now cleared, so this is buildable.**

- **FIX-2 landed 2026-07-28.** Any resampled or unit-converted source produces
  near-zero-but-not-zero nights; degeneracy detection is now scale-aware rather than an
  exact `== 0`, so those hours are classified as constant instead of having a 2D KDE
  fitted across a catastrophically ill-conditioned covariance.
- **Horizontal irradiance is registered** (`ghi`, `dni`, `dhi` against
  `IRRADIANCE_HORIZONTAL`, 2026-07-28). Open-Meteo supplies GHI/DNI/DHI on the
  horizontal, and `SOURCE_RENAMES["open_meteo"]` already maps `shortwave_radiation` — but
  onto `poa_global`, which is **wrong** now that a truthful target exists. Fixing that
  mapping is the first task of this item, and FEAT-2's resolver is what decides the rest.

---

# Housekeeping

## CHORE-1 — Default window half-width needs a real evaluation

`n_days=15` gives 61 pairs per hourly KDE on a two-year record — thin for a 2D density,
and part of why FIX-1 is so much worse on the Paris record than on the 11-year one, where
the same setting pools 341 days. Whether 15, 20 or a sample-size-aware default is right
needs a real evaluation against the month baseline.

**Do this inside FIX-1, not separately.** The Paris-vs-Heraklion gap in FIX-1's table is
this question already half-measured; running the evaluation twice would be running the
same experiment twice.

## CHORE-2 — `date_id` is not zero-padded

`'2011-1-2'` does not sort lexicographically. `convert_to_daily_wide` sensibly builds its
own padded `date_str` instead. Worth aligning, but it is a breaking change for anything
grouping on `date_id`.


## CHORE-3 — Document the on-disk format

**Status:** open · **Needs:** FEAT-1 to settle provenance first

**Assessment, checked `adapters._write_cache`.** The shape is **already
source-agnostic**: one irradiance column plus `temp_air`, `wind_speed` and the four
`INDEX_COLS`, written by file extension — csv / xlsx / parquet, `adapters.py:277-285`.
No redesign is needed. Two gaps:

- The calendar is four integer columns, not a timestamp. `INDEX_COLS` is what the core
  validates on, so a timestamp would be an *addition* for the file's sake, not a
  replacement. **Decide whether to add one.**
- Nothing records which source, or which irradiance form the file holds (FEAT-2, FEAT-1).

**To do:** write the schema into the docs — columns, dtypes, units, calendar convention,
and what is deliberately absent, with the reasoning already in `adapters.py`'s module
docstring (*"the column name is the provenance… no metadata sidecar"*). That position is
what FEAT-1 revisits, which is why this waits on it.

*(Was INBOX-6.)*

## CHORE-4 — Bring `docs/source/` back in line with the repo

**Status:** open · **Do last**, after FEAT-1 and CHORE-3

**Assessment.** Less drift than feared, and less again now. `quickstart.md` and
`workflow.md` already describe π(x₀), `generate_series` and the registry; the 2026-07-27
examples reorganisation repointed every stale path; and the 2026-07-28 `FIX-3` work
rewrote the PVGIS sections of `quickstart.md` and `README.md` and put `adapters` and
`variables` into `api.rst`, neither of which had been in the API docs at all.

What is left:

- **No page documents the on-disk format** (CHORE-3) — add one once CHORE-3 decides
  what it says.
- **`examples.md` still carries the walk-through inline.** Now that every use-case
  folder has its own README, decide whether that page should summarise and link rather
  than duplicate — two places to update is how it drifted the first time.
- **`workflow.md` has not been re-read** since the registry gained `ghi`/`dni`/`dhi`.
  Check whether it still describes the shipped set correctly.

Do this pass *after* the items it depends on, so it is one edit rather than three.

*(Was INBOX-3. The quickstart defect went to FIX-3 and landed with it.)*

---

# Inbox — not yet triaged

Raw notes land here — refined but not yet costed or classified — and leave by
graduating into a group above with a real ID, or by being dropped. Nothing stays long.

## INBOX-8 : Move envelope functionality from the examples into the code 

examples/tools/ contains fucntionality that could be part of the main library as a diagnostics or convenience fucntion. 

## Archived items from TODOs.md

`INBOX-1` … `INBOX-7` were triaged on **2026-07-27**:

| Was                                               | Became                                        |
| :------------------------------------------------ | :-------------------------------------------- |
| INBOX-1 — one folder per use case                 | **landed**, see `CHANGELOG.md`                |
| INBOX-2 — retire duplicate concept scripts        | **landed**, see `CHANGELOG.md`                |
| INBOX-3 — realign `docs/source/`                  | `CHORE-4`, minus the broken snippet → `FIX-3` |
| INBOX-4 — chained series between two dates        | `FEAT-3`                                      |
| INBOX-5 — downloads cache by default              | `FEAT-4`                                      |
| INBOX-6 — confirm and document the on-disk format | `CHORE-3`                                     |
| INBOX-7 — `MetDataProcessor` metadata dict        | `FEAT-5`                                      |
