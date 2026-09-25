"""
Marginal fidelity: does the synthetic ensemble reproduce the reference distribution, hour by
hour, month by month?

One distance per ``(month, hour)`` cell, judged against a year-split control band under a
pre-registered pass rule. Paper Test 3; the scalar summary behind the quantile traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ._base import check_same_attr
from .control import YearSplitBand
from .degeneracy import degeneracy_tolerance, is_degenerate
from .distances import KolmogorovSmirnovStatistic, SampleDistance, Wasserstein1
from .series import SeriesSet


@dataclass(frozen=True)
class MarginalFidelity:
    """
    Distance per ``(month, hour)`` cell, against a year-split control band.

    Parameters
    ----------
    distance : SampleDistance
        The judged metric. Default :class:`Wasserstein1`.
    control : YearSplitBand
        How the control band is built, and the seed.
    pass_share : float
        Pre-registered: the reference passes overall when at least this share of its
        non-degenerate cells pass. Fix it before looking at any number.
    extra_distances : tuple of SampleDistance
        Reported as additional full-power columns, never judged. Default: the KS statistic.

    Notes
    -----
    Per cell, three numbers answer three different questions:

    * **full-power** ``<name>``: all reference values against all synthetic values. The best
      estimate of the true distance -- the number to *quote*.
    * **control band**: for each split, the distance between reference half A and half B --
      how far apart two *real* samples are.
    * **size-matched** ``<name>_matched``: for the same splits, half A against a synthetic
      subsample the size of half B, so it sits on the control band's footing. The median of
      these is the number to *judge*: a cell passes when it is at or below the band's upper
      edge.

    Quoting the full-power number against the size-matched threshold would compare two
    different measurements.
    """

    distance: SampleDistance = field(default_factory=Wasserstein1)
    control: YearSplitBand = field(default_factory=YearSplitBand)
    pass_share: float = 0.90
    extra_distances: tuple[SampleDistance, ...] = (KolmogorovSmirnovStatistic(),)

    def evaluate(self, reference: SeriesSet, synthetic: SeriesSet) -> "MarginalResult":
        """
        Score every ``(month, hour)`` cell both sides cover.

        Deterministic for a given ``control.seed``: the splits are drawn first, then one
        synthetic subsample per cell and split, cells in ``(month, hour)`` order.
        """
        attr = check_same_attr(reference, synthetic)
        rng = self.control.generator()
        splits = self.control.splits(reference.n_members, rng)
        tolerance = degeneracy_tolerance(reference, synthetic)
        name = self.distance.name

        rows = []
        for m in range(1, 13):
            for h in range(24):
                ref_cell = reference.cell(m, h)          # (M, days)
                syn_cell = synthetic.cell(m, h)          # (N, days)
                if ref_cell.size == 0 or syn_cell.size == 0:
                    continue
                ref_all = ref_cell.ravel()
                syn_all = syn_cell.ravel(order="F")      # day-major, as the file stores it
                ref_sd = ref_all.std(ddof=1)
                syn_sd = syn_all.std(ddof=1)

                control = np.empty(len(splits))
                matched = np.empty(len(splits))
                for s, (half_a, half_b) in enumerate(splits):
                    a = ref_cell[half_a].ravel()
                    b = ref_cell[half_b].ravel()
                    control[s] = self.distance(a, b)
                    sub = rng.choice(syn_all, size=b.size, replace=False)
                    matched[s] = self.distance(a, sub)

                full = self.distance(ref_all, syn_all)
                lo, hi = self.control.bounds(control)
                matched_median = float(np.median(matched))
                scale = ref_sd if ref_sd > 0 else np.nan

                row = {
                    "month": m, "hour": h,
                    "n_ref": ref_all.size, "n_syn": syn_all.size,
                    "ref_mean": ref_all.mean(), "ref_sd": ref_sd,
                    "syn_mean": syn_all.mean(), "syn_sd": syn_sd,
                    name: full,
                }
                if self.distance.in_physical_units:
                    row[f"{name}_norm"] = full / scale
                row.update({
                    "bias_norm": (syn_all.mean() - ref_all.mean()) / scale,
                    "sd_ratio": syn_sd / scale,
                    f"{name}_matched": matched_median,
                    "control_lo": lo, "control_hi": hi,
                    "control_median": float(np.median(control)),
                    "degenerate": is_degenerate(ref_all, syn_all, tolerance),
                    "passes": matched_median <= hi,
                })
                for extra in self.extra_distances:
                    row[extra.name] = extra(ref_all, syn_all)
                rows.append(row)

        if not rows:
            raise ValueError("reference and synthetic share no (month, hour) cell")
        table = pd.DataFrame(rows)
        scored = table.loc[~table["degenerate"], "passes"]
        share = float(scored.mean()) if len(scored) else float("nan")
        return MarginalResult(
            table=table,
            attr=attr,
            distance_name=name,
            n_reference=reference.n_members,
            n_synthetic=synthetic.n_members,
            pass_share=share,
            pass_threshold=self.pass_share,
            passed=bool(share >= self.pass_share),
        )


@dataclass(frozen=True, eq=False)
class MarginalResult:
    """
    The outcome of :meth:`MarginalFidelity.evaluate`.

    Attributes
    ----------
    table : pd.DataFrame
        One row per scored ``(month, hour)`` cell. ``<name>`` full-power distance,
        ``<name>_norm`` the same over the reference sd (physical-unit distances only),
        ``bias_norm`` and ``sd_ratio`` (a level shift and a spread change are different
        defects, and the distance alone conflates them), ``<name>_matched`` the judged
        size-matched median, ``control_lo/hi/median``, ``degenerate``, ``passes``, and one
        column per extra distance. Normalised columns are NaN where the reference sd is 0.
    pass_share : float
        Share of non-degenerate cells that pass.
    passed : bool
        ``pass_share >= pass_threshold``.
    """

    table: pd.DataFrame
    attr: str
    distance_name: str
    n_reference: int
    n_synthetic: int
    pass_share: float
    pass_threshold: float
    passed: bool

    @property
    def scored(self) -> pd.DataFrame:
        """The rows that count towards :attr:`pass_share`: non-degenerate cells."""
        return self.table[~self.table["degenerate"]]

    def grid(self, column: str) -> np.ndarray:
        """
        One column as a ``(12, 24)`` month-by-hour array, NaN where a cell was not scored.

        Row ``month - 1``, column ``hour`` -- ready for a heatmap.
        """
        grid = np.full((12, 24), np.nan)
        grid[self.table["month"].to_numpy() - 1, self.table["hour"].to_numpy()] = self.table[column]
        return grid

    def summary(self) -> dict:
        """One flat row, for a per-variable summary table."""
        scored = self.scored
        name = self.distance_name
        out = {
            "attr": self.attr,
            "n_reference": self.n_reference,
            "n_synthetic": self.n_synthetic,
            "cells_scored": len(scored),
            "cells_degenerate": int(self.table["degenerate"].sum()),
            "cells_pass": int(scored["passes"].sum()),
            "pass_share": self.pass_share,
            "passed": self.passed,
        }
        if f"{name}_norm" in scored:
            out[f"{name}_norm_median"] = scored[f"{name}_norm"].median()
        out["bias_norm_median"] = scored["bias_norm"].median()
        out["sd_ratio_median"] = scored["sd_ratio"].median()
        return out
