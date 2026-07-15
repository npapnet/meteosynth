# TODOs

Known open items, most significant first. Each records what was measured, so nobody has
to re-derive it. Design rationale lives in [`docs/design/`](docs/design/README.md).

---

## 1. Generated irradiance is systematically ~13% too high

**Status:** open · **Impact:** absolute yield figures are not calibrated

A synthetic year of `poa_direct` totals **670 kWh/m²** against **594** observed on the
2011–2012 Paris record (+13%). Seasonal *shape* is faithful (correlation 0.95, peak month
matches), so this affects magnitudes, not the climatology. `wind_speed` is close (−5%).

Anyone using this for P50/P90 yield estimates needs this fixed first.

### It is not simply the bandwidth

This was originally attributed to `bandwidth=0.1`. That is wrong — the bias survives every
bandwidth, including Scott's rule. Measured on the May subset, 300-day ensemble, observed
3.27 kWh/m²:

| bandwidth | generated | bias |
|---|---|---|
| 0.05 | 3.56 | +9% |
| 0.1 (default) | 3.62 | +11% |
| 0.2 | 3.71 | +14% |
| 0.3 | 3.75 | +15% |
| 0.5 | 3.72 | +14% |
| None (Scott) | 3.71 | +14% |

Smaller bandwidths help but do not remove it. Contrast `wind_speed`, where bandwidth *is*
the whole story — 0.05 gives +12%, and Scott's rule gives **0%**.

### Two coupled causes

**(a) KDE boundary bias at the zero floor.** Every biased hour has `min == 0.0`: the data
piles against a hard physical bound. `_get_x_domain` spans exactly `[0, max]` with no
padding, so Gaussian mass that should fall below zero is renormalised back *into* the
domain, pushing the conditional mean up. This is the classic KDE boundary problem, and it
explains why `wind_speed` is unaffected — its distribution (min 0.07) does not sit against
a bound. It also explains the bandwidth trend: boundary bias scales with kernel width.

**(b) The error compounds along the 24-step walk.** One step from *true* observed values
is only +6%; the full chain from midnight reaches +18% by hour 12:

| | hour 12 mean | bias |
|---|---|---|
| observed | 398.7 | — |
| 1 step from true hour-11 values | 422.3 | +6% |
| 24-step chain from midnight | 469.7 | +18% |

Per-hour bias grows through the day (hour 6 +9% → hour 12 +18% → hour 18 +13%), which is
the signature of accumulation rather than a constant offset.

### Candidate fixes

- Boundary correction for the bounded-below case: reflection at zero, a log/sqrt transform
  before fitting, or beta/gamma kernels near the bound.
- Investigate whether `_calc_domain` taking `min`/`max` across *both* `previous` and
  `current` widens the domain for hours where the two ranges differ, leaking mass.
- Quantify the compounding separately: it may be inherent to the first-order chain rather
  than fixable in the kernel.
- Add a calibration test that pins generated-vs-observed bias per attribute, so any fix is
  measurable and cannot silently regress.

Related: the module header of `markov_chain_simulator_kde2d.py` records an open CRITICAL
note that padding the domain can produce **negative** values — the same boundary problem
seen from the other side. The two should be solved together.

---

## 2. Physical support, `start_value`, and hour-0 — all planned together

**Status:** designed, not yet implemented →
[`docs/design/variable-specs-and-initialisation.md`](docs/design/variable-specs-and-initialisation.md)

Four defects share one root cause — the package has no notion of what each quantity
physically *is*. They are planned as one change, targeting 0.2.0 (breaking):

- **Generated irradiance goes negative.** 1.29% of `poa_direct` values, all from the one
  `CN` dawn hour, where 30.25% of samples are below zero. `_calculate_1d_kde_distribution`
  pads its domain ±10% (`markov_chain_simulator_kde2d.py:129-130`), giving a sampling
  range of [−8.10, 89.10] when the observed minimum is 0. The module header claims padding
  was removed "to avoid this" — it was removed from `_get_x_domain` only; the 1D path
  still pads.
