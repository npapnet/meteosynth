Status: **first run complete** · Date: 2026-07-28 · Serves: `FIX-1` with `CHORE-1` folded in
· Design and pre-registered decision rule: [`PLAN.md`](PLAN.md)

# Findings — run 1: 21 March, Heraklion 2005–2023

## In one paragraph

On 21 March, against the pooled window it is actually fitted to, the generator shows
**no overshoot at any training-set size** — +1.1 % on the full 19-year record, and within
±0.2 % of zero at 9, 3 and 2 years, against a minimum detectable effect of 4.8 %. The
+14 % that `FIX-1` records on a two-year record **does not reproduce**: this run's own
two-year configurations come out at −0.02 %. What *is* real, and is resolvable, is a
different defect: the model **under-produces overcast days by about 4×** (0.6 % of
synthetic days below 1 kWh/m² against 2.4 % observed) while matching the median and P90
to ~1 %. A missing low tail pushes a mean upward, so this is a plausible mechanism *for*
`FIX-1` — but it is a statement about the tail, not about the mean, and it predicts the
overshoot should be worst where overcast days carry most weight.

---

## What was run

| | |
| :--- | :--- |
| Record | Heraklion (35.34, 25.14), PVGIS 5.3 / SARAH3, **2005–2023 = 19 years**, 166 536 hourly rows |
| Attribute | `poa_global`, `n_days = 15`, `bandwidth = 0.1` (both shipped defaults, held fixed) |
| Sizes | k ∈ {19, 9, 3, 2} years — full, full//2, full//5, plus 2 to match the Paris configuration |
| Draws | 1 at k=19 (only one subset exists), 5 random **nested** subsets at each smaller size |
| Day | **21 March only**, as agreed. The other three are wired and disabled |
| Realisations | **n = 1000** per configuration, independent draws via `gen_day` |
| Cost | 16 configurations, 8.3 min; all 12 self-checks pass |

The first pass at the briefed n = 30 was **uninformative by construction** and was
discarded: the day-to-day CV of daily totals at 21 March is **35 %**, not the 12 % the plan
assumed, which put the minimum detectable effect at ±17 %. That measurement was the first
run's real job, and it is why everything below is at n = 1000.

---

## Result 1 — no overshoot, and no dependence on record length

Measured against the **pooled ±15-day window**, which is what the generator is fitted to:

| k (years) | mean deviation | MDE at 80 % power |
| --------: | -------------: | ----------------: |
| 19 | **+1.06 %** | 4.8 % |
| 9 | +0.05 % | 6.2 % |
| 3 | −0.16 % | 9.2 % |
| 2 | **−0.02 %** | 12.2 % |

Flat, and centred on zero. Nothing survives Holm–Bonferroni. The between-draw spread grows
as k shrinks — 2.8 % at k=9 to 6.8 % at k=2 — which is the expected loss of precision, not
a drift in the estimate.

**This directly contradicts hypothesis (b), small-sample, at this day and variable**, and
it fails to reproduce the Paris +14 % in the configuration built to match it.

## Result 2 — the apparent size trend is the *reference* failing, not the model

Measured against the exact-date mean instead, a clean-looking trend appears — and it is an
artefact:

| k | vs `pool_mean` | vs `detrended_centre` | vs `centre_mean` |
| --: | --: | --: | --: |
| 19 | +1.06 % | −2.61 % | −4.45 % |
| 9 | +0.05 % | −3.85 % | −4.92 % |
| 3 | −0.16 % | +1.47 % | −8.10 % |
| 2 | −0.02 % | +2.07 % | **−10.92 %** |

`centre_mean` averages **one value per year**, so at k=2 it is the mean of two days drawn
from a distribution with CV 35 % — a standard error near 25 %. The "trend" is that error
growing. This is exactly the failure the two-sample bootstrap was adopted to expose
(`PLAN.md` §2); with the reference held fixed it would have been reported as a confident
model defect.

**The choice of reference alone moves the answer by up to 16.7 %** (centre vs detrended at
k=2), and by −3.6 % even on the full record. That is larger than the entire effect `FIX-1`
is chasing, and it is the single most important methodological finding here.

## Result 3 — the seasonal trend inside the window is real, and it is a `CHORE-1` number

