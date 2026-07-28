"""Source adapters: optional collection helpers, not a required layer.

Network-free throughout -- ``fetch_pvgis`` is exercised through its cache path and a
stubbed ``pvlib``, so the suite never depends on PVGIS being reachable.
"""

import sys
import types

import numpy as np
import pandas as pd
import pytest

from meteosynth import adapters
from meteosynth.adapters import (
    SOURCE_RENAMES,
    fetch_pvgis,
    fetch_pvgis_tmy,
    normalise,
    validate_support,
)


def _canonical_frame(n=48, **overrides):
    index = pd.date_range("2011-01-01", periods=n, freq="h")
    data = {
        "poa_global": np.clip(np.linspace(0, 800, n), 0, None),
        "temp_air": np.linspace(5, 20, n),
        "wind_speed": np.linspace(1, 6, n),
        "year": index.year, "month": index.month,
        "day": index.day, "hour": index.hour,
    }
    data.update(overrides)
    return pd.DataFrame(data)


# --- renaming ----------------------------------------------------------------------

def test_open_meteo_names_are_renamed():
    frame = pd.DataFrame(
        {"temperature_2m": [10.0, 11.0], "windspeed_10m": [3.0, 3.5]}
    )
    renamed = normalise(frame, source="open_meteo")

    assert list(renamed.columns) == ["temp_air", "wind_speed"]


def test_pvgis_is_a_known_source_but_needs_no_renaming():
    """pvlib already renames PVGIS's raw T2m / WS10m / G(i) before we see anything.

    The entry exists so that source="pvgis" is a known source rather than an error, and
    as the place a raw-CSV mapping would go if this package ever ingested one.
    """
    assert SOURCE_RENAMES["pvgis"] == {}

    frame = _canonical_frame()
    pd.testing.assert_frame_equal(normalise(frame, source="pvgis"), frame)


def test_an_unknown_source_is_an_error_not_a_no_op():
    """Passing data through unrenamed would look like it worked."""
    with pytest.raises(KeyError, match="unknown source"):
        normalise(_canonical_frame(), source="not_a_provider")


def test_already_canonical_names_are_a_no_op():
    frame = _canonical_frame()
    pd.testing.assert_frame_equal(normalise(frame, source="open_meteo"), frame)


# --- support validation ------------------------------------------------------------

def test_kelvin_temperature_slips_through():
    """Kelvin is *above* absolute zero, so the lower bound does not catch it.

    Documented rather than fixed: support validation is a necessary condition, not a
    sufficient one, and catching this would need the unit conversion this round
    deliberately excludes. Recorded so the limitation is visible rather than assumed
    away -- see test_fahrenheit_mislabelled_as_celsius_passes for the same point.
    """
    frame = _canonical_frame()
    frame["temp_air"] = np.linspace(280, 295, len(frame))    # kelvin, not degC

    validate_support(frame)      # passes, and that is the finding


def test_below_absolute_zero_fails():
    frame = _canonical_frame()
    frame.loc[0, "temp_air"] = -300.0
    with pytest.raises(ValueError, match="below its physical lower bound"):
        validate_support(frame)


def test_negative_irradiance_fails():
    frame = _canonical_frame()
    frame.loc[3, "poa_global"] = -50.0
    with pytest.raises(ValueError, match="below its physical lower bound"):
        validate_support(frame)


def test_the_error_names_the_column_and_the_expected_units():
    frame = _canonical_frame()
    frame.loc[0, "wind_speed"] = -1.0
    with pytest.raises(ValueError) as excinfo:
        validate_support(frame)

    message = str(excinfo.value)
    assert "wind_speed" in message
    assert "m/s" in message


def test_unregistered_columns_are_not_validated():
    frame = _canonical_frame(some_flag=np.full(48, -999.0))
    validate_support(frame)      # does not raise


# THE LIMITATION, asserted so nobody mistakes support validation for a unit check.
# Support is a necessary condition, not a sufficient one.
def test_fahrenheit_mislabelled_as_celsius_passes():
    frame = _canonical_frame()
    frame["temp_air"] = np.full(len(frame), 20.0)   # 20 degF read as 20 degC
    validate_support(frame)                          # passes: 20 is in support either way


# --- fetch_pvgis -------------------------------------------------------------------

def test_irradiance_choice_is_validated():
    with pytest.raises(ValueError, match="irradiance must be one of"):
        fetch_pvgis(48.86, 2.35, 2011, 2012, irradiance="infrared")


