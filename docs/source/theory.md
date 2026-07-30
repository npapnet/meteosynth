# Theory

This page explains how `meteosynth` turns a historical record into a generator
of statistically-plausible synthetic series.

```{note}
If terms like *ensemble*, *realisation*, *conditional distribution* or *P90* are new,
read {doc}`concepts` first — it defines the vocabulary this page uses, in plain language.
```

## The problem

Energy-project Monte-Carlo studies need *many* weather realisations, not one.
A single Typical Meteorological Year hides the year-to-year and hour-to-hour
variability that drives the tails of production and demand. `meteosynth`
instead learns the **transition statistics** of a variable and samples fresh
trajectories that reproduce those statistics.

## The process end to end

Before the mathematics, the shape of the whole thing. Everything below elaborates one of
these five steps.

**1. Pick the training data for one calendar day.** To model 21 May, take every day within
±*n* days of 21 May — pooled across *all* years of the record. Eleven years at `n_days=15`
gives 341 days. This is a *climatological* window: it answers "what is this time of year
like here", not "what happened in one particular May".

**2. Cut that window into hourly transition pairs.** For each hour separately, collect every
`(value at h−1, value at h)` observation the window contains. The 13:00→14:00 pairs are a
different dataset from the 14:00→15:00 pairs, and each gets its own model. This is what
makes the model *time-inhomogeneous within the day*: mid-afternoon behaves differently from
dawn, and nothing forces them to share statistics.

**3. Fit 25 models for that day, per attribute.**

| how many | what it models | used when |
| ---: | :--- | :--- |
| 23 | the within-day transitions, h−1 → h for h = 1…23 | every hour of every day |
| 1 | **π(x₀)**, the distribution of the 00:00 value alone | the day *starts* a series |
| 1 | the **cross-midnight** transition, 23:00 yesterday → 00:00 today | the day *continues* a series |

Hour 0 needs two of its own because it has no predecessor *within* its day — either a series
begins there (draw from π(x₀)) or it continues from yesterday (draw from the cross-midnight
model). The other 23 hours have an obvious predecessor and need only one model each.

Each attribute — irradiance, temperature, wind — gets its own independent set of 25. They
are never modelled jointly.

**4. Walk the day, hour by hour.** Holding a current value $v$ for hour $h-1$, take hour
$h$'s model, **slice** its joint density at $x_{t} = v$, renormalise the slice into a proper
conditional distribution, and draw one value from it. That drawn value becomes the input for
hour $h+1$. Twenty-four values later you have a day.

**5. Cross into the next day and repeat.** The 23:00 value feeds the *next* calendar day's
cross-midnight model, which produces its 00:00 value — and the next day uses **its own**
window's models, fitted to data centred on *its* date. So the statistics drift smoothly
through the season as the walk proceeds.

```{mermaid}
flowchart TD
    R["historical record<br/>(all years)"] -->|"±n days around 21 May,<br/>pooled across years"| W["training window<br/>e.g. 341 days"]
    W -->|"pairs, per hour"| P["23 sets of (previous, current)<br/>+ midnight values<br/>+ consecutive-date pairs"]
    P -->|"fit a 2D KDE to each"| M["25 models for 21 May<br/>(per attribute)"]
    M --> S["slice hour h's density<br/>at the current value v"]
    S --> C["conditional distribution<br/>p(x&#8341; | x&#8341;&#8331;&#8321; = v)"]
    C --> D["draw one value"]
    D -->|"becomes the input for hour h+1"| S
    D -->|"after 23:00, hand to<br/>22 May's cross-midnight model"| M2["25 models for 22 May"]
```

```{note}
Fitting is per **calendar day** and per **attribute**, so a chained year over three
attributes fits 365 × 3 × 25 models. That cost is why
{meth}`~meteosynth.generators.DayWindowGenerator.generate_ensemble` walks the calendar once
and lets every realisation share each day's fit, rather than repeating the walk per
realisation.
```

## First-order Markov assumption

We model a meteorological variable $X_t$ as a first-order Markov process: the
distribution of the next value depends only on the current value.

$$
P(X_{t+1} \mid X_t, X_{t-1}, \dots, X_0) = P(X_{t+1} \mid X_t)
$$

So everything reduces to learning the **conditional distribution**
$p(x_{t+1}\mid x_t)$ from data, then repeatedly sampling from it.

```{mermaid}
flowchart LR
    X0["X&#8320;"] -->|"p(x&#8321;|x&#8320;)"| X1["X&#8321;"]
    X1 -->|"p(x&#8322;|x&#8321;)"| X2["X&#8322;"]
    X2 -->|"p(x&#8323;|x&#8322;)"| X3["X&#8323;"]
    X3 --> D["&#8230;"]
```

