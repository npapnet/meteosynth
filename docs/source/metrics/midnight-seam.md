# Midnight seam

**Suitability: ✅ Recommended** for wind and temperature. **Skip for irradiance.**

## In plain words

meteosynth builds each day separately and then **stitches** the days together at
midnight with a separate model. This test looks at the stitch: is the jump from 23:00
one day to 00:00 the next as large as in real data, no larger and no smaller?

## How it is computed

For every pair of consecutive days:

$$\Delta = X_{0,\text{today}} - X_{23,\text{yesterday}}$$

Compare the distribution of Δ between real and synthetic data, for example with
{doc}`wasserstein` or by overlaying the two histograms.

## What it catches

- A bad join between days: steps that are too big, or phase jumps. In an energy model
  these look like false battery charge/discharge cycles.
- It is the **only** metric that tests the cross-midnight model on its own.

## What it misses

- Everything inside the day.

## Comment for meteosynth

- **Irradiance:** 23:00 and 00:00 are both dark all year, so Δ = 0 on both sides and the
  test passes trivially. If the join matters for irradiance, check **the sunrise ramp**
  instead: does it start at the right hour and rise at the right speed?
- **Temperature:** the most informative variable here. Overnight temperature changes
  slowly, so a bad join would show as a clear step.
- Needs series of at least two days (product M or Y).

**See also:** {doc}`autocorrelation`.
