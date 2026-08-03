# TODOs

**Open work only.** When an item lands it is folded into [`CHANGELOG.md`](CHANGELOG.md)
and removed from here, so this file never grows a "done" section. Design rationale lives
in [`docs/design/`](docs/design/README.md).

Each item records **what was measured**, so nobody has to re-derive it, and carries a
**stable ID** — cross-references elsewhere point at `FIX-2`, not at "item 7". Groups are
ordered by how much they block real use; within a group, most significant first.

> **Measurements keep; recipes do not.** An item states the problem, the evidence and the
> decision taken. It does **not** carry line numbers or a step-by-step implementation — by
> the time the work starts the code has moved, and a stale recipe is worse than none.
> Last reassessed against the codebase **2026-08-03**.

## ID allocation

> **Next ID: 23.**

IDs come from **one counter shared by every category**. The prefix says what an item
*is*; the number says *which* item it is. Only the number is the identity.

1. **Allocate from the single counter, then bump it** — `FIX-10`, `FEAT-10` or
   `CHORE-10`, never all three. No two items share a number.
2. **Numbers are never reused.** Landing, dropping or superseding an item does not free
   its number.
3. **Reclassification changes the prefix, never the number.** A feature that turns out to
   be a defect becomes `FIX-14`, so a stale `FEAT-14` in a commit message still resolves
   unambiguously.