## From samples to a joint density (2D KDE)

The training data is a set of `(previous, current)` pairs — each observed value
paired with the value that followed it. `MarkovChainSimulator2dKDE` fits a **2D
Gaussian kernel density estimate** to these pairs to approximate the joint
density $\hat p(x_t, x_{t+1})$:

$$
\hat p(x_t, x_{t+1}) = \frac{1}{n}\sum_{i=1}^{n}
    K_H\!\big((x_t, x_{t+1}) - (x_t^{(i)}, x_{t+1}^{(i)})\big)
$$

where $K_H$ is a Gaussian kernel whose bandwidth $H$ is either supplied
explicitly or chosen by Scott's rule.

## Conditioning and sampling

To transition from a known current value $x_t = v$, we take a **slice** through
the joint density at $x_t = v$ and renormalise it into a proper conditional
density:

$$
p(x_{t+1} \mid x_t = v) = \frac{\hat p(v, x_{t+1})}{\int \hat p(v, x)\,dx}
$$

We then draw from it by **inverse-transform sampling**: build the cumulative
distribution $F$, draw $u \sim \mathcal{U}(0,1)$, and return $F^{-1}(u)$ by
interpolation.

```{mermaid}
flowchart TD
    A["get_next_state(v)"] --> B["slice joint KDE at x&#8348; = v"]
    B --> C["normalise &#8594; conditional pdf"]
    C --> D["cumulative sum &#8594; cdf"]
    D --> E["draw u ~ U(0,1)"]
    E --> F["x&#8348;&#8330;&#8321; = interp(u, cdf, domain)"]
```

```{note}
The evaluation domain spans the observed data range, intersected with the
variable's declared physical **support** — and is not padded. An earlier version
padded the range by 10%, which could push sampled irradiance or wind speed
**below zero**. Since `np.interp` cannot return a value outside the domain it is
given, clamping the domain makes an out-of-support sample impossible rather than
merely rare.
```

The conditioning value is itself clamped into the range the model was fitted
over. Far enough outside it every kernel evaluates to ~0, the joint density sums
to zero, and the normalisation is $0/0$ — which would poison the *next* hour with
a NaN. Extrapolating a KDE beyond its data is not meaningful anyway, so the
nearest fitted value is both the safest and the most faithful answer.

### The cost of a draw, and the cached quantile grid

Evaluating a 1000-point KDE slice per sample dominates generation — about 97% of
runtime. Once a simulator has been asked for enough samples to pay for it (64),
it replaces that evaluation with a **precomputed table of conditional quantile
functions** on a 64-node grid of `previous` values. A draw then costs two
interpolations: along `previous` between the two bracketing nodes, and along the
quantile axis.

What is interpolated across `previous` is the **quantile function**, not the cdf
or the density. The conditional's location moves with `previous` — that is the
whole content of the model — and averaging two cdfs of distributions centred in
different places produces a bimodal blend of them, whereas averaging their
quantile functions shifts one into the other.

**Why wait for 64 rather than build the table up front?** Because building it *is* 64 draws'
worth of the same computation: a single draw evaluates the density over a 1000-point grid,
and the table evaluates it over 64 × 1000. So a model asked fewer than 64 times can never
repay the cost.

That is not a hypothetical case — it is the chained walk. `generate_series` fits a day's
models, takes **exactly one** sample from each, and moves to the next calendar day with
fresh ones. Building tables eagerly would make a synthetic year build 8 784 of them and use
each once, at 64× the cost, for no benefit whatsoever. The counter exists to protect that
path: it withholds the cost until a model has *proved* it will be asked enough times.

```{note}
Large ensembles run ~8× faster; a short run never reaches the threshold and is
bit-for-bit unchanged. Measured against the direct path over 20 000 draws, the cached
sampler is within 0.03% on the mean and 0.31% on the standard deviation. Both paths consume
exactly one number from the RNG, so which one is taken never perturbs the stream, and the
worst case is bounded at 2× — a model asked for about 128 samples pays 64 direct draws, then
a build worth 64 more, then cheap lookups.
```

When the ensemble size is known in advance and is large, the waiting is pointless:
{meth}`~meteosynth.generators.DayWindowGenerator.generate_ensemble` builds the tables up
front instead, so that every realisation is drawn through the same sampler rather than the
first 64 differing from the rest.

## Singularity handling

