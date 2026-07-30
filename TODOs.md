# TODOs

**Open work only.** When an item lands it is folded into [`CHANGELOG.md`](CHANGELOG.md)
and removed from here, so this file never grows a "done" section. Design rationale lives
in [`docs/design/`](docs/design/README.md).

Each item records **what was measured**, so nobody has to re-derive it, and carries a
**stable ID** — cross-references elsewhere point at `FIX-2`, not at "item 7". Groups are
ordered by how much they block real use; within a group, most significant first.

## ID allocation

> **Next ID: 17.**

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

**Retired numbers:** `FIX-2`, `FIX-3`, `FEAT-5`, `FEAT-13` → [`CHANGELOG.md`](CHANGELOG.md) ·
`FEAT-1` → superseded 2026-07-29 by `FEAT-13` ·
`INBOX-1` … `INBOX-7` → [triaged 2026-07-27](#archived-items-from-todosmd).

| ID                                                                              | Item                                            | Status                |
| :------------------------------------------------------------------------------ | :---------------------------------------------- | :-------------------- |
| [PERF-2](#perf-2--four-copies-of-the-same-data-in-every-simulator)              | Four copies of the same data in every simulator | open · low priority   |
| [PERF-3](#perf-3--fitted-generators-cannot-be-pickled-at-the-default-bandwidth) | Fitted generators cannot be pickled             | open · low priority   |
| [PERF-11](#perf-11--grid-node-spacing-may-want-to-depend-on-the-variable)       | Grid node spacing may want to be per-variable   | open · low priority   |
| [PERF-16](#perf-16--draw-samples-in-batches-across-realisations)                | Draw samples in batches across realisations     | open · **after FEAT-15** |
| [FIX-1](#fix-1--the-overcast-tail-is-under-produced)                            | The overcast tail is under-produced             | open · **deferred**   |
| [FEAT-2](#feat-2--irradiance-pick-one-column-by-availability)                   | Irradiance: pick one column by availability     | (3) and (4) open      |
| [FEAT-3](#feat-3--chained-series-between-two-dates)                             | Chained series between two dates                | open · shape decided  |
| [FEAT-4](#feat-4--downloads-cache-by-default-keyed-by-sourcesiteperiod)         | Downloads cache by default                      | open · **next**       |
| [FEAT-15](#feat-15--ensemble-of-n-synthetic-years-in-one-pass)                  | Ensemble of N synthetic years in one pass       | open · **measured**   |
| [VISION-1](#vision-1--ingest-sources-other-than-pvgis)                          | Ingest sources other than PVGIS                 | future                |
| [CHORE-1](#chore-1--default-window-half-width-needs-a-real-evaluation)          | Default window half-width needs evaluating      | open                  |
| [CHORE-2](#chore-2--date_id-is-not-zero-padded)                                 | `date_id` is not zero-padded                    | open · breaking       |
| [CHORE-3](#chore-3--document-the-on-disk-format)                                | Document the on-disk format                     | one question left     |
| [CHORE-4](#chore-4--bring-docssource-back-in-line-with-the-repo)                | Bring `docs/source/` back in line with the repo | open · do last        |
| [CHORE-12](#chore-12--nothing-pins-what-the-sampler-produces)                   | Nothing pins what the sampler produces          | open · **for review** |

## Order of work

Groups are ordered by how much they block real use; this is the order to *take them in*,
which is not the same thing.

1. **FEAT-4**, which now needs only its location decision — `FEAT-13` landed and
   defines everything else it consumes.
2. **CHORE-4** last, so the docs pass is one edit rather than two.
3. **FIX-1**, whenever the cost is worth paying — the tail deficit is real, measured and
   documented, and it does not affect any quantity the package currently advertises.
   **CHORE-1** stands on its own rather than folded into it; half of it is measured.

**FEAT-3** and **FEAT-15** are independent of all of it and can slot in anywhere. **FEAT-15**
is the largest measured win available in the package (24 h → 5 min for a 1000-year
ensemble), is the one item here driven by a stated primary use case, and its spec is
**accepted and ready to implement**.

**PERF-16 and CHORE-12 are a pair, in that order reversed**: `PERF-16` puts a second
value-producing routine into the sampler, and `CHORE-12` is the reason the suite would not
notice if it were wrong. Do not take `PERF-16` before `CHORE-12`.

---

# Performance & internals

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
because persisting them buys ~58 ms and duplicates data already on disk — argued in
[`rolling-day-window.md`](docs/design/completed/rolling-day-window.md). `PERF-1`'s quantile
grid does not change that: it is built lazily, only for hot simulators, and costs ~0.5 MB
and ~0.5 s, so persisting it is a worse trade than the one already rejected.

**Switching the default to `bandwidth=None` is not a way around it** — measured
2026-07-28, `examples/diagnostics-overshoot/`. Scott's rule chooses **0.390** at a ±7-day
window on a 19-year record against the hand-set **0.100** — a 3.9× wider kernel — and is
worse on every statistic tested: mean daily total drops to 0.944–0.987 of observed at
**all four** dates, P50 to 0.890–0.979, P90 to 0.902–0.996, all excluding 1. The signature
is over-smoothing (P10 rises while P50 and P90 fall). The custom `__reduce__` is the fix.

---

## PERF-11 — Grid node spacing may want to depend on the variable

**Status:** open · low priority · **Impact:** accuracy of the cached sampler, not speed

`PERF-1`'s conditional-quantile grid places its 64 nodes **uniformly** across the range of
`previous`. That was chosen by measurement, but the measurement was on **`poa_global`
only**, and there is a good reason to think it does not generalise.

Quantile spacing lost badly on irradiance — at 16 nodes it gave **−11.9 %** on the sampled
standard deviation against **−1.2 %** for uniform. The cause is specific: irradiance's
`previous` has a **huge atom at zero**, because night is most of the hours at some
transitions, so quantile nodes pile up resolving the difference between 0 and 0 and starve
the daytime range where the conditional actually moves.

**`temp_air` has no such atom.** Its marginal is unimodal and roughly symmetric with no
floor, so quantile spacing would concentrate nodes near the mode — where most transitions
actually land — and thin them in the tails. That is the case quantile spacing is *designed*
for, and it may well win. `wind_speed` sits in between: bounded below, but with no atom at
the bound (its observed minimum is 0.07), so it may behave like temperature.

### The metric to use

The obvious metric is misleading and was already measured to be so. **Do not use the
sup-norm of the quantile function**: on irradiance it reads 15–25 % of the domain even
where the sampler is distributionally exact, because it is dominated by conditioning
values at the sparse edges of the range that the chain essentially never visits.

Use the **distributional error under the marginal of `previous`**, which is the quantity
that actually reaches a user:

1. Draw `previous` values by resampling the simulator's own `previous_values` (20 000 is
   ample), pair each with a uniform draw, and map both through the cached sampler and
   through the direct path.
2. Report the relative error in the **mean** and the **standard deviation** of the two
   resulting samples. On irradiance, uniform spacing at 64 nodes gives −0.03 % and
   −0.04 %; those are the numbers a competing rule has to beat.
3. Report the **low-tail share** as well — the share below `0.25 ×` the observed median —
   since that is the statistic `FIX-1` turns on and the one most sensitive to node
   placement near a bound.

Repeat per attribute (`poa_global`, `temp_air`, `wind_speed`) and at several hours, since
degeneracy and skew both vary through the day.

### Why it is low priority, and cheap

Both spacings cost **exactly the same** to build and to sample — same node count, same
KDE evaluation, same two interpolations. So this is a pure accuracy question with no
performance trade-off, and the change if it lands is a few lines in
`_build_quantile_grid`. Against that: the current error on the attribute that was measured
is already ~0.03 %, two orders of magnitude below anything the diagnostics can resolve, so
there is no evidence yet that anything is actually wrong for temperature either.

**Adopt a per-variable rule only if it wins on all three attributes at the same node
count.** Two spacing rules selected by attribute is a maintenance cost that a marginal
accuracy gain does not justify; a single better rule would.

See [`docs/design/completed/PERF-1-precomputed-conditional-quantiles.md`](docs/design/completed/PERF-1-precomputed-conditional-quantiles.md)
for the measurements behind the current choice.

---

## PERF-16 — Draw samples in batches across realisations

**Status:** open · **blocked on `FEAT-15`** (there is nothing to batch until the loops are
inverted) · **Deliberately deferred**, see
[the closing section of the `FEAT-15` spec](docs/design/FEAT-15-ensemble-generation.md#decided-draw-one-value-at-a-time)

`get_next_state` returns **one** value per call. Once `FEAT-15` has all N realisations
passing through the same fitted simulator at the same hour, they could be drawn in a single
vectorised operation instead of N Python calls.

### Why it was deferred rather than done with `FEAT-15`

**The prize is bounded at ~3×**, against the ~300× `FEAT-15` delivers on its own. Fitting is
a floor of ~1 min per year of models regardless of sampling speed, so a 1000-realisation year
goes 4.9 min → ~1.5 min at absolute best.

**The risk lands where the suite is blind.** `CHORE-12` records that `PERF-1` introduced a
whole new sampling path and **all 271 tests passed unmodified** — and would have passed had
it been wrong. A batched sampler means two value-producing routines where there is now one,
and a subtly wrong weather value still looks like a weather value. **Close `CHORE-12` first**;
the two items are properly a pair, and doing this one first is how a silent modelling error
gets shipped.

### The measurement that shapes the options

A first attempt converted only the `KDE_2D` path and got **1.4×** (4.9 → 3.5 min at
N = 1000, `poa_global`). The remainder was dominated by the degenerate hours still looping in
Python. **But degeneracy is almost entirely an irradiance property**, measured over four
dates at a ±7-day window on Heraklion 2010–2020, 23 transitions per date:

| attribute | degenerate transitions | by date |
| :--- | --: | :--- |
| `poa_global` | **49/92 (53 %)** | 43 % Jun · 52 % Mar · 52 % Sep · **65 % Dec** |
| `temp_air` | **0/92** | never — no floor, no atom, varies at every hour |
| `wind_speed` | **0/92** | never |

**Consequence for scoping, and it is the useful part of this item:** converting the `KDE_2D`
path alone is **the complete job for `temp_air` and `wind_speed`**, since all 23 of their
transitions take it. The extra work of batching `KDE_1D` and `CONSTANT` buys speed on
**irradiance only**, and most of it in winter, when the nights are longest. So the natural
split is:

1. **Batch `KDE_2D` only** — full benefit for two of three shipped attributes, 1.4× on
   irradiance, one new path in the sampler.
2. **Batch `KDE_1D` and `CONSTANT` too** — an `np.interp` and a fill, so cheap to write; it
   is irradiance-specific speed, and the seasonal skew means a December ensemble gains most.

Do **(1)** first and re-measure per attribute before deciding whether **(2)** is worth
anything. The earlier reading that "(1) takes the risk for a third of the payoff" was
measured on `poa_global` and **does not generalise** — for temperature and wind, (1) *is* the
whole win.

### Also worth knowing

The first attempt materialised a `(N, 1001)` quantile array **per hour** — ~8 MB per hour at
N = 1000 — which is very likely why it under-delivered against the ~90× the per-draw
arithmetic suggests. A careful implementation must avoid that allocation, and the estimate
above should be treated as a floor, not a ceiling.

Both `_sample_from_grid` and `_get_next_state_kde1d` are already pure interpolation, so
neither needs new *maths* — only a shape-aware rewrite. Whatever lands must keep
`PERF-1`'s invariant that a sampling path consumes exactly one number from the generator per
draw, or an ensemble's streams desynchronise from a single series'.

---

# Fixes — known defects

## FIX-1 — The overcast tail is under-produced

**Status:** open · **deferred 2026-07-28** · **Impact:** confined to low-tail questions —
storage autonomy, worst-case days. **Nothing the package advertises is affected.**

Evidence: [`examples/diagnostics-overshoot/FINDINGS-2026-07-28.md`](examples/diagnostics-overshoot/FINDINGS-2026-07-28.md);
design and provenance in [`PLAN.md`](examples/diagnostics-overshoot/PLAN.md).

### Why it is deferred — the cost/benefit, measured

The fix is expensive: reflection, a log/sqrt transform or beta kernels all change
`MarkovChainSimulator2dKDE`'s density, which means re-baselining every golden test and
re-validating all three attributes. The benefit, measured on the 19-year Heraklion record:

| question | effect of the defect |
| :------- | :------------------- |
| Mean daily total, monthly or annual energy | **none** — ratio 0.994–1.007, no date excluding 1 |
| Daily P50, P90, and the daily maximum | **≤ 1–4 %**, and the mean of daily maxima is within 2 % |
| **Annual P90** (the exceedance figure a yield study quotes) | **0.12 % of the mean** — 2.3 kWh/m² on a mean year of 1879 |
| Daily P10 | biased **high by up to 9 %** |
| Frequency of overcast days | **~4× too few** where the record has any |

The annual figure is why this is cheap to postpone. Days below 1 kWh/m² are 3.47 % of the
record but carry **0.50 % of its energy**, and Heraklion's year-to-year CV is only 1.71 %,
so understating the daily spread by the measured 5.5 % moves an annual P90 by a tenth of a
percent. **A yield study cannot see this defect.**

### What it does affect, and must therefore be documented

- **Storage sizing, autonomy, worst-case-day analysis.** These read the low tail directly,
  and the model under-produces it fourfold. The package should say so rather than let a
  user discover it.
- **Any daily low percentile.** P10 runs up to 9 % high.
- **Sites with more overcast weather than Heraklion.** The relative deficit was ~3× at both
  dates tested, so it is a property of the kernel rather than of the climate — but the
  *consequence* grows with how much of the year is overcast, and a northern site has far
  more of it. Untested.

**Revisit when** any of those becomes a use case, when a second site shows a larger effect,
or when the KDE core is being touched anyway for another reason — the marginal cost is much
lower then.

### What is actually wrong

**The model produces too few overcast days**, at every date where the record contains any.
Measured against the pooled window the generator is fitted to, 19 years, n = 1000 per cell:

| date · threshold          | observed | synthetic (bw 0.1) |
| :------------------------ | -------: | -----------------: |
| 21 Mar · < 1 kWh/m²       |   1.40 % |         **0.20 %** |
| 21 Mar · < 0.25× median   |   3.16 % |         **1.10 %** |
| 21 Dec · < 1 kWh/m²       |  15.09 % |        **12.70 %** |
| 21 Dec · < 0.25× median   |   1.75 % |         **0.60 %** |
| 21 Mar ±15 d · < 1 kWh/m² |   2.38 % |         **0.40 %** |

Every interval excludes, at both bandwidths tested. 21 June and 21 September hold **no**
observed days below either threshold, so they cannot test it either way. Daily totals are
also mildly **under-dispersed** (sd ratio 0.891–1.001 at bandwidth 0.1).

**Mechanism:** a symmetric kernel across a bounded, right-skewed conditional density cannot
put enough mass near the floor without putting some below it.

**Not reproduced, do not re-derive:** a biased mean (the earlier Paris +13 %/+14 % figures
were measured under the pre-0.2.0 month-subset estimator and are kept in `PLAN.md`'s
appendix as provenance, not as live measurements); compounding along the 24-step walk
(per-hour bias is flat); any dependence on record length (k ∈ {19, 9, 3, 2} years, flat,
and two-year cells at −0.02 %).

### Candidate fixes

- **Boundary correction for the bounded-below case**: reflection at zero, a log/sqrt
  transform before fitting, or beta/gamma kernels near the bound. All three act directly on
  the tail deficit.
- A wider kernel is **not** the answer: Scott's rule makes every measured statistic worse
  (see `PERF-3`).
- Investigate whether `_calc_domain` taking `min`/`max` across *both* `previous` and
  `current` widens the domain where the two ranges differ.

`examples/diagnostics-overshoot/` is the calibration harness — nine configurations,
~2 minutes, with a null control, a positive control and an anchor cell. **Any attempted fix
should move the tail shares above without moving the mean ratios off 1.**

### Already tried — do not repeat

**Removing the ±10 % domain padding, both sides.** Landed in 0.2.0. Measured at the time as
moving the Paris total the wrong way (670 → 678 kWh/m²) — a number now understood to carry
no error bar. It did fix generated negatives, 1.29 % → 0.00 %, which was its actual purpose.
The padding is gone from both the 1D and 2D paths.

---

# Features — planned work


## FEAT-2 — Irradiance: pick one column by availability

**Status:** **(1) and (2) landed** with `FEAT-13` · (3) and (4) open · **Needed before VISION-1**

Questions (1) and (2) landed with `FEAT-13` — see
[the design doc](docs/design/completed/FEAT-13-met-dataset-format.md).
`MetDataset.irradiance_column` resolves the column by availability against the ordered
`IRRADIANCE_COLUMNS = ("poa_global", "ghi")`, and `MetDataset.provenance` records what a
cache holds. **(3) and (4) below remain open.**

> **Settled: one irradiance column is modelled, chosen by what the source supplies.**
> Components are *not* modelled separately and summed. What remains is **selection and
> provenance** — how the package chooses between `poa_global` and `poa_direct` when only
> one is available, and how it records which it used.

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

Fitting the three components independently and summing the *generated* series is not
equivalent to fitting `poa_global`: each component gets its own KDE and its own draw, so
the physical anticorrelation between direct and diffuse — a cloud moves one down and the
other up — is destroyed. The sum is then under-dispersed at the day scale, over-dispersed
hour to hour, and can produce hours no sky could.

The accepted consequence: a user needing internally consistent components — to re-transpose
onto a different tilt, say — cannot get them from this package. That is a limitation of the
one-attribute-at-a-time engine, not a bug.

### Still to decide

1. ~~How is the column selected?~~ **Landed:** `MetDataset.irradiance_column`.
2. ~~What does a cache hold?~~ **Landed:** `MetDataset.provenance`.
3. **Is a derived column distinguishable from a fetched one?** Today it is not.
   `adapters.py` states the position — *"the column name is the provenance… no metadata
   sidecar"* — and a summed `poa_global` sits byte-for-byte alongside a fetched one.
   `Provenance.notes` can *say* so — `examples/tools/site_data.py` writes exactly that
   — but nothing enforces or checks it, so a summed `poa_global` still sits byte-for-byte
   alongside a fetched one. Options: a dedicated provenance field, a naming convention, or
   accepting that the summation is exact enough for PVGIS. It will matter for a provider
   where the identity does not hold exactly.
4. **What does a saved synthetic series carry?** Whatever answers (1) and (3) for observed
   data should ride along with generated data, or a result cannot be audited later.

---

## FEAT-3 — Chained series between two dates

**Status:** open · shape decided · **Independent of everything else**

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

---

## FEAT-4 — Downloads cache by default, keyed by source/site/period

**Status:** open · **next** · **Impact:** the user-facing half of caching

`FEAT-13` landed the *record* — what a saved dataset says about itself, and the match
predicate `fetch_pvgis` now applies to a warm cache. This is the **policy**: for any
fetch, not only the examples,

- write to a cache subfolder **by default**, rather than only when handed an explicit
  path,
- **skip the download** when a matching file already exists,
- unless a `force_refetch` says otherwise.

Tracked separately because the two fail differently: a wrong record is a correctness bug,
a wrong default location is an ergonomics one. Only the location question is left.

**Assessment, post-FEAT-13.** `adapters.fetch_pvgis` still caches only when handed an
explicit `cache=` path — but it now *matches* what it finds there against the request and
raises `CacheMismatchError` rather than answering the wrong question, so the correctness
half is done. The examples still keep their own cache (`examples/tools/site_data.py`,
keyed by filename via `Site.cache_path`), which this would subsume.

**The one open question: where does a default cache live?** `./data/<source>/` relative to
the working directory (matches the examples, visible, easy to git-ignore) or a user-level
cache directory (survives moving between projects, but is invisible from any of them)?
**Decide this before starting** — it shapes the API surface, and `FEAT-13` deliberately
did not settle it.

Note the file *name* no longer has to encode anything: provenance is inside the file, so
the key can be a hash and the match check still answers honestly.

---

## FEAT-15 — Ensemble of N synthetic years in one pass

**Status:** open · **measured 2026-07-30** · **spec drafted** ·
**Impact:** the package's primary use case is currently ~300× slower than it needs to be

**Specification: [`docs/design/FEAT-15-ensemble-generation.md`](docs/design/FEAT-15-ensemble-generation.md)**
— carries the implementation plan, the test plan, and one open question (whether to
bulk-draw the samples) left for a decision. The measurements below are the evidence behind
it and are not repeated there in full.

Generating N realisations of a synthetic year means calling `generate_series` N times, and
**every call refits every day's generator from scratch**. Invert the loop — walk the
calendar once, and at each calendar day advance all N realisations through that day's
already-fitted models — and the fitting cost is paid once instead of N times.

Downstream shape wanted: a folder of N files, one realisation each, **or** one wide file
carrying all N realisations, for import into other software.

### The measurement

Heraklion 2010–2020 (96 432 rows), `poa_global`, ±7-day window, `bandwidth=0.1`.

**The LRU cache contributes nothing to an ensemble, and nothing to a single walk either.**
A 30-day walk × 5 realisations at the default `cache_size=8` performed **150** generator
fits for **30** distinct calendar days — a hit rate of exactly zero. Raising
`cache_size` to 32 cut it to **30** fits and the wall clock from 36.5 s to 15.9 s (2.3×),
confirming the misses were the whole cost. **70 % of that wall time was fitting.**

Per-unit costs, from which everything else follows:

| operation | cost |
| :--- | --: |
| fit one calendar day's generator (window subset + 25 KDEs), median of 5 dates | **180 ms** |
| — `DayWindowGenerator`'s docstring quotes *"~58 ms"*, measured on a **two-year** record; 11 years of pairs is what costs 3× more | |
| sample one day, direct path — what a chained walk does today | **57.7 ms** |
| sample one day, `PERF-1` cached-grid path | **0.62 ms** |
| sample one day, grid path vectorised across realisations | **0.32 ms** |

Projected onto a 365-day year, one attribute:

| N | today | inverted loop, scalar | inverted loop, vectorised |
| --: | --: | --: | --: |
| 10 | 14.5 min | 1.1 min | 1.1 min |
| 100 | **2.4 h** | 1.5 min | 1.3 min |
| 1000 | **24.1 h** | **4.9 min** | **3.4 min** |

**The win decomposes into two independent effects, and the second is free.** Amortising the
fit is worth ~N×; on top of that, a simulator asked for N samples instead of one crosses
`PERF-1`'s activation threshold and builds its quantile grid, worth a further **93×** on
sampling (57.7 → 0.62 ms). A chained year is the one path `PERF-1` deliberately leaves
untouched — see `_GRID_ACTIVATION_CALLS` — so the ensemble use case has never benefited
from it. Inverting the loop is what makes it apply.

**Memory moves the right way.** Holding all 366 generators to get the same amortisation
costs ~126 MB per attribute (the alternative the `DayWindowGenerator` docstring rejects);
the inverted loop holds **one** day's generator at a time. The output is
`N × 8760 × float64` = **67 MB** at N = 1000 per attribute.

**Statistically it is the same model.** Each realisation remains an independent chain
through the same per-day models — realisation *i*'s hour 0 on day *d* conditions on
realisation *i*'s hour 23 on day *d−1*, exactly as the chained walk does. The change is
purely the order of evaluation.

### The reproducibility question, and its answer

The concern that results would depend on N and not only on the seed is **correct for the
obvious implementation and avoidable in full.** Measured on one day, `seed=42`:

| RNG scheme | realisation 0 at N=2 vs 5 vs 50 |
| :--- | :--- |
| one shared stream, drawn realisation-major | **differs** — max 67.7 W/m² across the 24 hours |
| `SeedSequence(seed).spawn(N)`, one child per realisation | **bit-identical at all three** |

`spawn` keys each child on its **index**, not on the count: `spawn(10)[i]` and
`spawn(1000)[i]` generate identical state for i = 0, 3, 9 (`spawn_key == (i,)`). So with
per-realisation child streams, realisation *i* is a fixed function of `(seed, i)` alone.
Realisation 0 was also verified **bit-identical to the sequential walk** driven by the same
child stream.

Two properties this buys, both worth stating in the docstring: an ensemble can be **extended**
from 100 to 200 realisations without invalidating the first 100, and a single realisation can
be **reproduced in isolation** for debugging without generating the other 999.

> **Use `SeedSequence.spawn`, not one shared stream.** This is the whole decision, and it
> costs nothing to get right at the outset.

### The one residual N-dependence — decide explicitly

`PERF-1`'s grid activates on the 65th call to a simulator, so **which sampler a realisation
is drawn from depends on its index**: realisation 0 takes the direct path, realisation 500
takes the grid. That is N-independent, but it makes realisations not quite interchangeable.
Measured effect on one day's total: **−0.02 %** (grid vs direct, same stream).

Recommended: call `precompute_grid()` up front — the method exists for exactly this case —
so every realisation comes from the same sampler. The accepted cost is that ensemble output
**will not match today's chained output bit-for-bit** (~0.02 % here, −0.185 % on a 2000-day
mean in `PERF-1`'s measurement, KS p = 1.0). That is an order of magnitude below the
diagnostics' minimum detectable effect, and it is the same trade `PERF-1` already took.

### Shape

```python
dwg.generate_ensemble(start=(1, 1), n_days=365, n_realisations=1000, seed=1)
# -> (n_realisations, n_days, 24)
```

Reuse `generate_series`'s existing contract — `start`, `n_days`, `include_feb29`, the slot
walk — so the two cannot drift apart. `generate_series` becomes the `n_realisations=1` case
rather than a separate implementation.

**Settled 2026-07-30**, in the spec: one random stream per **(realisation, attribute)**,
keyed on the realisation index and `zlib.crc32` of the attribute name — so a realisation does
not depend on N *and* an attribute does not depend on which other attributes were requested;
`precompute_grid()` up front so every realisation is drawn from the same sampler; **one
long-format parquet file**, one row group flushed per calendar day, with a pivoted `.xlsx`
as a lossy one-way export. The output format also answers `FEAT-2` item (4) — *what a saved
synthetic series carries* — for the ensemble case.

**A latent trap in the shipped example, found while specifying this.**
`examples/use_cases/year/synthetic_year.py:201-202` seeds with
`SEED + 1000 * realisation + ATTRS.index(attr)`. The attribute key is **positional**, so
dropping one attribute from `ATTRS` shifts the others' seeds and silently changes their
series for the same nominal seed. Measured: `temp_air` requested alone does not reproduce its
column from a three-attribute run. The name-keyed scheme above fixes it; the example gets
repointed at `write_ensemble` as the last implementation step.

**Two constraints found while specifying it**, both of which shaped the above:

- **A long-format `.xlsx` is impossible at the target N.** Excel holds 1 048 576 rows;
  1000 realisations × 8760 hours is **8.76 M**, so long format caps out at ~119
  realisations. The export must pivot to wide (one sheet per attribute, hours × realisations,
  good to N ≈ 16 000) and refuse rather than truncate. Also needs a **new optional
  dependency** — neither `openpyxl` nor `xlsxwriter` is currently installed.
- **Streaming requires the inverted loop**, which is a second reason to prefer it: with the
  day loop outermost, day *d*'s rows can be flushed as they are produced. Today's
  realisation-major order cannot stream into a single file at all.

**Decided 2026-07-30: draw one value at a time.** Batching the draws across realisations is
worth at most ~3× more on top of the ~300× above, and puts a second value-producing routine
into the one place the suite is blind (`CHORE-12`). Split out as `PERF-16` and deliberately
deferred; it changes no API and no file format, so it can land any time afterwards.

### Fix the docstring this contradicts

`DayWindowGenerator`'s class docstring (`generators.py:459-461`) justifies `cache_size=8`
with *"Since callers walk the calendar in order, a small cache hits nearly always"*. **That
is false**: an ordered walk visits each slot exactly once and never revisits it, so the hit
rate is zero — measured above. The cache earns its keep only for repeated calls on the
*same* day, which is the day-ensemble use case (`gen_day`), not `generate_series`. Correct
the claim while this item is in the file.

---


# Direction — where the package is going

## VISION-1 — Ingest sources other than PVGIS

**Status:** future · **Unblocked** · **Shapes:** FEAT-13, FEAT-2

Support other providers (Open-Meteo, ERA5, local station data) via a thin **adapter
layer** that normalises each source into the canonical schema the core consumes
(`year, month, day, hour` plus the modelled columns), so the Markov code never learns a
provider's quirks.

The `VariableSpec` registry is the natural seam: an adapter maps provider columns to
registered spec names, converts units into each spec's declared `units`, and validates
against each spec's `support` — turning silent ingestion bugs (kW/m² read as W/m², °F as
°C) into an error at the boundary. `adapters.py` already has the shape of this; what is
missing is a second real provider to prove it.

**First task:** `SOURCE_RENAMES["open_meteo"]` maps `shortwave_radiation` onto
`poa_global`, which is **wrong** now that `ghi`/`dni`/`dhi` are registered against
`IRRADIANCE_HORIZONTAL`. Fix that mapping; FEAT-2's resolver decides the rest.

---

# Housekeeping

## CHORE-1 — Default window half-width needs a real evaluation

`n_days=15` gives 61 pairs per hourly KDE on a two-year record — thin for a 2D density.
Whether 15, 7 or a sample-size-aware default is right still needs a real evaluation.

**Measured 2026-07-28** (`examples/diagnostics-overshoot/`), as the share of the pooled
window's variance explained by position *within* the window — the cost of pooling a window
rather than a date:

| date   |    ±7 |    ±15 |
| :----- | ----: | -----: |
| 21 Mar | 3.8 % | 10.4 % |
| 21 Jun | 1.0 % |      — |
| 21 Sep | **19.3 %** |  — |
| 21 Dec | 0.4 % |      — |

Two findings, neither of which settles the default:

1. **Halving the window works as predicted** at 21 March — 10.4 % → 3.8 %, close to the
   fourfold reduction a locally linear seasonal trend implies.
2. **The cost is date-dependent, and worst where the record is *least* variable.**
   21 September is 19.3 % at ±7, worse than 21 March at twice the width, because the same
   seasonal slope is measured against a much smaller day-to-day variance (CV 19.9 % against
   31.8 %). A single global half-width cannot be right for both.

**What is still missing:** the other side of the trade. These numbers price the seasonal
contamination a wider window buys; nothing yet prices the sampling noise a narrower one
costs. Both bandwidths at ±7 reproduce the pool's mean, so ±7 is not obviously too thin at
19 years — but that is one record length, and the two-year case is untested.

## CHORE-2 — `date_id` is not zero-padded

`'2011-1-2'` does not sort lexicographically. `convert_to_daily_wide` sensibly builds its
own padded `date_str` instead. Worth aligning, but it is a breaking change for anything
grouping on `date_id`.

## CHORE-3 — Document the on-disk format

**Status:** open · **mostly landed with FEAT-13** — one question left

`FEAT-13` defined schema v1 (columns, dtypes, row identity, ranges, ordering,
completeness) and the parquet container that carries it, and `docs/source/workflow.md`
now documents it. What remains is one design question the schema deliberately did not
settle:

**The calendar is four integer columns, not a timestamp.** `INDEX_COLS` is what the core
validates on, so a timestamp would be an *addition* for the file's sake rather than a
replacement — one more column able to disagree with the four that govern. Decide whether
the convenience is worth that.

## CHORE-4 — Bring `docs/source/` back in line with the repo

**Status:** open · **Do last**, after CHORE-3 and FEAT-4

**Assessment.** Less drift than feared. `quickstart.md` and `workflow.md` already describe
π(x₀), `generate_series` and the registry; every stale example path has been repointed;
and the PVGIS sections of `quickstart.md` and `README.md` have been rewritten, with
`adapters` and `variables` added to `api.rst`. What is left:

- **`examples.md` still carries the walk-through inline.** Now that every use-case
  folder has its own README, decide whether that page should summarise and link rather
  than duplicate — two places to update is how it drifted the first time.
- **`theory.md` has not been re-read** since `FEAT-13`. It mentions the dataset only in
  passing, so it is likely fine, but nobody has checked.
- **The on-disk format now has a page** — `workflow.md` gained schema v1, `save`/`load`
  and the version-tolerance rule when `FEAT-13` landed. Revisit only if `CHORE-3`'s
  timestamp question changes the schema.

Do this pass *after* the items it depends on, so it is one edit rather than two.

## CHORE-12 — Nothing pins what the sampler produces

**Status:** open · **raised for review, not yet agreed** · **Recommended priority:
medium-low** — worth deciding on, not worth dropping other work for · **now gates
[`PERF-16`](#perf-16--draw-samples-in-batches-across-realisations)**, which would add a
second sampling path this gap cannot police

### The observation

`PERF-1` added an entirely new sampling path — a cached quantile grid replacing a live KDE
evaluation — and **all 271 existing tests passed without modification**. The suite could
not tell the difference between the two samplers, and could not have told the difference
had the new one been *wrong*. It tests **properties**: that a seed reproduces, that a
shared generator advances, that samples stay inside physical support, that degenerate
hours are classified correctly. All of those survive a sampler that returns materially
different numbers.

### Arguments against acting

- **The density computation *is* pinned.** `test_get_conditional_density_p1000` fixes
  `argmax == 463` and the density maximum to 1e-8 on a known fixture. What is unpinned is
  the step from that density to a sampled value, and the chain built on top of it.
- **Support truncation is pinned end-to-end**, over a whole generated year — the defect
  that actually shipped once (1.29 % negative irradiance) and the one most likely to recur.
- **A statistical property is genuinely awkward to pin.** An exact-value golden test on a
  sampler is brittle: a `numpy` or `scipy` release that changes generator internals or
  `gaussian_kde` would break it without anything being wrong.

### Arguments for

- The gap is **demonstrated, not hypothetical**: this change exercised it.
- Every modelling defect this repo has found — `FIX-2`, `FIX-3`, the two harness defects
  in the overshoot diagnostic — was found by *running things*, never by the suite.
- The natural check already exists but lives outside the suite:
  `examples/diagnostics-overshoot/` compares a generated ensemble against the pool it was
  fitted to. It needs a network fetch and ~5 minutes, so it cannot be a unit test — but a
  miniature of it can.

### What would close it

A **calibration test**, not a golden-value test. Fit on the existing `synthetic_mdp`
fixture (two years, a known generative process, all four attributes, already used across
the suite), draw a few hundred days, and assert against the training pool:

| assertion | suggested tolerance | what it catches |
| :--- | :--- | :--- |
| mean of daily total vs pool | within 5 % | a level shift — the `FIX-1` class of defect |
| sd of daily total vs pool | within 15 % | a dispersion collapse, e.g. a mis-built grid |
| every value inside support | exact | already covered; keep it here too |
| no NaN or inf anywhere | exact | the failure mode `FIX-2` produced |

Estimated cost: **one test file, a few tens of seconds**. The tolerances are the whole
design problem — too tight and it becomes a maintenance tax, too loose and it asserts
nothing. The numbers above are a starting point, not a measurement.

**Do it per attribute, not just for irradiance.** `temp_air` and `wind_speed` exercise
different structure — no floor, no degenerate hours — and a defect confined to one of
them is exactly what a single-attribute test would miss.

---

# Inbox — not yet triaged

Raw notes land here — refined but not yet costed or classified — and leave by
graduating into a group above with a real ID, or by being dropped. Nothing stays long.

## INBOX-10 : Move envelope functionality from the examples into the code

`examples/tools/` contains functionality that could be part of the main library as a
diagnostics or convenience function.

## INBOX-13 : make sure progress bar exists in example scripts and its functional 

`tdqm` is now part of core dependencies. I need to make sure that the code is able to visualize the concepts. Check whether this package is ok to put this functionality of a higher level one. 


## INBOX-14 : Implement cli

This package could benefit from cli subcommands `meteosyn fetch ...`, `meteosyn train ...` (for training a new model), `meteosyn generate ...`. Blocked by location of data files. 

