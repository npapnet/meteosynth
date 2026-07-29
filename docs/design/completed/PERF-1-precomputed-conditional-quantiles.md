Status: implemented · Date: 2026-07-28 · Serves: `PERF-1`

# Caching the conditional quantile function

Sampling used to evaluate a 1000-point KDE grid on **every** call to `get_next_state`,
which was ~97 % of generation runtime. A simulator that turns out to be sampled often now
caches its conditional inverse CDF over a grid of `previous` values and answers with two
interpolations.

**Measured on 21 March, Heraklion 2005–2023, ±7-day window, `bandwidth=0.1`:**

| ensemble size | before | after | |
| :--- | --: | --: | :--- |
| 64 draws | 91.6 ms/day | 91.6 ms/day | unchanged — below the threshold, same code path |
| 1000 draws | 91.6 ms/day | **11.5 ms/day** | **8.0×** |

This document records the three decisions that are not obvious, and the one thing the
test suite did *not* catch.

---

## 1. Interpolate the quantile function, not the CDF

The obvious cache is a table of conditional CDFs, one row per `previous` node, blended
linearly between the two bracketing rows. **That does not work**, and the reason is
structural rather than a matter of resolution.

The whole content of the model is that the conditional's *location* moves with
`previous` — a bright hour follows a bright hour. Averaging the CDFs of two distributions
centred in different places produces a **bimodal blend of both**, not a distribution
centred between them. Averaging their *quantile* functions shifts one into the other,
which is what the model means.

Measured as the sup-norm error of the sampled quantile function against the direct path,
21 March at `bandwidth=0.1`:

| nodes | CDF interpolation | quantile interpolation |
| --: | --: | --: |
| 16 | 40.5 % of domain | 38.6 % |
| 32 | 40.5 % | 28.4 % |
| 64 | 26.5 % | **19.2 %** |

Quantile interpolation reaches a given accuracy at roughly half the node count. It is also
free: sampling is inverse-transform anyway, so the cached quantile function *is* the thing
the sampler wants.

## 2. Uniform node spacing, not quantile spacing

Placing nodes at quantiles of the observed `previous` looks obviously right — it puts
resolution where the chain actually lands. **Measured, it is worse at every node count.**

Effect on 20 000 draws with `previous` drawn from its own marginal, 21 March, hour 9:

| spacing | nodes | mean error | sd error |
| :--- | --: | --: | --: |
| uniform | 16 | −0.09 % | −1.23 % |
| uniform | 32 | −0.04 % | −0.42 % |
| **uniform** | **64** | **−0.03 %** | **−0.04 %** |
| quantile | 16 | +2.54 % | −11.89 % |
| quantile | 32 | +0.40 % | −2.50 % |
| quantile | 64 | +0.00 % | −0.65 % |

Why: irradiance's `previous` piles up at zero, because night is most of the record's
hours at some transitions. Quantile spacing therefore spends most of its nodes resolving
the difference between 0 and 0, and starves the daytime range where the conditional
actually changes shape.

The lesson generalises beyond this package: **quantile spacing follows the marginal, but
accuracy needs nodes where the conditional varies.** For a bounded, heavily-atomic
predictor those are not the same places.

> **This was measured on `poa_global` only, and may not generalise across attributes.**
> The atom at zero is what defeats quantile spacing here; `temp_air` has no floor and no
> atom, so quantile spacing might genuinely win there. Tracked as `PERF-11`, which also
> records the metric to use — the distributional error under the marginal of `previous`,
> *not* the sup-norm of the quantile function, which §"What this changes" shows to be
> misleading.

## 3. Build lazily, at a threshold equal to the node count

Building the grid is one KDE evaluation over `64 × 1000` points — exactly 64 direct
calls' worth of work. Building it in `__init__`, as `PERF-1` originally proposed, would
therefore be a **64× pessimisation** for the path that matters most:

> `generate_series` fits a fresh generator for each day of the walk, takes **one** sample
> from each of that day's 24 hourly simulators, and moves on. A synthetic year would
> build 8784 grids and use each once.

So the grid is built on the 65th call to a given simulator. The consequences are worth
stating plainly:

- **Below the threshold, behaviour is bit-for-bit what it was.** Same code path, same
  arithmetic. Every existing test exercises this regime.
- **The worst case is bounded at 2×**, for a simulator asked for exactly ~128 samples:
  64 direct calls, then a build costing 64 more, then interpolation. Setting the
  threshold equal to the node count is what bounds it.
- **Memory is spent only where it pays.** A grid is ~0.5 MB (64 × 1001 float64); a hot
  day-generator with 11 non-degenerate hours holds ~6 MB. A year-long walk builds none,
  so it costs nothing. This is the difference between the lazy design and the
  `__init__` one, whose ~38 MB per generator `PERF-1` had flagged as the price of the
  feature.
- **Degenerate transitions never build one.** `KDE_1D` and `CONSTANT` are already a
  single interpolation and a lookup. At 21 March, 12 of a day's 23 transitions are
  degenerate (night), so only 11 grids are ever built.

`precompute_grid()` is exposed for the case where the ensemble size is known up front and
is large: it removes the crossover from the timing and makes every draw in the ensemble
come from the same sampler.

---

## What this changes about the numbers

**It changes sampled values, slightly.** End-to-end over 2000 synthetic days at 21 March,
cached against direct, driven from the same seed:

