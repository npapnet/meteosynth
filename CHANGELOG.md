# Changelog

All notable changes to `meteosynth` are recorded here.

**Style.** Work lands first under **Current sprint** — an unreleased, in-progress bucket
— and matures into a numbered version section once it ships. A sprint section is renamed
to its version heading (with a date) at release time rather than copied, so history reads
as one continuous log rather than a duplicate of the sprint notes. Categories follow
[Keep a Changelog](https://keepachangelog.com/) (`Added` / `Changed` / `Fixed` / `Removed`)
where they apply, loosely — this project prioritises saying *why*, in the style of
`TODOs.md` and `docs/design/`, over a strict template.

---

## Current sprint (unreleased) — targeting 0.2.0

**Breaking.** Implements
[`docs/design/variable-specs-and-initialisation.md`](docs/design/variable-specs-and-initialisation.md)
in full. The package had no notion of what each quantity physically *is*, and four
defects traced back to that absence: generated irradiance went negative, out-of-domain
starts crashed, hour 0 learned a 23-hour backwards jump, and a PVGIS quality flag was a
modellable "meteorological attribute".

252 tests passing (was 152).

### Added

- **`src/meteosynth/variables.py`** — `VariableSpec` and an extensible registry. A spec
  carries **constraints, not an identity**: it has no `name` field, so several column
  names share one. All four plane-of-array irradiance components share `IRRADIANCE`,
  since they differ only in which part of the incoming radiation they count. The names
  stay distinct because `poa_global ≈ direct + sky_diffuse + ground_diffuse`, so
  collapsing them would let a global series train under a name meaning direct — same
  units, same support, wrong by roughly a factor of two, undetectable. **The column name
  is the provenance**, which is why nothing in this design needs a metadata sidecar.
- **`src/meteosynth/adapters.py`** — an *optional* collection helper. The contract with
  the core is an ordinary canonical DataFrame, so a user who already has data never
  touches an adapter. `fetch_pvgis` defaults to `poa_global` (PVGIS returns either global
  or the three components depending on one `pvlib` flag) with `irradiance="direct"` as
  the override, plus optional caching. Renaming is keyed per source; support validation
  turns kW/m²-read-as-W/m² into an error at the boundary.
- **`DayWindowGenerator.generate_series(start, n_days)`** — a continuous chained series.
  Absorbs what was a hand-rolled loop in `examples/example_synthetic_year.py`.
- **π(x₀)** — a fitted initial distribution per training window, reusing the existing 1D
  KDE machinery so a degenerate π(x₀) returns the constant.
- **`Kind` enum** (`KDE_2D` / `KDE_1D` / `CONSTANT`) and `is_degenerate`.

### Changed

- **Sampling is truncated to each variable's physical support** in *both* paths, and the
  ±10% domain padding is gone. Negatives go from 1.29% (`poa_direct`) and 1.99%
  (`poa_sky_diffuse`) to **0.00%**, guaranteed by construction rather than hoped for:
  `np.interp` cannot return a value outside the domain it is given.
- **"Irradiance starts at zero" is now read off the data**, not hard-coded. Every
  observed 00:00 irradiance is zero, so π(x₀) degenerates to a spike at zero.
- **`attr_str` validates against the registry, not a whitelist.** Register a spec for
  `rel_humidity` and it is modellable with no change to this package.
- **Ingestion keeps `INDEX_COLS` + every registered column and drops the rest — by rule.**
  `solar_elevation` and `Int` fall out for having no spec, as does any future provider's
  quirk column, with no maintained exclusion list. The caller's original frame is never
  mutated. Registering a spec for `solar_elevation` makes it survive, and a test asserts
  exactly that, so the mechanism is the registry rather than a hidden list.
- **Randomness is threaded, not global.** `np.random.Generator` replaces the
  process-wide `np.random.seed` mutation, which an ensemble built from *n* independent
  one-day calls could not be seeded through.
- `gen_day_sequence` → `gen_day` (no `start_value`); `build_transition_pairs` covers
  hours 1–23 only.

### Fixed

- **The out-of-domain crash, which truncation alone did not close.** Truncation
  constrains the *sampling* domain but not the *conditioning value*. In a rolling series
  day *d*'s 23:00 comes from day *d*'s window fit while day *d+1*'s cross-midnight model
  is fitted on a different overlapping sample, so the conditioning value can land outside
  the fitted range — all-zero density, `0/0` → NaN, and the next hour dies with
  `ValueError: array must not contain infs or NaNs`. Now clamped into the fitted range,
  with a marginal fallback behind it. Measured at **0.27% (1/364)** of midnight steps
  over a generated year and pinned by `tests/test_window_boundary_continuity.py`, which
  records the number rather than asserting a hope.
- **Hour 0 no longer learns a 23-hour backwards jump.** It had no within-day predecessor
  and was paired with hour 23 of the *same* day. Re-measured on the full record:
  cross-midnight correlation is 0.981 (`wind_speed`) and 0.998 (`temp_air`) against
  0.360 and 0.890 for the pairs the old model learned. The design doc's original 0.218 /
  0.552 figures do not reproduce against the full 2011–2012 record.
- `examples/example_leap_year_windows.py` called an undefined `main()` at import (a
  pre-existing bug, unrelated to this work — it is a `#%%` cell script).

### Removed

- `gen_day_sequence`, `generate_ensemble`, `start_value`, `singularity_type`,
  `MET_DATA_COLS`, `MODELLED_ATTRS` as a gate, `REQUIRED_COLS`. An ensemble is now an
  explicit loop; `REQUIRED_COLS` could not express the new conditional rule ("all of
  these index columns and *any* registered one") and became `validate_columns()`.
- `generate_series` is deliberately **not** on `EnvSeriesGenerator`. A month subset has
  one pooled π(x₀) and one set of transitions shared by every generated day, so there is
  no honest answer to "what does day 32 look like". The month path keeps single-day
  generation; the absence is the demarcation, guarded by a test.

### Known

- Item 2's overshoot moved the **wrong way**: 670 → 678 kWh/m² (+13% → +14%) on the
  shipped record. Removing the lower pad restores mass that used to escape below zero,
  and that outweighed removing the upper pad. Recorded in `TODOs.md` item 2, which now
  notes the padding is two-sided and asks for the two sides to be measured separately.

---

## Earlier in this sprint (pre-0.2.0 work, non-breaking)

### Added

- `src/meteosynth/constants.py` — `MODELLED_ATTRS`, `INDEX_COLS`, `REQUIRED_COLS`: a
  single canonical source for "which columns matter", exported from the package
  top-level (`from meteosynth import MODELLED_ATTRS`). Replaces two independently
  hand-maintained copies — `generators.MET_DATA_COLS` and a private
  `MetDataProcessor.__met_data_columns` — that had no mechanism keeping them in sync.
  Resolves the inline TODO at the old `generators.py:38` and the one on
  `MetDataProcessor` about exposing its required columns for transparency. This is also
  a prerequisite for `variable-specs-and-initialisation.md`'s step 6 (trimming the
  modelled-attribute list to four columns): that becomes a one-line edit to
  `constants.py` instead of a two-file coordination problem.
- `tests/conftest.py` — calls `matplotlib.use("Agg")` at collection time, so the test
  suite is headless by construction. Previously `MPLBACKEND=Agg` had to be set by hand
  before invoking pytest (documented in `README.md` / `quickstart.md` but not enforced).
- `docs/design/completed/` — archive location for design docs whose feature has landed
  and is green in the test suite, so `docs/design/` itself only holds work still in
  flight. `rolling-day-window.md` and `transition-pair-alignment.md` moved there, each
  with an archive note recording the move date, the implementation date, and the commits
  that landed it.
- `CHANGELOG.md` (this file).

### Changed

- `generators.MET_DATA_COLS` is now `constants.MODELLED_ATTRS` re-exported under its
  historical name (was a `list`, now a `tuple` — no behavioural difference; equality and
  membership checks are unaffected).
- `MetDataProcessor`'s ingestion assertion reads `constants.REQUIRED_COLS` instead of a
  private duplicate list.
- `MarkovChainSimulator2dKDE.singularity_type` type-hinted as `Optional[str]`, correcting
  the previous `str = None`.
- `docs/design/README.md` split into an **active** table (proposed / in-progress docs)
  and a **completed** table (implemented and tested), rather than one undifferentiated
  list.

### Removed

- Unused imports with no behavioural effect: `Union` from
  `markov_chain_simulator_kde2d.py`; `numpy` from `met_data_processor.py`;
  `make_axes_locatable`, `make_interp_spline`, `BSpline` from `sup_plot_lib.py` (the
  latter two also drop that module's incidental dependency on `scipy.interpolate` and
  `mpl_toolkits.axes_grid1` — neither was actually exercised there).

Verified against the full test suite throughout (152/152 passing, no `MPLBACKEND` set by
hand) — every change above is either a pure consolidation or an unused-code removal, none
change observable behaviour.

---

## [0.1.0] — 2026-07-10

First tagged release (`v0.1.0`, commit `222e100`). Reconstructed from git history rather
than a contemporaneous changelog, which did not exist yet — dates are commit dates on
`main`.

### Added

- Core simulation engine: `MarkovChainSimulator2dKDE` — 2D-KDE-based continuous Markov
  chain simulator with `CC`/`CN`/`NC`/`NN` singularity handling for degenerate
  (constant-valued) hours.
- Two additional standalone simulator implementations, offered as alternatives:
  `ContinuousMarkovChainSimulator` (1D-KDE, binned) and `MarkovChainSimulatorDiscrete`
  (discrete-state transition matrix).
- `EnvSeriesGenerator` / `generate_hr_simulator` (`generators.py`) — fits 24 hourly
  simulators from a month-sliced training subset and stitches them into full-day
  synthetic profiles; `generate_ensemble` for Monte-Carlo-style batches of days.
- `MetDataProcessor` (`met_data_processor.py`) — ingestion, column validation, and
  `get_month_subset` slicing of a PVGIS-shaped hourly frame.
- `metdata_pvgis.py` — thin `pvlib.iotools` wrappers to fetch hourly / TMY data from
  PVGIS and cache it locally.
- `sup_plot_lib.py` — exploratory Seaborn/Matplotlib plotting helpers.
- Sphinx documentation (`docs/source/`): quickstart, theory, examples, and API reference;
  published via GitHub Actions + Cloudflare Workers.
- Initial test suite: `tests/test_markov_chain_simulator_kde2d.py`,
  `tests/test_markov_chain_simulator_singularity.py`.
- Packaging (`pyproject.toml`, `uv.lock`), `py.typed` marker.

### Fixed

- Documentation publishing pipeline: Cloudflare Wrangler version failure and the
  documentation URL, in three follow-up commits the same day the tag was cut
  (`7246695`, `c62982e`, `222e100`).

### Commits

`8dedbbb` Initial commit · `c849c79` initial codebase, green pytest · `b54fae7` GitHub
Actions + Cloudflare Workers docs publishing · `114c3ab` Finish v0.1.0 · `7246695`,
`c62982e`, `222e100` docs-publishing hotfixes.
