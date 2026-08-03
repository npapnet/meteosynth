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

## Current sprint — unreleased

**The suite can now tell when the sampler changes, and the caller can now say which
sampler runs.** Two items, in that order, because the first is what made the second safe
to take. `CHORE-12` closed a demonstrated blind spot: the tests checked rules but never
the numbers, so `PERF-1`'s entirely new sampling path passed 271 of them unmodified and
would have passed had it been wrong. `FEAT-17` then replaced the hidden counter that
decided which path a draw came from with three named modes. **471 tests passing
(was 447).**

### Added

- **A calibration test: the suite checks what the sampler *produces*, not only that it
  follows the rules** (`CHORE-12`). `tests/test_sampler_calibration.py` trains on the
  two-year synthetic fixture, draws 300 realisations at two calendar dates for all three
  attributes, and asserts the synthetic days match the pool they were fitted to on level
  (within 5 %), match a recorded reference on spread (within 25 %), and are finite and
  inside physical support. 18 tests, ~20 s, no network.

  **It was itself validated by fault injection**, since a test that cannot fail is what
  this item exists to complain about: a ±6–10 % level shift and a halved or 1.6× spread
  were each caught in **6 of 6 cells**, with **0 of 6** false positives on an untouched
  control.

  Two measurements shaped it, both recorded in the file. **Spread cannot be compared to
  the training pool**: a healthy `temp_air` reads 0.61 because the pool carries
  within-window seasonal drift the model deliberately does not reproduce, while a healthy
  `poa_direct` reads 0.95 — and narrowing the window fixes one while breaking the other.
  So spread is checked against its own measured value. And the fixture's **winter is
  darker than any real site** (0.7 W/m² daily mean in late December against 86 for
  Heraklion), so the second date is 21 October, where a level ratio is not two near-zero
  numbers divided by each other.

- **`sampling=` — say which path answers a draw, instead of a hidden counter deciding**
  (`FEAT-17`). Three named modes on `generate_series`, `generate_ensemble`,
  `write_ensemble`, `DayWindowGenerator`, `EnvSeriesGenerator`, `for_day`/`for_slot` and
  the simulator itself:

  | mode | behaviour |
  | :--- | :--- |
  | `"auto"` *(default)* | resolve **once, before drawing**, from what is known — an ensemble knows `n_realisations`; a bare `gen_day` loop knows nothing, so the counter advises |
  | `"exact"` | never build a quantile grid |
  | `"grid"` | build it up front, always |

  Exported as `SAMPLING_PATHS` and `resolve_sampling`. A mistyped mode raises rather than
  silently sampling from something else. `DayWindowGenerator`'s LRU cache is keyed on
  `(slot, sampling)`, so a generator fitted for one path is never handed back for another.

### Fixed

- **`precompute=False` did not disable the cached sampler** (`FEAT-17`). It skipped only
  the *eager* build; a hidden counter on each simulator still built the grid on the 65th
  draw, so **936 of 1000 realisations came from a grid the caller had declined** — an
  opt-out landing within 1.8× of the opt-in and 7× from what its name implied. Measured at
  N = 1000 on a 365-day year: `precompute=True` 20.2 min, `precompute=False` 36.8 min, a
  genuine exact path 4.5 h. Verified end to end at N = 200: `sampling="exact"` builds
  **0 of 23** grids where `precompute=False` built 23 of 23.

  Which sampler answers a draw no longer depends on call history at all. The counter
  survives as **advice only**: it keeps counting and logs once that a grid would have paid
  for itself, so the optimisation stays discoverable without ever changing a number.

### Removed

- **`precompute=` on `generate_ensemble` and `write_ensemble`** (`FEAT-17`), replaced by
  `sampling=`. It was the misnamed parameter above, and a boolean could not express the
  third state that mattered. **Ensemble files record the resolved path under a `sampling`
  key** in place of `precompute` — never `"auto"`, since a file should record what
  happened rather than what was asked for.

### Decisions

- **Choosing a sampling path is about determinism, not accuracy.** The grid's extra error
  is 0.03 % on the mean and 0.04–0.31 % on the standard deviation — ~100× below what the
  diagnostics harness can resolve — so the axis is *exact vs fast*, not *precise vs
  performant*. Pinned by a test asserting the two paths agree distributionally.
- **A calibration test asserts statistics, never individual draws.** A golden test on a
  sampler breaks whenever `numpy` or `scipy` changes generator internals without anything
  being wrong. Every tolerance was set from measured Monte-Carlo noise (±0.1–0.6 % on the
  level, ±3–9 % on the spread) before the threshold was chosen.

