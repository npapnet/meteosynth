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
from meteosynth.store import AmbiguousRecordError
from meteosynth.dataset import MetDataset
from meteosynth.provenance import Provenance

#: What the stubbed PVGIS claims to serve. Requests outside it fail the way the real API
#: fails -- naming the range -- which is the whole basis of `probe_year_range`.
STUB_YEARS = (2005, 2023)


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
        calls["range"] = (start, end)

        # PVGIS refuses an out-of-range request by *naming the range it does serve*,
        # which is what `probe_year_range` reads instead of bisecting. Reproduced here
        # so the probe is exercised rather than stubbed past.
        if start < STUB_YEARS[0] or end > STUB_YEARS[1]:
            raise ValueError(
                "Requested location is not available. Data is available "
                f"between {STUB_YEARS[0]} and {STUB_YEARS[1]}"
            )

        # Three days per year across the requested span, so a period subset of the
        # result has something to select. The real reader returns every hour; what
        # matters here is that the years asked for are the years present.
        frames = []
        for year in range(start, end + 1):
            index = pd.date_range(f"{year}-06-01", periods=72, freq="h")
            block = pd.DataFrame(index=index)
            block["temp_air"] = np.linspace(5, 20, len(index))
            block["wind_speed"] = np.linspace(1, 6, len(index))
            if components:
                block["poa_direct"] = np.clip(np.linspace(0, 700, len(index)), 0, None)
                block["poa_sky_diffuse"] = np.clip(np.linspace(0, 100, len(index)), 0, None)
                block["poa_ground_diffuse"] = np.zeros(len(index))
            else:
                block["poa_global"] = np.clip(np.linspace(0, 800, len(index)), 0, None)
            frames.append(block)
        return _pad(pd.concat(frames))

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


def test_a_default_fetch_keeps_every_column_the_provider_returned(stub_pvlib):
    """One record per site answers every later question about it.

    PVGIS returns global *or* the three components, never both, so choosing per
    component at fetch time means a download and a file for each. Collecting the
    components serves them all, because the total is recoverable by summation.
    """
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011)

    assert stub_pvlib["components"] is True
    for column in ("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse", "poa_global",
                   "temp_air", "wind_speed"):
        assert column in dataset.met_data.columns, column


def test_a_summed_total_says_so_in_provenance(stub_pvlib):
    """Derived is not the same as measured, and the record carries the difference."""
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011)

    assert "summed" in dataset.provenance.notes


def test_the_summed_total_is_the_sum(stub_pvlib):
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011)

    components = dataset.met_data[
        ["poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"]
    ].sum(axis=1)
    np.testing.assert_allclose(dataset.met_data["poa_global"], components, atol=1e-6)


def test_the_providers_own_total_is_still_reachable(stub_pvlib):
    """`components=False` reproduces what PVGIS itself calls poa_global."""
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2011, components=False)

    assert stub_pvlib["components"] is False
    assert "poa_global" in dataset.met_data.columns
    assert "poa_direct" not in dataset.met_data.columns
    assert "summed" not in (dataset.provenance.notes or ""), "this total is measured"


def test_a_component_cannot_be_asked_for_without_components(stub_pvlib):
    with pytest.raises(ValueError, match="needs components=True"):
        fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct", components=False)


# The emitted column keeps its specific name, so the NAME records the quantity.
# Provenance records what a name cannot: which site, which years, which source.
def test_the_column_name_is_the_quantity(stub_pvlib):
    globals_ds = fetch_pvgis(48.86, 2.35, 2011, 2011, components=False)
    direct_ds = fetch_pvgis(48.86, 2.35, 2011, 2011, irradiance="direct")

    assert set(globals_ds.variables) != set(direct_ds.variables)
    assert "poa_global" in globals_ds.variables
    assert "poa_direct" in direct_ds.variables
    assert "poa_direct" not in globals_ds.variables


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


def test_an_uncovered_period_is_a_mismatch(stub_pvlib, tmp_path):
    """`full_range=False` is what makes a narrow cache; it then cannot answer wider."""
    cache = tmp_path / "site.parquet"
    fetch_pvgis(48.86, 2.35, 2011, 2011, cache=cache, full_range=False)

    with pytest.raises(CacheMismatchError, match="period"):
        fetch_pvgis(48.86, 2.35, 2015, 2016, cache=cache, full_range=False)


def test_a_cache_holding_only_the_total_cannot_answer_for_a_component(stub_pvlib, tmp_path):
    """One PVGIS fetch cannot carry both forms -- the case that motivated the item."""
    cache = tmp_path / "site.parquet"
    fetch_pvgis(48.86, 2.35, 2011, 2011, components=False, cache=cache)

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


