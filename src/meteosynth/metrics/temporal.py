"""
Temporal fidelity: does multi-day persistence emerge correctly?

The generator is first order in the hour index; nothing in it fits memory beyond one hour.
Lag 1 is preserved by construction, so the diagnostic range is the lags after it. Paper
Test 2, autocorrelation part.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ._base import check_same_attr
from .autocorrelation import autocorrelation, decorrelation_time
from .climatology import Climatology
from .control import MemberSpreadBand
from .series import SeriesSet


@dataclass(frozen=True)
class TemporalFidelity:
    """
    Raw and anomaly autocorrelation to ``max_lag``, against the reference members' spread.

    Parameters
    ----------
    max_lag : int
        Longest lag, in hours. 240 h = 10 days spans the synoptic band.
    control : MemberSpreadBand
        Percentiles of the per-member band. A synthetic curve inside it is
        indistinguishable from a real year.
    batch : int
        Realisations per FFT batch; caps working memory.

    Notes
    -----
    **Raw and anomaly answer different questions.** The raw ACF of an hourly series is
    dominated by its daily and yearly cycles, so it mostly tests whether their *shape* is
    reproduced. The anomaly ACF, with the climatology removed, is what tests the Markov
    assumption.
    """

    max_lag: int = 240
    control: MemberSpreadBand = field(default_factory=MemberSpreadBand)
    batch: int = 100

    def evaluate(self, reference: SeriesSet, synthetic: SeriesSet,
                 climatology: Climatology) -> "TemporalResult":
        """
        ACFs of every member of both sides, and the per-lag comparison.

        Parameters
        ----------
        climatology : Climatology
            Subtracted from **both** sides. Build it from the reference with
            :meth:`Climatology.from_series`, and pass the same one when comparing ensembles.
        """
        attr = check_same_attr(reference, synthetic)
        acf = lambda m: autocorrelation(m, self.max_lag, self.batch)   # noqa: E731

        ref_raw = acf(reference.values)
        ref_anom = acf(climatology.anomalies(reference))
        syn_raw = acf(synthetic.values)
        syn_anom = acf(climatology.anomalies(synthetic))

        table = pd.DataFrame({"lag_hours": np.arange(self.max_lag + 1)})
        p_lo, p_hi = (f"{p:g}" for p in self.control.percentiles)
        for name, ref, syn in (("raw", ref_raw, syn_raw), ("anomaly", ref_anom, syn_anom)):
            lo, hi = self.control.bounds(ref)
            syn_mean = syn.mean(axis=0)
            table[f"ref_{name}_mean"] = ref.mean(axis=0)
            table[f"ref_{name}_p{p_lo}"] = lo
            table[f"ref_{name}_p{p_hi}"] = hi
            table[f"syn_{name}_mean"] = syn_mean
            table[f"syn_{name}_sem"] = (syn.std(axis=0, ddof=1) / np.sqrt(syn.shape[0])
                                        if syn.shape[0] > 1 else np.nan)
            table[f"{name}_inside_band"] = (syn_mean >= lo) & (syn_mean <= hi)

        return TemporalResult(
            table=table,
            attr=attr,
            acf_reference_raw=ref_raw,
            acf_reference_anomaly=ref_anom,
            acf_synthetic_raw=syn_raw,
            acf_synthetic_anomaly=syn_anom,
            tau_reference=decorrelation_time(ref_anom),
            tau_synthetic=decorrelation_time(syn_anom),
        )


@dataclass(frozen=True, eq=False)
class TemporalResult:
    """
    The outcome of :meth:`TemporalFidelity.evaluate`.

    Attributes
    ----------
    table : pd.DataFrame
        Per lag, for ``raw`` and ``anomaly``: reference mean and band edges
        (``ref_<kind>_p5``/``_p95`` at the default percentiles), synthetic mean and its
        standard error, and whether the synthetic mean is inside the band.
    acf_reference_raw, acf_reference_anomaly : np.ndarray
        ``(n_reference, max_lag + 1)`` -- one curve per reference member.
    acf_synthetic_raw, acf_synthetic_anomaly : np.ndarray
        ``(n_synthetic, max_lag + 1)``.
    tau_reference, tau_synthetic : np.ndarray
        Anomaly decorrelation time per member, hours.
    """

    table: pd.DataFrame
    attr: str
    acf_reference_raw: np.ndarray
    acf_reference_anomaly: np.ndarray
    acf_synthetic_raw: np.ndarray
    acf_synthetic_anomaly: np.ndarray
    tau_reference: np.ndarray
    tau_synthetic: np.ndarray

    @property
    def n_reference(self) -> int:
        return self.acf_reference_raw.shape[0]

    @property
    def n_synthetic(self) -> int:
        return self.acf_synthetic_raw.shape[0]

    def summary(self) -> dict:
        """One flat row, for a per-variable summary table."""
        inside = self.table["anomaly_inside_band"]
        tau_ref = float(self.tau_reference.mean())
        tau_syn = float(self.tau_synthetic.mean())
        return {
            "attr": self.attr,
            "n_reference": self.n_reference,
            "n_synthetic": self.n_synthetic,
            "anomaly_lags_inside": int(inside.sum()),
            "anomaly_share_inside": float(inside.mean()),
            "raw_share_inside": float(self.table["raw_inside_band"].mean()),
            "tau_reference_h": tau_ref,
            "tau_synthetic_h": tau_syn,
            "tau_ratio": tau_syn / tau_ref,
        }