| | grid | direct | difference |
| :--- | --: | --: | --: |
| mean daily total | 4.8427 | 4.8516 | **−0.185 %** |
| sd | 1.4441 | 1.4447 | −0.041 % |
| P50 | 5.2999 | 5.3203 | −0.384 % |
| P90 | 6.3464 | 6.3477 | −0.020 % |
| share below 1 kWh/m² | 0.20 % | 0.25 % | — |

Two-sample KS: **p = 1.0**. The per-transition error is ~0.03 %; the 0.185 % on the daily
mean is that error accumulating along a 24-step chain, where each step's small
displacement changes what the next step conditions on.

**Set that against what the package can measure.** The diagnostic in
`examples/diagnostics-overshoot/` has a minimum detectable effect of 1.4–4.8 % depending
on the date, and the defect it identified — the overcast-day deficit — is a factor of
about four. A 0.2 % shift is an order of magnitude below the smallest thing the harness
can see.

**But results published before this change will not reproduce to the last digit.**
`examples/diagnostics-overshoot/FINDINGS-2026-07-28.md` was measured on the direct path.
That file is a dated record of a run, not a fixture, and is left as measured.

The whole diagnostic was re-run on the cached sampler as an end-to-end check —
**16.6 min → 2.1 min**, all 14 self-checks passing:

| | published (direct) | re-run (cached) |
| :--- | :--- | :--- |
| mean ratio, bw 0.1, four dates | 1.007 / 0.998 / 0.994 / 1.001 | 1.003 / 0.997 / 0.992 / 1.001 |
| — does any exclude 1? | no | **no** |
| mean ratio, Scott, four dates | 0.967 / 0.987 / 0.977 / 0.944 | **identical**, all excluding |
| overcast share, 21 Mar (obs 1.40 %) | 0.20 % | **0.20 %** |
| overcast share, 21 Dec (obs 15.09 %) | 10.80 % / 12.70 % | 10.80 % / 12.50 % |
| anchor, ±15 (obs 2.38 %) | 0.40 % | 0.50 % |

Every conclusion holds. Note that the **Scott figures are identical** while the
`bandwidth=0.1` figures drift in the third digit — which is the accuracy analysis above
showing up exactly where it predicted: a wider kernel makes the conditional smoother in
`previous`, so the same 64 nodes resolve it far better (0.09 % against ~0.03–0.4 %).

---

## Test impact

**No existing test required changing, and all 271 continued to pass.** That is a less
comfortable fact than it sounds, and it is the reason this section exists.

### Why nothing broke

- **No test pins a sampled value.** The suite checks *properties* — reproducibility from a
  seed, that a shared generator advances, that samples stay inside physical support, that
  degenerate hours are classified correctly. All survive a sampler that returns slightly
  different numbers.
- **The tests that do pin exact numbers pin the direct path**
  (`test_get_conditional_density_p1000` pins `argmax == 463` and a density maximum to
  1e-8). `get_conditional_density` is untouched, and the cache is built from it.
- **Every existing test runs below the threshold.** The largest ensemble in the suite is
  200 draws of `generate_series`, which is one call per simulator per day.

### The gap that implies

**A sampler regression would have passed silently.** Nothing in the suite compares what
the sampler produces against what it used to produce, so a change that shifted the
conditional by 10 % — rather than 0.03 % — would have gone unnoticed. That is a real hole,
and it predates this work.

`tests/test_conditional_quantile_grid.py` closes it for the cached path specifically:

| test | what would break it |
| :--- | :--- |
| `test_no_grid_before_the_threshold` | a grid built eagerly, silently pessimising `generate_series` |
| `test_below_the_threshold_the_draws_are_bit_for_bit_the_old_ones` | any change to the pre-threshold path |
| `test_grid_and_direct_agree_distributionally` | a mis-indexed node, an un-normalised row, CDF-instead-of-quantile interpolation |
| `test_grid_respects_the_domain_and_the_clamp` | out-of-support samples, or extrapolation past the fitted range |
| `test_the_grid_does_not_perturb_the_random_stream` | a path consuming a different number of RNG draws |
| `test_sampling_stays_reproducible_across_the_threshold` | non-determinism introduced by the switch |
| `test_degenerate_kinds_never_build_a_grid` | wasted memory and time on night hours |

The one to keep is `test_the_grid_does_not_perturb_the_random_stream`. Both paths consume
exactly one number from the generator per call, so crossing the threshold part-way through
an ensemble cannot desynchronise anything else drawing from the same stream. Had that not
held, the switch would have shown up as a *modelling* difference in every attribute
generated alongside, and would have been extremely hard to attribute.

### What is still not covered

The suite has no end-to-end calibration test — nothing asserts that a generated ensemble
matches the record it was trained on. `examples/diagnostics-overshoot/` does that job, but
it needs a network fetch and a few minutes, so it cannot be a unit test.

**Whether that gap is worth closing is an open question, not a settled defect**, and it is
tracked as `CHORE-12` with the case both for and against it. The honest summary: the gap is
demonstrated rather than hypothetical — this change walked straight through it — but the
density computation *is* pinned, support truncation *is* covered end-to-end over a whole
generated year, and a golden-value test on a sampler would be brittle against a `numpy` or
`scipy` upgrade. A calibration test with deliberately loose tolerances is the shape that
would work. Not attempted here.
