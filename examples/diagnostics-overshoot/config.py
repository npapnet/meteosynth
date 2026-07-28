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
from typing import Optional

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

#: Half-width of the training window, in days. **7, not the shipped 15.** Halving the
#: window halves the pool (589 -> 285 days on a 19-year record) and cuts the within-window
#: seasonal smear, which matters here because the pool *is* the reference: any seasonal
#: spread inside it is spread the model is being asked to reproduce.
WINDOW_N_DAYS = 7

#: KDE bandwidth as a **factor**, not a setting. ``None`` is Scott's rule -- the intended
#: new default -- and 0.1 is what ships today. They are not a small distance apart: both
#: are multipliers on the data covariance, and Scott at this window and record length is
#: ~0.390, a 3.9x wider kernel. FIX-1's old bandwidth sweep rises monotonically across
#: that range, so which of the two changes moved a number has to stay answerable.
BANDWIDTHS: tuple[Optional[float], ...] = (None, 0.1)

# --------------------------------------------------------------------------------------
# Design
# --------------------------------------------------------------------------------------

#: Calendar days to run: four, spread evenly through the solar year. Consistency across
#: them is what replaces a multiplicity correction -- four near-independent tests of the
#: same claim, agreeing or not.
DAYS: list[tuple[int, int]] = [(3, 21), (6, 21), (9, 21), (12, 21)]

#: Available, not run. 21 May is the date FIX-1's +3.2 % row was measured on; it is kept
#: for anyone reconciling against that number, though the reference differs.
DAYS_BACKLOG: list[tuple[int, int]] = [(5, 21)]

#: The anchor cell: run 1's exact configuration (+/-15, bandwidth 0.1, 21 March). Not a
#: factor level -- a regression check. Every other setting changes in this run, so no
#: other cell is comparable to run 1; this one is, and it is what says the rewritten
#: step3 returns run 1's published numbers on run 1's settings.
ANCHOR: tuple[int, int, int, Optional[float]] = (3, 21, 15, 0.1)

#: Run 1's published figures for the anchor configuration, checked against by step3.
#: From FINDINGS.md: mean +1.06 % against the pool, sd ratio 0.915, and 0.60 % of
#: synthetic days below 1 kWh/m2.
ANCHOR_EXPECTED = {"mean_ratio": 1.0106, "sd_ratio": 0.915, "low_abs_share_syn": 0.0060}

#: Realisations per configuration. Run 1 measured the day-to-day CV at 10-39 % depending
#: on the date, which at n = 1000 puts the minimum detectable effect between ~1.4 %
#: (21 June) and ~4.8 % (21 March). n = 30, the original brief, was uninformative.
N_REALISATIONS = 1000

MASTER_SEED = 20260728

#: Bootstrap resamples. The **synthetic sample only** is resampled: the observed pool is
#: not a sample from a wider population being estimated, it is the exact object the model
#: was fitted to, so it enters as a known quantity.
N_BOOTSTRAP = 10_000

# --------------------------------------------------------------------------------------
# The statistics
# --------------------------------------------------------------------------------------

#: Absolute low-tail threshold, kWh/m2/day. Kept for continuity with run 1, which
#: reported 0.60 % of synthetic days below this against 2.38 % observed.
LOW_TAIL_ABS = 1.0

#: Relative low-tail threshold, as a fraction of the **observed pool median**. The
#: absolute threshold means very different things in March and June; this one travels.
LOW_TAIL_REL = 0.25


def bandwidth_tag(bandwidth: Optional[float]) -> str:
    """Filesystem- and CSV-safe name for a bandwidth level."""
    return "scott" if bandwidth is None else f"{bandwidth:g}".replace(".", "p")


def config_id(month: int, day: int, n_days: int, bandwidth: Optional[float]) -> str:
    """Stable identifier for one configuration, used as a key in every raw file."""
    return f"{month:02d}{day:02d}_w{n_days:02d}_{bandwidth_tag(bandwidth)}"


def configurations() -> list[tuple[int, int, int, Optional[float]]]:
    """
    Every ``(month, day, n_days, bandwidth)`` to run: the 4x2 grid, plus the anchor.

    The anchor is appended only if it is not already in the grid, so raising
    :data:`WINDOW_N_DAYS` back to 15 does not silently run the same cell twice.
    """
    grid = [
        (month, day, WINDOW_N_DAYS, bandwidth)
        for month, day in DAYS
        for bandwidth in BANDWIDTHS
    ]
    if ANCHOR not in grid:
        grid.append(ANCHOR)
    return grid


def ensure_dirs() -> None:
    """Create the output folders. Safe to call repeatedly."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