With **signed** day offsets, the trend across a ±15-day window is strongly significant
(linear t = +7.87 at 21 March). Measured on all four candidate days, 19 years:

| day | pool vs detrended centre | linear t | quadratic t | CV |
| :--- | --: | --: | --: | --: |
| 21 Mar | −3.64 % | **+7.87** | −2.45 | 35.2 % |
| 21 May | +2.07 % | +3.42 | +2.03 | 22.0 % |
| 21 Jun | **−0.79 %** | +4.50 | −1.75 | **10.1 %** |
| 21 Dec | **+6.38 %** | −1.43 | +3.34 | 39.3 % |

The signs are physical: at the winter solstice the seasonal curve is at a minimum, so a
symmetric window's mean sits *above* the target day; near the summer solstice the gap
nearly vanishes. **Within-window seasonal structure accounts for 10.4 % of the pool's
variance** at 21 March — a direct measurement of what the `n_days = 15` default costs, which
is what `CHORE-1` asks for.

Two corrections to the plan's reasoning, both now measured rather than assumed:

- The equinox is **not** the cleanest reference. Its linear trend is the largest of the
  four, and although a symmetric window cancels a linear term in the mean, the residual
  curvature still leaves a −3.6 % gap. **21 June is the cleanest** (−0.79 %).
- 21 June is also by far the most statistically efficient day to measure on — CV 10.1 %
  against 35.2 %, which at n = 1000 would give an MDE near **1.4 %** instead of 4.8 %.

## Result 4 — the real defect is a missing low tail

Full record, 21 March, synthetic (n=1000) against the observed pool (m=589):

| statistic | synthetic | observed | difference |
| :--- | --: | --: | --: |
| mean | 4.783 | 4.733 | +1.1 % |
| P50 | 5.166 | 5.231 | −1.2 % |
| P90 | 6.501 | 6.570 | −1.1 % |
| **P10** | 2.397 | 2.196 | **+9.2 %** |
| sd | 1.524 | 1.666 | −8.5 % |
| minimum | 0.571 | **0.000** | — |

| share of days below | synthetic | observed |
| :--- | --: | --: |
| 1.0 kWh/m² | **0.60 %** | **2.38 %** |
| 1.5 kWh/m² | 2.90 % | 5.26 % |
| 2.0 kWh/m² | 5.70 % | 9.17 % |

The centre and the bright end match to about 1 %. The overcast end does not: the model
produces roughly **a quarter as many** heavily overcast days as the record contains, and
never produces the fully dark day the record does. KS (p = 0.55) and Anderson–Darling
(p = 0.18) do not reject the distribution overall — the tail is too small a share of the
mass for an omnibus test to see it, which is why it needed to be looked at directly.

**The apparent under-dispersion is mostly not a defect.** Removing the within-window
seasonal spread — which the model legitimately cannot reproduce for one target date — moves
the sd ratio from 0.915 to **0.967**, and against 21 March alone it is **1.037**. So the
variance is close to right; it is the *shape of the lower tail* that is wrong.

## Result 5 — no compounding along the walk

`FIX-1` records a per-hour bias ramping through the day (hour 6 +9 % → hour 12 +18 %).
That signature does not appear here:

```
k=19:   6h +3%    9h +1%   12h +1%   15h −1%
k= 2:   6h −0%    9h +0%   12h +0%   15h −0%
```

Flat at every training-set size. Whatever produced the ramp in `FIX-1`'s measurement, it is
not reproduced by an independent-draw ensemble at 21 March on this record.

---

## Which branch of the decision rule fired

Three, and they are consistent:

- **"Interval covers 0 at every k."** At n = 30 the plan said this would be uninformative.
  At n = 1000 with an MDE of 4.8 % on the full record it is informative: any mean bias at
  21 March against the training pool is **smaller than ~5 %**, and is estimated at +1 %.
- **"`pool_mean` and `detrended_centre` disagree by an amount comparable to the bias."**
  They differ by −3.6 % on the full record. Part of `FIX-1`'s recorded +2–3 % is plausibly
  how it was measured.
- **"Large bias at k=2 that does not reproduce the Paris +14 %."** k=2 gives −0.02 %.

