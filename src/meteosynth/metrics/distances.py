"""
Distances between two samples of one quantity -- the pluggable part of the marginal test.

A distance is any callable taking two 1-D samples and returning a float, with a ``name``
(its column in result tables) and a flag saying whether the number is in the data's own
units. :class:`~meteosynth.metrics.MarginalFidelity` uses one as its judged metric and any
number more as extra columns, so adding a criterion means adding a class here, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

import numpy as np
from scipy.stats import ks_2samp, wasserstein_distance


@runtime_checkable
class SampleDistance(Protocol):
    """What a distance must provide to be used by the fidelity tests."""

    #: Column name in result tables, e.g. ``"w1"``.
    name: str
    #: True when the value is in the data's units (so dividing by an sd makes it unitless).
    in_physical_units: bool

    def __call__(self, a: np.ndarray, b: np.ndarray) -> float: ...


@dataclass(frozen=True)
class Wasserstein1:
    """
    Wasserstein-1 (earth mover's) distance between two 1-D samples.

    In the data's own units -- 0.4 m/s can be read without a table -- more sensitive in the
    tails than KS, and comparatively stable against sample size.
    """

    name: ClassVar[str] = "w1"
    in_physical_units: ClassVar[bool] = True

    def __call__(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(wasserstein_distance(a, b))


@dataclass(frozen=True)
class KolmogorovSmirnovStatistic:
    """
    The two-sample Kolmogorov-Smirnov statistic *D*: the largest gap between the two ECDFs.

    **The statistic only, never its p-value.** With tens of thousands of synthetic values
    against a few hundred observed, the p-value measures the sample size, not fidelity. *D*
    is still a useful unitless effect size.
    """

    name: ClassVar[str] = "ks_d"
    in_physical_units: ClassVar[bool] = False

    def __call__(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(ks_2samp(a, b).statistic)