def _install_stub_pvlib(monkeypatch, arity=2):
    """Install a fake ``pvlib.iotools`` whose readers return ``arity`` values.

    ``arity`` is a parameter because that is exactly what broke: pvlib has returned
    4-, 3- and 2-tuples from its PVGIS readers across versions, and the deleted
    ``metdata_pvgis`` module unpacked fixed shapes. The data is always ``result[0]``.
    """
    calls = {}

    def _pad(data):
        """Return ``data`` plus (arity - 1) trailing metadata values."""
        return (data, *({} for _ in range(arity - 1)))

    def get_pvgis_hourly(latitude, longitude, start, end, components=True, **kwargs):
        calls["components"] = components
        index = pd.date_range(f"{start}-01-01", periods=72, freq="h")
        data = pd.DataFrame(index=index)
        data["temp_air"] = np.linspace(5, 20, len(index))
        data["wind_speed"] = np.linspace(1, 6, len(index))
        if components:
            data["poa_direct"] = np.clip(np.linspace(0, 700, len(index)), 0, None)
            data["poa_sky_diffuse"] = np.clip(np.linspace(0, 100, len(index)), 0, None)
            data["poa_ground_diffuse"] = np.zeros(len(index))
        else:
            data["poa_global"] = np.clip(np.linspace(0, 800, len(index)), 0, None)
        return _pad(data)

    def get_pvgis_tmy(latitude, longitude, coerce_year=None, **kwargs):
        calls["coerce_year"] = coerce_year
        year = coerce_year if coerce_year is not None else 2005
        index = pd.date_range(f"{year}-01-01", periods=8760, freq="h")
        data = pd.DataFrame(index=index)
        # Horizontal, not plane-of-array -- what PVGIS TMY actually supplies.
        data["ghi"] = np.clip(np.linspace(0, 900, len(index)), 0, None)
        data["dni"] = np.clip(np.linspace(0, 800, len(index)), 0, None)
        data["dhi"] = np.clip(np.linspace(0, 200, len(index)), 0, None)
        data["temp_air"] = np.linspace(5, 30, len(index))
        data["wind_speed"] = np.linspace(1, 9, len(index))
        # An unregistered extra, to prove trimming happens by rule.
        data["pressure"] = np.full(len(index), 101325.0)
        return _pad(data)

    module = types.ModuleType("pvlib.iotools")
    module.get_pvgis_hourly = get_pvgis_hourly
    module.get_pvgis_tmy = get_pvgis_tmy
    parent = types.ModuleType("pvlib")
    parent.iotools = module
    monkeypatch.setitem(sys.modules, "pvlib", parent)
    monkeypatch.setitem(sys.modules, "pvlib.iotools", module)
    return calls


@pytest.fixture
def stub_pvlib(monkeypatch):
    """A fake pvlib.iotools returning either global or components, as PVGIS does."""
    return _install_stub_pvlib(monkeypatch)


def test_default_collects_global_irradiance(stub_pvlib):
    """PVGIS returns global or the three components depending on one flag."""
    frame = fetch_pvgis(48.86, 2.35, 2011, 2011)

    assert "poa_global" in frame.columns
    assert "poa_direct" not in frame.columns
    assert stub_pvlib["components"] is False


def test_direct_is_opted_into(stub_pvlib):
    frame = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct")

    assert "poa_direct" in frame.columns
    assert "poa_global" not in frame.columns
    assert stub_pvlib["components"] is True


# The emitted column keeps its specific name, so the NAME records the choice. This is
# why no metadata sidecar exists anywhere in the design.
def test_the_column_name_is_the_provenance(stub_pvlib):
    globals_frame = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="global")
    direct_frame = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct")

    assert set(globals_frame.columns) != set(direct_frame.columns)
    assert "poa_global" in globals_frame.columns
    assert "poa_direct" in direct_frame.columns


def test_fetched_frame_is_canonical_and_ingestible(stub_pvlib):
    from meteosynth.met_data_processor import MetDataProcessor

    frame = fetch_pvgis(48.86, 2.35, 2011, 2011)
    for col in ("year", "month", "day", "hour"):
        assert col in frame.columns

    mdp = MetDataProcessor(frame)
    assert "poa_global" in mdp.met_data.columns


def test_cache_round_trips(stub_pvlib, tmp_path):
    """Collection is slow and networked; modelling is not, and often runs later."""
    cache = tmp_path / "site.csv"

    first = fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)
    assert cache.exists()

    stub_pvlib.clear()
    second = fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)

    assert "components" not in stub_pvlib      # the network path was not taken
    # dtypes are not part of the canonical contract; a CSV round-trip may widen
    # int32 to int64 on some platforms.
    pd.testing.assert_frame_equal(first, second, check_dtype=False)


def test_cached_data_is_still_validated(stub_pvlib, tmp_path):
    """A corrupted cache must not slip past the boundary check."""
    cache = tmp_path / "site.csv"
    fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)

    corrupted = pd.read_csv(cache)
    corrupted.loc[0, "poa_global"] = -100.0
    corrupted.to_csv(cache, index=False)

    with pytest.raises(ValueError, match="below its physical lower bound"):
        fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)


