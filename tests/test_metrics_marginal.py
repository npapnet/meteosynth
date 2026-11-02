"""Tests for the marginal instruments and `MarginalFidelity`."""

import numpy as np
import pytest

from meteosynth.metrics import (
    KolmogorovSmirnovStatistic,
    MarginalFidelity,
    SampleDistance,
    SeriesSet,
    Wasserstein1,
    YearSplitBand,
    constant_cells,
    empirical_cdf,
    no_leap_calendar,
    quantile_traces,
)


def _series(values, attr="x"):
    month, day, hour = no_leap_calendar()
    return SeriesSet(values, month, day, hour, attr=attr)


def _draws(n_members, rng, shift=0.0, night_zero=False):
    """Independent hourly draws whose level depends on hour and month."""
    month, _, hour = no_leap_calendar()
    level = 5 + 2 * np.sin(2 * np.pi * hour / 24) + 0.3 * month
    values = level + shift + rng.gamma(2.0, 1.0, (n_members, 8760))
    if night_zero:
        values[:, (hour < 6) | (hour > 19)] = 0.0
    return values


FAST = YearSplitBand(n_splits=10)


def test_distances():
    a = np.random.default_rng(0).normal(size=500)
    assert Wasserstein1()(a, a + 3.0) == pytest.approx(3.0)
    assert Wasserstein1()(a, a) == 0.0
    assert KolmogorovSmirnovStatistic()(a, a) == 0.0
    assert isinstance(Wasserstein1(), SampleDistance)
    assert Wasserstein1.in_physical_units and not KolmogorovSmirnovStatistic.in_physical_units


def test_year_split_band():
    band = YearSplitBand(n_splits=5, seed=1)
    splits = band.splits(7, band.generator())
    assert len(splits) == 5
    for a, b in splits:
        assert len(a) == 3 and len(b) == 4
        assert sorted(np.concatenate([a, b])) == list(range(7))
    with pytest.raises(ValueError, match="at least 2"):
        band.splits(1, band.generator())


def test_same_distribution_passes_shifted_fails():
    rng = np.random.default_rng(4)
    reference = _series(_draws(8, rng))
    good = MarginalFidelity(control=FAST).evaluate(reference, _series(_draws(40, rng)))
    assert len(good.table) == 288
    assert good.passed and good.pass_share >= 0.9

    sd = reference.values.std()
    bad = MarginalFidelity(control=FAST).evaluate(reference, _series(_draws(40, rng, shift=sd)))
    assert not bad.passed and bad.pass_share < 0.1
    assert bad.scored["bias_norm"].median() > 0.5


# Night cells are 0 on both sides: flagged, excluded, and never the reason for a pass.
def test_night_cells_are_degenerate_and_excluded():
    rng = np.random.default_rng(5)
    reference = _series(_draws(6, rng, night_zero=True))
    synthetic = _series(_draws(20, rng, shift=5.0, night_zero=True))
    result = MarginalFidelity(control=FAST).evaluate(reference, synthetic)
    night = result.table["hour"].isin([0, 1, 2, 3, 4, 5, 20, 21, 22, 23])
    assert result.table.loc[night, "degenerate"].all()
    assert not result.table.loc[~night, "degenerate"].any()
    assert result.table.loc[night, "w1_norm"].isna().all()
    assert result.pass_share == pytest.approx(0.0)       # would be ~0.42 if night counted
    assert result.summary()["cells_degenerate"] == 120
    np.testing.assert_array_equal(constant_cells(reference, synthetic),
                                  result.grid("degenerate").astype(bool))


# Two *different* constants are a real failure, not a degenerate cell.
def test_different_constants_are_scored():
    rng = np.random.default_rng(6)
    ref_values = _draws(4, rng, night_zero=True)
    syn_values = _draws(10, rng, night_zero=True)
    month, _, hour = no_leap_calendar()
    syn_values[:, hour == 0] = 7.0
    result = MarginalFidelity(control=FAST).evaluate(_series(ref_values), _series(syn_values))
    midnight = result.table[result.table["hour"] == 0]
    assert not midnight["degenerate"].any()
    assert not midnight["passes"].any()


def test_reproducible_and_grid():
    rng = np.random.default_rng(7)
    reference, synthetic = _series(_draws(6, rng)), _series(_draws(12, rng))
    test = MarginalFidelity(control=FAST)
    a, b = test.evaluate(reference, synthetic), test.evaluate(reference, synthetic)
    assert a.table.equals(b.table)
    grid = a.grid("w1")
    assert grid.shape == (12, 24)
    assert grid[2, 5] == a.table.query("month == 3 and hour == 5")["w1"].item()


def test_partial_year_synthetic_scores_only_shared_cells():
    rng = np.random.default_rng(8)
    reference = _series(_draws(4, rng))
    month, day, hour = no_leap_calendar()
    july = month == 7
    synthetic = SeriesSet(_draws(10, rng)[:, july], month[july], day[july], hour[july])
    result = MarginalFidelity(control=FAST).evaluate(reference, synthetic)
    assert set(result.table["month"]) == {7}
    assert np.isnan(result.grid("w1")[0]).all()


def test_empirical_cdf():
    x, p = empirical_cdf([3.0, 1.0, np.nan, 2.0], n_points=None)
    np.testing.assert_array_equal(x, [1, 2, 3])
    np.testing.assert_allclose(p, [1 / 3, 2 / 3, 1])
    x, p = empirical_cdf(np.arange(10_000.0), n_points=11)
    assert len(x) == 11 and x[0] == 0 and x[-1] == 9999 and p[-1] == 1
    with pytest.raises(ValueError):
        empirical_cdf([np.nan])


def test_quantile_traces():
    rng = np.random.default_rng(9)
    s = _series(_draws(3, rng))
    traces = quantile_traces(s, month=1)
    assert traces.shape == (24, 7)
    assert (traces.diff(axis=1).iloc[:, 1:] >= 0).all().all()     # quantiles ascend
    month, day, hour = no_leap_calendar()
    july = month == 7
    with pytest.raises(ValueError, match="month 1"):
        quantile_traces(SeriesSet(s.values[:, july], month[july], day[july], hour[july]), 1)