---

## [0.3.2] — 2026-08-03

**Collect once per site, then work locally — and put the files where the work is.** Two
changes, in that order. A download used to be cached only if you named a file for it, and
a cached file only answered the exact period it was fetched for, so a second training
range meant a second download and finding either meant remembering its filename. Now
`fetch_pvgis` takes the provider's widest range by default, keeps every column it returns,
caches it, and finds it again by **provenance** — a record covering 2005–2023 answers a
request for 2010–2020 by narrowing (`FEAT-4`).

That settled *how* a record is found; `FEAT-21` settled *where*. A run has one workspace
root — the script's own folder when you run a script, the folder you are standing in when
you run a command — with `data/` for what was collected and `output/` for what was
generated hanging off it. **447 tests passing (was 357).**

### Added

- **`meteosynth.paths` — where a run reads and writes** (`FEAT-21`). One workspace root
  per run, with `data/` for what was collected and `output/` for what was generated
  hanging off it. `workspace(__file__)` roots at **the script's own folder**, so a script
  reads and writes beside itself whichever directory it was launched from;
  `workspace()` roots at the working directory, which is what a command line means and
  what the future CLI (`FEAT-14`) will call. Exports `Workspace` and `workspace` at the
  top level; `store.default_data_dir()` is now defined as `workspace().data_dir`, so the
  two cannot drift. **A relative `data_dir=` is read from the working directory**, not
  from the calling script — a path you type means what your shell would make of it. Still
  no environment variable and no global setting. See
  [`FEAT-21-workspace-and-file-locations.md`](docs/design/completed/FEAT-21-workspace-and-file-locations.md).
- **`meteosynth.store` — finding a collected record without opening it** (`FEAT-4`).
  `scan` and `resolve` read provenance and column names from **parquet footers**, so a
  folder is discoverable without loading any data: measured at **1.3 ms/file against
  113 ms** for a full `MetDataset.load`, 86× cheaper, which is what makes a scan viable
  as the selection mechanism instead of a manifest. No index file, no sidecar — the
  provenance `FEAT-13` put inside each record is the only source of truth. Also
  `default_data_dir`, `record_filename`, `describe_store` and `AmbiguousRecordError`.
- **`MetDataset.get_period_subset(start, end)`** — the years a request asked for, as a
  dataset in its own right, carrying provenance for **the period it now holds** plus a
  note naming where it was cut from. Verified exact on the 19-year Heraklion record
  narrowed to its middle 11 against the same 11 fetched separately: identical row count,
  index columns aligned, `temp_air` and `wind_speed` bit-identical, `poa_global` within
  **0.01 W/m²** — PVGIS's own two-decimal rounding. An uncontained period raises rather
  than returning the overlap, which would answer a different question silently.
- **`adapters.probe_year_range`** — asks PVGIS for year 1900 because the resulting error
  names both bounds, so one failed request gives the full range without bisecting. It was
  written in `examples/diagnostics-overshoot/step1_fetch.py` and moved into the library
  when "collect the widest range" became the default; the diagnostic now calls it.
- **Site labels resolve coordinates.** `fetch_pvgis(35.3387, 25.1442, site="heraklion")`
  once, then `fetch_pvgis(site="heraklion", start=2010, end=2020)` forever. The label is
  matched against `Provenance.site` in the store — no geocoding, no registry, no config
  file: a name means whatever the first fetch bound it to.

### Changed