Real meteorological slices are often degenerate — e.g. direct irradiance is
identically zero every night, so a covariance matrix collapses and the 2D KDE
cannot be fitted. `meteosynth` classifies each transition from the standard
deviations of the previous and current values, records the verdict on the
simulator as `kind`, and dispatches to a dedicated routine.

| `Kind` | Previous | Current | Strategy |
|------|----------|---------|----------|
| `KDE_2D` | varies   | varies  | Full 2D KDE + conditional sampling |
| `KDE_1D` | constant | varies  | Sample from the 1D KDE of the current values |
| `CONSTANT` | any    | constant| Return the constant current value (deterministic) |

```{mermaid}
flowchart TD
    S["std(previous), std(current)"] --> Q1{"current varies?"}
    Q1 -->|no| C["Kind.CONSTANT<br/>return the constant"]
    Q1 -->|yes| Q2{"previous varies?"}
    Q2 -->|no| K1["Kind.KDE_1D<br/>1D KDE of current"]
    Q2 -->|yes| K2["Kind.KDE_2D<br/>2D KDE conditional"]
```

This is what lets the generator run through a full 24-hour cycle that includes
dead night-time hours without numerical failure.

```{note}
**"Constant" means constant to within a tolerance, not `std == 0`.** The test used
to be exact, which worked only because PVGIS happens to store literal zeros at
night. Any source storing a physically-zero night as `1e-16` — interpolation,
resampling, unit conversion — fell through to the 2D branch, where a KDE was
fitted across a `previous` spanning ~50 and a `current` spanning ~1e-14. That
covariance is catastrophically ill-conditioned. The tolerance is now relative to
the largest magnitude the simulator holds across *both* axes, because what makes a
slice degenerate is being negligible next to the other axis.

A `KDE_2D` fit that turns out singular anyway — perfectly collinear data — degrades
to `KDE_1D` with a warning rather than failing several steps later. One unfittable
hour should not take a whole synthetic year with it.
```

## An initial distribution, then transitions

A Markov chain is formally two things: **an initial distribution and a set of
transitions**. `EnvSeriesGenerator` fits both.

The transitions are the familiar part: simulator `h` models `hour h-1 -> hour h`,
for h = 1…23. Hour 0 has no previous hour within the day, so there is nothing to
condition on — and rather than fake one, the chain starts from an **initial
distribution** π(x₀), fitted to the observed 00:00 value of every training day. It is
unconditional by construction: no slicing, no conditioning, just the distribution of
the first value.

```{mermaid}
flowchart LR
    subgraph Day["gen_day()"]
        P["&#960;(x&#8320;)"] --> H0["h0"] --> H1["h1"] --> Hn["&#8230; h23"]
    end
    Train["training subset"] --> Fit["fit &#960;(x&#8320;) + 23 hourly<br/>MarkovChainSimulator2dKDE"]
    Fit --> Day
```

Two consequences worth seeing:

- For **irradiance**, every observed 00:00 value is exactly zero. A density fitted to
  a list of identical numbers is a spike at that number, so π(x₀) returns 0.0 every
  time. *"Irradiance starts at zero" is an observation read off the data, not an
  assumption baked into a default argument.*
- For **temperature and wind**, π(x₀) is a real distribution over observed midnight
  values, so every drawn day gets its own realistic start. The old fixed default of
  `0.0` sat outside the observed midnight range of both.

π(x₀) is a **dated** object: midnight is a different distribution in January and in
July, so one that does not know *when* it is being asked about is fitted to both at
once and right for neither. That is why a chained series requires a start date.

An ensemble is an explicit loop over `gen_day()`, yielding an $N \times 24$ array —
exactly the kind of input a downstream energy model integrates over to obtain
distributions of output and requirements.

## Crossing midnight

Independent days reset at midnight. A **continuous series** links them:
`DayWindowGenerator.generate_series(start, n_days)` draws day 1's hour 0 from π(x₀),
and every later day's hour 0 from **that day's** cross-midnight model, conditioned on
the previous day's 23:00 value.

That model is fitted from *actual consecutive dates* — for each target day d, the
23:00 of d−1 looked up in the full record — never from calendar slots. The distinction
matters because the training window wraps climatologically: a Jan 2 window contains
late-December days, and pairing on the slot would produce Dec 31 **2012** → Jan 1
**2012**, a 364-day backwards jump presented as a one-hour step.

```{mermaid}
flowchart LR
    subgraph D1["14 March models"]
        P["&#960;(x&#8320;)"] --> A0["h0"] --> A23["&#8230; h23"]
    end
    subgraph D2["15 March models"]
        B0["h0"] --> B23["&#8230; h23"]
    end
    A23 -->|"cross-midnight model<br/><b>of 15 March</b>"| B0
```

