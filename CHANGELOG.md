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

## Current sprint (unreleased)

Targeting no particular version yet — none of this is breaking. The breaking work planned
for 0.2.0 is tracked separately in
[`docs/design/variable-specs-and-initialisation.md`](docs/design/variable-specs-and-initialisation.md)
and has not started.

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
