"""Ingestion: the registry decides what survives, not a hardcoded list.

MetDataset keeps INDEX_COLS plus every column that has a registered spec, and
drops the rest. ``solar_elevation`` and ``Int`` fall out **by that rule** -- neither is a
stochastic environmental quantity, so neither has a spec -- rather than by name. The
distinction matters: a future provider's quirk column falls out the same way, with no
package change and no maintained exclusion list.
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth.constants import INDEX_COLS
from meteosynth.dataset import MetDataset, trim_columns, validate_columns
from meteosynth.variables import VariableSpec, register, unregister


def _frame(**columns):
    index = pd.date_range("2011-01-01", periods=48, freq="h")
    base = {
        "year": index.year, "month": index.month,
        "day": index.day, "hour": index.hour,
    }
    return pd.DataFrame({**base, **columns})


def test_index_columns_plus_one_registered_column_is_enough():
    """A temperature-only source with no irradiance at all ingests cleanly."""
    ds = MetDataset(_frame(temp_air=np.linspace(5, 20, 48)))
    assert set(ds.met_data.columns) == {*INDEX_COLS, "temp_air"}


def test_a_missing_index_column_is_rejected():
    frame = _frame(temp_air=np.zeros(48)).drop(columns=["hour"])
    with pytest.raises(ValueError, match="missing required index columns"):
        MetDataset(frame)


def test_a_frame_with_nothing_modellable_is_rejected():
    frame = _frame(some_flag=np.zeros(48))
    with pytest.raises(ValueError, match="no modellable column"):
        MetDataset(frame)


def test_the_error_names_the_registered_set_and_the_fix():
    frame = _frame(some_flag=np.zeros(48))
    with pytest.raises(ValueError) as excinfo:
        MetDataset(frame)

    message = str(excinfo.value)
    assert "temp_air" in message      # what it would accept
    assert "some_flag" in message     # what it got
    assert "register" in message      # what to do about it


def test_unregistered_columns_are_dropped():
    frame = _frame(
        temp_air=np.zeros(48), solar_elevation=np.zeros(48), Int=np.zeros(48),
    )
    ds = MetDataset(frame)

    assert "solar_elevation" not in ds.met_data.columns
    assert "Int" not in ds.met_data.columns
    assert "temp_air" in ds.met_data.columns


def test_the_callers_frame_is_never_mutated():
    """Dropping is a property of the processed copy; the original stays intact.

    This is the mitigation for discarding solar_elevation, which has real downstream
    uses in PV work.
    """
    frame = _frame(temp_air=np.zeros(48), solar_elevation=np.arange(48.0))
    MetDataset(frame)

    assert "solar_elevation" in frame.columns
    np.testing.assert_array_equal(frame["solar_elevation"], np.arange(48.0))


# THE TEST THAT PROVES THE MECHANISM. If dropping were a hidden exclusion list, this
# would fail: registering a spec for solar_elevation makes it survive ingestion.
def test_registering_a_spec_makes_a_dropped_column_survive():
    frame = _frame(temp_air=np.zeros(48), solar_elevation=np.linspace(-10, 60, 48))

    assert "solar_elevation" not in MetDataset(frame).met_data.columns

    register("solar_elevation", VariableSpec((-90.0, 90.0), "degrees", "Solar elevation"))
    try:
        assert "solar_elevation" in MetDataset(frame).met_data.columns
    finally:
        unregister("solar_elevation")


def test_a_user_column_is_modellable_once_registered():
    """The agnostic promise: no package change needed for a new quantity."""
    from meteosynth.generators import EnvSeriesGenerator

    index = pd.date_range("2011-01-01", "2011-03-31 23:00", freq="h")
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "year": index.year, "month": index.month,
            "day": index.day, "hour": index.hour,
            "rel_humidity": np.clip(rng.normal(60, 10, len(index)), 0, 100),
        }
    )

    register("rel_humidity", VariableSpec((0.0, 100.0), "%", "Relative humidity"))
    try:
        ds = MetDataset(frame)
        assert "rel_humidity" in ds.met_data.columns

        generator = EnvSeriesGenerator(ds.get_month_subset(2), attr_str="rel_humidity")
        day = generator.gen_day(seed=1)

        assert day.shape == (24,)
        assert np.isfinite(day).all()
        assert day.min() >= 0.0 and day.max() <= 100.0   # support is enforced
    finally:
        unregister("rel_humidity")


def test_trim_and_validate_are_usable_standalone():
    frame = _frame(temp_air=np.zeros(48), Int=np.zeros(48))

    validate_columns(frame)                      # does not raise
    assert "Int" not in trim_columns(frame).columns


def test_required_cols_is_gone():
    """A flat tuple cannot express "all of these and any of those"."""
    import meteosynth.constants as constants

    assert not hasattr(constants, "REQUIRED_COLS")