4. **Triage preserves the number.** `INBOX-8` graduates to `FEAT-8`; the link across
   triage survives without an annotation. The ID only becomes citable at that point — see
   [the record-keeping rules](docs/design/architecture.md#the-rules-this-implies).
5. **IDs below 10 are legacy** and predate this scheme, so several categories reuse the
   same low numbers (`FIX-1`, `PERF-1`, `FEAT-1` are three different items). For those the
   full `PREFIX-N` string is the identity; they are **not** renumbered. From `#10` up, the
   number alone is unambiguous.

**Retired numbers:** `FIX-2`, `FIX-3`, `FIX-18`, `FEAT-4`, `FEAT-5`, `FEAT-13`, `FEAT-15`, `FEAT-21` → [`CHANGELOG.md`](CHANGELOG.md) ·
`FEAT-1` → superseded 2026-07-29 by `FEAT-13` ·
`INBOX-1` … `INBOX-7` → [triaged 2026-07-27](CHANGELOG.md#changed) ·
`INBOX-10`, `INBOX-13`, `INBOX-14` → triaged 2026-08-01, see the note below.

> **`INBOX-13` could not keep its number.** `13` was already spent by `FEAT-13`, which
> landed in 0.3.0 and is cited by `CHANGELOG.md`, a design-doc filename and several
> `TODOs.md` entries. Rule 2 outranks rule 4: a number is never reused, so the item was
> re-allocated from the counter instead of graduating in place. It also split in two, so
> it would have needed a fresh ID regardless — it is now `FIX-18` and `CHORE-19`.
> `INBOX-10` and `INBOX-14` were clean and kept their numbers.

| ID | Item | Status |
| :--- | :--- | :--- |
| [FEAT-17](#feat-17--choose-the-sampling-path-explicitly-not-by-a-hidden-counter) | Choose the sampling path explicitly | open · **carries a shipped defect** · gated on CHORE-12 |
| [CHORE-12](#chore-12--nothing-pins-what-the-sampler-produces-against-its-training-pool) | Nothing pins the sampler against its pool | open · **gates FEAT-17 and PERF-16** |
| [FIX-1](#fix-1--the-overcast-tail-is-under-produced) | The overcast tail is under-produced | open · **deferred, with evidence** |
| [CHORE-19](#chore-19--monthly_statisticspy-still-predates-feat-15) | `monthly_statistics.py` predates FEAT-15 | open · small and concrete |
| [FEAT-10](#feat-10--promote-the-envelope-diagnostics-out-of-examples) | Promote the envelope diagnostics | open · first move is a deletion |
| [FEAT-3](#feat-3--chained-series-between-two-dates) | Chained series between two dates | open · shape decided · independent |
| [FEAT-2](#feat-2--is-a-derived-irradiance-column-distinguishable-from-a-fetched-one) | Is a derived column distinguishable? | (3) open · needed before VISION-1 |
| [CHORE-22](#chore-22--the-benchmarks-noise-floor-measures-the-wrong-scatter) | Benchmark noise floor measures the wrong scatter | open · low priority |
| [CHORE-1](#chore-1--default-window-half-width-needs-a-real-evaluation) | Default window half-width | open · half measured |
| [PERF-16](#perf-16--the-grid-build-not-the-draws) | The grid **build**, not the draws | open · **after CHORE-12** |
| [PERF-11](#perf-11--grid-node-spacing-may-want-to-depend-on-the-variable) | Grid node spacing per variable | open · low priority |
| [PERF-2](#perf-2--four-copies-of-the-same-data-in-every-simulator) | Four copies of the same data | open · low priority |
| [PERF-3](#perf-3--fitted-generators-cannot-be-pickled-at-the-default-bandwidth) | Fitted generators cannot be pickled | open · low priority |
| [FEAT-14](#feat-14--a-cli-subcommand-set) | A CLI subcommand set, and its name | open · low priority · unblocked |
| [CHORE-2](#chore-2--date_id-is-not-zero-padded) | `date_id` is not zero-padded | open · breaking · documented |
| [CHORE-3](#chore-3--should-the-on-disk-format-carry-a-timestamp) | Timestamp in the on-disk format? | open · one question |
| [CHORE-4](#chore-4--bring-docssource-back-in-line-with-the-repo) | Bring `docs/source/` back in line | open · **do last** |
| [VISION-1](#vision-1--ingest-sources-other-than-pvgis) | Ingest sources other than PVGIS | future |

## Order of work

Groups below are ordered by how much they block real use. This list is the order to
*take them in*, which is not the same thing.

1. **CHORE-12, then FEAT-17.** `CHORE-12` gates two items and is the suite's one
   demonstrated blind spot; `FEAT-17` is the only open item carrying a defect that ships
   today. Doing `FEAT-17` first is how a silent modelling change gets released.
2. **CHORE-19 and FEAT-10's first move together.** Both delete a pre-`FEAT-15` calling
   pattern from `examples/`, both change drawn values, and both need the same
   before/after comparison. One pass, one re-run of the diagnostics anchor cell.
3. **FEAT-3** whenever convenient — independent of everything else and small.
4. **FIX-1 and CHORE-1** are both modelling questions about the same kernel. Take them
   together if either is taken; `FIX-1` is deliberately deferred and `CHORE-1` is half
   measured.
5. **PERF-16, PERF-11, PERF-2, PERF-3** are all low priority. `PERF-16` waits on
   `CHORE-12`; `PERF-11` and `PERF-16`'s first direction are the same question about node
   count and placement, so answer them together.
6. **FEAT-14 and CHORE-4 last.** Both are documentation-shaped and both are cheaper once
   the items above stop moving the surface they describe.

**FEAT-17, PERF-16 and FEAT-10 all touch the sampler or its callers.** Whichever runs
first shortens the others: `FEAT-10`'s deletion removes one of `FEAT-17`'s two callers.

---

# Fixes — known defects

## FIX-1 — The overcast tail is under-produced

**Status:** open · **deferred 2026-07-28** · **Impact:** low-tail questions only —
storage autonomy, worst-case days. **Nothing the package advertises is affected.**

Evidence: [`FINDINGS-2026-07-28.md`](examples/diagnostics-overshoot/FINDINGS-2026-07-28.md);
design and provenance in [`PLAN.md`](examples/diagnostics-overshoot/PLAN.md).

**The model produces too few overcast days**, at every date where the record contains any.
Measured against the pooled window the generator is fitted to, 19 years, n = 1000 per cell:

| date · threshold | observed | synthetic (bw 0.1) |
| :--- | ---: | ---: |
| 21 Mar · < 1 kWh/m² | 1.40 % | **0.20 %** |
| 21 Mar · < 0.25× median | 3.16 % | **1.10 %** |
| 21 Dec · < 1 kWh/m² | 15.09 % | **12.70 %** |
| 21 Dec · < 0.25× median | 1.75 % | **0.60 %** |
| 21 Mar ±15 d · < 1 kWh/m² | 2.38 % | **0.40 %** |

Every interval excludes, at both bandwidths tested. 21 June and 21 September hold **no**
observed days below either threshold, so they cannot test it. Daily totals are also mildly
under-dispersed (sd ratio 0.891–1.001 at bandwidth 0.1).

**Mechanism:** a symmetric kernel across a bounded, right-skewed conditional density
cannot put enough mass near the floor without putting some below it.

### Why it is deferred

The fix changes `MarkovChainSimulator2dKDE`'s density, so every golden test needs
re-baselining and all three attributes re-validating. Against that:

| question | effect of the defect |
| :--- | :--- |
| Mean daily total, monthly or annual energy | **none** — ratio 0.994–1.007, no date excluding 1 |
| Daily P50, P90, daily maximum | **≤ 1–4 %**; mean of daily maxima within 2 % |
| **Annual P90** (what a yield study quotes) | **0.12 % of the mean** — 2.3 kWh/m² on a mean year of 1879 |
| Daily P10 | biased **high by up to 9 %** |
| Frequency of overcast days | **~4× too few** where the record has any |

Days below 1 kWh/m² are 3.47 % of the record but carry **0.50 % of its energy**, and
Heraklion's year-to-year CV is only 1.71 %. **A yield study cannot see this defect.**

**Revisit when** a low-tail use case appears, a second site shows a larger effect, or the
KDE core is being touched anyway — the marginal cost is much lower then. What must be
documented meanwhile: storage sizing and worst-case-day analysis read the low tail
directly, any daily low percentile runs up to 9 % high, and a more overcast site than
Heraklion is untested.

### Candidate fixes, and one dead end

Boundary correction for the bounded-below case — reflection at zero, a log/sqrt transform
before fitting, or beta/gamma kernels near the bound. Also worth checking whether
`_calc_domain` taking min/max across *both* `previous` and `current` widens the domain
where the two ranges differ.

**A wider kernel is not the answer** (see `PERF-3` for the numbers). **Do not re-derive:**
a biased mean — the old Paris +13/+14 % figures came from the retired pre-0.2.0 estimator;
compounding along the 24-step walk (per-hour bias is flat); any dependence on record
length (k ∈ {19, 9, 3, 2} years, flat). **Already tried:** removing the ±10 % domain
padding, landed in 0.2.0 — it fixed generated negatives (1.29 % → 0.00 %), which was its
purpose, and did not touch the tail.

`examples/diagnostics-overshoot/` is the calibration harness — nine configurations,
~2 minutes, with a null control, a positive control and an anchor cell. **Any attempted
fix must move the tail shares without moving the mean ratios off 1.**

---

# Features — planned work

## FEAT-17 — Choose the sampling path explicitly, not by a hidden counter

**Status:** open · **carries a shipped defect** · **gated on `CHORE-12`** — this changes
the default sampler for every caller

`MarkovChainSimulator2dKDE` answers a draw two ways: evaluate the conditional density live
(**the exact path**), or read a precomputed quantile table (**the table path**). Which one
runs is decided by a hidden mutable counter on the simulator — the 65th draw switches
paths. Decide it from **arguments** instead, and demote the counter to advisory.

> **"Exact path" means *no table*, not *no approximation*.** It still discretises the
> value axis and integrates by cumulative sum. The table adds interpolation across nodes
> of `previous` and a discretised quantile axis on top of those.

### The shipped defect

`generate_ensemble(..., precompute=False)` reads as "do not use the table". **It does not
do that.** It skips only the *eager* build; the counter still fires on the 65th draw, so
936 of 1000 realisations come from the table anyway. Measured at N = 1000, `poa_global`,
±7-day window, 365 days, one attribute:

| what you ask for | what you get | cost |
| :--- | :--- | ---: |
| `precompute=True` | table built up front | **20.2 min** |
| `precompute=False` | *64 exact draws, then the table anyway* | **36.8 min** |
| the exact path, genuinely | no table ever built | **4.5 h** |

An opt-out that lands within 1.8× of the opt-in and 7× from what its name implies. Today
the only way to get the exact path is to monkeypatch a private constant.

### What the choice costs, and what it is not

**The exact path costs ~13× for a large ensemble** — 4.5 h against 20 min. Large enough
that it must be opted into rather than defaulted to silently; small enough to afford for
one authoritative run. At the other end the ordering reverses: a chained year takes one
draw per simulator, so building tables would be a ~9× *pessimisation*. Neither path is
right for both, which is why the caller has to be able to say.

**Accuracy is not at stake.** The table's extra error is 0.03 % on the mean and
0.04–0.31 % on the standard deviation over 20 000 draws; a 2000-day end-to-end mean moves
−0.185 % with a KS test at p = 1.0. The diagnostics harness cannot resolve below 1.4–4.8 %.
What the exact path buys is **determinism and auditability**, a different axis from
accuracy: *exact vs fast*, not *precise vs performant*.

### The decision to implement

- **Default to the exact path.** Fail toward predictability. The failure mode becomes
  "slower than it needed to be" — visible and fixable by one argument — instead of
  "silently different numbers depending on call history", which caused two real defects
  during `FEAT-15`.
- **Opt in with a draw count, not a boolean** — something the caller knows, rather than
  asking them to have done the cost arithmetic. A count also survives a change to the node
  count for accuracy reasons (`PERF-11`), because the crossover is recomputed.
- **Retire `precompute=`**, or keep it as a thin alias. It is the misnamed parameter above.
- **Keep the counter as advice.** Keep counting, never switch paths, and log once when the
  threshold passes unhinted so the optimisation stays discoverable.

**Callers to update:** two, both in `examples/`, both loops whose bound the callee cannot
see — `tools/envelope.py` and `diagnostics-overshoot/step2_simulate.py`. The second is the
calibration harness at n = 1000 and currently gets the table free from the counter; without
a hint its runtime regresses ~8× and would look like a harness fault. **`FEAT-10` deletes
the first of those callers**, so doing it first shortens this. No library-internal caller
is affected.

---

## FEAT-10 — Promote the envelope diagnostics out of `examples/`

**Status:** open · **rescoped by measurement, and it shrank** · *graduated from `INBOX-10`,
2026-08-01* · **overlaps `FEAT-17`**

`examples/tools/envelope.py` holds machinery that reads like library code and has **two
independent consumers** — the three `use_cases/day/day_envelope_*.py` scripts and
`diagnostics-overshoot/step2_simulate.py`, which imports across folder boundaries.

### The first move is a deletion, not a promotion

The obvious candidate for promotion was `envelope.synthetic_ensemble` — draw *n*
independent synthetic days for one calendar date. **`FEAT-15` already shipped that** as
`generate_ensemble(start=(month, day), n_days=1, n_realisations=n)`, and nobody noticed.

The two differ in **which sampler and which streams**, not in meaning: the library version
keys a stream per realisation instead of sharing one `rng`, and settles the table path by
realisation count instead of letting the counter flip mid-ensemble. Both differences are
improvements, and the second is exactly the defect `FEAT-17` describes.

So **delete `synthetic_ensemble`** and repoint the three day scripts and the diagnostic at
`generate_ensemble`. Different streams mean different numbers, so compare drawn values
before and after and re-run the diagnostics anchor cell — a silent shift there is precisely
what `CHORE-12` warns about.

### What is left, and it is the harder question

| function | kind | promote? |
| :--- | :--- | :--- |
| `day_matrix`, `ensemble_frame` | reshaping — overlaps `convert_to_daily_wide` and `Ensemble.to_wide` | probably; check for genuine duplication first |
| `_percentiles`, `_daily_aggregate` | four lines of numpy each | not worth a public name |
| `report_day_stats` | prints a formatted comparison | only as a value-returning function; a library should not `print` |
| `apply_chart_style`, `plot_day_envelope` | opinionated matplotlib figures | **the real question** |

**Settle this before writing anything: does this package ship figures?** `sup_plot_lib.py`
says yes, but it is the module nothing else imports, and `plot_day_envelope` is far more
opinionated. Shipping it means committing to it as API. **Reshaping helpers and a figure
library are two different items** — decide which this is before starting.

---

## FEAT-3 — Chained series between two dates

**Status:** open · shape decided · **independent of everything else**

Explicit *start* dates already work. What is missing is the **end**: `n_days` is a count,
and the model carries no year at all — it is climatological by construction — so
"1 Jan → 31 Mar" and "2030-01-01 → 2030-12-31" are different asks.

> **Settled: `end=(month, day)` on `generate_series`, mutually exclusive with `n_days`.**
> The smallest change, and it stays calendar-only. Real dates in / timestamped frame out
> was rejected: it puts a year into a model that has none, and leap years would then have
> to mean something.

Three semantics the implementation has to get right, all already visible in the walk:

- **`end` is inclusive and wraps.** `start=(12, 30), end=(1, 2)` is four days, not an
  error — the walk is already circular.
- **`include_feb29=False` shortens the count**, since the walk skips that slot. Deriving
  `n_days` must skip it the same way or the series overshoots by a day.
- **`end=(2, 29)` with `include_feb29=False` should raise**, mirroring the existing guard
  on the same `start`.

---

## FEAT-2 — Is a derived irradiance column distinguishable from a fetched one?

**Status:** (1), (2) and (4) landed with `FEAT-13` / `FEAT-15` · **(3) open** · **needed
before `VISION-1`**

> **Settled: one irradiance column is modelled, chosen by what the source supplies.**
> `MetDataset.irradiance_column` resolves it against the ordered
> `IRRADIANCE_COLUMNS = ("poa_global", "ghi")`, and provenance records what a record holds.
> `write_ensemble` carries that provenance into generated output.

**Summing synthetic components is ruled out** and should not be revisited: fitting the
three components independently and summing the *generated* series destroys the physical
anticorrelation between direct and diffuse, giving a sum that is under-dispersed daily,
over-dispersed hourly, and able to produce hours no sky could. The accepted consequence is
that a user needing internally consistent components — to re-transpose onto another tilt —
cannot get them here. That is a limitation of the one-attribute-at-a-time engine, not a bug.

### What remains

**A derived total is *stated* but not *typed*.** `fetch_pvgis` collects the three
components and derives `poa_global` by summation on every ordinary call, writing a note
into `Provenance.notes`. Nothing enforces or checks that note, and a summed `poa_global`
sits byte-for-byte alongside a fetched one.

Options: a dedicated provenance field, a naming convention, or accepting the summation as
exact enough. **Nothing is wrong today** — measured on Heraklion 2010, fetched
`poa_global` against the summed components over 8760 hours: max difference **0.01 W/m²**
(PVGIS's own two-decimal rounding), mean 0.0003 W/m², annual totals identical to 0.1 kWh/m².
It will matter for a provider where the identity does not hold exactly, which is `VISION-1`.

---

## FEAT-14 — A CLI subcommand set

**Status:** open · **low priority** · **unblocked** — `FEAT-4` landed 2026-08-01,
`FEAT-21` 2026-08-03 · *graduated from `INBOX-14`, 2026-08-01*

A console-script entry point over the two things a user currently writes a script for:

```console
meteosynth fetch     ...   # -> a saved MetDataset
meteosynth generate  ...   # a MetDataset -> a series or an ensemble on disk
```

### The first decision: what the command is called

**The spelling is not settled** — `meteosynth` here and in the design docs, `meteogen` in
the request that prompted `FEAT-21`. Settle it before writing the `[project.scripts]` line,
because an entry-point name is the one part of a CLI that cannot change later without
breaking every invocation already written into a Makefile, a CI job or a paper's methods
section. Nothing else turns on it, which is why it was left open rather than argued in the
abstract.

### Why *low* priority and not *no* priority

The audience writes Python — a synthetic year is an input to a yield model, not an end
product — so nobody is blocked. What a CLI buys is a **reproducible one-line invocation**.
Worth having after the pieces underneath stop moving.

### What is already built for it

`FEAT-21` answered every subcommand's first question — *where does the file go?* —
so the CLI exposes a policy rather than inventing one: `workspace()` with no argument
**is** the command case. `store` supplies the rest: `record_filename` for naming,
`describe_store()` for `--list`, `resolve` and `fetch_pvgis(site=...)` for `--site`, and
`AmbiguousRecordError` with candidates in the message for a folder that answers two ways.
`--site`/`--years` map onto `fetch_pvgis`'s own arguments, so the wrapper is thin.

### The scope decision to take when it starts

`fetch` and `generate` are the whole of the value. **Drop `train`** unless something
changes: the package has no persisted fitted model to train *into*, generators are fitted
lazily behind an LRU cache, and persisting them was measured and rejected twice (`PERF-3`
and [`rolling-day-window.md`](docs/design/completed/rolling-day-window.md)). A
fitted-model artefact would be a design question of its own, not a subcommand.

Exit codes matter more than output formatting, since the point is scripted use.

---

# Performance & internals

## PERF-16 — The grid **build**, not the draws

**Status:** open · **gated on `CHORE-12`** · **rescoped by measurement** · originally
"batch the draws", deferred with
[`FEAT-15`](docs/design/completed/FEAT-15-ensemble-generation.md#decided-draw-one-value-at-a-time)

`FEAT-15` passes all N realisations through one fitted simulator at each hour, so draws
*could* be vectorised instead of looped in Python. **Measuring moved the bottleneck, and
the batching is now the smaller half of this item.**

Per calendar day at N = 1000: building the quantile grids costs **~3.3 s**, fitting the
models 199 ms, drawing one realisation's day 0.68 ms. The build is **~79 % of the per-day
cost at N = 1000 and nearly all of it at N = 100**, and it is paid per day per attribute
*regardless of N* — a 365-day three-attribute ensemble spends ~60 min there whether it
holds 100 realisations or 10 000.

**So batching the draws is capped at ~1.2×** (revised down from ~3× once the build was
measured), against 77× that `FEAT-15` already delivered. Attack the build instead: it is
~5× the prize and adds no new sampling path, so it avoids `CHORE-12`'s blind spot.

Three directions, none investigated:

- **Fewer nodes or coarser evaluation.** `PERF-1` measured 32 nodes at 0.04 % / 0.42 %
  error against 64 at 0.03 % / 0.04 % — half the build cost for an error still far below
  what the diagnostics can resolve. **`PERF-11` asks the sibling question about node
  *placement*; answer the two together.**
- **Reuse across adjacent days.** Consecutive training windows overlap ~93 % at ±7 days,
  so consecutive grids are nearly the same object. Exploiting that weakens the "each day
  has its own fit" property the rolling window exists for, so it needs an argument, not
  just an implementation.
- **Vectorise the build**, which is 11 independent KDE evaluations per day.

### If the draw batching is taken anyway

Degeneracy is almost entirely an irradiance property — measured over four dates at ±7 days
on Heraklion 2010–2020, 23 transitions per date:

| attribute | degenerate transitions | by date |
| :--- | ---: | :--- |
| `poa_global` | **49/92 (53 %)** | 43 % Jun · 52 % Mar · 52 % Sep · **65 % Dec** |
| `temp_air` | **0/92** | never — no floor, no atom |
| `wind_speed` | **0/92** | never |

**So converting the `KDE_2D` path alone is the complete job for `temp_air` and
`wind_speed`.** Batching the degenerate paths too buys speed on irradiance only, mostly in
winter. A first attempt converting `KDE_2D` only got 1.4× on irradiance; the earlier
reading that this "takes the risk for a third of the payoff" was measured on `poa_global`
and does not generalise.

Two constraints on any implementation: it must not materialise a per-hour array across all
realisations (the first attempt allocated ~8 MB per hour at N = 1000), and it must keep
`PERF-1`'s invariant that a sampling path consumes exactly one number from the generator
per draw, or an ensemble's streams desynchronise from a single series'.

---

## PERF-11 — Grid node spacing may want to depend on the variable

**Status:** open · low priority · **Impact:** accuracy of the cached sampler, not speed

`PERF-1`'s conditional-quantile grid places its nodes **uniformly** across the range of
`previous`. That was chosen by measurement, but only on **`poa_global`**, and there is
reason to think it does not generalise.

Quantile spacing lost badly on irradiance — at 16 nodes, **−11.9 %** on the sampled
standard deviation against **−1.2 %** for uniform. The cause is specific: irradiance's
`previous` has a **huge atom at zero**, since night is most of the hours at some
transitions, so quantile nodes pile up resolving 0 against 0 and starve the daytime range
where the conditional actually moves. **`temp_air` has no such atom** — unimodal, roughly
symmetric, no floor — which is the case quantile spacing is designed for, and it may well
win. `wind_speed` sits between: bounded below, but with no atom at the bound.

**Do not judge it by the sup-norm of the quantile function.** Already measured to be
misleading: on irradiance it reads 15–25 % of the domain even where the sampler is
distributionally exact, because it is dominated by conditioning values at the sparse edges
that the chain essentially never visits. Use the **distributional error under the marginal
of `previous`** — relative error in the mean and standard deviation of samples drawn
through both paths, plus the low-tail share, which is the statistic `FIX-1` turns on and
the one most sensitive to placement near a bound. Uniform at 64 nodes gives −0.03 % and
−0.04 % on irradiance; that is what a competing rule has to beat, per attribute and at
several hours.

**Adopt a per-variable rule only if it wins on all three attributes at the same node
count.** Two spacing rules selected by attribute is a maintenance cost a marginal gain
does not justify; a single better rule would. Both spacings cost exactly the same to build
and sample, so this is pure accuracy with no trade-off — and the current error on the one
attribute measured is already two orders of magnitude below what the diagnostics resolve,
so there is no evidence anything is actually wrong.

Measurements behind the current choice:
[`PERF-1-precomputed-conditional-quantiles.md`](docs/design/completed/PERF-1-precomputed-conditional-quantiles.md).

---

## PERF-2 — Four copies of the same data in every simulator

**Status:** open · low priority

`MarkovChainSimulator2dKDE` holds `self.data`, `self.previous_values`,
`self.current_values` *and* `joint_kde.dataset` — ~15× overhead (992 bytes of payload held
as ~14.6 KB). Trimming touches that class's golden tests.

---

## PERF-3 — Fitted generators cannot be pickled at the default bandwidth

**Status:** open · low priority

`scipy` stores a local lambda in `covariance_factor`, so `bandwidth=0.1` raises
`AttributeError: Can't get local object 'gaussian_kde.set_bandwidth.<locals>.<lambda>'`
while `bandwidth=None` pickles fine at 262 KB. This blocks disk-caching or multiprocessing
of fitted generators. A custom `__reduce__` is the fix.

Not blocking anything today: generators are built lazily behind an LRU cache precisely
because persisting them buys ~58 ms and duplicates data already on disk — argued in
[`rolling-day-window.md`](docs/design/completed/rolling-day-window.md). `PERF-1`'s quantile
grid does not change that; persisting it is a worse trade than the one already rejected.

**Switching the default to `bandwidth=None` is not a way around it.** Measured 2026-07-28:
Scott's rule chooses **0.390** at ±7 days on a 19-year record against the hand-set
**0.100** — a 3.9× wider kernel — and is worse on every statistic tested. Mean daily total
drops to 0.944–0.987 of observed at **all four** dates, P50 to 0.890–0.979, P90 to
0.902–0.996, all excluding 1. The signature is over-smoothing: P10 rises while P50 and P90
fall.

---

# Direction — where the package is going

## VISION-1 — Ingest sources other than PVGIS

**Status:** future · unblocked · **shaped by** `FEAT-13`, `FEAT-2`

Support other providers (Open-Meteo, ERA5, local station data) through a thin adapter
layer that normalises each source into the canonical schema, so the Markov core never
learns a provider's quirks.

The `VariableSpec` registry is the natural seam: an adapter maps provider columns to
registered spec names, converts into each spec's declared units, and validates against its
`support` — turning silent ingestion bugs (kW/m² read as W/m², °F as °C) into an error at
the boundary. `adapters.py` already has the shape; what is missing is a second real
provider to prove it.

**First task:** `SOURCE_RENAMES["open_meteo"]` maps `shortwave_radiation` onto
`poa_global`, which is **wrong** now that `ghi`/`dni`/`dhi` are registered against
`IRRADIANCE_HORIZONTAL`. Fix that mapping; `FEAT-2`'s resolver decides the rest.

---

# Housekeeping

## CHORE-12 — Nothing pins what the sampler produces against its training pool

**Status:** open · **raised for review, not yet agreed** · **gates `FEAT-17` and
`PERF-16`**, both of which would change or add a sampling path

### The observation, and what has since narrowed it

`PERF-1` added an entirely new sampling path and **all 271 existing tests passed without
modification** — the suite could not tell the two samplers apart, and could not have told
had the new one been wrong. It tests **properties**: that a seed reproduces, that a shared
generator advances, that samples stay inside support, that degenerate hours are classified
correctly. All survive a sampler returning materially different numbers.

**`tests/test_conditional_quantile_grid.py` has since closed half of this** — it compares
the grid path against the direct path distributionally and checks the random stream is not
perturbed. What remains uncovered is the other half: **whether either path is right against
the pool it was fitted to.** That is the gap `FEAT-17` and `PERF-16` would widen.

### Arguments against acting

The density computation *is* pinned, to a known fixture. Support truncation is pinned
end-to-end over a generated year — the defect that actually shipped once (1.29 % negative
irradiance) and the one most likely to recur. And a statistical property is genuinely
awkward to pin: an exact-value golden test on a sampler is brittle against a `numpy` or
`scipy` release that changes generator internals.

### Arguments for

The gap is **demonstrated, not hypothetical**. Every modelling defect this repo has found
— `FIX-2`, `FIX-3`, the two harness defects in the overshoot diagnostic — was found by
running things, never by the suite. And the natural check already exists but lives outside
it: `examples/diagnostics-overshoot/` needs a network fetch and ~5 minutes, so it cannot be
a unit test — but a miniature of it can.

### What would close it

A **calibration test**, not a golden-value test. Fit on the existing two-year synthetic
fixture, draw a few hundred days, assert against the training pool:

| assertion | suggested tolerance | what it catches |
| :--- | :--- | :--- |
| mean of daily total vs pool | within 5 % | a level shift — the `FIX-1` class |
| sd of daily total vs pool | within 15 % | a dispersion collapse, e.g. a mis-built grid |
| every value inside support | exact | already covered; keep it here too |
| no NaN or inf anywhere | exact | the failure mode `FIX-2` produced |

**Do it per attribute, not just irradiance.** `temp_air` and `wind_speed` have no floor
and no degenerate hours, and a defect confined to one of them is exactly what a
single-attribute test would miss. Cost: one test file, a few tens of seconds. **The
tolerances are the whole design problem** — too tight is a maintenance tax, too loose
asserts nothing. The numbers above are a starting point, not a measurement.

## CHORE-19 — `monthly_statistics.py` still predates `FEAT-15`

**Status:** open · low priority · *split from `INBOX-13` on triage, 2026-08-01*

The library side is fine: `generate_series`, `generate_ensemble` and `write_ensemble` all
take `progress=`, and the bar persists for an ensemble but not for a series — the right way
round, since an ensemble is one walk and a series is one of hundreds.

`examples/use_cases/month/monthly_statistics.py` is **the only script with a real wait and
no feedback**, and the reason is the same as the fix: it calls `generate_series` in a loop,
refitting all 31 days of May once per realisation — **the exact pattern `FEAT-15` exists to
replace**. `year/synthetic_year.py` was converted when `FEAT-15` landed; this one was
missed.

**So the fix is not to add a bar but to call `generate_ensemble(..., progress=True)`**,
which walks the calendar once and brings the bar with it. `FEAT-15` measured ~77× at
N = 1000 on a full year; this script's realisation count is 12, so expect much less —
**measure it rather than quoting that figure.** Values will change, since per-realisation
streams replace the shared `rng`: the script reports level, spread and P50/P90 against
observed years, so compare those rather than raw arrays. **Take this with `FEAT-10`**,
which deletes the same pattern from `examples/tools/envelope.py`.

## CHORE-22 — The benchmark's noise floor measures the wrong scatter

**Status:** open · low priority · *raised 2026-08-03 from a demonstrated false positive*

`examples/benchmark/` derives its change threshold from `NOISE_REPEATS` runs of one
configuration **back to back inside a single process** — same thermal state, same
background load. It then applies that threshold to comparisons **between** runs, hours or
days apart, where exactly those things differ.

The gap is demonstrated twice over, both on 2026-08-03:

- **Between runs.** One run flagged **9 of 9 rows as changed**, by 3.2–11.9 % and all in
  the same direction, against a within-run CV of 0.17 % that had floored the threshold at
  2.0 %. Nothing in the package had changed; the earlier run had been sharing the machine.
- **Within one run.** The additivity control — Sweep D, the longest row and the last —
  read 0.921 where two earlier runs read 1.001 and 1.007, and `wind_speed` moved 6 % in
  the same run. The floor is measured on short cheap rows early in the process and cannot
  see drift fourteen minutes in.

The second case is the sharper one: a threshold measured from back-to-back repeats says
nothing about rows separated by ten minutes of sustained load, and Sweep D is the row that
suffers most because it is the one that runs last.

An instrument that reports a change when nothing changed gets ignored when something does
— the same argument `CHORE-12` makes about the test suite.

Options, none costed: estimate a between-run term from the JSON history the folder already
keeps; report the delta without a verdict when only cross-session data exists; record
machine load with each run and decline the comparison when it differs materially; or —
cheapest, and it addresses the within-run half — interleave the sweeps so no single row is
always last, or repeat Sweep C at the end and take the spread across both.

## CHORE-1 — Default window half-width needs a real evaluation

`n_days=15` gives 61 pairs per hourly KDE on a two-year record — thin for a 2D density.
Whether 15, 7 or a sample-size-aware default is right still needs a real evaluation.

**Measured 2026-07-28**, as the share of the pooled window's variance explained by position
*within* the window — the cost of pooling a window rather than a date:

| date | ±7 | ±15 |
| :--- | ---: | ---: |
| 21 Mar | 3.8 % | 10.4 % |
| 21 Jun | 1.0 % | — |
| 21 Sep | **19.3 %** | — |
| 21 Dec | 0.4 % | — |

Two findings, neither settling the default:

1. **Halving the window works as predicted** at 21 March — 10.4 % → 3.8 %, close to the
   fourfold reduction a locally linear seasonal trend implies.
2. **The cost is date-dependent, and worst where the record is *least* variable.**
   21 September is 19.3 % at ±7, worse than 21 March at twice the width, because the same
   seasonal slope is measured against a much smaller day-to-day variance (CV 19.9 % against
   31.8 %). **A single global half-width cannot be right for both.**

**What is missing is the other side of the trade.** These numbers price the seasonal
contamination a wider window buys; nothing prices the sampling noise a narrower one costs.
Both bandwidths at ±7 reproduce the pool's mean, so ±7 is not obviously too thin at 19
years — but that is one record length, and the two-year case is untested.

## CHORE-2 — `date_id` is not zero-padded

`'2011-1-2'` does not sort lexicographically. `convert_to_daily_wide` sensibly builds its
own padded `date_str` instead, and `_add_date_id`'s docstring now warns not to rely on
`date_id` for ordering — so the trap is documented rather than silent. Worth aligning, but
it is a breaking change for anything grouping on `date_id`.

## CHORE-3 — Should the on-disk format carry a timestamp?

**Status:** open · one question, the rest landed with `FEAT-13`

`FEAT-13` defined schema v1 and the parquet container, and `docs/source/workflow.md`
documents it. What remains is the one question the schema deliberately did not settle:

**The calendar is four integer columns, not a timestamp.** `INDEX_COLS` is what the core
validates on, so a timestamp would be an *addition* for the file's sake rather than a
replacement — one more column able to disagree with the four that govern. Decide whether
the convenience is worth that.

## CHORE-4 — Bring `docs/source/` back in line with the repo

**Status:** open · **do last** · *narrowed 2026-08-03 — `FEAT-21` brought its own
documentation pass*

**Less drift than feared, and shrinking.** `quickstart.md` and `workflow.md` describe
π(x₀), `generate_series` and the registry; every module has an `api.rst` entry; the PVGIS
and file-location sections of `quickstart.md`, `workflow.md` and `README.md` were rewritten
by `FEAT-4` and `FEAT-21`. What is left:

- **`examples.md` still carries the walk-through inline** (~310 lines). Now that every
  use-case folder has its own README, decide whether that page should summarise and link
  rather than duplicate — two places to update is how it drifted the first time.
- **`theory.md` has not been re-read** since `FEAT-13`. It mentions the dataset only in
  passing, so it is likely fine, but nobody has checked.

Do this pass *after* the items it depends on, so it is one edit rather than two.

---

# Inbox — not yet triaged

Raw notes land here — refined but not yet costed or classified — and leave by
graduating into a group above with a real ID, or by being dropped. Nothing stays long.
