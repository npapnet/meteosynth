"""
Autocorrelation of many series at once, and the decorrelation time read off it.
"""

from __future__ import annotations

import numpy as np
from scipy.fft import irfft, next_fast_len, rfft


def autocorrelation(matrix: np.ndarray, max_lag: int, batch: int = 100) -> np.ndarray:
    """
    Autocorrelation of each row, lags ``0..max_lag``, by FFT.

    Parameters
    ----------
    matrix : np.ndarray
        ``(n_rows, T)`` -- one series per row, e.g. ``SeriesSet.values`` or its anomalies.
        A 1-D series is treated as one row.
    max_lag : int
        Longest lag, in samples. Must be below ``T``.
    batch : int
        Rows transformed at once. Caps the working memory independently of ``n_rows``.

    Returns
    -------
    np.ndarray
        ``(n_rows, max_lag + 1)``; column 0 is 1. A constant row has no defined
        autocorrelation and comes back as NaN.

    Notes
    -----
    **Computed within each row, never across rows.** Concatenating independent
    realisations would put a discontinuity at every join and manufacture a decay that is an
    artefact of the layout.

    **The biased estimator** (dividing by ``T`` at every lag) is used deliberately: it gives
    a smoothly decaying, positive-definite curve, where the unbiased one inflates the long
    lags exactly where the sample is thinnest.
    """
    matrix = np.atleast_2d(np.asarray(matrix, dtype=np.float64))
    n_rows, T = matrix.shape
    if not 0 <= max_lag < T:
        raise ValueError(f"max_lag must be in 0..{T - 1} for series of length {T}, got {max_lag}")

    nfft = next_fast_len(2 * T)
    out = np.empty((n_rows, max_lag + 1))
    for start in range(0, n_rows, batch):
        chunk = matrix[start:start + batch]
        centred = chunk - chunk.mean(axis=1, keepdims=True)
        spectrum = rfft(centred, n=nfft, axis=1)
        acov = irfft(spectrum * np.conj(spectrum), n=nfft, axis=1)[:, :max_lag + 1]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[start:start + batch] = acov / acov[:, :1]
    return out


def decorrelation_time(acf: np.ndarray) -> float | np.ndarray:
    """
    Integral decorrelation time, in the ACF's lag units: ``1 + 2 * sum(rho)``.

    The sum runs up to the first lag at or below zero. Past that crossing the terms are
    noise around zero, and summing them adds variance without adding signal.

    Parameters
    ----------
    acf : np.ndarray
        One ACF (1-D, lag 0 first) or one per row (2-D).

    Returns
    -------
    float or np.ndarray
        A float for a 1-D input, one value per row for a 2-D input.
    """
    acf = np.asarray(acf, dtype=np.float64)
    if acf.ndim == 2:
        return np.array([decorrelation_time(row) for row in acf])
    negative = np.flatnonzero(acf[1:] <= 0)
    cut = int(negative[0]) + 1 if negative.size else len(acf)
    return float(1 + 2 * acf[1:cut].sum())
