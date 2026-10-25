# Wasserstein distance (W₁)

**Suitability: ✅ Recommended.** This is the main single number for "are the values right?".

## In plain words

Picture the real histogram and the synthetic histogram as two piles of sand. The
Wasserstein distance is **how far you would have to shovel the sand, on average, to
turn one pile into the other**. If the piles are identical the answer is zero. If the
synthetic pile is the real one moved 1 m/s to the right, the answer is exactly 1 m/s.

## How it is computed

$$\mathcal{W}_1(P,Q) = \int_{-\infty}^{\infty} \left| F_P(x) - F_Q(x) \right| \, dx$$

$F_P$ and $F_Q$ are the cumulative distributions of the real and synthetic values: the
fraction of values below $x$. The distance is the area between the two curves.
(`scipy.stats.wasserstein_distance`.)

To compare variables, divide by the standard deviation of the real data: **W₁/σ**.

## What it catches

- Shifts in level, spread that is too wide or too narrow, and skew.
- Errors in the tails. Because it adds up the area between the curves, it responds to
  differences in the extremes more than KS does.

## What it misses

- Anything about **order in time**. If you shuffle the hours, W₁ doesn't change. Pair it
  with {doc}`autocorrelation`.

## Comment for meteosynth

- The result comes out in **physical units** (W/m², °C, m/s), so a reader can judge it
  without a lookup table. It is also fairly stable when sample sizes differ. That's why
  it is preferred over {doc}`ks`.
- Compute it **per hour** (and per month for a year product), not pooled over the day.
  Pooling over hours hides diurnal errors (see {doc}`cardinality`).
- **Night hours for irradiance** are zero on both sides. W₁ = 0 there is automatic, and
  σ = 0 makes W₁/σ undefined, so leave them out of any average.
- Judge it against the control band (see {doc}`index`). Report the median and 90th
  percentile of W₁/σ across (month, hour) cells.

**See also:** {doc}`quantile-traces` (the same information as a figure), {doc}`ks`.
