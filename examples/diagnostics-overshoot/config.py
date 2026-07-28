"""
Single source of truth for the overshoot diagnostics run.

Every knob the four ``step*.py`` scripts obey lives here, so a re-run at a different
sample size or on a different calendar day is a one-line edit rather than a search
through four files. See ``PLAN.md`` for why each value is what it is.

Importing this module has no side effects beyond putting ``examples/`` on ``sys.path``
so the shared helpers in ``examples/tools/`` can be imported by scripts that live in a
hyphenated folder (which is therefore not an importable package itself).
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
EXAMPLES_ROOT = HERE.parent

# examples/tools/ holds site definitions and the observed-vs-synthetic helpers this
# analysis reuses rather than duplicates.
if str(EXAMPLES_ROOT) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_ROOT))

RESULTS_DIR = HERE / "results"
RAW_DIR = RESULTS_DIR / "raw"
FIGURES_DIR = HERE / "figures"

# --------------------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------------------

#: Widest range PVGIS 5.3 (SARAH3) serves for this site, confirmed by probing the API on
#: 2026-07-28: requesting 2004 returns "enter an integer between 2005 and 2023".
#: :mod:`step1_fetch` re-probes rather than trusting this, and writes what it actually
#: got to ``results/raw/record_meta.json``.
REQUESTED_YEARS = (2005, 2023)

#: Where the fetched record is cached. Lives in the shared ``examples/data/`` folder,
#: which is already git-ignored, so it is not re-downloaded per analysis.
RECORD_CACHE = EXAMPLES_ROOT / "data" / "pvgis_hourly_heraklion_2005_2023.csv"

RECORD_META = RAW_DIR / "record_meta.json"

# --------------------------------------------------------------------------------------
# What is modelled
# --------------------------------------------------------------------------------------

ATTR = "poa_global"
ATTR_UNIT = "W/m2"
DAILY_UNIT = "kWh/m2/day"

#: Half-width of the training window, in days. The shipped default, held fixed: this
#: analysis asks about the *record* length, not the window width.
WINDOW_N_DAYS = 15

#: KDE bandwidth. The shipped default, held fixed -- the bandwidth sweep is already
#: recorded in FIX-1 and is not repeated here.
BANDWIDTH = 0.1

# --------------------------------------------------------------------------------------
# Design
# --------------------------------------------------------------------------------------

#: Calendar days to run. 21 March alone for the first run: the equinox is where the
#: seasonal trend across a centred window is closest to linear, so the reference is at
#: its least sensitive to which estimator is used for it (PLAN.md section 4).
DAYS: list[tuple[int, int]] = [(3, 21)]

#: Wired and ready, deliberately not run yet. Uncomment to enable -- nothing else needs
#: to change.
DAYS_BACKLOG: list[tuple[int, int]] = [
    (6, 21),   # summer solstice: worst centre point for a symmetric window
    (12, 21),  # winter solstice: most hours at the zero floor -- the boundary-bias test
    (5, 21),   # reconciles against the figure already in FIX-1's table
]

#: Realisations per configuration. At sigma ~12 % this gives a 95 % interval of roughly
#: +/-4.3 % on the mean deviation: enough to resolve the +14 % thin-record effect,
#: **not** enough to resolve a residual +2-3 % at the full record. Raise with --n.
N_REALISATIONS = 30

#: Random year-subsets per size. The full record admits only one subset, so it gets 1.
#: Smaller sizes get several so that "how many years" is separated from "which years".
N_DRAWS = 5

MASTER_SEED = 20260728

#: Bootstrap and permutation resamples.
N_BOOTSTRAP = 10_000
N_PERMUTATION = 10_000

#: The three reference estimators, in report order. ``detrended_centre`` is primary:
#: it targets the centre day like ``centre_mean`` but estimates it from the whole
#: window, so it carries far less variance at small k.
REFERENCES = ("detrended_centre", "centre_mean", "pool_mean")
PRIMARY_REFERENCE = "detrended_centre"


def training_sizes(n_years: int) -> list[int]:
    """
    Training-set sizes in years, largest first.

    Full, ``full // 2`` and ``full // 5`` as briefed, plus **2** -- which reproduces the
    two-year Paris configuration that measured +14 %. Without that level the design has
    no point in the regime where the defect is known to be severe.

    Duplicates are dropped, so a short record degrades gracefully rather than running
    the same size twice.
    """
    sizes = [n_years, n_years // 2, n_years // 5, 2]
    seen: list[int] = []
    for size in sizes:
        if size >= 2 and size not in seen:
            seen.append(size)
    return seen


def config_id(k: int, draw: int, month: int, day: int) -> str:
    """Stable identifier for one configuration, used as a key in every raw file."""
    return f"k{k:02d}_d{draw}_{month:02d}{day:02d}"


def ensure_dirs() -> None:
    """Create the output folders. Safe to call repeatedly."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
