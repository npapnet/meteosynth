# Validating synthetic data

meteosynth gives you many synthetic weather years. This section is about the next
question: **how do you tell whether they are any good?**

There is a long list of metrics people use to judge synthetic weather. Some fit what
this package produces. Some only fit under particular conditions. Some can't be
measured here at all. Each page below covers one metric: what it is, in plain words,
and a short comment on how well it fits meteosynth.

Before you go through the metrics, read {doc}`cardinality`. Most mistakes happen there.

---

## Two kinds of question

```{mermaid}
flowchart LR
    S["synthetic years"] --> A["Statistical & physical fidelity<br/>does it look like the real weather?"]
    S --> B["Energy-system utility<br/>does it give the same engineering answers?"]
    A --> A1["distributions"]
    A --> A2["persistence over time"]
    A --> A3["links between variables"]
    B --> B1["reliability, storage,<br/>building loads"]
```

- **Fidelity** metrics compare the synthetic series with the real record directly.
  These are the ones this section focuses on.
- **Utility** metrics feed the series into an energy model and compare the results.
  These need a model that meteosynth doesn't have. They are listed on one page,
  {doc}`energy-system`, so you know where they fit.

---

## A number on its own means nothing

Suppose a metric says the synthetic and real wind distributions are **0.4 m/s apart**.
Is that good?

You can't tell until you know how far apart **two real samples** of the same climate
are. So every metric gets a **control band**:

1. Split the real years at random into two halves.
2. Compute the metric between half A and half B.
3. Repeat many times. The range of results (5th–95th percentile) is the natural amount
   of "disagreement" between real weather and real weather.

Then use one rule, fixed **before** you look at any result:

> A metric **passes** when its value is at or below the 95th percentile of the control
> band on at least 90 % of the cells (hours, months, lags…) it is computed on.

Fixing the rule in advance means nobody can move the threshold after seeing the result.

---

## Summary

| Metric | What it checks | Suited to meteosynth? |
| :--- | :--- | :--- |
| {doc}`wasserstein` | Is the distribution of values right? | ✅ Recommended |
| {doc}`ks` | Is the distribution of values right? | ⚠️ Use with care |
| {doc}`quantile-traces` | Level, spread and extremes, hour by hour | ✅ Recommended |
| {doc}`autocorrelation` | How long does the weather "remember"? | ✅ Recommended |
| {doc}`power-spectrum` | Slow swings vs fast jitter | ⚠️ Limited — prefer ACF |
| {doc}`annual-dispersion` | Do synthetic years differ from each other as much as real ones? | ✅ Recommended — the headline test |
| {doc}`midnight-seam` | Are the days joined together cleanly? | ✅ Recommended (not for irradiance) |
| {doc}`spell-lengths` | How long do calm / dull / hot spells last? | ✅ Recommended |
| {doc}`cross-correlation` | Do variables move together? | ❌ Not suited now |
| {doc}`tail-dependence` | Do extremes happen together? | ❌ Not suited now |
| {doc}`rank-histogram` | Does one synthetic year fit inside the real ones? | ⚠️ Only for one synthetic year (M:1) |
| {doc}`energy-system` | LOLE, EENS, storage and building loads | ❌ Out of scope |

**Short version:** a first study only needs Wasserstein distance (or quantile traces),
the autocorrelation and the annual dispersion test. The spell-length and midnight-seam
checks are cheap to add on top.

```{toctree}
:maxdepth: 1
:caption: Choosing a comparison

cardinality
```

```{toctree}
:maxdepth: 1
:caption: Distributions

wasserstein
ks
quantile-traces
```

```{toctree}
:maxdepth: 1
:caption: Time structure

autocorrelation
power-spectrum
annual-dispersion
midnight-seam
spell-lengths
```

```{toctree}
:maxdepth: 1
:caption: Several variables

cross-correlation
tail-dependence
```

```{toctree}
:maxdepth: 1
:caption: Special cases

rank-histogram
energy-system
```