- **The timing benchmark runs in a third of the time, and moved to `examples/benchmark/`.**
  It answered "does cost scale with the number of realisations?" by running all three
  attributes at three realisation counts — two-thirds of its budget spent establishing, at
  triple price, a fact its own measurements explain: cost is **attributes × days and
  independent of N**, because it is dominated by a per-day-per-attribute grid build. The
  N sweep now runs the cheapest attribute alone, the additivity control that used to fall
  out of it for free is an explicit fourth sweep (`CROSS_CHECK`), and `N_DAYS` dropped
  from 5. **24.7 min → ~14 min with every ratio intact**: N scaling 1.03× → 0.98×, the
  attribute split 3.24× → 3.36×/3.37×, additivity 1.001 → 1.014.

  Shortening the runs cost sensitivity at first — Sweep C's noise floor, the threshold
  every comparison is judged by, widened from 2.0 % to 7.7 % at three days — but a control
  bought it back. **The first generation in a process runs ~12 % slow**, and it landed on
  Sweep A's baseline, which every other Sweep A row is divided by, making 100× the
  realisations read as *0.91× the time*. It was invisible while Sweep A's rows were 330 s
  of three-attribute work. A discarded warm-up run (`WARMUP`) now pays it off for ~3 % of
  the total, which straightened Sweep A to 1.00× / 1.01× / 1.07× and — since Sweep C's
  first repeat carried the same overhead — **restored the 2.0 % floor**. The shipped
  build measures the original sensitivity at 57 % of the original runtime.

  Also recorded for the first time: **the first calendar *day* of every run costs ~16 %
  more** than the rest, reproducibly, which inflates absolute seconds-per-day at low
  `N_DAYS` but cancels in every ratio.

  `BENCHMARK_VERSION` 2.1 → 4.1, so the history comparison refuses earlier files outright
  rather than reporting a phantom regression against a different measurement. The
  rationale moved out of the module docstring into `examples/benchmark/README.md`, leaving
  the docstring at a quarter of its length.
- **Every example folder is self-contained** (`FEAT-21`). A script collects its record
  into a `data/` folder beside itself and writes into an `output/` folder beside itself,
  both git-ignored, replacing the shared `examples/data/` and `examples/output/`. The
  repository used to demonstrate three different conventions — the working directory in
  `use_cases/year-leros/`, a hard-coded `examples/data` in four more folders, a named file
  in `diagnostics-overshoot/` — so no reader could learn the rule from the examples. The
  Heraklion record is now downloaded once per folder that needs it rather than shared;
  ~530 KB a time, and the price of a folder being copyable on its own.
- **The examples find their records by provenance instead of naming files** (`FEAT-21`).
  `examples/data/` held two overlapping Heraklion records, so discovery would rightly
  refuse to choose and every script named its cache file to get round it. One record per
  folder removes the collision, so the scripts now show the package's ordinary path.
  `Site.cache_path` and `load_site`'s `cache=` argument are gone; `load_site`,
  `save_frame` and `save_figure` take the caller's `Workspace` instead.
  **`examples/diagnostics-overshoot/` still names its file**, and now says why: it fetches
  with `components=False` for PVGIS's own `poa_global`, and `StoredRecord.holds`
  deliberately treats a components record as answering that request. Right for the
  package, wrong for a measuring instrument whose dated findings are cited — so name a
  file when *how* a record was collected is load-bearing, and give a folder when only its
  site and period are.

- **`cache=None` now means "use the project's data store", not "do not cache".**
  Downloads land in `./data/` under the working directory. `data_dir=` picks another
  folder for one call, `cache=<path>` keeps the previous explicit-file behaviour, and
  `cache=False` is the opt-out. Callers relying on the old default will now write files.

  **The store is project-local by construction, with no environment variable and no
  global setting.** Two projects side by side keep two independent stores; a script reads
  the folder it sits next to regardless of which shell launched it. Ambient configuration
  was built and then removed during this sprint, because it lets the same script read a
  different store depending on how it was started — the class of surprise a
  provenance-checked format exists to remove.

  The working directory rather than the calling script's folder, because a library cannot
  reliably locate its caller — it would have to walk the call stack, which breaks in a
  REPL, a notebook and anything frozen. A script that wants its own folder passes
  `data_dir=Path(__file__).parent / "data"`.
- **A cached period is matched by containment, not equality.** A wider record answers a
  narrower request and is narrowed on the way out; one that merely *overlaps* is still a
  mismatch. Both the discovery path and the validation path call one function,
  `store.period_contains`, after the two were written separately and disagreed on the
  no-period case — which showed up as a covering cache being refused.
- **`fetch_pvgis` keeps every column the provider returned**, and `start`/`end` select a
  view rather than sizing the download. PVGIS serves either `poa_global` or the three
  plane-of-array components, never both, so a per-component choice at fetch time meant a
  separate download and file for each; collecting the components serves them all, and
  `poa_global` is derived by summation and **recorded as derived** in provenance.
  `components=False` still gets the provider's own total. Previously the components were
  downloaded and two of the three discarded.
- **`examples/tools/site_data.py` no longer bypasses `fetch_pvgis`.** It existed to fetch
  components and sum them by hand, which the adapter now does, and the unused
  `add_time_columns` is gone. It named its cache file explicitly for a while, because the
  shared `examples/data/` held two overlapping Heraklion records; `FEAT-21` gave each
  folder its own store, so it hands over a folder and lets provenance decide.
