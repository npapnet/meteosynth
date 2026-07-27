# TODOs

Known open items, most significant first. Each records what was measured, so nobody has
to re-derive it. Design rationale lives in [`docs/design/`](docs/design/README.md).

---

## 1. Leap years and the end of February — verify and lock in

**Status:** ✅ **DONE** — behaviour confirmed **correct**, now tested and demonstrable
· `tests/test_leap_year_windows.py` (30 tests) ·
`examples/concepts/example_leap_year_windows.py` · documented in `docs/source/theory.md` and
`docs/design/completed/rolling-day-window.md`

The shipped record is 2 years (2011–2012) with exactly one leap day, so **no test and no
example exercised the cases that actually mattered**: a multi-year record with several leap
years, or a record with none at all. The behaviour could not be seen working, which was
reason enough to distrust it. Both are now covered by synthetic records (2011–2020 with
leap years 2012/2016/2020, and 2021–2023 with none).

A mutation check confirms the tests bite: swapping the `all_leap` index for pandas'
year-dependent `dayofyear` leaks **Mar 2 in from the 7 non-leap years** while leap years
contribute Feb 29 — the window silently drifts by a day depending on the year — and
`test_feb28_window_pools_leap_day_from_leap_years_only` catches it.

### The two questions

**Q1 — With a 10-year record containing leap years, does a Feb 28 window pick up Feb 29
from the leap years *and* Mar 1 from all years?**

Measured on a synthetic 2011–2020 record (leap: 2012, 2016, 2020),
`get_day_window_subset(2, 28, n_days=2)`:

| calendar day | years contributing |
|---|---|
| 02-26 | 10 |
| 02-27 | 10 |
| 02-28 | 10 |
| **02-29** | **3** — the leap years only |
| 03-01 | 10 |

**Yes — this is correct.** Feb 29 observations are pooled from the years that have them;
Mar 1 from all ten.

**Q2 — With a record containing *no* leap years, can Feb 29 still be generated from late
February and early March?**

Measured on a synthetic 2021–2023 record (no leap years),
`get_day_window_subset(2, 29, n_days=15)` returns **90 days spanning Feb 14 – Mar 15**,
containing no real Feb 29, and `wind_speed` / `temp_air` generate cleanly from it.

**Yes — this is correct too.** Slot 60 simply contributes nothing, and the target is
synthesised from its neighbours.

### What is genuinely worth knowing

- **Non-leap years contribute one day fewer** to *any* window spanning slot 60. On the
  10-year record every target from Feb 27 to Mar 2 pools **303** days rather than the
  310 an unaffected target (e.g. Jun 15) pools. This is faithful to the calendar — those
  days do not exist — but it should be stated, not discovered.
- **A Feb 29 generator is mostly interpolation.** Even with leap years present, only
  3 of 10 years contribute a real Feb 29, so the Feb-29 model is overwhelmingly built from
  its neighbours. With no leap years it is *entirely* so. That is the intended design, but
  a user reading "synthetic Feb 29" deserves to know it is not built from observed Feb 29s.

### Delivered

1. **`tests/test_leap_year_windows.py`** — 30 tests over both fixtures: the Q1 table as
   exact year-count assertions; Q2 span/emptiness/generation; the slot-60 boundary
   parametrised over eight target/`n_days` combinations; the deficit; slot symmetry; and
   a guard that the fixture's nights are *exactly* zero (see the note below).
2. **`examples/concepts/example_leap_year_windows.py`** — prints the tables above plus where the
   leap day enters and leaves a window, and plots which (year, slot) cells feed a
   synthetic Feb 29. No PVGIS fetch.
