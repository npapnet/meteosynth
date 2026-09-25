"""
Fidelity metrics: how closely a synthetic ensemble reproduces the reference record.

Computation only. Nothing here takes a path, opens a file, reads file metadata, prints or
plots -- scripts do that, and hand the data over as two :class:`SeriesSet` objects:

    reference = SeriesSet.from_reference_frame(observed_frame, "wind_speed")
    synthetic = SeriesSet.from_ensemble(ensemble, "wind_speed")

    marginal = MarginalFidelity().evaluate(reference, synthetic)
    climatology = Climatology.from_series(reference)
    temporal = TemporalFidelity().evaluate(reference, synthetic, climatology)

**reference** is the side a synthetic result is compared against -- usually the training
record, but nothing here assumes so. **synthetic** is the generated side.

Layout
------
series            :class:`SeriesSet` -- the data object -- and its ``from_*`` helpers
climatology       :class:`Climatology`
autocorrelation   :func:`autocorrelation`, :func:`decorrelation_time`
distribution      :func:`empirical_cdf`, :func:`quantile_traces`
distances         :class:`SampleDistance` protocol, :class:`Wasserstein1`, :class:`KolmogorovSmirnovStatistic`
control           :class:`YearSplitBand`, :class:`MemberSpreadBand`
degeneracy        :func:`constant_cells` -- the night-hour mask
marginal          :class:`MarginalFidelity` -> :class:`MarginalResult`
temporal          :class:`TemporalFidelity` -> :class:`TemporalResult`

Design record: ``docs/design/completed/FEAT-23-metrics-package.md``.
"""

from ._base import FidelityResult, FidelityTest
from .autocorrelation import autocorrelation, decorrelation_time
from .climatology import Climatology
from .control import ControlBand, MemberSpreadBand, YearSplitBand
from .degeneracy import constant_cells, degeneracy_tolerance, is_degenerate
from .distances import KolmogorovSmirnovStatistic, SampleDistance, Wasserstein1
from .distribution import DEFAULT_QUANTILES, empirical_cdf, quantile_traces
from .marginal import MarginalFidelity, MarginalResult
from .series import SeriesSet, no_leap_calendar
from .temporal import TemporalFidelity, TemporalResult

__all__ = [
    # the data object
    "SeriesSet",
    "no_leap_calendar",
    # instruments
    "Climatology",
    "autocorrelation",
    "decorrelation_time",
    "empirical_cdf",
    "quantile_traces",
    "DEFAULT_QUANTILES",
    "SampleDistance",
    "Wasserstein1",
    "KolmogorovSmirnovStatistic",
    "ControlBand",
    "YearSplitBand",
    "MemberSpreadBand",
    "constant_cells",
    "degeneracy_tolerance",
    "is_degenerate",
    # fidelity tests
    "FidelityTest",
    "FidelityResult",
    "MarginalFidelity",
    "MarginalResult",
    "TemporalFidelity",
    "TemporalResult",
]