# --- containment: a wider cache answers a narrower request ---------------------------
#
# The property that makes one download per site enough. These build their cache directly
# rather than through the stub, because the stub returns a fixed 72 hours regardless of
# the range asked for -- fine for every other test here, useless for one about coverage.

def _multi_year_cache(path, *, start, end, columns=("poa_global",),
                      latitude=48.86, longitude=2.35, site=None):
    """A real cached record physically spanning ``start``-``end``."""
    frames = []
    for year in range(start, end + 1):
        index = pd.date_range(f"{year}-06-01", periods=48, freq="h")
        frame = pd.DataFrame({
            "year": index.year, "month": index.month,
            "day": index.day, "hour": index.hour,
            "temp_air": np.linspace(5, 20, len(index)),
            "wind_speed": np.linspace(1, 6, len(index)),
        })
        for col in columns:
            frame[col] = np.clip(np.linspace(0, 700, len(index)), 0, None)
        frames.append(frame)

    MetDataset(
        pd.concat(frames, ignore_index=True),
        provenance=Provenance(source="pvgis_hourly", site=site, latitude=latitude,
                              longitude=longitude, start_year=start, end_year=end),
    ).save(path)
    return path


def test_a_wider_cache_answers_a_narrower_request(stub_pvlib, tmp_path):
    cache = _multi_year_cache(tmp_path / "wide.parquet", start=2005, end=2015)

    dataset = fetch_pvgis(48.86, 2.35, 2010, 2012, cache=cache)

    assert set(dataset.met_data["year"]) == {2010, 2011, 2012}
    assert stub_pvlib == {}, "a covering cache must not touch the network"


def test_a_narrowed_result_records_the_period_it_holds(stub_pvlib, tmp_path):
    cache = _multi_year_cache(tmp_path / "wide.parquet", start=2005, end=2015)

    dataset = fetch_pvgis(48.86, 2.35, 2010, 2012, cache=cache)

    assert (dataset.provenance.start_year, dataset.provenance.end_year) == (2010, 2012)
    assert "subset from wide.parquet" in dataset.provenance.notes


def test_an_exactly_matching_cache_is_returned_whole(stub_pvlib, tmp_path):
    """No narrowing, and therefore no 'subset from' note to explain."""
    cache = _multi_year_cache(tmp_path / "exact.parquet", start=2010, end=2012)

    dataset = fetch_pvgis(48.86, 2.35, 2010, 2012, cache=cache)

    assert (dataset.provenance.start_year, dataset.provenance.end_year) == (2010, 2012)
    assert not (dataset.provenance.notes or "")


def test_a_narrower_cache_does_not_answer_a_wider_request(stub_pvlib, tmp_path):
    """Overlap is not coverage: the missing years have to come from somewhere."""
    cache = _multi_year_cache(tmp_path / "narrow.parquet", start=2010, end=2012)

    with pytest.raises(CacheMismatchError, match="does not contain"):
        fetch_pvgis(48.86, 2.35, 2005, 2015, cache=cache)


def test_a_partially_overlapping_cache_is_still_a_mismatch(stub_pvlib, tmp_path):
    cache = _multi_year_cache(tmp_path / "partial.parquet", start=2010, end=2012)

    with pytest.raises(CacheMismatchError, match="does not contain"):
        fetch_pvgis(48.86, 2.35, 2011, 2015, cache=cache)


def test_containment_does_not_weaken_the_site_check(stub_pvlib, tmp_path):
    """The defect FEAT-13 was filed for must survive the period rule loosening."""
    cache = _multi_year_cache(tmp_path / "heraklion.parquet", start=2005, end=2015,
                              latitude=35.3387, longitude=25.1442)

    with pytest.raises(CacheMismatchError, match="site"):
        fetch_pvgis(48.86, 2.35, 2010, 2012, cache=cache)


def test_the_three_components_answer_a_request_for_the_total(stub_pvlib, tmp_path):
    """A total is reconstructible from its parts; the reverse is never true."""
    cache = _multi_year_cache(
        tmp_path / "components.parquet", start=2010, end=2012,
        columns=("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"),
    )

    dataset = fetch_pvgis(48.86, 2.35, 2010, 2012, irradiance="global", cache=cache)

    assert stub_pvlib == {}, "the components cover the request; no fetch needed"
    assert "poa_direct" in dataset.met_data.columns


def test_a_total_does_not_answer_a_request_for_a_part(stub_pvlib, tmp_path):
    cache = _multi_year_cache(tmp_path / "total.parquet", start=2010, end=2012,
                              columns=("poa_global",))

    with pytest.raises(CacheMismatchError, match="columns"):
        fetch_pvgis(48.86, 2.35, 2010, 2012, irradiance="direct", cache=cache)


