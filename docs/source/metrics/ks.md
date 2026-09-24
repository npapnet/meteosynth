# Kolmogorov–Smirnov distance (KS D)

**Suitability: ⚠️ Use with care.** Use the distance D, never the p-value. Prefer {doc}`wasserstein`.

## In plain words

Draw the two cumulative curves: the fraction of real values below *x*, and the fraction
of synthetic values below *x*. **D is the largest vertical gap between them.** It's a
worst-case measure: it tells you where the two distributions disagree the most.

## How it is computed

$$D_{n,m} = \sup_x \left| F_n(x) - G_m(x) \right|$$

$F_n$ is the real cumulative distribution (from $n$ values) and $G_m$ is the synthetic
one (from $m$ values). D is between 0 (identical) and 1 (no overlap).
(`scipy.stats.ks_2samp`.)

## What it catches

- Any difference in shape or position between the distributions.

## What it misses

- **How much** of the distribution is wrong. D reports only the single worst point. It is
  also weakest in the tails, where the cumulative curves are close to 0 or 1.
- It has no units, so "D = 0.06" tells a reader nothing on its own.

## Comment for meteosynth

- **Don't use the p-value.** With thousands of synthetic values, *any* tiny difference
  becomes "significant". The p-value measures how big N is, not how good the model is.
- D depends on the sample size, so an hour-by-hour D and a D pooled over all hours
  **aren't on the same scale**. Never average them together.
- If you report it, report D next to its control band, and only as a companion to W₁.

**See also:** {doc}`wasserstein`, {doc}`cardinality`.
