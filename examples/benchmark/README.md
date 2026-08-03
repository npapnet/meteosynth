# `examples/benchmark/` — what drives generation time?

The repo's second measuring instrument. [`diagnostics-overshoot/`](../diagnostics-overshoot/)
asks whether the generator is *right*; this one asks what it *costs*, and answers in
ratios rather than seconds.

```bash
uv run python examples/benchmark/leros_timing_benchmark.py     # ~14 min
```

One JSON per run into `benchmarks/`, named for the machine. Git-ignored: this history is
local by nature, and committing it would push one machine's numbers into every clone.

## Read ratios, never seconds

**A second in one of these files is not a second in another.** Every absolute duration
here — and every one quoted in a README, docstring or changelog anywhere in this repo — is
a property of the machine that produced it as much as of the code. It means nothing until
set against another measurement from *the same machine*. Ratios travel; seconds do not.

## The four sweeps

| sweep | question | design |
| :--- | :--- | :--- |
| **A** | Does cost scale with the number of realisations? | `poa_global` alone, N stepped 10 → 100 → 1000 |
| **B** | How is a day's cost split between the attributes? | each attribute alone, one N |
| **C** | How much does an identical run vary? | one configuration, repeated |
| **D** | Do B's three sum to one run that does all three? | all attributes together, one N |

**Sweep A runs one attribute, not three.** The answer is *no* — cost is set by a
per-day-per-attribute grid build — so sweeping N on three attributes would establish the
same fact at three times the price. The cheapest attribute makes the sweep nearly free.

**Sweep B needs only one N**, precisely because Sweep A shows N barely matters. Measuring
the split at every N would re-measure the same three numbers three times. The three
attributes are not alike: `poa_global` is degenerate at night, so many of its 23 hourly
transitions collapse to a constant and never need a full 2D KDE, while `temp_air` and
`wind_speed` need all 23 and cost several times more. Sweep B is what turns "a day costs
X" into "a day costs X *because of* these attributes".

**Sweep C is what makes a comparison honest.** Sweeps A and B cannot measure scatter —
their rows differ in N or attribute, so any spread confounds a real effect with machine
noise. C repeats one fixed configuration and reports the coefficient of variation; a
difference smaller than a few multiples of that is thermal state and background load, not
a regression. It uses the cheapest attribute so repeats stay affordable, which does mean
the floor is measured on one configuration and assumed to transfer.

> **Known limitation, tracked as `CHORE-22`.** Those repeats run back-to-back inside one
> process — same thermal state, same load — but the threshold is applied to comparisons
> *between* runs, where exactly those things differ, and to rows measured minutes apart
> *within* one. On 2026-08-03 that produced 9 false positives out of 9 rows in one run,
> and a Sweep D reading 8 % off in another.

**Sweep D is the only check on the decomposition.** A gap between B's sum and one combined
run would mean something other than fitting and drawing is on the clock. Measured 1.001,
1.007 — and then **0.921**, which is the interesting one.

That third reading is almost certainly not a real finding about additivity. Sweep D is the
**longest run and the last**, so it is the row most exposed to whatever the machine is
doing fourteen minutes in; the same run had `wind_speed` move 6 % against the run before
it. The honest reading is that this benchmark controls for the *start* of a process
(`WARMUP`) but not for **drift across one** — a second instance of `CHORE-22`. Treat a
single Sweep D reading as suggestive, and re-run before believing it.

## Two controls that make it a fair test

**`PRECOMPUTE = True`, forced.** `meteosynth` decides for itself whether to build each
simulator's cached quantile grid, switching it on above 64 realisations. Left alone, a
10-realisation run would take the direct path and a 100-realisation run the cached one, so
the two would differ by *which algorithm ran* as much as by how many realisations were
asked for.

**A discarded warm-up run before any timing** (`WARMUP`, since 4.1). The first generation
in a process runs ~12 % slow, and it always landed on Sweep A's baseline — which every
other Sweep A row is divided by. That made 100× the realisations read as *0.91× the time*,
an artefact large enough to clear the noise floor this same script reports. One discarded
day pays it off for ~3 % of the total. It was invisible before version 3.0 only because
Sweep A's rows were then 330 s of three-attribute work, which amortised it away.

It bought more than it was meant to. Sweep C's first repeat had been carrying the same
overhead, so removing it **tightened the noise floor from 4.7 % to 2.0 %** — the value the
original 24.7-minute build reported — and straightened Sweep A to 1.00× / 1.01× / 1.07×.
A control, not an optimisation, and it recovered the sensitivity that shortening the run
had cost.

Related and separate: **the first calendar day of every run costs ~16 % more** than the
rest — 10.3 s against a steady ~8.9 s, reproduced in every repeat. That inflates absolute
seconds-per-day at low `N_DAYS`, but every row pays it identically, so no ratio moves.

## The runtime budget

Cost is **attributes × days** and independent of N, so the budget is a count of
attribute-days:

| sweep | attribute-days | dropping it loses |
| :--- | :--- | :--- |
| A — N scaling | 3 cheap | the N-independence claim itself |
| B — attribute split | 1 cheap + 2 dear | the whole "why a day costs X" |
| C — noise floor | 3 cheap | the threshold every comparison uses |
| D — additivity | 1 cheap + 2 dear | the only check on the decomposition |

`N_DAYS` scales all four linearly and is the honest knob. `CROSS_CHECK = False` drops
Sweep D for ~40 %. **Lowering `ATTR_SPLIT_N` saves almost nothing** — not a flaw, but
Sweep A's finding arriving as a bill.

### How it got to ~14 minutes

The 5-day, three-attribute-sweep design took **24.7 min**. Sweeping one attribute instead
of three left every ratio intact — N scaling 1.03× → 0.98×, the attribute split 3.24× →
3.36×/3.37×, additivity 1.001 → 1.014 — and cut it to 10.8 min at 3 days.

What moved was **Sweep C's noise floor, 2.0 % → 7.7 %**: fewer days means a noisier per-day
mean and a larger warm-up share, so that build detected an ~8 % regression where the 5-day
one claimed ~2 %. Two caveats — the 0.17 % CV behind the old floor was measured on an idle
machine, and one run cannot separate "fewer days" from "busier machine".

`N_DAYS = 4` plus the warm-up is the shipped setting: **~14 min at a 2.0 % floor** — the
original sensitivity at 57 % of the original runtime. **The floor is measured, not
assumed**, so read it in Sweep C's output rather than trusting this page.

## Versioning

`BENCHMARK_VERSION` guards the history comparison. Bump the **major** part when a
measurement changes meaning — a different day count, a different control — and older files
are refused outright rather than compared against a different measurement. Bump the
**minor** part when a sweep is merely added or refined; older files still compare on the
rows they share.

| version | change |
| :--- | :--- |
| 4.1 | discarded warm-up run |
| 4.0 | `N_DAYS` 3 → 4 |
| 3.0 | Sweep A on one attribute; Sweep D split out; `N_DAYS` 5 → 3; moved to `examples/benchmark/` |
