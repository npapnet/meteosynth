"""
Control bands: how far apart two samples of the *real* climate are.

A distance of 0.4 m/s is neither good nor bad until it is set against the distance between
two real samples of the same site and variable. A control band is that scale; a synthetic
result inside it is indistinguishable from real data. Different tests build it differently,
so each strategy is its own small class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


class ControlBand(Protocol):
    """What every control band exposes: the percentiles that bound it."""

    percentiles: tuple[float, float]


@dataclass(frozen=True)
class YearSplitBand:
    """
    Split the reference members into two halves at random, many times.

    Used by :class:`~meteosynth.metrics.MarginalFidelity`: for every split, the distance
    between half A and half B is one draw of "two real samples". The halves are **whole
    members** (whole years), because days inside one year are not independent of each other.

    Parameters
    ----------
    n_splits : int
        Random half-splits. The band settles well before 100; more only smooths its edges.
    percentiles : tuple of float
        The band's lower and upper edge. The upper one is the pass threshold.
    seed : int
        Root entropy for the splits and for any subsampling done alongside them. Fixed per
        test, so every variable and every ensemble is judged on identical splits.
    """

    n_splits: int = 100
    percentiles: tuple[float, float] = (5.0, 95.0)
    seed: int = 11

    def __post_init__(self):
        if self.n_splits < 1:
            raise ValueError(f"n_splits must be >= 1, got {self.n_splits}")

    def generator(self) -> np.random.Generator:
        """A fresh generator at :attr:`seed`."""
        return np.random.default_rng(self.seed)

    def splits(self, n_members: int, rng: np.random.Generator) -> list[tuple[np.ndarray, np.ndarray]]:
        """
        ``n_splits`` pairs of member indices ``(half_a, half_b)``.

        Half A holds ``n_members // 2``; half B the rest.

        Raises
        ------
        ValueError
            If there are fewer than 2 members to split.
        """
        if n_members < 2:
            raise ValueError(f"a year-split band needs at least 2 reference members, got {n_members}")
        half = n_members // 2
        orders = [rng.permutation(n_members) for _ in range(self.n_splits)]
        return [(order[:half], order[half:]) for order in orders]

    def bounds(self, control: np.ndarray) -> tuple[float, float]:
        """The band's ``(lower, upper)`` edge over a set of control distances."""
        lo, hi = np.percentile(control, self.percentiles)
        return float(lo), float(hi)


@dataclass(frozen=True)
class MemberSpreadBand:
    """
    The spread of a per-member curve across the reference members.

    Used by :class:`~meteosynth.metrics.TemporalFidelity`: each observed year gives its own
    autocorrelation curve, so the spread of those curves *is* the natural scale -- no
    splitting needed.
    """

    percentiles: tuple[float, float] = (5.0, 95.0)

    def bounds(self, curves: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-column ``(lower, upper)`` edges over ``(n_members, n_points)`` curves."""
        lo = np.percentile(curves, self.percentiles[0], axis=0)
        hi = np.percentile(curves, self.percentiles[1], axis=0)
        return lo, hi
