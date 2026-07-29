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
    CacheMismatchError,
    fetch_pvgis,
    fetch_pvgis_tmy,
    normalise,
    validate_support,
)
from meteosynth.dataset import MetDataset


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


# --- support validation, as an opt-in hard check -------------------------------------
#
# MetDataset clips rather than raises, so ingestion is uniform however the data arrived.
# validate_support survives as the stricter check a caller can ask for explicitly, which
# keeps both behaviours available and neither of them implicit.

def test_kelvin_temperature_slips_through():
    """Kelvin is *above* absolute zero, so the lower bound does not catch it.

    Documented rather than fixed: support validation is a necessary condition, not a
    sufficient one, and catching this would need the unit conversion the package
    deliberately excludes.
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
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011)

    assert "poa_global" in dataset.met_data.columns
    assert "poa_direct" not in dataset.met_data.columns
    assert stub_pvlib["components"] is False


def test_direct_is_opted_into(stub_pvlib):
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct")

    assert "poa_direct" in dataset.met_data.columns
    assert "poa_global" not in dataset.met_data.columns
    assert stub_pvlib["components"] is True


# The emitted column keeps its specific name, so the NAME records the quantity.
# Provenance records what a name cannot: which site, which years, which source.
def test_the_column_name_is_the_quantity(stub_pvlib):
    globals_ds = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="global")
    direct_ds = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct")

    assert set(globals_ds.variables) != set(direct_ds.variables)
    assert "poa_global" in globals_ds.variables
    assert "poa_direct" in direct_ds.variables


def test_a_fetch_stamps_provenance(stub_pvlib):
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011, site="paris")

    assert dataset.provenance.source == "pvgis_hourly"
    assert dataset.provenance.site == "paris"
    assert (dataset.provenance.latitude, dataset.provenance.longitude) == (48.86, 2.35)
    assert (dataset.provenance.start_year, dataset.provenance.end_year) == (2011, 2011)
    assert dataset.provenance.fetched is not None


def test_a_fetched_dataset_is_canonical(stub_pvlib):
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011)

    for col in ("year", "month", "day", "hour"):
        assert col in dataset.met_data.columns
    assert dataset.irradiance_column == "poa_global"


# --- caching -------------------------------------------------------------------------

def test_cache_round_trips(stub_pvlib, tmp_path):
    """Collection is slow and networked; modelling is not, and often runs later."""
    cache = tmp_path / "site.parquet"

    first = fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)
    assert cache.exists()

    stub_pvlib.clear()
    second = fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)

    assert "components" not in stub_pvlib      # the network path was not taken
    assert first == second                     # round-trip identity, dtypes included


def test_a_cache_must_be_parquet(stub_pvlib, tmp_path):
    """CSV carries neither provenance nor dtypes, so it cannot answer a match check."""
    with pytest.raises(ValueError, match="must be a .parquet path"):
        fetch_pvgis(48.86, 2.35, 2011, 2011, cache=tmp_path / "site.csv")


def test_a_different_site_is_a_mismatch_not_a_silent_answer(stub_pvlib, tmp_path):
    """The defect this item was filed for: a warm cache answering the wrong question."""
    cache = tmp_path / "heraklion.parquet"
    fetch_pvgis(35.3387, 25.1442, 2011, 2011, cache=cache)

    with pytest.raises(CacheMismatchError) as excinfo:
        fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)

    message = str(excinfo.value)
    assert "site" in message
    assert "35.3387" in message and "48.86" in message


def test_a_different_period_is_a_mismatch(stub_pvlib, tmp_path):
    cache = tmp_path / "site.parquet"
    fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache)

    with pytest.raises(CacheMismatchError, match="period"):
        fetch_pvgis(48.86, 2.35, 2015, 2016, cache=cache)


def test_a_different_irradiance_form_is_a_mismatch(stub_pvlib, tmp_path):
    """One PVGIS fetch cannot carry both forms -- the case that motivated the item."""
    cache = tmp_path / "site.parquet"
    fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="global", cache=cache)

    with pytest.raises(CacheMismatchError, match="columns"):
        fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct", cache=cache)


def test_coordinates_match_to_four_decimals(stub_pvlib, tmp_path):
    """Float noise must not read as a different site and cost a silent re-download."""
    cache = tmp_path / "site.parquet"
    fetch_pvgis(35.3387, 25.1442, 2011, 2011, cache=cache)

    stub_pvlib.clear()
    fetch_pvgis(35.33870000001, 25.14420000001, 2011, 2011, cache=cache)

    assert "components" not in stub_pvlib      # matched, so no network


def test_force_refetch_overwrites_a_mismatched_cache(stub_pvlib, tmp_path):
    """The explicit way to repurpose a path, so nothing is destroyed by accident."""
    cache = tmp_path / "site.parquet"
    fetch_pvgis(35.3387, 25.1442, 2011, 2011, cache=cache)

    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache, force_refetch=True)

    assert dataset.provenance.latitude == 48.86
    assert MetDataset.load(cache).provenance.latitude == 48.86


def test_adapters_are_optional(synthetic_ds):
    """Use case B: the user already has data and no adapter is involved at all."""
    assert synthetic_ds.met_data is not None
    assert "temp_air" in synthetic_ds.met_data.columns
    assert synthetic_ds.provenance.source == "user"


# --- arity independence -------------------------------------------------------------
#
# The defect this guards against: pvlib changed how many values its PVGIS readers
# return, and the old metdata_pvgis module unpacked fixed shapes, so both of its fetch
# functions raised on every call. Nothing depended on them, so the suite stayed green
# and it went unnoticed until someone followed the README.

@pytest.mark.parametrize("arity", [2, 3, 4])
def test_hourly_survives_any_pvlib_return_arity(monkeypatch, arity):
    _install_stub_pvlib(monkeypatch, arity=arity)

    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011)

    assert "poa_global" in dataset.met_data.columns
    assert len(dataset.met_data) == 72


@pytest.mark.parametrize("arity", [2, 3, 4])
def test_tmy_survives_any_pvlib_return_arity(monkeypatch, arity):
    _install_stub_pvlib(monkeypatch, arity=arity)

    dataset = fetch_pvgis_tmy(35.34, 25.14)

    assert "ghi" in dataset.met_data.columns
    assert len(dataset.met_data) == 8760


# --- TMY ----------------------------------------------------------------------------

def test_tmy_irradiance_is_horizontal_not_plane_of_array(stub_pvlib):
    """Different quantity, different names -- they differ by however much a panel tilts.

    Silently interchanging them is the factor-of-two error the naming scheme exists to
    prevent, in the plane dimension rather than the component one.
    """
    dataset = fetch_pvgis_tmy(35.34, 25.14)

    assert {"ghi", "dni", "dhi"} <= set(dataset.variables)
    assert not any(col.startswith("poa_") for col in dataset.variables)


def test_tmy_resolves_to_ghi(stub_pvlib):
    """A caller should not need to know which of the two fetchers produced their data."""
    assert fetch_pvgis_tmy(35.34, 25.14).irradiance_column == "ghi"


def test_tmy_drops_unregistered_columns_by_rule(stub_pvlib):
    """PVGIS supplies pressure and friends; a column is kept iff it has a spec."""
    dataset = fetch_pvgis_tmy(35.34, 25.14)

    assert "pressure" not in dataset.met_data.columns
    assert set(dataset.met_data.columns) == {
        "ghi", "dni", "dhi", "temp_air", "wind_speed",
        "year", "month", "day", "hour",
    }


def test_tmy_records_no_period_rather_than_a_fabricated_one(stub_pvlib):
    """Each month comes from a different real year, so there is no range to write."""
    provenance = fetch_pvgis_tmy(35.34, 25.14).provenance

    assert provenance.source == "pvgis_tmy"
    assert provenance.start_year is None
    assert provenance.end_year is None


def test_tmy_coerce_year_is_passed_through_not_applied_for_you(stub_pvlib):
    """Rewriting the year silently would destroy which real year each month came from."""
    fetch_pvgis_tmy(35.34, 25.14)
    assert stub_pvlib["coerce_year"] is None

    fetch_pvgis_tmy(35.34, 25.14, coerce_year=2023)
    assert stub_pvlib["coerce_year"] == 2023


def test_tmy_cache_round_trips(stub_pvlib, tmp_path):
    cache = tmp_path / "tmy.parquet"

    first = fetch_pvgis_tmy(35.34, 25.14, cache=cache)
    assert cache.exists()

    stub_pvlib.clear()
    second = fetch_pvgis_tmy(35.34, 25.14, cache=cache)

    assert "coerce_year" not in stub_pvlib      # the network path was not taken
    assert first == second
