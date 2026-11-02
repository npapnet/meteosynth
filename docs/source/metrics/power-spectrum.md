# Power spectral density (PSD)

**Suitability: ⚠️ Limited — prefer {doc}`autocorrelation`.** It's valid, but it holds the same information as the ACF in a form fewer readers can use.

## In plain words

Break the series into slow waves and fast waves and ask **how much of the variation
belongs to each speed**. A strong peak at "once per day" is the daily cycle. Energy at
"once every few days" is passing weather systems. Energy at "every hour or two" is
jitter.

## How it is computed

$$S(\omega) = \frac{1}{2\pi} \sum_{k=-\infty}^{\infty} \gamma(k)\, e^{-i\omega k}$$

$\gamma(k)$ is the autocovariance at lag $k$ and $\omega$ is the frequency. In practice
you use a periodogram (a discrete Fourier transform), averaged over years or
realisations.

## What it catches

- A missing or distorted daily cycle.
- Too much hour-to-hour noise (the high-frequency end), a common artefact of Markov
  chains.

## What it misses

- Nothing the ACF doesn't also see. It is the Fourier transform of the same quantity.

## Comment for meteosynth

- **Which bands you can see depends on the series length:**

  | Band | Needs |
  | :--- | :--- |
  | Daily cycle and faster | any product, even one day |
  | Weather systems (2–10 days) | at least ~20 days (month or year product) |
  | Annual peak | several chained years (≳ 5) to get more than one sample |
  | Slower than one year | nothing to find: the model has no year-to-year memory |

- **"Kolmogorov −5/3 turbulence decay" can't be tested.** It happens at
  second-to-minute scales, and hourly data can't show it whatever the generator does.
  Don't claim it.
- For a first study, **drop the PSD** and use the ACF as the only time-structure metric.

**See also:** {doc}`autocorrelation`, {doc}`cardinality`.
