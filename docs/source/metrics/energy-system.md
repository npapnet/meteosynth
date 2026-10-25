# Energy-system metrics

**Suitability: ❌ Out of scope for meteosynth itself.** Each of these needs an energy model (a power-system dispatch model, a load profile, a building simulator) that the package doesn't include.

These metrics answer the question the synthetic weather is ultimately for: **does it lead
to the same engineering decisions as real weather?** They are listed here because the
literature expects them, and so you can see where they would plug in.

---

## Loss of Load Expectation (LOLE)

**In plain words:** the expected number of hours per year when the available power is
not enough to meet demand.

$$\text{LOLE} = \sum_{t=1}^{T} \mathbb{P}(C_t < L_t) \quad [\text{h/year}]$$

$C_t$ is the available capacity and $L_t$ the load at hour $t$. Loss of Load Hours
(LOLH) is the same idea counted in hours.

**Comment:** synthetic weather that smooths out variability or misses multi-day calms
gives LOLE values that are **too optimistic**. The {doc}`spell-lengths` and
{doc}`autocorrelation` tests are the upstream checks that predict this.

## Expected Energy Not Served (EENS)

**In plain words:** not *how often* the power falls short, but *how much* energy is
missing in total.

$$\text{EENS} = \sum_{t=1}^{T} \mathbb{E}\left[\max(0, L_t - C_t)\right] \quad [\text{MWh/year}]$$

**Comment:** same sensitivity as LOLE, and more affected by the depth of shortfalls.

## Storage sizing and net-load deficit

**In plain words:** how big a battery or hydrogen store must be to get through the worst
stretch of low wind and sun.

$$\text{NLD}(\tau) = \int_{t_0}^{t_0+\tau} \Big( L_t - \big[P_{\text{solar}}(t) + P_{\text{wind}}(t)\big] \Big)\, dt$$

**Comment:** very sensitive to long spells, and also to **joint** wind–sun lulls, which
meteosynth doesn't currently model (see {doc}`tail-dependence`). Breaks at the joins
between synthetic days would also cause false charge/discharge cycles (see
{doc}`midnight-seam`). Expect synthetic storage requirements to be **underestimated**
until those gaps are closed.

## Building thermal loads

**In plain words:** feed synthetic temperature and sunshine into a building simulator
(for example EnergyPlus) and compare peak heating/cooling loads and annual energy use
with the results from real weather.

**Comment:** peak cooling depends on hot **and** sunny hours happening together, which
meteosynth doesn't reproduce, because the variables are generated independently. Annual
totals are a fairer test than peaks for now.

---

**Bottom line:** run these in a downstream study, once the fidelity metrics in this
section have passed. Read any result alongside the known limitations: no cross-variable
coupling and no year-to-year memory.
