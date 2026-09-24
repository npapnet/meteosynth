# Cardinality: how many against how many

Every metric compares **some real data** with **some synthetic data**. Before asking
*which* metric to use, ask *how much* data sits on each side. We write that as **M:N**:

- **M** = the number of real (observed) years or replicates,
- **N** = the number of synthetic realisations.

Cardinality doesn't decide whether you *can* compute a metric. You almost always can.
It decides **whether the answer means anything**, and **where the uncertainty is**.

---

## The four cases

| Case | In words | Where the uncertainty is | What to do |
| :--- | :--- | :--- | :--- |
| **1:1** | one real year vs one synthetic year | on both sides, and you can't remove it | Only compare *structure* (ACF, spectrum). Distribution distances are meaningless here, because two real years differ from each other too |
| **1:N** | one real year vs many synthetic years | on the real side: that one year's weather | Well powered, but aimed at the wrong target. A difference could be model error, or just an unusual year |
| **M:N** | all real years vs many synthetic years | almost entirely on the real side | **The normal case.** Use the control band from {doc}`index` |
| **M:1** | all real years vs one synthetic year | on the single synthetic draw | Change the question. Don't ask "how far apart are they?", ask "does this year fall *inside* the real ones?", using a {doc}`rank-histogram` |

Two points that go against intuition:

- **1:1 is best for time-structure metrics.** Autocorrelation and the power spectrum
  describe *one trajectory*, so comparing one year with one year is fair. It's the
  distribution metrics that fall apart at 1:1.
- **M:1 needs a different tool, not a looser threshold.**

### Which metric works in which case

| Metric | 1:1 | 1:N | M:N | M:1 |
| :--- | :---: | :---: | :---: | :---: |
| Wasserstein, KS, quantile traces | ⚠️ | ⚠️ | ✅ | ❌ |
| Autocorrelation, power spectrum | ✅ | ✅ | ✅ | ✅ |
| Annual dispersion | ❌ | ❌ | ✅ | ❌ |
| Cross-correlation | ⚠️ | ⚠️ | ✅ | ⚠️ |
| Tail dependence | ❌ | ❌ | ⚠️ | ❌ |
| Rank histogram | ❌ | ❌ | ⚠️ | ✅ |

---

## A bigger N doesn't fix everything

N is cheap in meteosynth. The model for each day is fitted once and shared by every
realisation, so 1 000 realisations cost little more than 100. With N in the hundreds
or thousands, the synthetic side of any metric is **effectively exact**.

That moves all the remaining uncertainty to the **real** side, and only more real years
can reduce it. Three quantities each help with something different:

| Increase… | Helps with | Does not help with |
| :--- | :--- | :--- |
| **N** (synthetic realisations) | precision on the synthetic side | anything on the real side |
| **T** (length of each series) | the longest lag or slowest cycle you can see | per-hour distributions |
| **M** (real years) | every control band, every tail estimate | anything about the generator |

So if a reviewer asks "why 1 000 realisations?", the answer is: so that the error bars
belong to the weather record, not to the generator.

---

## Folding: borrowing data to get enough of it

Twenty real years give only twenty values for "12:00 on 21 June". That isn't enough to
draw a histogram. So you **fold**: you pool data along some axis until you have
enough. Every fold buys sample size by making an assumption.

| Fold | Real side | Synthetic side | The assumption you're making |
| :--- | :--- | :--- | :--- |
| **Across years ↔ realisations** | pool the years | pool the realisations | the climate didn't change over the record (it did, a little, for temperature). **The safe default** |
| **Calendar window (±W days)** | pool neighbouring days | already built in: the model was *fitted* to this pool | 6 June and 6 July belong with 21 June. This makes the test about *fidelity to the training data*, not the exact date |
| **Hour of day** | pool all 24 hours | pool all 24 hours | the time of day doesn't matter. This **hides every diurnal error**, so never report it alone |
| **Along time** | — | — | never. For ACF and spectrum, time *is* what you're measuring |

**Rule of thumb:** fold both sides the same way, and always say which fold you used.
A number quoted without its fold can't be interpreted.

---

## Product scale: how long is each series?

Some metrics also need a long enough series (T). meteosynth can produce four
"products":

| Product | What | T | Good for |
| :--- | :--- | ---: | :--- |
| **D** | one day | 24 h | distributions per hour; ACF up to ~12 h |
| **M** | one month | 744 h | adds multi-day persistence (2–10 day weather systems) |
| **Y** | one year | 8 760 h | everything within a year; tail estimates become possible |
| **KY** | several years chained | K × 8 760 h | the annual cycle with more than one sample |

meteosynth has **no memory from one year to the next**: each year is drawn fresh from
the same climate. So nothing slower than one cycle per year can be found, whatever
product you use.

For the questions an energy study asks, **Y at M:N** (all real years against many
synthetic years) is the comparison to aim for.
