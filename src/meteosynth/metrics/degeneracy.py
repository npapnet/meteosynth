"""
Degenerate cells: where reference and synthetic are the same constant.

Night-time irradiance is 0 on both sides. Any distance there is 0, so the cell "passes"
automatically -- and roughly half of irradiance's cells are like that. Left in a pooled pass
share they inflate it, so they are flagged and excluded.

"Constant" uses :data:`~meteosynth.constants.DEGENERACY_RTOL`, the tolerance behind the
simulator's ``Kind.CONSTANT``: a night hour here is one where the *model* is degenerate,
not one where the sun is nominally below the horizon.
"""

from __future__ import annotations

import numpy as np

from ..constants import DEGENERACY_RTOL
from .series import SeriesSet


def degeneracy_tolerance(reference: SeriesSet, synthetic: SeriesSet) -> float:
    """
    The spread below which a cell counts as constant, in the data's units.

    Scaled by the largest magnitude on either side, so the test asks "is this negligible
    next to the rest of the data?" rather than "is this exactly zero?" -- the same question
    the simulator asks.
    """
    scale = max(float(np.max(np.abs(reference.values))), float(np.max(np.abs(synthetic.values))))
    return DEGENERACY_RTOL * scale


def is_degenerate(reference_values: np.ndarray, synthetic_values: np.ndarray,
                  tolerance: float) -> bool:
    """
    True when both samples are constant **and** equal, to within ``tolerance``.

    Two different constants (reference 0, synthetic 5) are *not* degenerate: that is a real
    failure and must be scored.
    """
    ref = np.asarray(reference_values, dtype=np.float64).ravel()
    syn = np.asarray(synthetic_values, dtype=np.float64).ravel()
    return bool(
        np.std(ref) <= tolerance
        and np.std(syn) <= tolerance
        and abs(ref.mean() - syn.mean()) <= tolerance
    )


def constant_cells(reference: SeriesSet, synthetic: SeriesSet) -> np.ndarray:
    """
    ``(12, 24)`` boolean grid: which ``(month, hour)`` cells are degenerate.

    Row ``month - 1``, column ``hour``. A cell either side does not cover is ``False``.
    """
    tolerance = degeneracy_tolerance(reference, synthetic)
    grid = np.zeros((12, 24), dtype=bool)
    for m in range(1, 13):
        for h in range(24):
            ref, syn = reference.cell(m, h), synthetic.cell(m, h)
            if ref.size and syn.size:
                grid[m - 1, h] = is_degenerate(ref, syn, tolerance)
    return grid
