# Cross-correlation between variables

**Suitability: ❌ Not suited now.** The answer is known in advance. Use it only to put a number on a stated limitation.

## In plain words

In real weather the variables move together: sunny hours tend to be warm hours. The
cross-correlation measures **how strongly two variables rise and fall together**, either
at the same hour or with a delay.

## How it is computed

- **Pearson** $\rho$: linear co-movement.
- **Spearman** $\rho_s$: the same, computed on ranks, so it captures any
  "one goes up, the other goes up" pattern, straight-line or not.

Compute these for each pair (irradiance–temperature, irradiance–wind, temperature–wind)
at lag 0 and at short lags. Compare the real value with the synthetic value. For pairs
involving irradiance, use daylight hours only.

Correlate **across days or realisations for the same hour**, not along the time axis of
one series. Both sides then mean "independent draws of the same date".

## What it catches

- Whether the joint behaviour of the variables is preserved.

## Comment for meteosynth

- meteosynth **generates each variable independently**. The ensemble files say so in
  their own metadata: *"within a realisation, a hot hour is not thereby a sunny one."*
  So the synthetic correlation will be about **zero**, whatever the real one is.
- The metric therefore tests a **known design choice**, not model quality. At most, give
  a one-table statement: "observed ρ = …, synthetic ≈ 0, as expected".
- It becomes useful again once a coupled multi-variable model exists. It will then be the
  metric that shows the fix works.

**See also:** {doc}`tail-dependence`.