- **The test suite can no longer write to the checkout.** An autouse conftest fixture
  runs every test from its own empty working directory — without it a fetching test would
  write into `./data/`, and a later test could then pass by finding that file. `chdir`
  rather than a setting, because the working directory *is* the mechanism.

### Fixed

- **The documented install and run commands did not work** (`FIX-18`). `tqdm` became a
  core dependency and the `examples` extra was removed with it, but 27 commands across 13
  files still said `uv sync --extra examples` / `uv run --extra examples python …`, which
  fails outright: `error: Extra 'examples' is not defined`. `uv sync` alone now runs
  everything under `examples/`.
- **`examples/diagnostics-overshoot/` could not run at all.** Step 1 passed a `.csv` path
  to `fetch_pvgis`, which has required parquet since `FEAT-13`, and then subscripted the
  `MetDataset` it returns as if it were a frame; step 2 read the cache with
  `pd.read_csv`. Broken since 0.3.0 and unnoticed because the harness is not part of the
  test suite. **The repo's measuring instrument works again**, and its output is
  unchanged: `step2` + `step3` regenerate all four summary CSVs byte-identically to the
  committed ones, and the anchor cell reproduces.

### Removed

- **`examples/tools/fetch_site_data.py`** (`FEAT-21`) — primed the one shared
  `examples/data/` store. With a store per script folder there is nothing shared to prime;
  each script fetches into its own on the first run and says so before it starts.
- **`examples/tools/migrate_cache.py`** (`FEAT-21`) — converted the legacy CSV caches to
  parquet. Those CSVs are deleted, and it imported `DATA_DIR` from `site_data`, which no
  longer exists. Dead on both counts.
- **`examples/data/` and `examples/output/`** (`FEAT-21`) — replaced by a `data/` and an
  `output/` inside each example folder.

### Decisions

- **A script's files belong beside the script; a command's belong where it was run.**
  Two entry points, one rule, written down once in `meteosynth.paths` rather than copied
  into each script — the repository had already accumulated three conventions that
  disagreed. An explicitly typed relative path stays relative to the working directory,
  because a path you type should mean what your shell would make of it. See
  [`FEAT-21-workspace-and-file-locations.md`](docs/design/completed/FEAT-21-workspace-and-file-locations.md).
- **Name a file when *how* a record was collected is load-bearing; give a folder when only
  its site and period are.** Discovery matches on site, period and quantity, and treats a
  three-component record as answering a `poa_global` request — exact to PVGIS's own
  rounding. That is right for the package and wrong for `diagnostics-overshoot/`, which
  fetches with `components=False` and whose dated findings are cited, so it is the one
  place in `examples/` that still names its cache file.
- **A folder that could answer a request two ways raises rather than choosing.** Which
  record a result was trained on is part of the result, so a rule like "the widest wins"
  would make it depend on what else is in the folder. `AmbiguousRecordError` lists the
  candidates.
- **Discovery lives in `store.py`; `adapters` stays explicit.** A named file must answer
  the request or raise — that is `CacheMismatchError`, unchanged. Finding an unnamed one
  is a separate operation with a separate failure mode.
- **It is a *store*, not a *cache*, and the vocabulary now says so.** A cache is
  expendable, transparent and shared; this is none of the three. Delete a record and you
  lose the exact input a result was built on — providers revise their archives, so a
  refetch may not return the same numbers, which makes the file part of the analysis
  rather than an accelerator for it. Hence `store.py`, `default_data_dir`,
  `describe_store`, `record_filename` and `AmbiguousRecordError`. The two names published
  in earlier releases — `CacheMismatchError` and the `cache=` parameter — are deliberately
  **not** renamed: `cache=` still means "this exact file", which was always accurate, and
  renaming a shipped exception is a real break for a cosmetic gain.
- **The filename is a convenience, not an identity.** `<source>_<site>_<start>_<end>.parquet`
  exists so a human listing the folder can see what they have; provenance inside the file
  is what is matched, so a renamed file still answers honestly. The convention is exactly
  what `examples/tools/site_data.py` already wrote, so no cached file needed migrating.
- **`fetch_pvgis_tmy` keeps opt-in caching**, and the asymmetry with `fetch_pvgis` is the
  point. Default caching is only safe when a record's identity is fully written into its
  provenance, and a TMY's is not: `coerce_year` and `roll_utc_offset` change what comes
  back — pvlib's `_coerce_and_roll_tmy` rewrites the year *and can roll the series* — and
  neither is a provenance field. A discovered TMY could answer a different question than
  the one asked. Intended for the same default and reverted on finding this.