3. **Documented** in `docs/source/theory.md` (a "What this means around the end of
   February" subsection) and `docs/design/completed/rolling-day-window.md` (Caveat B), both stating
   the deficit and the interpolation point explicitly.

**One correction to the plan above:** slot symmetry is 31 slots only when leap years are
present. On a leap-free record the Feb 29 window carries **30** populated slots — slot 60
is selected but never populated, because nothing in the record occupies it.

> **Note on a false alarm — which turned out to be a real bug.** While investigating,
> `poa_direct` produced a NaN for a Feb 29 target on a synthetic leap-free fixture. It is
> **not** a leap defect: a control run showed the same NaN for ordinary targets (Sep 10,
> Jan 2), and the real record is clean at every target including Feb 29.
>
> The cause is **not** the fixture being unrealistic. It is that `sin(pi)` is
> `1.2246e-16`, not `0`, so the fixture's night values were ~`1e-14` rather than exactly
> zero — which is enough to defeat the exact `std == 0` degeneracy test and route a
> constant-zero hour into the 2D KDE path. See item 7: that brittleness is a genuine
> library bug, not a fixture defect, and this fixture merely tripped over it.
>
> A fixture for these tests should still use a realistic diurnal profile (zero at night,
> peak near noon) so the degeneracy paths are exercised the way real data exercises them.
> But it should not need *exact* zeros to avoid NaN — and once item 7 is fixed, it will
> not.

---

## 2. Generated irradiance is systematically ~13% too high

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

- **The `CN` dawn hour's ±10% padding is two-sided, and only one side has been looked at.**
  `_calculate_1d_kde_distribution` pads its domain by 10% at *both* ends. The known
  CRITICAL concerns the lower pad, which produces negative irradiance. The **upper** pad
  inflates the domain maximum by 10% at the dawn hour — which for irradiance is the first
  non-degenerate hour of the day, i.e. exactly where the compounding measured in (b) above
  begins, twelve steps before noon. Removing the padding therefore moves the annual total
  in **both directions at once**: dropping the lower pad restores mass that currently
  escapes below zero (total up), dropping the upper pad removes headroom (total down). Net
  sign is unmeasured. Measure the two sides *separately* — the truncation work planned in
  `docs/design/variable-specs-and-initialisation.md` §3 changes both simultaneously, and a
  single before/after number would confound them. This is the concrete form of the "same
  boundary problem seen from the other side" note below.
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

## 3. Physical support, `start_value`, and hour-0 — all fixed together

**Status:** ✅ **DONE** (2026-07-22) — implemented, tested, 219 tests passing ·
design: [`docs/design/variable-specs-and-initialisation.md`](docs/design/variable-specs-and-initialisation.md)

Four defects shared one root cause — the package had no notion of what each quantity
physically *is*. They were fixed as one change, 0.2.0 (breaking):

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
  *same* day — a 23-hour backwards jump. Re-measured on the full record during
  implementation: **wind 0.360 → 0.981**, **temp 0.890 → 0.998** for the real
  cross-midnight step. (The design doc's original 0.218 / 0.552 figures for the
  same-day pairs do not reproduce against the full 2011–2012 record; the direction and
  size of the wind finding hold, but temperature's same-day correlation is high because
  its seasonal component correlates *any* two hours of the same day.)

### What landed

- `src/meteosynth/variables.py` — `VariableSpec` (constraints only, no `name`) and an
  extensible registry. One shared `IRRADIANCE` spec serves all four POA component names.
- Sampling truncated to the support in **both** paths; the ±10% padding removed.
  Negatives go to **0.00%**, measured over ensembles and a full generated year.
- `start_value` gone. π(x₀) fitted per window, reusing the existing 1D KDE machinery so
  a degenerate π(x₀) returns the constant — irradiance starts at zero *from the data*.
- Real 23:00(d−1) → 00:00(d) model, built from actual consecutive dates, plus
  `DayWindowGenerator.generate_series(start, n_days)`.
- Global `np.random.seed` replaced by threaded `np.random.Generator`.
- `MODELLED_ATTRS` whitelist replaced by the registry; ingestion keeps `INDEX_COLS` +
  registered columns and drops the rest **by rule**.
- `src/meteosynth/adapters.py` — optional collection helper; `fetch_pvgis` defaults to
  `poa_global` with `irradiance="direct"` as the override.

### Found during implementation

**The out-of-domain crash was still reachable after truncation.** Truncation constrains
the *sampling* domain but not the *conditioning value*. In a rolling series, day d's
23:00 comes from day d's window fit while day d+1's cross-midnight model is fitted on a
different (overlapping) sample, so the conditioning value can land outside the fitted
range — all-zero density, `0/0` → NaN, next hour dies. Fixed by clamping the
conditioning value into the fitted range in `get_conditional_density_gen`, with a
marginal fallback behind it. Measured frequency: **0.27% (1/364)** of midnight steps
over a generated year, pinned by `tests/test_window_boundary_continuity.py`.

Note this fixed the *negatives* but not item 2's overshoot — and it moved that number
the *wrong* way, 670 → **678 kWh/m²** (+13% → +14%) on the shipped record. Removing the
lower pad restores mass that used to escape below zero, and that outweighed removing the
upper pad. See item 2's two-sided padding note.

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
[`docs/design/completed/rolling-day-window.md`](docs/design/completed/rolling-day-window.md).

---

## 6. Ingest sources other than PVGIS

**Status:** future

Support other providers (Open-Meteo, etc.) via a thin **adapter layer** that normalises
each source into the canonical schema the core consumes (`year, month, day, hour` plus the
modelled columns), so the Markov code never learns a provider's quirks.

The `VariableSpec` registry from item 3 is the natural seam: an adapter maps provider
columns to registered spec names, converts units into each spec's declared `units`, and
validates against each spec's `support` — turning silent ingestion bugs (kW/m² read as
W/m², °F as °C) into an error at the boundary. See
[`docs/design/variable-specs-and-initialisation.md`](docs/design/variable-specs-and-initialisation.md).