# --- fetch once per site: the default cache, probing, and site labels -----------------

def test_a_fetch_stores_in_the_default_data_dir(stub_pvlib, tmp_path):
    """Nothing named, and it still lands somewhere findable next time."""

    fetch_pvgis(48.86, 2.35, site="paris")

    written = list((tmp_path / "data").glob("*.parquet"))
    assert [p.name for p in written] == ["pvgis_hourly_paris_2005_2023.parquet"]


def test_the_default_cache_is_found_again_without_being_named(stub_pvlib, tmp_path):
    first = fetch_pvgis(48.86, 2.35, site="paris")

    stub_pvlib.clear()
    second = fetch_pvgis(48.86, 2.35, site="paris")

    assert stub_pvlib == {}, "a covering record was already on disk"
    assert first == second


def test_cache_false_neither_reads_nor_writes(stub_pvlib, tmp_path):

    fetch_pvgis(48.86, 2.35, site="paris", cache=False)
    assert not (tmp_path / "data").exists()

    stub_pvlib.clear()
    fetch_pvgis(48.86, 2.35, site="paris", cache=False)
    assert stub_pvlib["components"] is True, "caching off means the network every time"


def test_the_download_is_the_widest_range_the_provider_serves(stub_pvlib):
    """`start`/`end` select a view; they do not size the download."""
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2012)

    assert stub_pvlib["range"] == STUB_YEARS
    assert set(dataset.met_data["year"]) == {2011, 2012}
    assert (dataset.provenance.start_year, dataset.provenance.end_year) == (2011, 2012)


def test_the_whole_record_is_returned_when_no_period_is_asked_for(stub_pvlib):
    dataset = fetch_pvgis(48.86, 2.35)

    assert (dataset.provenance.start_year,
            dataset.provenance.end_year) == STUB_YEARS


def test_full_range_false_downloads_only_what_was_asked_for(stub_pvlib):
    dataset = fetch_pvgis(48.86, 2.35, 2011, 2012, full_range=False)

    assert stub_pvlib["range"] == (2011, 2012)
    assert (dataset.provenance.start_year, dataset.provenance.end_year) == (2011, 2012)


def test_full_range_false_needs_a_period(stub_pvlib):
    with pytest.raises(ValueError, match="needs an explicit start and end"):
        fetch_pvgis(48.86, 2.35, full_range=False)


def test_a_period_the_provider_cannot_serve_is_refused(stub_pvlib):
    """Better than silently returning the overlap, which is what a clamp would do."""
    with pytest.raises(ValueError, match="does not contain the requested"):
        fetch_pvgis(48.86, 2.35, 1990, 2000)


def test_half_a_period_is_refused(stub_pvlib):
    with pytest.raises(ValueError, match="both start and end or neither"):
        fetch_pvgis(48.86, 2.35, start=2011)


def test_probe_reads_the_range_out_of_the_providers_own_error(stub_pvlib):
    """One deliberately-failing request names both bounds -- no bisection."""
    assert adapters.probe_year_range(48.86, 2.35) == STUB_YEARS


def test_an_unparseable_probe_refuses_rather_than_guessing(monkeypatch):
    """Guessing a range here would silently truncate a record."""
    module = types.ModuleType("pvlib.iotools")

    def get_pvgis_hourly(**kwargs):
        raise ValueError("the service is having a bad day")

    module.get_pvgis_hourly = get_pvgis_hourly
    parent = types.ModuleType("pvlib")
    parent.iotools = module
    monkeypatch.setitem(sys.modules, "pvlib", parent)
    monkeypatch.setitem(sys.modules, "pvlib.iotools", module)

    with pytest.raises(RuntimeError, match="could not read a year range"):
        adapters.probe_year_range(48.86, 2.35)


def test_a_site_label_resolves_coordinates_after_the_first_fetch(stub_pvlib, tmp_path):
    """The point of a label: type it once with coordinates, then never again."""
    fetch_pvgis(35.3387, 25.1442, site="heraklion")

    stub_pvlib.clear()
    dataset = fetch_pvgis(site="heraklion", start=2010, end=2020)

    assert stub_pvlib == {}
    assert (dataset.provenance.latitude, dataset.provenance.longitude) == (35.3387, 25.1442)
    assert set(dataset.met_data["year"]) == set(range(2010, 2021))


def test_an_unknown_site_label_says_what_it_needs(stub_pvlib, tmp_path):

    with pytest.raises(ValueError, match="coordinates are unknown"):
        fetch_pvgis(site="atlantis", start=2011, end=2012)


def test_coordinates_are_required_when_nothing_identifies_the_site(stub_pvlib):
    with pytest.raises(ValueError, match="give latitude and longitude"):
        fetch_pvgis(start=2011, end=2012)


