"""
Descriptive distribution curves: the empirical CDF and hourly quantile traces.

Instruments, not tests -- they describe one side and leave the judging to the fidelity
tests. Both return plain arrays or frames, ready to plot.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .series import SeriesSet

#: The percentile traces the paper's Figure 1 plots (paper Test 3).
DEFAULT_QUANTILES = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)


def empirical_cdf(values, n_points: int | None = 1001) -> tuple[np.ndarray, np.ndarray]:
    """
    The empirical cumulative distribution function of a sample.

    Parameters
    ----------
    values : array-like
        Any shape; flattened. NaN is dropped.
    n_points : int or None
        When the sample is larger than this, return the curve at ``n_points`` evenly spaced
        probabilities instead of at every value. 8.76 M synthetic values plot no better than
        1 001 points and take far longer. ``None`` keeps every value.

    Returns
    -------
    x, p : np.ndarray
        Values and their cumulative probabilities, ``x`` ascending.
    """
    data = np.asarray(values, dtype=np.float64).ravel()
    data = data[~np.isnan(data)]
    if data.size == 0:
        raise ValueError("empirical_cdf needs at least one non-NaN value")

    if n_points is not None and data.size > n_points:
        p = np.linspace(0.0, 1.0, num=n_points)
        return np.quantile(data, p), p

    x = np.sort(data)
    return x, np.arange(1, x.size + 1, dtype=np.float64) / x.size


def quantile_traces(series: SeriesSet, month: int,
                    quantiles=DEFAULT_QUANTILES) -> pd.DataFrame:
    """
    Per hour of day, the given quantiles of every value in one month.

    Parameters
    ----------
    series : SeriesSet
        Either side; all members are pooled.
    month : int
        1..12.
    quantiles : sequence of float
        Probabilities in ``[0, 1]``.

    Returns
    -------
    pd.DataFrame
        Index ``hour`` (0..23), one column per quantile. Plot reference and synthetic on
        the same axes to see level, spread, skew and boundary behaviour together.

    Raises
    ------
    ValueError
        If ``series`` does not cover ``month``.
    """
    if not np.any(series.month == month):
        raise ValueError(f"series does not cover month {month}")
    rows = [np.quantile(series.cell(month, h), quantiles) for h in range(24)]
    return pd.DataFrame(rows, index=pd.RangeIndex(24, name="hour"), columns=list(quantiles))
