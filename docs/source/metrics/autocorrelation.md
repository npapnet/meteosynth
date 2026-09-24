# Autocorrelation (ACF)

**Suitability: ✅ Recommended.** This is the most direct test of how the generator works.

## In plain words

If it is windy now, how likely is it to be windy in 1 hour? In 6 hours? In 3 days? The
autocorrelation measures that **memory**. It starts at 1 for lag 0 and usually falls
towards 0 as the lag grows. The speed of the fall tells you how long weather situations
last.

## How it is computed

$$\rho(k) = \frac{\mathbb{E}\left[(X_t - \mu)(X_{t+k} - \mu)\right]}{\sigma^2}$$

$X_t$ is the value at hour $t$, $k$ is the lag in hours, and $\mu$ and $\sigma^2$ are the
mean and variance.

**First subtract the climatology.** Take away the typical value for that hour of day
(and, for irradiance and temperature, that day of year) and compute ρ on what's left:
the *anomaly*. Use the **real** climatology on both sides so that both get the same
subtraction. Without this step, the ACF mostly measures the daily sun cycle rather than
weather memory.

Compute ρ within each series and then average over years or realisations. Never glue
independent realisations end to end: every join would add a fake break.

## What it catches

- Weather systems that fade away too quickly or too slowly.
- For storage studies, whether multi-day lulls have the right length.

## What it misses

- The distribution of values. See {doc}`wasserstein`.

## Comment for meteosynth

- The generator is a **first-order** chain: it models only how each hour follows the one
  before. So **lag 1 is right by construction**, and everything longer has to *emerge*.
  The useful range is **lags 6–48 h**, and for storage-related questions up to about
  10 days (240 h).
- **Expected failure:** memory that fades faster than in reality beyond about a day. If
  you find it, report it as a scope limit ("fine for yearly yield, weaker for storage
  sizing") rather than hiding it.
- Needs a long enough series: a single day (product D) supports lags up to about 12 h
  only. Use a month or year product for anything longer (see {doc}`cardinality`).
- Works at every cardinality, including 1:1.

**See also:** {doc}`power-spectrum`, {doc}`spell-lengths`, {doc}`annual-dispersion`.