---

## 7. Degeneracy detection uses an exact float comparison, and is brittle

**Status:** open · **Impact:** silent NaN output on any data with floating-point residue ·
**Blocks:** item 6 (other sources)

`_cat_singularity` (`markov_chain_simulator_kde2d.py`) decides whether a slice is
degenerate with an **exact** comparison:

```python
std_prev = np.std(self.previous_values)
std_curr = np.std(self.current_values)
if std_prev == 0 and std_curr == 0:      # CC
elif std_prev == 0 and std_curr > 0:     # CN
elif std_prev > 0 and std_curr == 0:     # NC
else:                                    # NN  <- everything else lands here
```

This works **only because PVGIS supplies exact zeros at night** (`unique values = [0.]`,
`std` exactly `0.0`). It is luck, not robustness.

Any value that is physically zero but numerically `1e-16` — from interpolation,
resampling, unit conversion, or a provider that stores near-zero noise — lands in the `NN`
branch. A 2D KDE is then fitted where `current` spans ~`1e-13` while `previous` spans
~50. The covariance is catastrophically ill-conditioned, the density evaluates to ~0
across the whole grid, and `conditional_density = joint_density / np.sum(joint_density)`
becomes `0/0` → **NaN**, which then propagates into the next hour.

Reproduced: a fixture built with `np.clip(np.sin((hour - 6)/12*np.pi), 0, None)` has
`sin(pi) == 1.2246e-16`, giving hour-18 values of ~`1e-14`, `std = 1.6e-14 > 0` → `NN` →
NaN. Note the failure is **silent** — a `RuntimeWarning: invalid value encountered in
divide` and then a NaN in the output, not an exception.

**This directly threatens item 6.** Ingesting Open-Meteo (or any resampled/unit-converted
source) is exactly the scenario that produces near-zero-but-not-zero nights.

### Fix

Replace the exact test with a scale-aware tolerance — e.g. compare the range or standard
deviation against the data's own scale (`np.isclose`, or `ptp < atol + rtol * scale`)
rather than against literal `0`. Land it with the `Kind` rename in item 3, which already
rewrites this function. Add a test with deliberately residue-laden input (night values of
`1e-16` rather than `0.0`) asserting the hour is still treated as constant and the output
is finite.