## What this does *not* establish

Scope discipline matters here, because the result is a negative one:

- **One day, one variable, one site.** `FIX-1`'s +14 % is Paris, `poa_direct`, and a
  *chained synthetic year* via `generate_series`; its +3.2 % is Heraklion **21 May**. This
  run is Heraklion, `poa_global`, 21 March, independent `gen_day` draws. It does not refute
  those measurements — it fails to reproduce the effect in this configuration.
- **Chaining is untested here.** Every draw starts fresh from π(x₀). If the defect lives in
  the day-to-day walk, this design cannot see it.
- **The low-tail finding is one day.** Its own prediction — that the deficit matters most
  where overcast days carry the most weight — is untested until 21 December runs.

## Recommended next steps

1. **Enable the other three days at n = 1000** (~25 min, one line in `config.py`).
   **21 December is the decisive test**: CV 39 %, the largest overcast share, and the day
   where a missing low tail should bias the mean upward most. **21 June is the sharpest
   measurement available** — MDE ≈ 1.4 %, and the smallest reference gap of the four.
2. **Reframe `FIX-1` around the lower tail**, not a mean overshoot. "Too few overcast days"
   is measurable, has a clear mechanism (kernel smoothing near a bound), and predicts where
   a mean bias should appear. The existing candidate fixes — reflection, log/sqrt transform,
   beta kernels — all act on exactly this.
3. **Give `CHORE-1` its number**: within-window seasonal structure is 10.4 % of pool
   variance at 21 March, and the pool-vs-centre gap runs from −3.6 % to +6.4 % across the
   year. That is the measured cost of `n_days = 15`.
4. **Re-measure `FIX-1`'s original cases with this harness** — Paris, `poa_direct`, and a
   chained year — since those are the configurations where the effect was seen and the ones
   this run did not cover. See **the Paris hypothesis** below, which is now the leading
   explanation for that +14 %.

### The Paris hypothesis

> **Working hypothesis, recorded 2026-07-28: the +14 % is most likely a statistical
> artefact — one measurement, on a two-year training record, with nothing establishing its
> spread.**

Run 1 supplies support that did not exist when `FIX-1` was written. At k = 2 the mean across
five random year-subsets is −0.02 %, but individual draws run from **−5.6 % to +12.7 %**,
with a between-draw spread of 6.8 %. A single two-year record landing near +13 % is an
ordinary outcome, not a remarkable one.

`FIX-1`'s Paris row is one synthetic year against one observed 2011–2012 mean — a single
realisation against a reference estimated from two years, with nothing separating model bias
from the sampling noise of either side. That is the same shape of defect as the `centre_mean`
reference in Result 2, where an artefact looked exactly like a clean trend.

Settling it means running Paris at k ∈ {19, 9, 3, 2}, **with 2011–2012 as an explicitly
named draw**, so the original configuration is reproduced and then placed against the
distribution of everything else. One caveat to keep honest: annual totals average over 365
days, so their year-to-year CV is far below a single day's 35 % — the two-year *training*
sample is the more likely source of the artefact than the annual aggregation, and separating
those is what the run has to do. Planned as strand B in [`PLAN.md`](PLAN.md); it needs a
chained-year mode, since run 1 exercises independent draws only.

---

## Two harness defects found and fixed during the run

Recorded because both would have produced confident, wrong answers, and neither was caught
by any test — only by the self-checks and cross-checks:

1. **Unsigned day offsets.** `meteosynth.day_window.circular_delta` is deliberately
   unsigned (it answers "how far apart", which is what window *selection* needs). Used for
   detrending it silently folds the season's rising and falling sides onto one curve, so a
   quadratic in `|offset|` cannot represent a trend at all. This produced a spurious −11 %
   headline. Fixed with a local signed helper; a symmetry check now guards it.
2. **Two concurrent runs appending to the same files.** A second run was started before the
   first was stopped, and both appended to the same CSVs, interleaving rows from a buggy
   and a fixed simulation into output that looked entirely plausible. Fixed with a PID
   lockfile and a duplicate-`config_id` check.

The first was caught because the pool-vs-centre gap was too large to be physical at an
equinox; the second because a `config_id` appeared twice. Both are now assertions that
fail loudly.
