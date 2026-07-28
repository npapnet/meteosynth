Status: **runs 1 and 2 complete** · Date: 2026-07-28 · Serves: `FIX-1` with `CHORE-1`
folded in · Design: [`PLAN.md`](PLAN.md)

> **[Run 2 is the current result](#findings--run-2-four-dates-two-bandwidths-heraklion-20052023)
> and is at the end of this file.** Run 1 is kept below it, unedited, because run 2's
> anchor cell reproduces it and the pair is the evidence that the rewritten harness
> computes what the old one did. Where the two disagree in *framing* — three references
> versus one, a k-sweep versus none — run 2's design is the one `PLAN.md` describes.

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
growing. This is exactly the failure the two-sample bootstrap was adopted to expose; with
the reference held fixed it would have been reported as a confident model defect. *(Run 2
sidesteps it differently: the reference is the pooled training window itself, which the
model was fitted to, so there is nothing left to estimate.)*

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
those is what the run has to do. **Not pursued.** Run 2 is scoped to how the current code
behaves against its own training data; reproducing a pre-0.2.0 measurement is a question
about the repo's history, not about the package. The provenance of `FIX-1`'s numbers is
recorded in [`PLAN.md`](PLAN.md)'s appendix instead.

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

---

# Findings — run 2: four dates, two bandwidths, Heraklion 2005–2023

Status: **complete**, 2026-07-28 · 9 configurations, 16.6 min, all 14 self-checks passing
· Figures: `figures/` · Tables: `results/summary_*.csv`

## In one paragraph

Against the pooled window it was actually fitted to, the generator **does not overshoot at
any of the four dates**: at the shipped `bandwidth=0.1` the mean of the daily total covers
the observed mean everywhere (ratios 0.994–1.007, none excluding 1). `FIX-1`'s headline —
generated irradiance systematically too high — **is not reproduced**. Two real defects are,
both consistent across every date that can test them. First, **the overcast tail is missing**:
where the record holds days below 1 kWh/m², the model produces 0.2 % against 1.4 % observed
at 21 March and 12.7 % against 15.1 % at 21 December, confirming run 1's finding at a second
date and a second threshold. Second, **the intended new default is worse than the one it
would replace**: Scott's rule pulls the mean *down* by 1.3–5.6 % at all four dates and
narrows the distribution (sd ratio 0.80–0.92). Both are consistent, signed, and outside their
intervals.

---

## What was run

| | |
| :--- | :--- |
| Record | Heraklion (35.34, 25.14), PVGIS 5.3 / SARAH3, 2005–2023 = **19 years**, 166 536 hourly rows |
| Attribute | `poa_global` |
| Window | **±7 days** — 285 pooled days per configuration (the shipped default is 15) |
| Bandwidth | **factor**: Scott's rule and 0.1 |
| Dates | 21 Mar · 21 Jun · 21 Sep · 21 Dec |
| Realisations | **n = 1000** per configuration, independent `gen_day` draws |
| Reference | **the pooled window itself** — one reference, known rather than estimated |
| Anchor | one extra cell at ±15 / 0.1, 21 Mar, reproducing run 1 |
| Cost | 9 configurations, **16.6 min** (~1.1 min each; the ±15 anchor took 3.8) |

## Result 1 — no overshoot, at any date, at the shipped bandwidth

Mean of the daily total, synthetic / observed:

| date | bandwidth 0.1 | 95 % CI | Scott | 95 % CI |
| :--- | --: | :--- | --: | :--- |
| 21 Mar | 1.007 | [0.990, 1.025] | **0.967** | [0.950, 0.983] |
| 21 Jun | 0.998 | [0.992, 1.003] | **0.987** | [0.982, 0.992] |
| 21 Sep | 0.994 | [0.982, 1.006] | **0.978** | [0.967, 0.988] |
| 21 Dec | 1.001 | [0.978, 1.025] | **0.944** | [0.924, 0.964] |

At `0.1`, **0 of 4** dates exclude 1. The anchor cell agrees: 1.001 at ±15. The largest
deviation anywhere at the shipped setting is 0.6 %, against an interval half a percent wide
at 21 June — the sharpest cell in the design.

**This is not a null result from lack of power.** The positive control recovers an injected
+10 % as a lift of **1.100**, detected in **9 of 9** configurations. The instrument sees a
10 % effect everywhere; there is no 10 % effect to see.

## Result 2 — Scott's rule is the wrong default, and in a legible way

Every Scott cell is *below* 1 on the mean, and all four exclude — the only statistic in the
run consistent across all four dates in both senses:

| statistic | Scott, range over the four dates | dates excluding |
| :--- | :--- | :--- |
| mean of daily sum | 0.944 – 0.987 | **4/4 · consistent** |
| P50 of daily sum | 0.890 – 0.979 | **4/4 · consistent** |
| P90 of daily sum | 0.902 – 0.996 | **4/4 · consistent** |
| sd of daily sum | 0.796 – 0.922 | 3/4 |
| P10 of daily sum | 0.998 – 1.160 | 2/4 |

The signature is over-smoothing, not a shift: P10 goes **up** while P50 and P90 go **down**,
so the distribution is squeezed toward its centre and the mean falls with the long upper
tail. That is what a 3.9× wider kernel does — Scott chooses a factor of **0.390** at this
pool size against the hand-set **0.100**, and the two are the same kind of number, a
multiplier on the data covariance.

**`FIX-1`'s old bandwidth sweep pointed the right way for the wrong reason.** It recorded
larger bandwidths making the bias *worse* and read that as boundary leakage inflating the
mean. Here a wider kernel moves the mean the other way, which suggests what that sweep
measured under the retired month-based estimator does not transfer.

## Result 3 — the overcast tail is missing, and it reproduces

Only two of the four dates can test this: 21 June and 21 September have **no observed days**
below either threshold, so a deficit is not measurable there, and those cells are excluded
rather than counted as agreement. On the two dates that can:

| date · threshold | observed | synthetic, Scott | synthetic, 0.1 |
| :--- | --: | --: | --: |
| 21 Mar · < 1 kWh/m² | 1.40 % | **0.20 %** | **0.20 %** |
| 21 Mar · < 0.25× median | 3.16 % | **1.00 %** | **1.10 %** |
| 21 Dec · < 1 kWh/m² | 15.09 % | **10.80 %** | **12.70 %** |
| 21 Dec · < 0.25× median | 1.75 % | **0.50 %** | **0.60 %** |

**2/2 informative dates, both thresholds, both bandwidths, every interval excluding.** The
deficit is ~7× at 21 March and ~1.2–1.4× at 21 December on the absolute threshold, and ~3× at
both dates on the relative one — so the *relative* deficit is roughly constant while the
absolute one is not, which is what a threshold that scales with the season should do.

The anchor cell reproduces run 1: **0.40 % against 2.38 % observed** at ±15 on 21 March,
where run 1 reported 0.60 % against 2.38 %.

**A deficit of the darkest days is not what raises a mean.** Run 1 offered the missing low
tail as a mechanism *for* `FIX-1`'s overshoot. Run 2 measures both in the same cells and they
do not go together: the tail is missing at 21 March and 21 December, and the mean is right at
both. Whatever the tail costs, it is not a mean bias at the shipped bandwidth.

## Result 4 — mild under-dispersion, at both bandwidths

sd of the daily total comes in at **0.891–1.001** at bandwidth 0.1 (2/4 dates excluding) and
0.796–0.922 at Scott (3/4). Under this run's framing that is a real defect rather than an
artefact: the model was fitted to the pool it is compared against, so it should reproduce the
pool's spread. Run 1's "the model legitimately cannot reproduce a window's seasonal spread"
argument does not apply here — that argument was about targeting a calendar date.

The daily **maximum** behaves differently and is worth recording: its sd is *below* 1 at
March, September and December but **above** it at June (1.187 at 0.1, 1.345 at Scott). June's
observed maxima are nearly degenerate — sd 32.7 W/m² on a mean of 1006, because every June
day is clear — and the KDE cannot represent a spike that narrow.

## Result 5 — `CHORE-1`, measured at both window widths

Share of the pooled window's variance explained by position within the window:

| date | ±7 | ±15 |
| :--- | --: | --: |
| 21 Mar | **3.8 %** | **10.4 %** |
| 21 Jun | 1.0 % | — |
| 21 Sep | **19.3 %** | — |
| 21 Dec | 0.4 % | — |

Two things fall out. **Halving the window worked as predicted at 21 March** — 10.4 % → 3.8 %,
close to the fourfold reduction a locally linear trend implies, and the ±15 figure reproduces
run 1's exactly. But **21 September is 19.3 % at ±7**, worse than 21 March at twice the width.
The seasonal slope is comparable at the two equinoxes; what differs is the noise it is
measured against — September's day-to-day CV is 19.9 % against March's 31.8 %, so the same
seasonal signal is a much larger share of a smaller variance.

**`CHORE-1` cannot be answered with one number.** The cost of a window depends on the date,
and it is worst where the record is *least* variable — the opposite of where intuition puts
it.

## Controls, and what they establish

| control | result |
| :--- | :--- |
| **Null** — observed pool resampled in place of the synthetic sample | 88/90 statistics cover the observed value. The two that do not are 2.2 % of the family, against the 5 % a 95 % interval permits. |
| **Positive** — synthetic sample inflated 10 % | lift recovered as **1.100**, detected in **9/9**. |
| **Anchor** — run 1's configuration re-run | mean ratio 1.001 vs run 1's 1.011; sd 0.962 vs 0.915; tail share 0.40 % vs 0.60 %; seasonal share **10.4 % vs 10.4 %**. |

The anchor is the load-bearing one: it says the rewritten harness — one reference instead of
three, a different bootstrap, a different statistic set — returns run 1's numbers on run 1's
settings.

## Two harness corrections made during the run

Recorded because both would have produced confidently wrong readings, and neither was caught
by a test:

1. **A bootstrap of zero events returns `[0, 0]`.** When the model produces no day below a
   threshold, resampling it produces no day below the threshold every time, and the
   degenerate interval "excludes" any observed share however small the sample. The upper
   bound now falls back to the rule of three (`3/n`), which at n = 1000 is 0.3 % — still
   comfortably below the 1.4 % and 15.1 % observed shares, so the finding stands, but on an
   interval that means something.
2. **An empty observed tail is not evidence.** June and September hold no days below either
   threshold, so those cells were being counted as "did not confirm the deficit" and
   diluting a 2/2 result into a 2/4 one. Informative cells are now identified explicitly, and
   the consistency rule additionally requires the four dates to **agree in sign** — four
   dates disagreeing about direction is not one effect measured four times.

## What this does not establish

- **One site, one variable, independent draws.** Chained series (`generate_series`) are not
  exercised, so nothing here speaks to drift along a multi-day walk.
- **Two dates carry the tail finding.** June and September cannot test it at all.
- **The window comparison is two points on one date.** ±7 against ±15 at 21 March is not an
  evaluation of the default.
- **Nothing about `poa_direct`, Paris, or pre-0.2.0 code.** Out of scope by design.

## What follows for `FIX-1` and `CHORE-1`

1. **`FIX-1`'s headline does not survive.** No overshoot at the shipped bandwidth at any of
   four dates, on a 19-year record, with an instrument demonstrated to detect 10 %. The
   +14 % belongs in a provenance note, not cited as a live figure.
2. **Restate it as the overcast deficit** — measured, reproduced at two dates and two
   thresholds, with a mechanism (kernel smoothing across a bounded, skewed density) and an
   existing set of candidate fixes that act on exactly it: reflection, a log or square-root
   transform, beta kernels near the bound.
3. **Do not adopt Scott's rule as the irradiance default** on this evidence. It is worse than
   0.1 on the mean and the spread at every date tested. `PERF-3` — that only Scott pickles —
   needs solving another way, most likely the custom `__reduce__` it already proposes.
4. **`CHORE-1` gets numbers, not an answer**: 3.8 % at ±7 and 10.4 % at ±15 on 21 March, plus
   the finding that the cost is date-dependent and worst at 21 September.