Guard separately against the underlying `0/0`: if `np.sum(joint_density)` is ~0, that is
unrecoverable and should raise with a clear message rather than return NaN.

---

## 8. Smaller items

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

---

## 9. Cached data metadata and cache check (coordinates, time period, source)

**Status:** open · **Impact:** prevents redundant network fetches and accidental cached file mismatches

Saved datasets (e.g. from PVGIS or other providers) currently do not carry embedded metadata identifying their origin parameters.

### Requirement & Implementation Plan

- **Metadata Tracking**: Include metadata tags or headers when caching meteorological data, recording:
  - Source provider (e.g., `"PVGIS"`),
  - Geographic coordinates (`latitude`, `longitude`),
  - Time period (`start_year`, `end_year`).
- **Automatic Cache Match Check**: When fetching data (e.g. via `fetch_pvgis_hourly`), check if an existing cached file matches the requested latitude, longitude, period, and source. If a matching cached version exists, use it immediately and skip the API call.
- **Force / Override Flag**: Introduce a `force_refetch` (or `override`) parameter on the fetch/load method calls so users can explicitly force a fresh network request when needed.

---

## 10. `metdata_pvgis` unpacks `pvlib` return values that no longer exist

**Status:** open · **Impact:** both fetch functions in the module raise on every call ·
**Effort:** one line each

`pvlib` changed the arity of its PVGIS readers. `src/meteosynth/metdata_pvgis.py` still
unpacks the old shapes, so with the pinned `pvlib` (0.15.2, verified 2026-07-27) neither
function can run:

| function | line | unpacks | `pvlib` 0.15.2 returns | result |
|---|---|---|---|---|
| `fetch_pvgis_hourly` | `metdata_pvgis.py:81` | `data, _inputs, _metadata` | `(data, meta)` | `ValueError: not enough values to unpack (expected 3, got 2)` |
| `fetch_pvgis_tmy` | `metdata_pvgis.py:113` | `tmy_data, _months, _inputs, tmy_meta` | `(data, meta)` | same, expected 4 got 2 |

Nothing in the package depends on either — which is why the test suite is green and this
went unnoticed. `adapters.fetch_pvgis` already does it correctly (`data, _ = ...`,
`adapters.py:236`), and `examples/tools/site_data.py` deliberately indexes `result[0]`
rather than unpacking, so it works against either arity.

### Fix

Index instead of unpacking (`result = get_pvgis_hourly(...); data = result[0]`), matching
`site_data.py`. That is arity-agnostic and needs no version check. Add a smoke test that
calls both functions against a recorded response so a future `pvlib` change is caught by
CI rather than by a user.

Worth deciding at the same time: **whether `metdata_pvgis` should exist at all.** It
overlaps `adapters.fetch_pvgis`, which is the newer, spec-aware path (it normalises,
validates against `support`, and emits a canonical frame). If the module stays, it should
delegate to the adapter rather than call `pvlib` a second, differently-broken way.

---

## 11. Irradiance: pick one column by availability — never sum synthetic components

**Status:** open · **Decision needed before item 6 (other sources)** · **Impact:** how a
synthetic irradiance series is interpreted and whether two of them can be combined

> **Settled (2026-07-27): one irradiance column is modelled, and it is chosen by what the
> source supplies.** Components are *not* modelled separately and summed. The open work
> below is about **selection and provenance** — how the package decides between
> `poa_global` and `poa_direct` when only one of them is available, and how it records
> which one it used — not about decomposition.

PVGIS returns **either** the global plane-of-array irradiance **or** its three
components, never both — one boolean, two mutually exclusive column sets:

```text
components=False -> poa_global
components=True  -> poa_direct, poa_sky_diffuse, poa_ground_diffuse
```

