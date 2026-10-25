# Hourly quantile traces

**Suitability: ✅ Recommended.** This is the best *figure* for distributions: one plot shows level, spread, extremes and boundaries.

## In plain words

For each hour of the day, sort the values and read off a few percentiles: the 1 %, 5 %,
25 %, median, 75 %, 95 % and 99 % points. Join them across the 24 hours and you get
seven lines. Draw them for the real data and for the synthetic data on the same axes.
If the lines overlap, the model has the right typical value, the right spread and the
right extremes **at every hour of the day**.

## How it is computed

For each hour $h$ and percentile $p \in \{0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99\}$:

$$q_p(h) = F_h^{-1}(p)$$

$F_h$ is the distribution of values at hour $h$, taken over all days of a chosen month
and over all years (real side) or all realisations (synthetic side). Use two contrasting
months, for example January and July.

## What it catches

- Wrong level or spread at particular hours.
- **Boundary problems**: mass pushed below zero wind, or an unrealistic pile-up of values
  right at the limit.

## What it misses

- Anything about how hours follow each other. See {doc}`autocorrelation`.

## Comment for meteosynth

- The model uses a symmetric kernel on quantities that have hard limits. Look closely at
  the **1 % and 5 % lines at the calmest hours for wind**. The record has hundreds of
  exact zeros, and this is where kernel smoothing shows itself.
- **Irradiance:** half the hours are night, and there the lines are flat at zero and
  carry no information. Mask them out. Also check a **clear-sky ceiling**: the fraction of
  synthetic values above the highest real value for that date-slot and hour. 900 W/m² at
  07:00 in December is inside the global limits but physically impossible.
- **Temperature:** no active boundary, so only the traces themselves matter.
- Use {doc}`wasserstein` (W₁/σ per cell) as the single number that goes with this figure.

**See also:** {doc}`wasserstein`.
