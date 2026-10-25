"""
The shape every fidelity test and result follows.

A test is a frozen settings object with ``evaluate(reference, synthetic, ...)``; a result
holds tables and arrays and a one-row ``summary()``. Nothing prints, plots or writes. New
tests (annual dispersion, midnight seam, spell lengths, ...) follow the same shape, so a
script can loop over them without special cases.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from .series import SeriesSet


class FidelityResult(Protocol):
    """What every fidelity result provides."""

    #: The detailed table: one row per cell, lag, window... as the test defines.
    table: pd.DataFrame

    def summary(self) -> dict:
        """One flat row -- the line a script writes to its ``*_summary.csv``."""
        ...


class FidelityTest(Protocol):
    """What every fidelity test provides."""

    def evaluate(self, reference: SeriesSet, synthetic: SeriesSet) -> FidelityResult: ...


def check_same_attr(reference: SeriesSet, synthetic: SeriesSet) -> str:
    """The shared attribute name, or an error if the two sides name different ones."""
    if reference.attr and synthetic.attr and reference.attr != synthetic.attr:
        raise ValueError(
            f"reference holds {reference.attr!r} but synthetic holds {synthetic.attr!r}"
        )
    return reference.attr or synthetic.attr