---

## [0.3.1] — 2026-07-31

**Ensembles are now a first-class operation, and the package's primary use case got ~77×
faster.** Generating N synthetic years used to mean calling `generate_series` N times, which
refits every calendar day's models N times over; the calendar is now walked **once** and every
realisation advances through each day's single fit. Measured on Heraklion 2010–2020,
`poa_global`, a 365-day year: 1000 realisations drop from **~27 h to ~21 min**. 345 tests
passing (was 314). Design:
[`docs/design/completed/FEAT-15-ensemble-generation.md`](docs/design/completed/FEAT-15-ensemble-generation.md).

### Added

- **`DayWindowGenerator.generate_ensemble(start, n_days, n_realisations, seed=…)`**
  (`FEAT-15`) — N independent chained series in one calendar walk, returning
  `(n_realisations, n_days, 24)`. Statistically identical to N calls to `generate_series`:
  each realisation is its own chain, and realisation *i*'s hour 0 on day *d* still conditions
  on realisation *i*'s own 23:00 of day *d−1*. Only the order of evaluation changed.
- **`write_ensemble` / `read_ensemble` / `Ensemble`** — one **long-format parquet file** per
  ensemble, streamed one calendar day per row group, so peak memory holds one day rather than
  the whole ensemble. Schema: `realisation`, `day_index`, `month`, `day`, `hour`, one column
  per attribute, with `ensemble_schema_version` and the full generating parameters (seed,
  span, window half-width, bandwidth, source provenance) embedded as parquet key-value
  metadata. A newer schema version is refused rather than guessed at, as `MetDataset.load`
  does. `Ensemble.realisation(i)` and `Ensemble.to_wide(attr)` are the views.
- **`ensemble_to_xlsx`** — a lossy one-way export, **pivoted to wide**, one sheet per
  attribute. The pivot is forced, not preferred: a long-format ensemble of 1000 realisations
  is 8.76 M rows against Excel's 1 048 576 limit, capping long format at ~119 realisations.
  Needs the new `meteosynth[excel]` extra; it refuses rather than truncates past a
  worksheet's limits.
- **`realisation_stream(seed, realisation, attr_str)`** — the keying that makes a realisation
  identifiable. Streams are derived from `(seed, realisation index, crc32(attribute name))`,
  so a realisation does not depend on how many were requested, and an attribute does not
  depend on which others were requested alongside it.
- **`EnvSeriesGenerator.precompute_grids()`** — build a day's cached quantile grids up front,
  so every member of an ensemble is drawn from the same sampler instead of the sampler
  switching part-way through. This is why an ensemble **above 64 realisations** does not
  reproduce a chained series bit-for-bit: the shift is ~0.02 % on a daily total, KS p = 1.0.
  Pass `precompute=` explicitly to compare two ensembles that straddle that boundary.

### Changed

- **`generate_series` is now the one-realisation case of the same walk**, not a second
  implementation — so the calendar rules (the Feb 29 skip, the New Year wrap, which models a
  day uses) cannot drift between the two. Verified **bit-for-bit identical** to the previous
  implementation across three attributes and three calendar spans, including the
  `rng=<Generator>` path that advances a shared stream across calls.
- **`DayWindowGenerator`'s docstring no longer claims its LRU cache helps a calendar walk.**
  It does not: an ordered walk visits each slot exactly once and never returns, so the hit
  rate is zero at any cache size. Measured — a 30-day walk repeated 5 times performed 150
  fits for 30 distinct days. The cache earns its keep only for repeated requests for the
  *same* day (`gen_day`).
- **`examples/use_cases/year/synthetic_year.py` generates an ensemble** rather than one
  series per realisation, and reports the spread across realisations — the quantity a single
  series cannot give you.

### Decisions

