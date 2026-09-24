# Annual dispersion and the variance cascade

**Suitability: ✅ Recommended — the headline test.** meteosynth's whole product is *many plausible years*. This test checks whether those years differ from each other the way real years do.

## In plain words

Energy studies ask things like "what is the P90 yield?", meaning the yield you beat in
9 years out of 10. That depends entirely on **how much one year differs from another**.
If synthetic years are too alike, P90 looks too optimistic. If they differ too much, it
looks too pessimistic.

The test has three parts:

1. **Annual means.** Plot the distribution (ECDF) of the annual mean for the N synthetic
   years and mark the M real years as dots. P50 and P90 can be read straight off the
   plot.
2. **The variance cascade.** Average the series over blocks of 1, 3, 7, 30, 90 and
   365 days. For each block length, divide the synthetic variance by the real variance
   and plot the ratio against block length.
3. **The consistency band.** With only M real years, the real spread is itself
   uncertain. A ratio inside the band is *consistent* with reality.

## How it is computed

For block length $L$ days, $\bar X_L$ is the mean over a block and

$$r(L) = \frac{\operatorname{Var}_{\text{syn}}(\bar X_L)}{\operatorname{Var}_{\text{obs}}(\bar X_L)}$$

The band comes from the χ² distribution of a sample variance with $M-1$ degrees of
freedom. For the spread ratio (standard-deviation ratio) it is about **0.79–1.38 at
M = 19**, and about 0.74–1.59 at M = 11. That difference is a good reason to use the
full record.

## What it catches

- Too little or too much year-to-year spread, **and why**. A ratio above 1 at short
  blocks that falls below 1 at long blocks means day-to-day variation is too strong while
  the year-scale component is missing.

## What it misses

- The shape of the distribution within a year. See {doc}`quantile-traces`.

## Comment for meteosynth

- **Expect the ratio to fall at long blocks.** meteosynth has **no year-to-year memory**:
  a windy year in reality tends to be windy in every month, but synthetic years can't do
  that. The test tells you how much this matters for annual figures.
- **Cross-check with the ACF.** A generator with no memory between blocks predicts an
  annual variance of roughly $\sigma^2_{\text{day}}\,\tau / 365$, where $\tau$ is the
  decorrelation time from {doc}`autocorrelation`. If the prediction matches, you have
  explained the result, not just measured it.
- **Irradiance and temperature:** subtract the seasonal cycle (a day-of-year
  climatology) before blocking. Otherwise "January isn't July" swamps the 30–90 day
  blocks. **Temperature** also has a warming trend across the record, which widens the
  real spread. Detrend, or report the trend alongside.
- Needs the year product at M:N.

**See also:** {doc}`autocorrelation`, {doc}`cardinality`.