- **`start_value=0.0` is inert for irradiance and wrong for everything else.** Hour 0 is
  `CC` for irradiance, so the value is ignored entirely (`start_value` of 0, 500 or −999
  give an identical day). For `wind_speed` and `temp_air` it is *outside* the hour-0
  observed domain ([0.62, 5.31] and [5.92, 20.14]).
- **Out-of-domain starts crash.** `wind_speed` at ≥12, `temp_air` at ≥60 or ≤−50:
  all-zero KDE density → `0/0` → NaN → `ValueError: array must not contain infs or NaNs`
  on the following hour.
- **Hour 0 learns noise.** `hour_prev = (hour - 1) % 24` pairs hour 0 with hour 23 of the
  *same* day — a 23-hour backwards jump. Correlation +0.218 for wind and +0.552 for temp,
  against **+0.989** and **+0.993** for the real cross-midnight step.

The fix: a `VariableSpec` registry declaring each quantity's support, sampling truncated
to it, and `start_value` replaced by a fitted initial distribution π(x₀) plus a genuine
23:00(d−1) → 00:00(d) transition.

Note this fixes the *negatives* but not item 1's *+13% overshoot* — truncation stops mass
escaping below the bound without undoing the upward push against it. Deliberately kept
separate so the bias work starts from a clean baseline.

The current hour-0 behaviour is pinned by
`test_hour_zero_pairs_with_hour_23_of_the_same_day`, so it cannot change by accident
before then.

---

## 4. Sampling re-evaluates the KDE on every call

**Status:** open · **Impact:** ~97% of generation runtime

`get_next_state` re-evaluates a 1000-point grid through `gaussian_kde.evaluate` on every
single call — 53.5 ms per generated day, against 58 ms to *fit* all 24 hourly models.
Fitting is not the bottleneck; sampling is.

Precomputing the conditional CDF on a grid of `previous` values in `__init__` would make
sampling two interpolations. This is the module's own long-standing TODO
(`markov_chain_simulator_kde2d.py`). Note it trades memory for speed: a 200×1000 grid per
simulator is ~1.6 MB, or ~38 MB per generator.

---

## 5. Fitted generators cannot be pickled at the default bandwidth

**Status:** open · low priority

```text
bandwidth=0.1  -> AttributeError: Can't get local object
                  'gaussian_kde.set_bandwidth.<locals>.<lambda>'
bandwidth=None -> pickles fine, 262 KB
```

`scipy` stores a local lambda in `covariance_factor`. This blocks any disk-caching or
multiprocessing of fitted generators. A custom `__reduce__` would fix it.

Deliberately not blocking anything today: generators are built lazily behind an LRU cache
precisely because persisting them buys ~58 ms and duplicates data already on disk. See
[`docs/design/rolling-day-window.md`](docs/design/rolling-day-window.md).

---

## 6. Ingest sources other than PVGIS

**Status:** future

Support other providers (Open-Meteo, etc.) via a thin **adapter layer** that normalises
each source into the canonical schema the core consumes (`year, month, day, hour` plus the
modelled columns), so the Markov code never learns a provider's quirks.

The `VariableSpec` registry from item 2 is the natural seam: an adapter maps provider
columns to registered spec names, converts units into each spec's declared `units`, and
validates against each spec's `support` — turning silent ingestion bugs (kW/m² read as
W/m², °F as °C) into an error at the boundary. See
[`docs/design/variable-specs-and-initialisation.md`](docs/design/variable-specs-and-initialisation.md).

---

## 7. Smaller items

- **Four copies of the same data.** `MarkovChainSimulator2dKDE` holds `self.data`,
  `self.previous_values`, `self.current_values`, *and* `joint_kde.dataset` — ~15× overhead
  (992 bytes of payload held as ~14.6 KB). Trimming touches that class's golden tests.
- **Default window half-width.** `n_days=15` gives 61 pairs per hourly KDE on a two-year
  record — thin for a 2D density. Whether 15 or 20 is better needs a real evaluation
  against the month baseline.
- **`date_id` is not zero-padded** (`'2011-1-2'`), so it does not sort lexicographically.
  `convert_to_daily_wide` sensibly builds its own padded `date_str`. Worth aligning, but
  it is a breaking change for anything grouping on `date_id`.
- **No `conftest.py`.** `MPLBACKEND=Agg` is required for the test suite but only
  documented, not enforced.