The chain is therefore **time-inhomogeneous at daily resolution**: each calendar day
uses models fitted to its own window, and the boundary step belongs to the *later*
day, so every generated value comes from a model belonging to its own date.

On the shipped record a real one-hour step across midnight correlates at 0.98
(`wind_speed`) and 1.00 (`temp_air`); the same-day 23:00 → 00:00 pairs the old hour-0
model learned correlate at only 0.36 and 0.89.

## Choosing the training subset

The first-order chain assumes **stationarity within the training subset**: the
statistics it learns are only meaningful if the days it pools share a climate.
That makes the choice of subset a modelling decision, not a detail.
`meteosynth` offers two strategies.

**By calendar month** — `MetDataset.get_month_subset(5)` pools every day
in May. Simple, but it has two defects. It is **off-centre**: a model for May 1
trains on data whose centre of mass sits on May 16, biased roughly fifteen days
late in the season. And it **jumps**: May 31 and June 1 train on *disjoint*
data, so the generator steps discontinuously at every month boundary — twelve
times a year, on dates with no physical meaning.

**By rolling day window** — `MetDataset.get_day_window_subset(5, 1)`
pools every day within $n$ days of May 1 (default $n = 15$), across all years in
the record. It is centred on the target by construction and slides smoothly from
one day to the next.

```{note}
The window buys **centring and smoothness, not sample size**. With a two-year
record, $n=15$ pools $(2 \times 15 + 1) \times 2 = 62$ days — the same as a
31-day month. $n$ is the bias–variance knob: larger $n$ gives more transition
pairs but a blurrier season.
```

### The `all_leap` calendar

A window centred on January 2 must reach back into December, so days are indexed
on a circular calendar rather than by date. `meteosynth` maps each `(month, day)`
to a **slot** against a fixed *leap* reference year:

$$
\text{Jan 1} \rightarrow 1, \quad \dots \quad
\text{Feb 28} \rightarrow 59, \quad
\text{Feb 29} \rightarrow 60, \quad
\text{Mar 1} \rightarrow 61, \quad \dots \quad
\text{Dec 31} \rightarrow 366
$$

Non-leap years simply never emit slot 60. This is the CF-conventions `all_leap`
(or `366_day`) calendar — `dayofyear` *as if every year were a leap year*.
Membership is then a circular distance with period 366:

$$
\delta(s, c) = \min\big((s - c) \bmod 366,\; 366 - (s - c) \bmod 366\big)
\;\le\; n
$$

The period is fixed by the index, not tunable: only $366$ makes the
Dec 31 $\rightarrow$ Jan 1 wrap cost exactly one day.

```{note}
Do **not** substitute pandas' `.dt.dayofyear` here. In a leap year March 1 is
day 61; in a non-leap year it is day 60. Pooling years by `dayofyear` would
misalign the entire March–December calendar by a day.
```

Two consequences fall out for free, with no special-casing:

- **The year wraps.** A January 2 window with $n=4$ reaches Dec 29–31; a
  December 30 window reaches Jan 1–3.
- **February 29 is an ordinary day.** Its observations are pooled into any
  nearby window rather than discarded, *and* it can be requested as a generation
  target like any other slot.

### What this means around the end of February

Two properties follow, and both are easier to trust once seen —
`examples/concepts/example_leap_year_windows.py` demonstrates them on synthetic records
with and without leap years, since the shipped 2011–2012 record has only one
leap day and cannot.

**Leap-day observations come only from leap years.** On a ten-year record
(2011–2020, three leap years), asking for February 28 with $n=2$ pools:

| day | slot | years contributing |
|---|---|---|
| 02-26 | 57 | all ten |
| 02-27 | 58 | all ten |
| 02-28 | 59 | all ten |
| **02-29** | **60** | **three** — the leap years only |
| 03-01 | 61 | all ten |

March 1 is reached simply because it is the next slot. Nothing special happens
at the month boundary.

**Non-leap years contribute one day fewer** to any window spanning slot 60. That
same ten-year record pools 310 days for an unaffected target such as June 15,
but 303 for anything spanning the leap slot — a deficit of exactly seven, the
number of non-leap years. This is faithful to the calendar rather than a defect:
those days genuinely do not exist.