def test_adapters_are_optional(synthetic_mdp):
    """Use case B: the user already has data and no adapter is involved at all."""
    assert synthetic_mdp.met_data is not None
    assert "temp_air" in synthetic_mdp.met_data.columns


# --- arity independence -------------------------------------------------------------
#
# The defect this guards against: pvlib changed how many values its PVGIS readers
# return, and the old metdata_pvgis module unpacked fixed shapes, so both of its fetch
# functions raised on every call. Nothing depended on them, so the suite stayed green
# and it went unnoticed until someone followed the README.
#
# Testing the *property* -- that the data is result[0] whatever else comes back -- beats
# testing against a recorded response: there is no fixture to rot and no network.

@pytest.mark.parametrize("arity", [2, 3, 4])
def test_hourly_survives_any_pvlib_return_arity(monkeypatch, arity):
    _install_stub_pvlib(monkeypatch, arity=arity)

    frame = fetch_pvgis(48.86, 2.35, 2011, 2011)

    assert "poa_global" in frame.columns
    assert len(frame) == 72


@pytest.mark.parametrize("arity", [2, 3, 4])
def test_tmy_survives_any_pvlib_return_arity(monkeypatch, arity):
    _install_stub_pvlib(monkeypatch, arity=arity)

    frame = fetch_pvgis_tmy(35.34, 25.14)

    assert "ghi" in frame.columns
    assert len(frame) == 8760


# --- TMY ----------------------------------------------------------------------------

def test_tmy_irradiance_is_horizontal_not_plane_of_array(stub_pvlib):
    """Different quantity, different names -- they differ by however much a panel tilts.

    Silently interchanging them is the factor-of-two error the naming scheme exists to
    prevent, in the plane dimension rather than the component one.
    """
    frame = fetch_pvgis_tmy(35.34, 25.14)

    assert {"ghi", "dni", "dhi"} <= set(frame.columns)
    assert not any(col.startswith("poa_") for col in frame.columns)


def test_tmy_drops_unregistered_columns_by_rule(stub_pvlib):
    """PVGIS supplies pressure and friends; a column is kept iff it has a spec."""
    frame = fetch_pvgis_tmy(35.34, 25.14)

    assert "pressure" not in frame.columns
    assert set(frame.columns) == {"ghi", "dni", "dhi", "temp_air", "wind_speed",
                                  "year", "month", "day", "hour"}


def test_tmy_frame_is_canonical_and_ingestible(stub_pvlib):
    """The whole point of registering ghi/dni/dhi: the irradiance survives ingestion."""
    from meteosynth.met_data_processor import MetDataProcessor

    frame = fetch_pvgis_tmy(35.34, 25.14, coerce_year=2023)
    for col in ("year", "month", "day", "hour"):
        assert col in frame.columns

    mdp = MetDataProcessor(frame)
    assert "ghi" in mdp.met_data.columns


def test_tmy_coerce_year_is_passed_through_not_applied_for_you(stub_pvlib):
    """Rewriting the year silently would destroy which real year each month came from."""
    fetch_pvgis_tmy(35.34, 25.14)
    assert stub_pvlib["coerce_year"] is None

    fetch_pvgis_tmy(35.34, 25.14, coerce_year=2023)
    assert stub_pvlib["coerce_year"] == 2023


def test_tmy_cache_round_trips(stub_pvlib, tmp_path):
    cache = tmp_path / "tmy.csv"

    first = fetch_pvgis_tmy(35.34, 25.14, cache=cache)
    assert cache.exists()

    stub_pvlib.clear()
    second = fetch_pvgis_tmy(35.34, 25.14, cache=cache)

    assert "coerce_year" not in stub_pvlib      # the network path was not taken
    pd.testing.assert_frame_equal(first, second, check_dtype=False)


def test_horizontal_irradiance_is_actually_validated(stub_pvlib, tmp_path):
    """Before ghi was registered this slipped through unchecked, which is the bug.

    validate_support skips unregistered columns, so a TMY frame used to carry its
    irradiance past the boundary with no check at all -- and then lose it entirely at
    ingestion, since MetDataProcessor trims to the registered set.
    """
    cache = tmp_path / "tmy.csv"
    fetch_pvgis_tmy(35.34, 25.14, cache=cache)

    corrupted = pd.read_csv(cache)
    corrupted.loc[0, "ghi"] = -50.0
    corrupted.to_csv(cache, index=False)

    with pytest.raises(ValueError, match="below its physical lower bound") as excinfo:
        fetch_pvgis_tmy(35.34, 25.14, cache=cache)

    message = str(excinfo.value)
    assert "ghi" in message
    assert "Horizontal-plane irradiance" in message    # the honest long_name, not POA
