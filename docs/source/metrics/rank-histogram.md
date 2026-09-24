# Rank (PIT) histogram

**Suitability: ⚠️ Only for one synthetic series against many real years (M:1).** With many realisations (M:N), use {doc}`wasserstein` and {doc}`annual-dispersion` instead.

## In plain words

Take one hour. Line up the M real values for that hour, smallest to largest. There are
M + 1 gaps: below the smallest, between each pair, above the largest. See **which gap
your single synthetic value lands in**. Do this for every hour of the year and count.
If the generator is honest, the synthetic value lands in each gap about equally often
and the histogram is **flat**.

## How it is computed

For each hour $t$, the rank is the number of real values below the synthetic one:

$$r_t = \#\{\, j : x^{\text{obs}}_{j,t} < x^{\text{syn}}_t \,\}, \qquad r_t \in \{0, \dots, M\}$$

Build a histogram of $r_t$ over all hours and test it for flatness with a χ² test.

## How to read the shape

| Shape | Meaning |
| :--- | :--- |
| flat | well calibrated |
| ∪ (U-shaped) | synthetic spread **too narrow**: it often lands outside the real range |
| ∩ (hump) | synthetic spread **too wide** |
| sloped | synthetic values biased high or low |

## Comment for meteosynth

- This is the right tool when you have **one** chained synthetic year (for example from
  `generate_series`) and want to know whether it sits inside the real record. Distance
  metrics don't work there, because one side has only one sample.
- Needs M ≳ 10 real years, so that there are enough gaps.
- With an ensemble of hundreds or thousands of realisations, it works but other metrics
  are better powered.
- Build it per hour. Never pool over hours of the day.

**See also:** {doc}`cardinality`.