- **Random streams are keyed by realisation index and attribute name**, never by position or
  a shared stream — both alternatives make a result depend on the shape of the request rather
  than on the seed.
  [Rationale](docs/design/completed/FEAT-15-ensemble-generation.md#1-randomness-one-stream-per-realisation-attribute-keyed-by-name).
- **Ensemble output is one long-format parquet file; `.xlsx` is a pivoted export.**
  [Rationale](docs/design/completed/FEAT-15-ensemble-generation.md#3-output-one-long-format-parquet-file-flushed-per-day).
- **Every member of an ensemble is drawn from the same sampler**, at the cost of bit-for-bit
  agreement with a chained series above 64 realisations, because exchangeability is what
  makes members comparable.
  [Rationale](docs/design/completed/FEAT-15-ensemble-generation.md#2-draw-every-realisation-from-the-same-sampler).
- **Draws are not batched across realisations.** Fitting and grid-building are ~84 % of the
  per-day cost, so batching is worth ~1.2× at most; deferred as `PERF-16`, which targets the
  grid **build** (~79 % of per-day cost at N = 1000) instead.

### Commits

`399a330` generate ensembles in one calendar walk (`FEAT-15`) · `8674a58` finish
`perf-for_n_realisations` · `4a72a37` plan · `20e12f9` README description and pruning.

---

## [0.3.0] — 2026-07-29

**Breaking.** The training record is now an object with a format. `MetDataset` replaces
`MetDataProcessor` as the package's core noun: source-agnostic, validated on
construction, and round-trippable to disk without loss. Adapters construct one rather
than returning a bare frame, so a cached file can be matched against the question being
asked of it instead of trusted on its path. 314 tests passing (was 252). Design:
[`docs/design/completed/FEAT-13-met-dataset-format.md`](docs/design/completed/FEAT-13-met-dataset-format.md).

The sprint also carries the measurement work that preceded it: `PERF-1` made ensemble
sampling ~8× faster, `FIX-1` was restated on measurement and deferred, and
`examples/diagnostics-overshoot/` became the instrument those two were argued with.

### Added

- **`MetDataset` — the training record is now an object with a format** (`FEAT-13`).
  The package's core business is generating synthetic series from a training record, and
  getting that record is auxiliary; but nothing *was* the record, so provenance had
  nowhere to live except a fetcher's cache and validation nowhere except a fetcher's
  boundary check. `MetDataset` is that missing noun: source-agnostic, validated on
  construction, and round-trippable to disk. `MetDataset.load(p) == ds` holds by
  construction.
- **Schema v1, enforced however the data arrived.** Canonical dtypes and row order;
  `(year, month, day, hour)` unique; a real `all_leap` calendar; unregistered columns
  dropped. Duplicate rows and impossible calendars now raise at the front door — both
  were already fatal, but inside `pivot` and `day_slot`, several calls from the data that
  needed fixing. Values outside a spec's physical support are **clipped, warned and
  counted** rather than refused: real records carry small negative irradiance at night
  from sensor noise, and the check cannot catch the unit errors it was written for anyway
  (280 K and 20 °F both sit inside support). Incomplete days are reported, not rejected.
- **Lossless parquet I/O with provenance embedded.** `save`/`load` go through `pyarrow`
  on both sides, storing source, site, coordinates, period and fetch date as parquet
  key-value metadata — a documented feature of the format rather than pandas-internal
  `attrs` behaviour. A saved dataset stays readable by any plain `pd.read_parquet`.
  `read_csv`/`to_csv` remain as explicitly lossy interchange, named so they cannot be
  mistaken for a matching pair.
- **A cache is matched against the request, not trusted on its path** (`FEAT-1`,
  superseded into `FEAT-13`). `fetch_pvgis` and `fetch_pvgis_tmy` return a `MetDataset`
  and compare a warm cache's provenance — source, coordinates to 4 dp (~11 m), period,
  and whether it holds the requested column — raising `CacheMismatchError` rather than
  silently answering a Paris request with a Heraklion file. `force_refetch=True` is the
  explicit way to repurpose a path.
- **`MetDataset.irradiance_column`** (`FEAT-2` (1)) resolves which column to model from
  what is present, so a script stops caring whether its record came from PVGIS hourly
  (`poa_global`) or a TMY (`ghi`). It refuses to guess when only *components* of a total
  are present: a component is a part of a total, and answering with `poa_direct` would be
  the factor-of-two error the distinct column names exist to prevent.
- **`MetDataset.describe()`** (`FEAT-5`) reports rows, years, dates, incomplete dates,
  per-column non-null counts, what was clipped, and provenance.
- **`examples/tools/migrate_cache.py`** converts the legacy CSV caches in place,
  recovering site and period from the filename — the only place the old format recorded
  them, and the weakness the new one removes. Measured on the shipped caches: 4.9 MB →
  0.6 MB, 4.3 MB → 0.5 MB, 0.8 MB → 0.1 MB.
- **A progress bar on the day walk.** `generate_series(..., progress=True)` shows a
  `tqdm` bar over the days, used by `year/synthetic_year.py` (outer bar over the run,
  inner bar over each attribute's 365 days). Opt-in and non-persistent: an ensemble is
  this method called hundreds of times, and hundreds of leftover bars would be worse than
  none. Measured at ~2.7 days/s, so ~2 min per attribute on the 11-year record.
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
- **`examples/diagnostics-overshoot/`** — the repo's measuring instrument, and the first
  thing to cite when making a claim about generator accuracy. Fits on a 19-year PVGIS
  record, draws 1000 synthetic days at each of four dates against two bandwidths, and
  scores them against the pooled window they were fitted to. One command
  (`run_all.py`, ~5 min) behind four separately-runnable steps.

  What makes it evidence rather than a demonstration: **the training pool is the
  reference**, so the comparison target is a known quantity rather than an estimate;
  a **null control** (observed data resampled in place of synthetic — must show nothing)
  and a **positive control** (a +10 % injection — must be detected) run before any result
  is read; an **anchor cell** reproduces the prior run's configuration so a harness change
  cannot silently move the numbers; a **pre-registered decision rule** in `PLAN.md` fixes
  the reading before the data arrives; and findings are written to **one dated file per
  run**, never edited afterwards. `step3` reads only the CSVs `step2` wrote, so any check
  made by hand against them is a check against exactly what the analysis saw.
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

- **`MetDataProcessor` is now `MetDataset`, in `dataset.py`.** The name described a
  processor; the thing is a dataset. Its slicing methods are unchanged in behaviour, and
  the `mdp` abbreviation is retired throughout.
- **`validate_support` is an opt-in hard check, not the ingestion rule.** Ingestion clips
  and reports; callers who would rather be stopped than repaired call it directly. This
  removes the asymmetry where adapter data was validated more strictly than a hand-built
  frame — which was the actual hole: `MetDataProcessor` never called it at all, so
  `poa_global = -500` ingested cleanly on the core path.
- **`pyarrow` replaces `openpyxl` as a dependency.** XLSX support is gone: it existed to
  serve a cache format that CSV export covers, while parquet is the only format that
  round-trips. The `.parquet` branch of the old cache writer had never worked — `pyarrow`
  was not installed, so it raised `ImportError` on that path.
- **Sampling is ~8× faster for ensembles** (`PERF-1`). `get_next_state` used to evaluate a
  1000-point KDE grid on every call — ~97 % of generation runtime. A simulator that turns
  out to be sampled often now caches its conditional **inverse CDF** over 64 uniform
  `previous` nodes and answers with two interpolations. Measured on 21 March, Heraklion
  2005–2023: 1000 synthetic days go from 91.6 to **11.5 ms/day**, and the
  `examples/diagnostics-overshoot/` run from **16.6 min to 2.1 min**.

  Three design points, argued and measured in
  [`docs/design/completed/PERF-1-precomputed-conditional-quantiles.md`](docs/design/completed/PERF-1-precomputed-conditional-quantiles.md):
  the **quantile function** is what is interpolated across `previous`, because averaging
  two CDFs of distributions centred in different places produces a bimodal blend of them;
  node spacing is **uniform, not quantile-based**, because irradiance's `previous` piles up
  at zero and quantile nodes would starve the daytime range; and the cache is built
  **lazily**, on the 65th call, because building it costs 64 direct calls' worth of work
  and `generate_series` takes exactly one sample per simulator — building it in `__init__`
  as originally proposed would have been a 64× pessimisation for a year-long walk.

  Behaviour below the threshold is bit-for-bit unchanged. Above it, sampled values shift
  by ~0.03 % per transition and ~0.19 % on a daily total (KS p = 1.0 against the direct
  path over 2000 days) — an order of magnitude below the smallest effect the diagnostics
  can resolve. `precompute_grid()` forces the cache when the ensemble size is known up
  front.
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
  **Order of work** section recording the sequence and, more usefully, the couplings.

  *Both couplings it recorded were later retired by measurement: `CHORE-1` no longer folds
  into `FIX-1`, and `PERF-1` did not have to wait for it. See the two entries below.*
- **`FIX-1` restated on measurement, and deferred.** It read "generated irradiance is
  systematically too high (+14 %)" and was first in the queue. Measured against the pool
  the model is fitted to — Heraklion 2005–2023, four dates through the year, n = 1000 per
  cell — the mean daily total lands **within 0.7 %** and no date's interval excludes
  parity. The +14 % came from a retired estimator (month subsets, `gen_day_sequence`,
  pre-0.2.0) on one two-year record with no repetition.

  What is real, and now what the item records, is a **deficit of heavily overcast days**:
  ~4× too few where a record holds any, confirmed at two dates and two thresholds. It is
  worth **0.12 % of an annual P90**, so yield work is unaffected; storage autonomy and
  worst-case-day work are not, and a **daily P10 runs up to 9 % high**. Deferred on that
  basis, with the limitation documented in `README.md` and the use-case READMEs rather
  than left for a user to discover.
- **`CHORE-1` gained numbers instead of an answer.** Within-window seasonal structure is
  3.8 % of pool variance at ±7 days and 10.4 % at ±15 on 21 March — but **19.3 % at ±7 on
  21 September**, because the same seasonal slope sits on a smaller day-to-day variance.
  A single global half-width cannot be right for every date, which is more than the item
  previously knew and less than it asked for.

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
- **XLSX support, and `openpyxl` with it.** The cache no longer writes by file extension;
  parquet is the canonical format and CSV the interchange one, and nothing else was
  reading the spreadsheets.

### Decisions

All five are argued in
[`FEAT-13-met-dataset-format.md`](docs/design/completed/FEAT-13-met-dataset-format.md).

- **A file is optional, and its format is still worth specifying** — the opposite inference
  is what left provenance with nowhere to live but a fetcher's cache.
- **Out-of-support values are repaired, not refused** — structural defects raise, physically
  impossible values are clipped and counted.
- **A mismatched cache raises rather than refetching** — the caller chose the path, so a
  mismatch is a mistake to surface, not a stale entry to evict.
- **The irradiance resolver refuses to reconstruct a total from components** — resolution is
  a lookup; summing is a claim about the data, and stays explicit.
- **`MetDataset` takes no `attr_str=None` "resolve it for me" default** — it would put the
  solar quantity back at the centre of a variable-agnostic package.

### Known at release

- **The overcast-tail deficit is unfixed and deliberately so.** The model produces ~4×
  too few heavily overcast days where a record holds any. Worth 0.12 % of an annual P90,
  so yield work is unaffected; storage autonomy and worst-case-day work are not. Tracked
  as `TODOs.md` **FIX-1**, with the limitation documented in `README.md` and the use-case
  READMEs rather than left for a user to discover.
- **`SOURCE_RENAMES["open_meteo"]` still maps `shortwave_radiation` onto `poa_global`**,
  which is wrong — shortwave radiation is horizontal, so it should be `ghi`. Harmless
  today because no Open-Meteo path is exercised, and the resolver's preference order would
  amplify it once one is. First task of `VISION-1`.
- **Nothing pins what the sampler produces distributionally.** The suite tests properties,
  not calibration, so `PERF-1`'s entirely new sampling path passed 271 tests unmodified.
  Raised for a decision as `TODOs.md` **CHORE-12**.
- **No schema migration exists.** `MetDataset.load` refuses a future `schema_version`
  rather than guessing, but there is nothing to migrate *from* yet. The first v1→v2 change
  is when that becomes real.

### Commits

`16aea3f` use-case examples and examples reorganisation · `c2525fe` concepts ·
`eecf5d5` retire `metdata_pvgis` · `4f04f80` scale-aware degeneracy (`FIX-2`) ·
`ec983f5` architecture spec · `94bd229`, `dd41c25`, `a44a428`, `436142b` overshoot
diagnostic and `FIX-1` restatement · `ea2ef89`, `479ba6c` cached conditional quantiles
(`PERF-1`) · `1ae1f13`, `960954c`, `256b25e`, `84d98ac` 0.2.1 · `e5e87ca` design-doc
archive · `7a33b76` single-source version in the docs · `5b99851` `FEAT-13` planning ·
`6a8d30f` `MetDataset` · `7106b81`, `f540ac3` progress bar · `4545624` finish
decoupling-ingestion-gen.

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

- **`generate_series` is deliberately not on `EnvSeriesGenerator`** — a month subset shares
  one π(x₀) across every generated day, so "what does day 32 look like" has no honest
  answer. Guarded by a test.
  [Rationale](docs/design/completed/variable-specs-and-initialisation.md).
- **Fitted generators are deliberately not persisted** — it would write source data back to
  disk, ~31× duplicated across overlapping windows, to save ~58 ms of fitting.
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
