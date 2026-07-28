# Changelog

All notable changes to `meteosynth` are recorded here.

**Style.** Entries describe **what the package is now**, not how it got there. Work lands
first under **Current sprint** — an unreleased, in-progress bucket — and that section is
*renamed* to its version heading at release time rather than copied, so history reads as
one continuous log. Categories follow [Keep a Changelog](https://keepachangelog.com/)
(`Added` / `Changed` / `Fixed` / `Removed`).

Two project-specific conventions:

- **`### Decisions`** — a release may carry one, holding a single line per significant
  design decision, each linking to the design doc that argues it. The argument itself
  stays in [`docs/design/`](docs/design/README.md); the changelog only records that the
  decision was taken and where to read it.
- **Completed [`TODOs.md`](TODOs.md) items land here.** `TODOs.md` holds open work only,
  so when an item ships it is folded into the release entry and removed from that file.

---

## Current sprint (unreleased)

### Added

- **`examples/` reorganised by purpose** into `use_cases/` (applied workflows),
  `concepts/` (how the package behaves) and `tools/` (shared helpers), with an index at
  `examples/README.md`. Downloads cache to `examples/data/`; everything generated goes to
  `examples/output/`, git-ignored via its own `.gitignore` so the folder exists in a clone
  but its contents never do.
- **Use cases split by time scale** into `use_cases/day/`, `use_cases/month/` and
  `use_cases/year/`, each with a `README.md` saying what its scripts answer, what they
  write and how long they take, indexed by `use_cases/README.md`. The scale is not a
  filing detail — it changes what can be asked: a day is checkable against eleven real
  ones, a month only means something as an ensemble, a year is produced rather than
  checked. The scripts needed no changes: their `sys.path` bootstrap searches upward for
  `examples/` rather than counting parents, and output names already carry `day_` /
  `month_` / `year_` prefixes, so one flat `examples/output/` still works.
- **Five use cases on an 11-year Heraklion record (2010–2020, PVGIS).**
  `day/day_envelope_pv|temp|wind.py` draw 200 synthetic 21 Mays each and report shape,
  spread and daily-aggregate against the eleven observed ones; `year/synthetic_year.py`
  writes an 8760-hour series of all three attributes; `month/monthly_statistics.py`
  reports an ensemble of twelve synthetic Mays against the observed years (level, spread,
  P50/P90).
- **An opt-in year heatmap** on `year/synthetic_year.py` — day of year across, hour of
  day down, one panel per attribute. Off by default (`PLOT_HEATMAP = False`), because
  that script exists to produce a file; matplotlib is imported only if it is switched on.
  It shows what the monthly summary table cannot: the seasonal envelope, and the summer
  day widening at both ends rather than merely getting brighter.
- **`examples/tools/`** — `site_data.py` (sites, cached records, output paths),
  `envelope.py` (observed-vs-synthetic comparison and figures), `fetch_site_data.py`
  (runnable cache priming).
- **`docs/source/concepts.md`** — foundational terminology in plain language (ensemble,
  realisation, envelope, coverage, P50/P90, support, π(x₀), …), first in the
  getting-started toctree.
- **`adapters.fetch_pvgis_tmy`** — fetches a PVGIS Typical Meteorological Year as a
  canonical frame, through the same normalise / validate / cache path as its hourly
  sibling. Its irradiance is **horizontal** (`ghi`, `dni`, `dhi`), not plane-of-array, and
  the column names are what keep the two from being confused. `coerce_year` is passed
  through rather than defaulted: a TMY stitches each month from a different real year, and
  silently rewriting that would destroy which year each month came from.
- **`IRRADIANCE_HORIZONTAL`**, with `ghi`, `dni` and `dhi` registered against it. A
  distinct spec object from `IRRADIANCE` despite identical support and units, because
  `long_name` is quoted back to the user by `validate_support` — naming a horizontal
  quantity "plane-of-array" would misinform exactly when someone is debugging where their
  numbers came from. Without the registration a TMY frame would have passed the boundary
  check unvalidated and then lost its irradiance entirely at ingestion, since
  `MetDataProcessor` trims to the registered set.
- **`meteosynth.adapters` and `meteosynth.variables` in the API docs.** Neither had an
  `automodule` entry, so the collection helpers and the spec registry were undocumented.

### Changed

- The concept scripts share one data loader instead of four copies of
  `load_or_fetch_data`, and no longer depend on the working directory.
- **`TODOs.md` regrouped** into Fixes / Performance & internals / Features / Direction /
  Housekeeping, with stable IDs (`FIX-1`, `PERF-2`, …) so cross-references survive
  re-ordering. Completed items moved into this file; stale ones removed.
- **`TODOs.md` inbox triaged and emptied.** `INBOX-1` … `INBOX-7` were costed and
  classified: two landed (this entry), one merged into `FIX-3`, and the rest graduated to
  `FEAT-3` (chained series between two dates, shape settled as `end=(month, day)`),
  `FEAT-4` (downloads cache by default), `FEAT-5` (`MetDataProcessor.metadata`), `CHORE-3`
  (document the on-disk format) and `CHORE-4` (realign `docs/source/`). The file gained an
  **Order of work** section recording the sequence and, more usefully, the couplings —
  `CHORE-1` folds into `FIX-1` because they are the same experiment, and `PERF-1` follows
  `FIX-1` because a precomputed CDF grid must encode whatever boundary correction lands.

### Fixed

- **Degeneracy detection is scale-aware instead of an exact float comparison.**
  `_cat_singularity` decided whether a transition was degenerate with `np.std(...) == 0`,
  which worked only because PVGIS happens to store literal zeros at night. Any source
  storing a physically-zero night as `1e-16` — interpolation, resampling, unit
  conversion, or a provider that keeps near-zero noise — fell through to the 2D branch,
  and a 2D KDE was fitted across a `previous` spanning ~50 against a `current` spanning
  ~1e-14. The comparison is now against the scale of the simulator's own data
  (`_DEGENERACY_RTOL = 1e-9`), so such a slice is classified `CONSTANT` or `KDE_1D` as it
  should be. Exact-zero sources are unaffected: when every value is zero the tolerance is
  zero too.

  Two corrections to how this was recorded in `TODOs.md`. The **silent NaN it described
  is no longer reachable** — the `0/0` guard added during the window-boundary work
  already falls back to the marginal of `current`, so the residue fixture now yields
  finite output either way. What the exact comparison still caused was *misclassification*:
  a needless and badly-conditioned 2D fit where a constant or 1D model was correct. And
  the item proposed *raising* on an unrecoverable joint density; that would contradict the
  fallback already in the code, so this degrades and warns instead.

- **A singular covariance no longer crashes.** When `previous` and `current` are
  perfectly collinear both axes vary, so the 2D branch was taken, but `gaussian_kde`
  raises `LinAlgError` — caught by setting `joint_kde` to `None` while `kind` stayed
  `KDE_2D`. The first sample then reached `np.sum(None)` and died with
  `TypeError: ufunc 'isfinite' not supported for the input types`, which names nothing
  that went wrong. Such a transition is now re-categorised as `KDE_1D` with a warning,
  and `get_conditional_density_gen` guards the `None` explicitly.

  Degrading rather than raising matches what the class already does when the joint
  density vanishes, and means one unfittable hour cannot take a whole synthetic year
  with it.

- **PVGIS fetching worked in neither module.** `pvlib` changed the arity of its PVGIS
  readers; `metdata_pvgis.fetch_pvgis_hourly` unpacked three values and
  `fetch_pvgis_tmy` four, against the two that pvlib 0.15.2 returns, so both raised
  `ValueError` on every call. Nothing in the package depended on them, which is why the
  suite stayed green — but `README.md` and `docs/source/quickstart.md` both taught the
  broken call, so a new user's first contact with real data failed.

  `adapters.fetch_pvgis` turned out to share the fragility in weaker form: `data, _ = ...`
  unpacks exactly two, which happens to match the installed pvlib and would break on the
  next change. Both fetchers now **index rather than unpack**, which is arity-agnostic and
  needs no version check.

  Guarded by a parametrised test that stubs pvlib returning 2-, 3- and 4-tuples and
  asserts both fetchers work against all three. That tests the property directly, with no
  recorded response to rot and no network dependency.

### Removed

- **`metdata_pvgis.py`.** It overlapped `adapters.fetch_pvgis`, which is the newer,
  spec-aware path — it normalises, validates against `support`, emits a canonical frame,
  and imports pvlib lazily rather than at module import. Everything the module held is
  covered elsewhere: `fetch_pvgis_hourly` → `adapters.fetch_pvgis`; `add_time_columns` →
  `adapters._add_index_cols`; `save_hourly` → `adapters._write_cache`;
  `SITE_CRETE`/`SITE_PARIS` → `examples/tools/site_data.py`; `fetch_pvgis_tmy` → the new
  adapter function above. Its `DATA_DIR`/`XLSX_FNAME` pointed at a pre-move cache path and
  went with it.
- **Two concept scripts that duplicated a use case.**
  `concepts/example_markov_generation.py` (a month subset, ten profiles, no comparison)
  is superseded by the `day_envelope_*` scripts, which ask the same question against real
  observations; `EnvSeriesGenerator` on a month subset is still demonstrated by
  `concepts/example_rolling_window.py`, which contrasts it with the window and is the
  point of that script. `concepts/example_synthetic_year.py` is superseded by
  `use_cases/year/synthetic_year.py`; its year heatmap — the one thing it had that the use
  case did not — moved across as the opt-in plot above.
  `concepts/example_exploratory_analysis.py` stays month-based: it is the only runnable
  demonstration of `sup_plot_lib`, and that is what it is for.

---

## [0.2.0] — 2026-07-22

**Breaking.** The package now carries an explicit notion of what each quantity physically
*is*, and the chain is started and continued from fitted distributions rather than from a
supplied value. 252 tests passing (was 152). Design:
[`docs/design/completed/variable-specs-and-initialisation.md`](docs/design/completed/variable-specs-and-initialisation.md).

### Added

- **`variables.py`** — `VariableSpec` (`support`, `units`, `long_name`) and an extensible
  registry. Ships `IRRADIANCE` (shared by the four `poa_*` columns), `TEMP_AIR` and
  `WIND_SPEED`; `register()` makes any further column modellable with no change to the
  package.
- **`constants.py`** — `INDEX_COLS`, `SHIPPED_ATTRS` and `modelled_attrs()`, replacing
  two independently maintained column lists.
- **`adapters.py`** — optional collection helper: `fetch_pvgis` (with caching),
  per-source column renaming, and `validate_support`, which turns kW/m²-read-as-W/m² into
  an error at the boundary.
- **`DayWindowGenerator.generate_series(start, n_days)`** — a continuous series chained
  across midnight, replacing hand-rolled calendar loops in the examples.
- **π(x₀)** — a fitted initial distribution per training window, and a **cross-midnight
  model** 23:00 (d−1) → 00:00 (d) built from genuinely consecutive calendar dates.
- **`Kind`** enum (`KDE_2D` / `KDE_1D` / `CONSTANT`) and `is_degenerate`.
- **Leap-year behaviour verified and locked in.** `tests/test_leap_year_windows.py`
  (30 tests) over a multi-leap and a leap-free synthetic record, plus
  `examples/concepts/example_leap_year_windows.py`. A Feb 28 window pools Feb 29 from the
  years that have one and Mar 1 from all of them; a Feb 29 target is generable from a
  record containing no leap day at all. Two consequences are documented rather than left
  to be discovered: non-leap years contribute one day fewer to any window spanning slot
  60, and a Feb 29 model is overwhelmingly built from its neighbours (3 of 10 years
  contribute a real one). Documented in [`docs/source/theory.md`](docs/source/theory.md)
  and [`rolling-day-window.md`](docs/design/completed/rolling-day-window.md) Caveat B.
- **`tests/conftest.py`** — headless matplotlib by construction, so `MPLBACKEND=Agg` no
  longer has to be set by hand.
- **`docs/design/completed/`** — archive for design docs whose feature has landed and is
  green, so `docs/design/` holds only work in flight.
- `CHANGELOG.md` (this file).

### Changed

- **Sampling is truncated to each variable's physical support** in both the 1D and 2D
  paths, and the ±10 % domain padding is gone. Generated negatives: **0.00 %** (was
  1.29 % `poa_direct`, 1.99 % `poa_sky_diffuse`) — by construction, since `np.interp`
  cannot return a value outside the domain it is given.
- **Hour 0 is drawn from π(x₀), or from the cross-midnight model when continuing a
  series** — never from a fabricated same-day pair. Cross-midnight correlation is 0.981
  (`wind_speed`) and 0.998 (`temp_air`), against 0.360 and 0.890 for the pairs the old
  hour-0 model learned.
- **"Irradiance starts at zero" is read off the data.** Every observed 00:00 irradiance
  is zero, so π(x₀) degenerates to a spike there.
- **`attr_str` validates against the registry, not a whitelist**, and ingestion keeps
  `INDEX_COLS` plus every registered column, dropping the rest (`solar_elevation`, `Int`).
  The caller's frame is never mutated.
- **Randomness is threaded** through `np.random.Generator`; the process-wide
  `np.random.seed` mutation is gone.
- `gen_day_sequence` → `gen_day` (no `start_value`); `build_transition_pairs` covers
  hours 1–23 only; `singularity_type` string codes → the `Kind` enum.

### Fixed

- **Out-of-domain conditioning values no longer produce NaN.** Truncation constrains the
  sampling domain but not the value being conditioned on, which in a rolling series can
  land outside the fitted range (all-zero density → `0/0` → NaN → the next hour dies).
  Now clamped into the fitted range with a marginal fallback behind it. Measured at
  **0.27 % (1/364)** of midnight steps over a generated year and pinned by
  `tests/test_window_boundary_continuity.py`.
- `example_leap_year_windows.py` called an undefined `main()` at import.

### Removed

- `gen_day_sequence`, `generate_ensemble`, `start_value`, `singularity_type`,
  `MET_DATA_COLS`, `MODELLED_ATTRS` as a gate, and `REQUIRED_COLS` (now
  `validate_columns()`, which can express "all index columns **and any** registered one").
  An ensemble is an explicit loop.
- Unused imports in `markov_chain_simulator_kde2d.py`, `met_data_processor.py` and
  `sup_plot_lib.py`, dropping the latter's incidental `scipy.interpolate` and
  `mpl_toolkits` dependencies.

### Decisions

- **`generate_series` is deliberately not on `EnvSeriesGenerator`.** A month subset has
  one pooled π(x₀) and one set of transitions shared by every generated day, so "what does
  day 32 look like" has no honest answer. The month path keeps single-day generation; the
  absence is guarded by a test.
  [Rationale](docs/design/completed/variable-specs-and-initialisation.md).
- **Fitted generators are deliberately not persisted to disk.** Persisting them would
  write numbers already in the source data, ~31× duplicated across overlapping windows, to
  save ~58 ms of fitting.
  [Rationale](docs/design/completed/rolling-day-window.md).

### Known at release

- Generated irradiance overshoots observed daily totals, and the support work moved that
  the wrong way on the shipped record (+13 % → +14 %): removing the lower pad restored
  mass that used to escape below zero, which outweighed removing the upper pad. Tracked as
  `TODOs.md` **FIX-1**.

### Commits

`3c8e534` design-doc archive · `88ea99c` `constants.py` consolidation · `e2337e4`
physical support, fitted π(x₀), chained series · `662682b`, `e690750` finish 0.2.0.

---

## [0.1.0] — 2026-07-10

First tagged release (`v0.1.0`, commit `222e100`). Reconstructed from git history rather
than a contemporaneous changelog — dates are commit dates on `main`.

### Added

- **`MarkovChainSimulator2dKDE`** — the core engine: a 2D-KDE continuous Markov-chain
  simulator with `CC`/`CN`/`NC`/`NN` handling for degenerate (constant-valued) hours.
- Two alternative simulators: `ContinuousMarkovChainSimulator` (binned 1D KDE) and
  `MarkovChainSimulatorDiscrete` (discrete transition matrix).
- **`EnvSeriesGenerator`** / `generate_hr_simulator` — 24 hourly simulators fitted from a
  month-sliced subset and stitched into full-day profiles; `generate_ensemble` for batches.
- **`MetDataProcessor`** — ingestion, column validation, `get_month_subset`.
- `metdata_pvgis.py` — `pvlib.iotools` wrappers for PVGIS hourly/TMY data with local
  caching.
- `sup_plot_lib.py` — exploratory plotting helpers.
- Sphinx documentation (quickstart, theory, examples, API), published via GitHub Actions
  and Cloudflare Workers.
- Initial test suite; packaging (`pyproject.toml`, `uv.lock`), `py.typed`.

### Fixed

- Documentation publishing pipeline: Cloudflare Wrangler version failure and the docs URL
  (`7246695`, `c62982e`, `222e100`).

### Commits

`8dedbbb` initial commit · `c849c79` initial codebase, green pytest · `b54fae7` docs
publishing · `114c3ab` finish 0.1.0 · `7246695`, `c62982e`, `222e100` docs hotfixes.
