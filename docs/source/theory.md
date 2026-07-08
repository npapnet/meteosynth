# Theory

This page explains how `meteosynth` turns a historical record into a generator
of statistically-plausible synthetic series.

## The problem

Energy-project Monte-Carlo studies need *many* weather realisations, not one.
A single Typical Meteorological Year hides the year-to-year and hour-to-hour
variability that drives the tails of production and demand. `meteosynth`
instead learns the **transition statistics** of a variable and samples fresh
trajectories that reproduce those statistics.

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
The evaluation domain spans exactly the observed data range (no padding). An
earlier version padded the range by 10%, which could push sampled irradiance or
wind speed **below zero** — physically impossible. Keeping the domain tight to
the data avoids that.
```

## Singularity handling

Real meteorological slices are often degenerate — e.g. direct irradiance is
identically zero every night, so a covariance matrix collapses and the 2D KDE
cannot be fitted. `meteosynth` classifies each transition into one of four
cases using the standard deviations of the previous and current values, and
dispatches to a dedicated routine.

| Code | Previous | Current | Strategy |
|------|----------|---------|----------|
| `NN` | varies   | varies  | Full 2D KDE + conditional sampling |
| `CN` | constant | varies  | Sample from the 1D KDE of the current values |
| `NC` | varies   | constant| Return the constant current value |
| `CC` | constant | constant| Return the constant value (deterministic) |

```{mermaid}
flowchart TD
    S["std(previous), std(current)"] --> Q1{"prev varies?"}
    Q1 -->|no| Q2{"current varies?"}
    Q1 -->|yes| Q3{"current varies?"}
    Q2 -->|no| CC["CC: constant &#8594; constant"]
    Q2 -->|yes| CN["CN: 1D KDE of current"]
    Q3 -->|no| NC["NC: return constant"]
    Q3 -->|yes| NN["NN: 2D KDE conditional"]
```

This is what lets the generator run through a full 24-hour cycle that includes
dead night-time hours without numerical failure.

## Building a day, then an ensemble

`EnvSeriesGenerator` fits **one simulator per hour of the day** — simulator
`h` models the transition `hour h-1 -> hour h`. A synthetic day is produced by
starting from an initial value (e.g. 0 W/m² at midnight) and walking the 24
hourly simulators in sequence.

```{mermaid}
flowchart LR
    subgraph Day["gen_day_sequence"]
        H0["h0"] --> H1["h1"] --> H2["h2"] --> Hn["&#8230; h23"]
    end
    Train["month subset"] --> Fit["fit 24 hourly<br/>MarkovChainSimulator2dKDE"]
    Fit --> Day
    Day -->|"repeat n_days"| Ens["generate_ensemble<br/>(n_days &times; 24)"]
```

Because each day is an independent draw, `generate_ensemble(n_days=N)` yields an
$N \times 24$ array — exactly the kind of input a downstream energy model
integrates over to obtain distributions of output and requirements.

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
- **Stationarity within the training subset.** Train on comparable periods
  (e.g. a single month) so the diurnal and seasonal statistics are consistent.
- **Kernel bandwidth matters.** Too small overfits the sample; too large washes
  out real structure. Tune `bandwidth` per variable.