`adapters.fetch_pvgis` handles this by making the caller choose one via
`irradiance="global"|"direct"|...` and emitting exactly that column. The examples need
both the components (for the concept scripts) and the total (for the PV use case), so
`examples/tools/site_data.py:add_poa_global` fetches `components=True` and reconstructs
the total by summation.

**The reconstruction is numerically sound.** Measured on Heraklion 2010, fetched
`poa_global` against the summed components, 8760 hours: max absolute difference
**0.01 W/m²**, mean **0.0003 W/m²**, annual totals identical to four significant figures
(1914.6 vs 1914.6 kWh/m²). The 0.01 is PVGIS's own two-decimal rounding. So
`poa_global == poa_direct + poa_sky_diffuse + poa_ground_diffuse` holds for this provider.

That matters for **one** operation only: deriving an *observed* total from *observed*
components, before any fitting, which is exact and stays allowed. It says nothing about
the synthetic side.

### Why summing synthetic components is ruled out

Recording the reasoning so it does not get re-litigated. Fitting the three components
independently and summing the *generated* series is not equivalent to fitting
`poa_global`: each component gets its own KDE and its own random draw, so the physical
anticorrelation between direct and diffuse — a cloud moves one down and the other up —
is destroyed. The sum is then under-dispersed at the day scale and over-dispersed hour to
hour, and it can produce hours that no sky could.

The consequence to document rather than fix: a user who needs internally consistent
components — to re-transpose onto a different tilt, say, which needs direct and diffuse
separately — cannot get them from this package. That is a limitation of the
one-attribute-at-a-time engine, and it is accepted, not a bug to file.

### The questions still to decide

1. **How is the column selected?** The rule wanted is *by availability*: use whichever
   irradiance column the source actually supplies, rather than making every caller name
   one. Today `adapters.fetch_pvgis` requires an explicit `irradiance="global"|"direct"|…`
   at fetch time, and a user-supplied frame gets no help at all — `EnvSeriesGenerator`
   just takes an `attr_str` and fails if that exact column is absent. What is missing is a
   resolver: given a frame, return the one irradiance column to model, following a
   documented preference order (`poa_global` first as the quantity a plane actually
   receives, then `poa_direct`, …), erroring only when none is present and saying which
   were looked for. Note this must **not** silently pick a different quantity than the
   caller expected: preference order is for when nothing was asked for, not an override.
2. **What does a cache hold?** One PVGIS fetch cannot carry both forms, and two fetches of
   the same site and period differ only by a flag no filename currently records. Ties into
   item 9 (cache metadata): whichever form was fetched is another field the metadata has
   to carry, otherwise a warm cache silently answers a question it was not asked.
3. **Is a derived column distinguishable from a fetched one?** Today it is not.
   `adapters.py`'s docstring states the design position — *"the column name is the
   provenance… no metadata sidecar"* — and a summed `poa_global` sits byte-for-byte
   alongside a fetched one with a different derivation behind it. Either the position gets
   qualified or derivation gets recorded. Options: a `source`/provenance field on the frame
   (`DataFrame.attrs` — lost on a CSV round-trip), a sidecar keyed to the cache file (item
   9), a naming convention, or accepting that the summation is exact enough (measured
   above) that the distinction does not matter for PVGIS. It will matter for a provider
   where the identity does *not* hold exactly.
4. **What does a saved synthetic series carry?** Whatever answers (1) and (3) for observed
   data should ride along with generated data too: a file holding one `poa_global` column
   with no record of which source column it was modelled from, and how that column was
   obtained, cannot be audited later.

### Related

Item 6 makes this concrete rather than academic: Open-Meteo supplies GHI/DNI/DHI on the
**horizontal**, not plane-of-array components, so "which irradiance is this column" stops
being a PVGIS-only question — and the availability-based selection in (1) is exactly the
seam where a provider that offers a different set plugs in. Item 9's metadata is the
natural place for the answer to live.