```{note}
**A synthetic February 29 is overwhelmingly interpolation.** Even with three
leap years in a ten-year record, only 3 of the 303 pooled days — about 1% — are
real February 29 observations; the rest is late February and early March. If the
record contains *no* leap year at all, the window pools slot 60 zero times and
February 29 is generated entirely from its neighbours. That is the intended
design, and it is what lets you generate a leap day from a record that has never
seen one — but "synthetic Feb 29" does not mean "built from observed Feb 29s".
```

```{mermaid}
flowchart LR
    D["(month, day)"] --> S["day_slot &#8594; 1&#8230;366<br/>all_leap calendar"]
    S --> C["circular_delta(slot, centre)<br/>period = 366"]
    C --> W["&#948; &#8804; n &#8594; window subset"]
    W --> G["EnvSeriesGenerator"]
```

The window is **climatological, not chronological**: a January 2 2011 target
pools December *2011* as a proxy for late-December climate. The pool is
therefore not a real time-ordered process — which is the intent, and also why a
chronological "±n days by timestamp" design would fail outright, since January 2
2011 would want December 2010.

## Model variants

`meteosynth` ships three transition models with a common `get_next_state` /
`generate_sequence` interface:

- **`MarkovChainSimulator2dKDE`** — continuous state, joint 2D KDE with explicit
  singularity handling. The default and most robust choice.
- **`ContinuousMarkovChainSimulator`** — continuous state, but builds a separate
  1D KDE per rounded "previous" bin. Simpler, faster to reason about, less
  smooth across bins.
- **`MarkovChainSimulatorDiscrete`** — a classic discrete transition-count
  matrix for categorical/quantised states.

## Assumptions and limitations

- **First-order memory only.** Longer-range persistence (multi-day weather
  regimes) is not captured by a single-lag chain.
- **Stationarity within the training subset.** Train on comparable periods so the
  diurnal and seasonal statistics are consistent — a calendar month, or better,
  a rolling day window centred on the target.
- **Kernel bandwidth matters, and the shipped default is the measured one.**
  Too small overfits the sample; too large washes out real structure. The
  default `bandwidth=0.1` was checked against Scott's rule on a 19-year record
  at four dates through the year: Scott pulls the mean daily total *down* by
  1.3–5.6% at every date and narrows the distribution (P10 up, P50 and P90 down
  — the signature of over-smoothing, from a kernel 3.9× wider). Tune per
  variable if you have the evidence to; do not switch to Scott's rule for
  irradiance on general principle.
- **The overcast tail is under-produced.** Where a record holds heavily overcast
  days, the generator makes roughly **four times too few** of them — 0.2%
  against 1.4% observed below 1 kWh/m² at 21 March, 12.7% against 15.1% at
  21 December. Irradiance piles against a hard floor at zero, and a symmetric
  kernel cannot put enough mass near the bound without putting some below it.
  How much this matters depends entirely on the question: it moves an annual P90
  by 0.12%, so a yield study cannot see it, but it reaches anything reading the
  dark end directly — storage autonomy, worst-case days, a daily P10 (up to 9%
  high). Tracked as `FIX-1` and deliberately deferred.
- **Mild under-dispersion.** The standard deviation of the daily total comes out
  at 0.89–1.00 of observed at the shipped bandwidth. The model is compared
  against the very pool it was fitted to, so it *should* reproduce that pool's
  spread.
- **Absolute magnitudes are calibrated, against the pool.** Measured against the
  pooled window it was fitted to, the mean daily total lands within 0.7% of
  observed at all four dates — with a positive control confirming the instrument
  detects an injected 10% effect in 9 of 9 configurations. An earlier claim of a
  systematic +14% overshoot, taken from a two-year Paris record, does not
  reproduce and is superseded; see `examples/diagnostics-overshoot/`.
- **Thin samples in short records.** Sample size scales as
  $(2n + 1) \times n_\text{years}$ for a window, or $\sim 30 \times
  n_\text{years}$ for a month. Two years gives ~61 pairs per hourly KDE — thin
  for a 2D density. Prefer more years over a wider $n$ where you have them.
- **A window pools days that are not the target day.** The share of a pooled
  window's variance explained by *position within the window* is the price of
  pooling: 10.4% at ±15 days on 21 March, falling to 3.8% at ±7 — but 19.3% at
  ±7 on 21 September, because the seasonal slope there is measured against a much
  smaller day-to-day variance. The cost of a window is date-dependent and worst
  where the record is *least* variable, which is the opposite of where intuition
  puts it. There is no single right $n$.
- **Independent draws are what has been measured.** The diagnostics exercise
  `gen_day` at one site on one variable. Nothing there speaks to drift along a
  multi-day chained walk.