def test_an_ambiguous_default_cache_refuses(stub_pvlib, tmp_path):
    """Two records answer; choosing would make the result depend on the folder."""
    cache_dir = tmp_path / "data"
    fetch_pvgis(48.86, 2.35, site="paris")
    _multi_year_cache(cache_dir / "hand_placed.parquet", start=2005, end=2020,
                      columns=("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse",
                               "poa_global"),
                      latitude=48.86, longitude=2.35, site="paris")

    with pytest.raises(AmbiguousRecordError, match="2 stored records"):
        fetch_pvgis(48.86, 2.35, site="paris", start=2011, end=2012)


def test_force_refetch_ignores_a_covering_cache(stub_pvlib, tmp_path):
    fetch_pvgis(48.86, 2.35, site="paris")

    stub_pvlib.clear()
    fetch_pvgis(48.86, 2.35, site="paris", force_refetch=True)

    assert stub_pvlib["components"] is True


def test_tmy_caching_stays_opt_in(stub_pvlib, tmp_path):
    """The asymmetry with fetch_pvgis is deliberate, so assert it rather than assume it.

    A TMY's identity is not fully expressible in provenance -- `coerce_year` and
    `roll_utc_offset` change what comes back and neither is a provenance field -- so a
    record found by *searching* could answer a different question than the one asked.
    """

    fetch_pvgis_tmy(48.86, 2.35, site="paris")

    assert not (tmp_path / "data").exists()


def test_a_named_tmy_cache_still_round_trips(stub_pvlib, tmp_path):
    cache = tmp_path / "tmy.parquet"

    first = fetch_pvgis_tmy(48.86, 2.35, site="paris", cache=cache)
    assert cache.exists()

    stub_pvlib.clear()
    second = fetch_pvgis_tmy(48.86, 2.35, site="paris", cache=cache)

    assert "coerce_year" not in stub_pvlib      # the network path was not taken
    assert first == second


def test_a_tmy_and_an_hourly_record_do_not_answer_for_each_other(stub_pvlib, tmp_path):
    """Different sources, so an hourly default cache never resolves to a TMY."""
    fetch_pvgis(48.86, 2.35, site="paris")
    fetch_pvgis_tmy(48.86, 2.35, site="paris", cache=tmp_path / "cache" / "tmy.parquet")

    stub_pvlib.clear()
    hourly = fetch_pvgis(48.86, 2.35, site="paris", start=2011, end=2012)

    assert stub_pvlib == {}, "the hourly record was cached; the TMY must not confuse it"
    assert hourly.provenance.source == "pvgis_hourly"
    assert "ghi" not in hourly.met_data.columns


def test_data_dir_relocates_the_store_per_call(stub_pvlib, tmp_path):
    """The explicit replacement for the environment variable that was removed."""
    fetch_pvgis(48.86, 2.35, site="paris", data_dir=tmp_path / "inputs")

    assert [p.name for p in (tmp_path / "inputs").glob("*.parquet")] == [
        "pvgis_hourly_paris_2005_2023.parquet"
    ]
    assert not (tmp_path / "data").exists(), "the default was not used"


def test_a_record_is_found_again_in_the_same_data_dir(stub_pvlib, tmp_path):
    first = fetch_pvgis(48.86, 2.35, site="paris", data_dir=tmp_path / "inputs")

    stub_pvlib.clear()
    second = fetch_pvgis(site="paris", start=2011, end=2012, data_dir=tmp_path / "inputs")

    assert stub_pvlib == {}, "the store answered; no download"
    assert second.provenance.start_year == 2011
    assert first.provenance.site == second.provenance.site


def test_two_data_dirs_are_independent_stores(stub_pvlib, tmp_path):
    """What "project-local" means: one project cannot read another's records."""
    fetch_pvgis(48.86, 2.35, site="paris", data_dir=tmp_path / "project_a")

    stub_pvlib.clear()
    fetch_pvgis(48.86, 2.35, site="paris", data_dir=tmp_path / "project_b")

    assert stub_pvlib["components"] is True, "project_b had to fetch for itself"
    assert (tmp_path / "project_a" / "pvgis_hourly_paris_2005_2023.parquet").exists()
    assert (tmp_path / "project_b" / "pvgis_hourly_paris_2005_2023.parquet").exists()


def test_data_dir_is_ignored_when_a_file_is_named(stub_pvlib, tmp_path):
    """`cache=` has always meant "this exact file", and still does."""
    named = tmp_path / "named.parquet"

    fetch_pvgis(48.86, 2.35, site="paris", cache=named, data_dir=tmp_path / "inputs")

    assert named.exists()
    assert not (tmp_path / "inputs").exists()
