"""Tests for the temporal instruments and `TemporalFidelity`, against closed-form answers."""

import numpy as np
import pytest

from meteosynth.metrics import (
    Climatology,
    SeriesSet,
    TemporalFidelity,
    autocorrelation,
    decorrelation_time,
    no_leap_calendar,
)


def _ar1(n_members, phi, rng, n_hours=8760):
    """Stationary AR(1) rows with unit innovation variance."""
    noise = rng.standard_normal((n_members, n_hours))
    out = np.empty_like(noise)
    out[:, 0] = noise[:, 0] / np.sqrt(1 - phi ** 2)
    for t in range(1, n_hours):
        out[:, t] = phi * out[:, t - 1] + noise[:, t]
    return out


def _series(values, attr="x"):
    month, day, hour = no_leap_calendar()
    return SeriesSet(values, month, day, hour, attr=attr)


# AR(1) with coefficient phi has rho(k) = phi**k and tau = (1 + phi) / (1 - phi).
def test_autocorrelation_of_ar1():
    phi = 0.8
    rows = _ar1(20, phi, np.random.default_rng(1))
    acf = autocorrelation(rows, max_lag=10)
    assert acf.shape == (20, 11)
    np.testing.assert_allclose(acf[:, 0], 1.0)
    np.testing.assert_allclose(acf.mean(axis=0), phi ** np.arange(11), atol=0.02)
    # The integral estimate runs low (measured 8.07 h against 9 here): each sample ACF lag
    # is biased slightly downward and the sum truncates at the first noisy zero crossing.
    tau = decorrelation_time(acf.mean(axis=0))
    assert tau == pytest.approx((1 + phi) / (1 - phi), rel=0.15)


def test_autocorrelation_edge_cases():
    np.testing.assert_allclose(autocorrelation(np.arange(50.0), 3)[0, 0], 1.0)  # 1-D input
    assert np.isnan(autocorrelation(np.ones((1, 50)), 3)).all()                 # constant row
    with pytest.raises(ValueError, match="max_lag"):
        autocorrelation(np.zeros((1, 10)), 10)


# Batching must not change the answer.
def test_autocorrelation_batch_invariant():
    rows = np.random.default_rng(2).standard_normal((7, 500))
    np.testing.assert_allclose(autocorrelation(rows, 20, batch=2),
                               autocorrelation(rows, 20, batch=100))


def test_decorrelation_time_truncates_at_first_crossing():
    assert decorrelation_time(np.array([1.0, 0.5, 0.25, -0.1, 0.9])) == pytest.approx(2.5)
    np.testing.assert_allclose(decorrelation_time(np.array([[1.0, 0.5, -1], [1.0, 0.0, 1]])),
                               [2.0, 1.0])


# A pure seasonal + diurnal signal is entirely climatology: its anomalies vanish.
def test_climatology_removes_a_deterministic_cycle():
    month, day, hour = no_leap_calendar()
    probe = _series(np.zeros((1, 8760)))
    signal = 10 * np.sin(2 * np.pi * probe.slots / 366) + np.cos(2 * np.pi * hour / 24)
    reference = _series(np.tile(signal, (3, 1)))
    # +/-1 day of smoothing flattens a 366-day sine by 10 * (1 - cos(2 pi / 366)) ~ 0.001.
    clim = Climatology.from_series(reference, half_width=1)
    anomalies = clim.anomalies(_series(signal[None, :]))[0]
    # Feb 28 and Mar 1 border the empty Feb 29 slot, so their window is one-sided and sits
    # slightly off the seasonal slope (0.046 here); everywhere else the cycle is removed.
    beside_gap = (month == 2) & (day == 28) | (month == 3) & (day == 1)
    np.testing.assert_allclose(anomalies[~beside_gap], 0.0, atol=2e-3)
    assert np.abs(anomalies[beside_gap]).max() < 0.1
    assert clim.means.shape == (366, 24)
    # Feb 29 has no data; with no smoothing at all it cannot be filled, and says so.
    with pytest.raises(ValueError, match="no data"):
        Climatology.from_series(reference, half_width=0)


def test_climatology_smoothing_wraps_new_year_and_fills_feb29():
    month, day, hour = no_leap_calendar()
    values = np.where((month == 1) & (day == 1), 100.0, 0.0)[None, :]
    clim = Climatology.from_series(_series(values), half_width=2)
    # Jan 1 (slot 1) spreads into Dec 30/31 (slots 365/366) across the year boundary.
    assert clim.means[365, 0] == pytest.approx(20.0)
    assert clim.means[364, 0] == pytest.approx(20.0)
    assert clim.means[363, 0] == pytest.approx(0.0)
    assert not np.isnan(clim.means[59]).any()          # Feb 29 filled from neighbours
    with pytest.raises(ValueError, match="half_width"):
        Climatology.from_series(_series(values), half_width=200)


def test_temporal_fidelity_passes_same_process_and_fails_shuffled_days():
    rng = np.random.default_rng(3)
    phi = 0.99                                         # memory well beyond one day
    reference = _series(_ar1(12, phi, rng))
    synthetic = _series(_ar1(30, phi, rng))
    clim = Climatology.from_series(reference)
    test = TemporalFidelity(max_lag=72)

    same = test.evaluate(reference, synthetic, clim)
    assert same.table.shape[0] == 73
    assert same.table["anomaly_inside_band"].mean() > 0.9
    assert same.summary()["tau_ratio"] == pytest.approx(1.0, rel=0.25)

    # Shuffling whole days keeps every hourly marginal but destroys multi-day memory.
    days = synthetic.values.reshape(30, 365, 24)
    shuffled = days[:, rng.permutation(365), :].reshape(30, 8760)
    broken = test.evaluate(reference, _series(shuffled), clim)
    assert not broken.table.loc[broken.table["lag_hours"] >= 24, "anomaly_inside_band"].any()
    assert broken.summary()["tau_ratio"] < 0.5


def test_temporal_fidelity_rejects_mismatched_attrs():
    a = _series(np.zeros((2, 8760)) + np.arange(8760), attr="a")
    b = _series(np.zeros((2, 8760)) + np.arange(8760), attr="b")
    with pytest.raises(ValueError, match="holds"):
        TemporalFidelity(max_lag=5).evaluate(a, b, Climatology.from_series(a))
