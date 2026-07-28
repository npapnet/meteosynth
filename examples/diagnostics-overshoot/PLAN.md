Status: **executed — run 1 complete, see [`FINDINGS.md`](FINDINGS.md)** · Date: 2026-07-28
· Serves: `FIX-1` with `CHORE-1` folded in

> **Run 1 executed 2026-07-28** at 21 March, n = 1000 (not the briefed 30 — the measured CV
> is 35 %, not the 12 % assumed here, which made n = 30 uninformative by construction; that
> measurement was the first run's job). Three departures from this plan are recorded in
> `FINDINGS.md`: **"achieved power" was replaced by minimum detectable effect**, since
> post-hoc power on an observed effect is a monotone restatement of the p-value; **the
> equinox turned out not to be the cleanest reference** (21 June is); and two harness
> defects were found and fixed mid-run.

> **Revision 2** folds in review comments on §1–§4: `n` is tunable and starts at **30**;
> the deviation bootstrap resamples **both** samples rather than adopting Welch; the
> reference is the **centre day**, not the window mean; and the first run is **21 March
> only**, with the solstice days built into the harness but not executed.
>
> **Revision 3** adds [Raw data written to disk](#raw-data-written-to-disk-for-independent-checking) —
> every observed and synthetic daily total, and the hours behind them, dumped in tidy form
> so the analysis can be independently checked rather than taken on trust.
>
> Review of the remaining sections is still open — this plan is not yet approved for execution.

# Diagnostics: is the irradiance overshoot real, and is it a sample-size effect?

## The question

`FIX-1` records a generated-irradiance bias that is **not a constant**:

| record                      | measured   |
| :-------------------------- | :--------- |
| Paris 2011–2012 (2 yr)      | **+14 %**  |
| Heraklion 2010–2020 (11 yr) | **+2–3 %** |

Three explanations fit that table equally well, and the repo cannot currently tell them
apart:

- **(a) Structural.** A real KDE boundary bias at the zero floor, plus compounding along
  the 24-step walk. Training-set size only modulates it.
- **(b) Small-sample.** The bias is an estimation artefact that decays as the pool grows,
  and the 11-year figure is the tail of it.
- **(c) Not there at all.** The +2–3 % is inside the noise of a single-point comparison, or
  an artefact of the reference it was measured against. A false positive.

This plan measures the bias as a **function of training-set size**, with enough
realisations and a wide enough record that (a), (b) and (c) separate. Everything lives in
`examples/diagnostics-overshoot/`. No library code is touched.

---

## Assessment of the brief, and four recommended changes

The brief is sound in shape — vary the training years, repeat, look at the spread. Four
things need changing before it can answer the question it asks, and one of them is the
reason the experiment would otherwise fail.

### 1. `n` is tunable, and the first run uses `n = 30` — with its limits stated up front

**Settled:** `N_REALISATIONS` is a `config.py` constant with a `--n` CLI override, so the
run can be repeated at a higher `n` once the first results are seen. First run: **n = 30**.

What n = 30 can and cannot resolve, so the first run is not over-read. With σ ≈ 12 %
(the day-to-day coefficient of variation of daily totals), the 95 % interval on the mean
deviation is roughly **±4.3 %**:

| effect to detect       | n = 30                                        |
| :--------------------- | :-------------------------------------------- |
| **+14 %** (Paris, k=2) | resolved clearly — 3× the interval half-width |
| **+2–3 %** (k = 19)    | **not resolvable** — inside the interval      |

So the first run answers *"does the bias blow up as the record thins, and how fast?"* —
which is the shape of the size curve, and the question `CHORE-1` actually asks. It does
**not** settle whether a residual 2–3 % survives at the full record; that needs n in the
hundreds and is the natural second run. The reported CIs will make which of the two is
being claimed obvious on their face.

At n = 30 the whole first run costs **well under two minutes**, so re-running at higher n
is cheap and needs no re-plumbing.

### 2. The bootstrap should resample **both** samples, not just the synthetic one

Agreed that Welch is not required for test (a), and agreed it is the appropriate mean
comparison in test (b). The correction needed is narrower than "use a different test": it
is **what the bootstrap resamples**.

Bootstrapping only the n synthetic deviations `d_i` holds the reference `R` fixed, so the
resulting interval carries only Monte-Carlo noise from the synthetic draws and implicitly
asserts `R` is exact. `R` is an estimate from finite observed data, and with the centre-day
reference of §3 it is estimated from **one value per year**:

| reference          | values behind `R`, k = 19 | k = 2 | SE of `R` at k = 2 (σ = 12 %) |
| :----------------- | ------------------------: | ----: | ----------------------------: |
| `pool_mean`        |                       589 |    62 |                        ~1.5 % |
| `centre_mean`      |                    **19** | **2** |                    **~8.5 %** |

At k = 2 the reference is the mean of two numbers. Treating it as a constant would report
an interval several times tighter than the truth, exactly in the regime where `FIX-1` says
the defect is worst — and the small-k end is what the first run exists to measure.

**Recommendation, keeping the stated formulation intact:** the test is still "bootstrap the
distribution of `d` and ask whether it is centred on zero". The change is that each
bootstrap iteration resamples the **n synthetic totals and the m observed values behind
`R`**, recomputing `d` from both. Same test, both sources of noise propagated.

Welch drops to a cheap parametric cross-check on (a) — reported, not relied on — and stays
as the mean comparison in (b), as proposed.

### 3. The reference is the **centre day**; the window-mean bias is quantified, not adopted

**Settled: the centre day is the correct target** — deviation is measured against the day
in question, not the ±15-day window mean, because the window mean carries a seasonal-trend
bias of plausibly 1–2 %, the same order as the effect.

Three references are computed, and all three are reported per configuration:

| reference          | what it is                                                                           | trade-off                                            |
| :----------------- | :------------------------------------------------------------------------------------ | :---------------------------------------------------- |
| `detrended_centre` | quadratic fit of daily total vs day-of-year across the window, evaluated at the centre | **primary** — same target as `centre_mean`, estimated from all 31k days, so far lower variance |
| `centre_mean`      | mean over that exact calendar date only, one value per year                            | unbiased, but m = k — very noisy at small k (see §2)  |
| `pool_mean`        | mean over the ±15-day, all-years pool — as originally briefed                          | lowest variance, seasonally biased; kept because it is what `FIX-1`'s existing numbers were measured against |

`detrended_centre` and `centre_mean` estimate the *same* quantity; the first is the
low-variance estimator of it. Where they agree, the trend correction is doing no work and
`centre_mean` can be read directly. Where they disagree at small k, the disagreement is
`centre_mean`'s variance, not a bias — and §2's two-sample bootstrap is what makes that
visible rather than hidden.

The gap between `pool_mean` and `detrended_centre` **is** the window-mean bias, measured
rather than assumed. That number is a deliverable in its own right: it says how much of
`FIX-1`'s existing +2–3 % is reference artefact.

### 4. First run is **21 March only**; the solstices are built in but not executed

**Settled.** 21 March is the equinox: the seasonal trend is near-linear there, so the
reference is at its least sensitive to the choice made in §3, and the primary measurement
is as clean as the calendar allows.

`config.py` carries the full day list, with the others commented out and ready:

| day        | status                     | why it is wanted later                                                                     |
| :--------- | :------------------------- | :------------------------------------------------------------------------------------------ |
| **21 Mar** | **first run**              | Equinox — least reference sensitivity. The primary test.                                     |
| 21 Jun     | harness ready, not run     | Solstice — the **worst** centre point for a symmetric window, so it bounds the §3 correction. |
| 21 Dec     | harness ready, not run     | Winter solstice: short day, most hours at the zero floor. Discriminates cause (a) boundary bias from (b) small sample — hypothesis (a) predicts the largest relative bias here. |
| 21 May     | harness ready, not run     | Reconciles against the figure already in `FIX-1`'s table.                                    |

Running these is a one-line config change, so the second run costs nothing but time.

> **Backlog item, not recorded yet:** *assess the reference error at the solstices*, where a
> centred window is at its most curved and the `pool_mean` / `detrended_centre` gap is
> widest. This is a real open question independent of `FIX-1`'s outcome. Offered as `#11`
> under the new ID scheme once this analysis reports — not written into `TODOs.md` mid-flight.

---

## Experimental design

### Factors

| factor              | levels                                                             |
| :------------------ | :----------------------------------------------------------------- |
| training-set size k | **full**, **full // 2**, **full // 5**, **2** — see note below      |
| year-subset draw    | 1 draw at full (only one exists); **5 random draws** at each smaller size |
| calendar day        | **21 Mar** (first run) — 21 Jun · 21 Dec · 21 May wired but disabled |
| realisations n      | **30**, tunable via `--n`                                           |
| attribute           | `poa_global` (irradiance only, as briefed)                          |
| `n_days` (window)   | 15 — the shipped default, held fixed                                |
| `bandwidth`         | 0.1 — the shipped default, held fixed (the sweep is already in `FIX-1`; not repeated) |

**On k.** PVGIS 5.3 (SARAH3) is expected to cover **2005–2023 = 19 years**; step 1 probes
the API rather than assuming it. Integer division as briefed then gives k ∈ {19, 9, 3}.

**k = 2 is added** because it reproduces the Paris configuration that measured +14 %. Without
it the design has no level in the regime where the defect is known to be severe, and a
flat curve over 3–19 years would be uninformative about what happens below 3.

**Years are drawn at random, not taken as the first k.** Taking 2005–2013 as "the half"
would confound sample size with climate period — dimming/brightening trends are real at
this magnitude. Five random draws per size give the **spread against which years were
included** that the brief asks for, and separate "how many years" from "which years".

**Common random numbers across sizes.** The same seed stream is used for draw *i* at every
size, so size-to-size comparisons are paired and much of the Monte-Carlo noise cancels.
Free variance reduction.

### Deviation metric

For realisation *i*, daily total `E_i = Σ_h x_{i,h} / 1000` in kWh/m²/day. Observed totals
`O_j`, j = 1…m, computed identically. Reference `R` is the mean of the observed values per
§3 (`detrended_centre` primary). Then

```
d_i = (E_i − R) / R
```

Reported per configuration, **for each of the three references**: `mean(d)`, `sd(d)`, and
the two-sample bootstrap 95 % CI on `mean(d)` (10 000 resamples, distribution-free — daily
totals are left-skewed in summer, so a normal interval is not assumed).

### Tests

**(a) Is the deviation distribution centred on zero?**

- **Two-sample bootstrap** — primary. Each of 10 000 iterations resamples the n synthetic
  totals *and* the m observed values behind `R`, recomputes `d`, and records `mean(d)`. The
  test is whether the resulting interval excludes zero. This is the briefed test with both
  noise sources propagated (§2).
- **Welch's t** on {E_i} vs {O_j} — parametric cross-check, reported alongside. If it
  disagrees materially with the bootstrap, the skew is doing the work and the bootstrap is
  believed.
- **Permutation test** on the difference of means, 10 000 shuffles.
- **Holm–Bonferroni** across the family actually run (4 sizes on the first run). The
  **primary pre-registered test is the full record at 21 Mar**; everything else is reported
  with effect size and CI, and significance is secondary. Leaning on CIs rather than
  p-values is what keeps hypothesis (c) honestly answerable at n = 30.
- **Achieved power**, computed from the measured σ, reported for every configuration — so
  an underpowered cell says so on its face rather than reading as "no effect".

**(b) Do the distributions match, not just the means?**

- Two-sample **Kolmogorov–Smirnov** and **Anderson–Darling** (the latter is far more
  sensitive in the tails, which is where a boundary defect would show).
- **Variance ratio** with a bootstrap CI. Under- or over-dispersion is a *separate* defect
  from mean bias and would point somewhere different; `FEAT-2` already predicts dispersion
  problems for a related reason.
- Summary table: mean, sd, skew, P10 / P50 / P90, both samples.
- **Q–Q plot** and overlaid ECDFs.

### Raw data written to disk, for independent checking

Every number the analysis rests on is written out, so the conclusion can be re-derived —
or contradicted — without re-running the simulation or trusting `step3`. Five tidy
long-format files under `results/raw/`, plus a README describing every column and unit.

| file                          | one row per                     | key columns                                                                                      |
| :---------------------------- | :------------------------------- | :------------------------------------------------------------------------------------------------ |
| `config_index.csv`            | configuration                    | `config_id`, `k`, `draw`, **`years`** (the actual year list, comma-separated), `month`, `day`, `seed`, `n` |
| `observed_daily_totals.csv`   | configuration × observed day     | `config_id`, `date`, `year`, `month`, `day`, `slot`, `total_kwh_m2`, `is_centre`, `days_from_centre` |
| `synthetic_daily_totals.csv`  | configuration × realisation      | `config_id`, `realisation`, `total_kwh_m2`, and `dev_*` against each of the three references       |
| `observed_hourly.csv`         | configuration × observed day × h | `config_id`, `date`, `hour`, `poa_global_w_m2`                                                     |
| `synthetic_hourly.csv`        | configuration × realisation × h  | `config_id`, `realisation`, `hour`, `poa_global_w_m2`                                              |
| `references.csv`              | configuration × reference        | `config_id`, `reference` (`pool_mean` / `centre_mean` / `detrended_centre`), `value_kwh_m2`, `m` (values behind it) |

**Units are explicit in the column names.** Hourly values are W/m² exactly as PVGIS
supplies them; daily totals are `sum(hourly) / 1000` in kWh/m²/day. That division is the
only arithmetic between the two files, so it is directly checkable.

**`is_centre` is what answers the immediate ask.** Filtering
`observed_daily_totals.csv` on `is_centre & (config_id == 'k19_d0_0321')` gives the
aggregated total for **every 21 March in the training record, one row per year**;
`synthetic_daily_totals.csv` for the same `config_id` gives all 30 synthetic 21 Marches.
Those two columns side by side are the whole experiment at its smallest.

**`years` in `config_index.csv` is the traceability column** — it records exactly which
years each random draw selected, so a suspicious result at some `k` can be traced to the
years behind it rather than re-guessed.

**Volume is trivial** at the first run's settings: ~9 400 observed daily rows, 480
synthetic, ~226 000 hourly rows across both — a few MB of CSV. No sampling or truncation is
applied; if a later run at high `n` makes the hourly dumps awkward, they move to parquet
rather than being thinned.

`step3_analyse.py` reads **only these files**, never in-memory state from `step2`. That is
deliberate: it means any check done by hand against the CSVs is a check against exactly
what the analysis saw.

#### Sanity checks the harness asserts on its own

Run automatically at the end of `step2`, printed as a pass/fail block, so a corrupted run
is caught before anything is concluded from it:

- `sum(observed_hourly) / 1000 == observed_daily_totals` to floating tolerance, and the
  same for the synthetic pair.
- Observed row counts: `is_centre` count == `k`; window count == `31 × k` (less any missing
  Feb 29, which cannot arise for a 21 March window but is checked generally).
- Every `year` in the observed rows appears in that config's `years` list, and no others —
  the direct test that year-subsetting did what it claimed.
- No negative irradiance in either sample, and no daily total above a clear-sky ceiling for
  the latitude and date.
- Synthetic row count == `n` per configuration.

### Free by-product: per-hour bias

The hourly means of every ensemble are recorded, so `FIX-1`'s compounding signature
(hour 6 +9 % → hour 12 +18 % → hour 18 +13 %) can be re-measured **at each sample size**.
If compounding is structural the profile shape survives at k = 19; if it is a small-sample
artefact it flattens. This costs nothing beyond writing a second CSV, and it bears directly
on cause (a) vs (b).

---

## Deliverables and the decision rule

Pre-registered, so the conclusion is not chosen after seeing the data. **The first run
(21 Mar, n = 30) decides the size question; two branches need a second run to settle**, and
the plan says so in advance rather than discovering it afterwards.

| outcome of the first run                                                    | what it means                  | path forward                                                                                                     |
| :--------------------------------------------------------------------------- | :------------------------------ | :----------------------------------------------------------------------------------------------------------------- |
| Bias falls steeply as k grows — large and clearly non-zero at k = 2, interval covering 0 by k = 19 | **(b) small-sample**            | `CHORE-1` becomes the fix: sample-size-aware window default, a minimum-pool guard, a documented warning. Boundary correction is downgraded. **Confirm at higher `n`** before acting, since n = 30 cannot exclude a residual 2–3 %. |
| Bias roughly flat in k and clearly non-zero throughout                       | **(a) structural**              | Enable 21 Dec and 21 Jun to split boundary bias from compounding: hypothesis (a)-boundary predicts the largest relative bias at 21 Dec, where most hours sit at the zero floor. The per-hour profile is the second discriminator. |
| Interval covers 0 at every k, including k = 2                                | **(c) or underpowered**         | At n = 30 this is **not** evidence of absence — it is the expected result if the true bias is ≤ 4 %. Re-run at n ≥ 500 before concluding anything. Only a tight interval around 0 at high `n` restates `FIX-1`. |
| `pool_mean` and `detrended_centre` disagree by an amount comparable to the bias | **reference artefact**          | Part of `FIX-1`'s existing +2–3 % is how it was measured. Restate those rows, then re-ask the question against the corrected reference. |
| Large bias at k = 2 that does **not** reproduce the Paris +14 %              | site- or period-specific        | The Paris figure is not purely a sample-size effect; something about that record differs. Widen to Paris before theorising. |

Two branches deliberately cannot fire on the first run: anything keyed to 21 Dec, and any
claim that the residual bias at full record is zero. Both are second-run questions, and
both are one config change away.

Whatever lands, the harness becomes the **calibration test** `FIX-1` asks for — the thing
that makes any future fix measurable and stops it silently regressing.

---

## Structure and cost

```
examples/diagnostics-overshoot/
├── PLAN.md              this file
├── README.md            what it is and how to run it (written on completion)
├── FINDINGS.md          the result, and which branch of the decision rule fired
├── config.py            sizes, days, n, seeds, paths — single source of truth
├── step1_fetch.py       probe PVGIS for the widest range, fetch, cache
├── step2_simulate.py    all configurations -> results/raw/*.csv, then self-checks them
├── step3_analyse.py     reads results/raw/ only -> results/summary_*.csv
├── step4_figures.py     spread-vs-years, ECDF/QQ, per-hour bias
├── .gitignore           ignores results/raw/ and figures/
├── results/
│   ├── raw/             the six tidy files above, plus README.md describing them
│   └── summary_*.csv    the small aggregate tables
└── figures/
```

Steps are separate scripts so the ~40-minute simulation is paid **once**: step 3 and step 4
re-run against the CSVs in seconds. Every script is import-safe and cell-friendly for an
interactive session.

**Reuses, does not duplicate:** `examples/tools/site_data.py` (sites, cache paths) and
`examples/tools/envelope.py` (`day_matrix`, `synthetic_ensemble`, chart style). Data is
fetched with `meteosynth.adapters.fetch_pvgis(irradiance="global")` — the library path,
one column, no component reconstruction needed.

**Cost.** First run: 16 year-subsets × 1 day = 16 configurations × 30 realisations
× ~53.5 ms ≈ **30 seconds of sampling**, plus generator fitting and a one-off ~1–2 minute
download — call it **under three minutes end to end**. Step 2 still times one configuration
and prints a measured ETA before committing, and writes incrementally so an interrupted run
is resumable; both matter once `--n` is raised or the other three days are enabled, where
the cost scales to tens of minutes.

**Reproducibility.** One master seed in `config.py`, per-configuration streams derived via
`np.random.SeedSequence`. Every raw draw is written to disk.

**Committed vs ignored.** `FINDINGS.md` and the small `results/summary_*.csv` tables are
committed — they are the evidence `FIX-1` will cite. `results/raw/` and `figures/` are
git-ignored, matching the repo's existing rule for `examples/output/`. Git-ignored means
*not in version control*, not *not written*: the raw files are always on disk after a run,
which is the point of them. Say the word if you would rather the first run's raw output be
committed too, as a fixed reference the second run can be diffed against.

**No new TODO ID.** This is `FIX-1` + `CHORE-1` work under their existing IDs; nothing here
needs one.

---

## Two risks worth naming now

1. **PVGIS may not serve 19 years in one request**, or may rate-limit. Step 1 probes and
   falls back to the widest range that succeeds, chunking by year if needed. If the record
   turns out narrower than ~15 years, the k levels shrink accordingly and the plan still
   runs — with less resolution on the large-k end, which is the end where the answer
   matters most. This would be reported, not papered over.
2. **σ may be larger than the 12 % assumed**, in which case n = 30 resolves even less than
   the ±4.3 % projected in §1. This is handled by reporting the CI as the primary output
   rather than a p-value, and by printing achieved power per configuration — an underpowered
   cell will say so on its face rather than being read as "no effect". The measured σ from
   the first run is also what sizes `n` for the second.

> **Both risks materialised.** Risk 1 did not bite — PVGIS served 2005–2023 in one request.
> Risk 2 did, and badly: the measured CV is **35 %**, roughly three times the 12 % assumed,
> which put the n = 30 MDE at ±17 % and made that pass uninformative. Recovering from it cost
> one re-run at n = 1000.

---

# Run 1 — what came back

**Executed 2026-07-28. Full detail, tables and caveats in [`FINDINGS.md`](FINDINGS.md);
this section is the short form so the plan stands alone.**

Heraklion 2005–2023 (19 years), 21 March, `poa_global`, n = 1000, 16 configurations,
8.3 min, all 12 self-checks passing.

**No overshoot, and no dependence on record length.** Against the pooled window the
generator is fitted to:

| k (years) | mean deviation | MDE @ 80 % |
| --------: | -------------: | ---------: |
| 19 | **+1.06 %** | 4.8 % |
| 9 | +0.05 % | 6.2 % |
| 3 | −0.16 % | 9.2 % |
| 2 | **−0.02 %** | 12.2 % |

Nothing survives Holm. The two-year level — built specifically to match the Paris
configuration — does not reproduce +14 %.

Four further results, each of which changes what the next run should do:

1. **The choice of reference moves the answer by more than the effect being chased** —
   up to 16.7 % at k = 2, and −3.6 % even on the full record. A clean-looking size trend
   against `centre_mean` (−4.5 % → −10.9 %) is that reference disintegrating, not the model.
2. **The real defect is a missing low tail**, not a mean shift: **~4× too few overcast days**
   (0.60 % vs 2.38 % below 1 kWh/m²), with P50 and P90 matching to ~1 %. A missing low tail
   raises a mean, so this is a plausible mechanism *for* `FIX-1` — and it predicts where the
   overshoot should appear.
3. **The apparent under-dispersion is mostly legitimate.** Within-window seasonal structure
   is 10.4 % of pool variance; removing it moves the sd ratio 0.915 → 0.967, and against
   21 March alone it is 1.037. **That 10.4 % is `CHORE-1`'s missing number.**
4. **No compounding along the walk** — the per-hour bias is flat (+3 % → −1 %) at every k,
   so `FIX-1`'s hour-6 → hour-12 ramp does not reproduce here.

**Two plan assumptions were wrong, and are now measured rather than assumed:** the equinox
is *not* the cleanest reference (21 June is, at −0.79 % against 21 March's −3.64 %), and
21 June is also the most statistically efficient day available (CV 10.1 % vs 35.2 %, giving
an MDE near 1.4 % at n = 1000).

**Two harness defects** were found and fixed mid-run — unsigned day offsets, and two
concurrent runs interleaving rows into one another's output. Both now fail loudly. Recorded
in `FINDINGS.md` because both produced plausible, wrong answers.

---

# Run 2 — planned, not started

Two independent strands. Either can go first; **A is cheap and sharpens run 1, B tests the
hypothesis that motivates the whole item.**

## A. The remaining three calendar days, Heraklion

**One line in `config.py`** — move the entries from `DAYS_BACKLOG` into `DAYS` — then
`step2 --n 1000`. About **25 minutes**, no code changes.

| day | why it earns its place |
| :--- | :--- |
| **21 Dec** | **The decisive test.** CV 39 %, the largest overcast share of the year. If the missing low tail is the mechanism, the mean bias should be *largest here*. If December comes out at ~0 % too, the low-tail deficit does not translate into a mean bias and `FIX-1` needs a different explanation. |
| **21 Jun** | **The sharpest measurement available** — CV 10.1 %, MDE ≈ 1.4 %, and the smallest reference gap (−0.79 %). This is the configuration that could detect a genuine 2–3 % bias, which 21 March could not. |
| **21 May** | Reconciles directly against `FIX-1`'s existing +3.2 % Heraklion figure, on the same date it was measured. |

Expected outcomes are worth writing down before running, so the result is not read
backwards: the low-tail mechanism predicts **Dec ≫ Mar ≈ May > Jun** in mean bias, roughly
ordered by overcast share. A flat result across all four would falsify it.

## B. Paris, at a record length it was never tested at

See the hypothesis below. This needs **two additions to the harness**, so it is the more
expensive strand:

1. **A site parameter.** `config.py` hard-codes Heraklion; `step1`/`step2` take it from
   `record_meta.json`. Making the site a config value is small, and `tools.site_data`
   already defines `PARIS`.
2. **A chained-year mode** — the significant one. `FIX-1`'s +14 % is an *annual total from
   `generate_series`*, not an ensemble of independent `gen_day` draws. Run 1 cannot speak to
   it at all, because chaining is exactly what run 1 does not exercise. Step 2 needs a mode
   that generates `n` full synthetic years and totals each, with the observed annual totals
   as the reference sample.

Note the cost changes shape: a synthetic year is 365 days, so n = 100 years ≈ 36 500
generated days ≈ 30 min per configuration. **n = 100 with 4 sizes and 3 draws is several
hours** — this one wants running overnight, or with `PERF-1` landed first.

Also fetch `poa_direct` alongside `poa_global`, since `FIX-1`'s Paris figure is the direct
component.

---

# The Paris hypothesis

> **Working hypothesis (recorded 2026-07-28): the original Paris +14 % is most likely a
> statistical artefact — a single measurement, on a two-year training record, with no
> repetition to establish its spread.**

This is now the leading explanation, and run 1 supplies quantitative support for it that did
not exist when `FIX-1` was written.

**What run 1 showed about two-year records.** At k = 2 the *mean* across five random
year-subsets is −0.02 %, but the individual draws range from **−5.6 % to +12.7 %**, with a
between-draw spread of 6.8 %. A single two-year record landing near +13 % is an ordinary
outcome, not a remarkable one — and that is on one calendar day, where the estimate is
noisiest.

**Why the original number has no error bar.** `FIX-1`'s Paris row is one synthetic year
against one observed 2011–2012 mean: a single realisation, against a reference estimated
from two years. Nothing in that design separates model bias from the sampling noise of
either side. It is a point estimate presented without the spread that would say whether it
is meaningful — which is the same defect the `centre_mean` reference showed in run 1, where
an artefact looked exactly like a clean trend.

**What would settle it.** Strand B above: Paris at k ∈ {19, 9, 3, 2} with several draws per
size, *including 2011–2012 as an explicitly named draw* so the original configuration is
reproduced exactly and then placed against the distribution of everything else. Two
outcomes, both informative:

- **2011–2012 sits inside the k = 2 spread** → the +14 % was a draw, not a defect, and
  `FIX-1`'s headline number should be retired in favour of the distribution.
- **2011–2012 sits outside it** → something about that record or that site is real, and the
  +14 % survives as evidence.

**Caveat worth keeping honest:** annual totals average over 365 days, so their year-to-year
CV is far smaller than a single day's 35 %. The two-year *training* sample is the part most
likely to carry the artefact, not the annual aggregation. That distinction is exactly what
strand B measures, and it is why strand B needs the chained-year mode rather than reusing
run 1's ensemble path.

---

# Picking this up on another workstation

Everything needed to resume is either committed or regenerable from a fixed seed. Nothing
is carried in a notebook or a shell session.

**Committed** — travels with the repo: `PLAN.md`, `FINDINGS.md`, `README.md`, `config.py`,
the four `step*.py`, and `results/summary_*.csv`.

**Not committed** — regenerate on the new machine:

```bash
# 1. the PVGIS record  (~2 min, network; ~6 MB into examples/data/, git-ignored)
uv run python examples/diagnostics-overshoot/step1_fetch.py

# 2. run 1, exactly as reported            (~8.3 min)
uv run python examples/diagnostics-overshoot/step2_simulate.py --n 1000 --draws 5

# 3. analysis and figures                  (~2 min, ~10 s)
uv run python examples/diagnostics-overshoot/step3_analyse.py
uv run python examples/diagnostics-overshoot/step4_figures.py
```

`results/raw/` is ~15 MB and `figures/` ~400 KB; both are git-ignored and both come back
from the commands above.

**The numbers should reproduce exactly.** `MASTER_SEED` is fixed in `config.py` and every
per-configuration stream derives from it via `np.random.SeedSequence`, so the year subsets,
the seeds and the draws are all determined. The one caveat is library versions: a change in
`numpy`'s generator or `scipy`'s `gaussian_kde` would shift the draws. The run reported here
used **pvlib 0.15.2** on Python ≥ 3.10; `uv.lock` pins the rest.

**If the numbers do not reproduce**, that is a finding rather than a nuisance — check
`results/raw/config_index.csv` first, since it records the exact `years` and `seed` behind
every configuration.

**Nothing is committed to `TODOs.md` yet.** `FIX-1` still reads as originally written. The
restatement it needs — mean overshoot → missing low tail — and `CHORE-1`'s 10.4 % number are
both waiting on a decision, not on more work. Two candidate new items are also parked and
unrecorded: the solstice reference-error question, and the Paris hypothesis above, either of
which would take **`#11`** under the ID scheme.
