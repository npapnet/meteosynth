# Tail dependence (λ_L, λ_U)

**Suitability: ❌ Not suited now.** The answer is known in advance, and at short scales there is too little real data.

## In plain words

*On the worst 5 % of days for wind, how often is it also among the worst 5 % for sun?*
If the answer is "about as often as chance", the two variables are independent in their
extremes. Energy planners care because windless *and* sunless periods
(**Dunkelflaute**) are what empty a storage system.

## How it is computed

$$\lambda_L = \lim_{u \to 0^+} \mathbb{P}(U_1 \le u \mid U_2 \le u)$$

$U_1, U_2$ are the two variables converted to ranks between 0 and 1. $\lambda_U$ is the
same for the upper extremes. In practice you can't take the limit, so report the curve
$\hat\lambda(u)$ for $u$ from about 0.02 to 0.20, with a bootstrap band. Draw the line
$\hat\lambda(u) = u$ for comparison: that is what independent variables would give.

Use **daily** values (daily mean wind, daily irradiance total), because a Dunkelflaute is
an event lasting a day or more.

## What it catches

- Whether joint extremes happen as often as in reality.

## Comment for meteosynth

- Variables are generated independently (see {doc}`cross-correlation`), so the synthetic
  curve **will lie on the independence line**. The gap between the real curve and that
  line is the size of a capability the package doesn't have yet.
- **Too little real data at short scales.** A stable estimate needs about 30 joint
  exceedances. One day with a ±15-day window over 11 years gives about 17. A full year
  gives about 200. Adding more realisations doesn't help, because the shortage is on the
  real side. If you quote it at all, quote it from a year-long product.
- It needs copulas explained to the reader, which is a lot of space for a foregone
  conclusion. Keep it for a future paper that models the variables jointly.

**See also:** {doc}`cross-correlation`, {doc}`spell-lengths`, {doc}`cardinality`.
