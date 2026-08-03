"""The training format: schema, strictness, and round-trip identity.

The three structural checks here exist because none of them was caught at ingestion
before ``MetDataset`` did it. Two were already fatal -- a duplicate calendar row died
inside ``pivot``, an impossible month died inside ``day_slot`` -- but they died several
calls away from the data that needed fixing. The third, physical support, was never
checked at all on the core path: only the adapters looked.
"""

import json
import warnings

import numpy as np
import pandas as pd
import pytest

from meteosynth.dataset import SCHEMA_VERSION, MetDataset
from meteosynth.provenance import Provenance


def _frame(n=48, **overrides):
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


# --- the schema ----------------------------------------------------------------------

def test_dtypes_are_canonicalised_whatever_arrives():
    """Round-trip identity holds by construction rather than by luck."""
    frame = _frame()
    frame["year"] = frame["year"].astype("int64")
    frame["hour"] = frame["hour"].astype("int16")
    frame["temp_air"] = frame["temp_air"].astype("float32")

    dataset = MetDataset(frame)

    assert dataset.met_data["year"].dtype == np.int32
    assert dataset.met_data["hour"].dtype == np.int8
    assert dataset.met_data["temp_air"].dtype == np.float64


def test_rows_are_sorted_by_calendar():
    shuffled = _frame().sample(frac=1.0, random_state=0)

    dataset = MetDataset(shuffled)

    expected = dataset.met_data[["year", "month", "day", "hour"]]
    assert expected.equals(expected.sort_values(["year", "month", "day", "hour"]))


def test_a_shuffled_frame_equals_an_ordered_one():
    """Canonical order means two datasets over the same data are the same dataset."""
    frame = _frame()
    assert MetDataset(frame.sample(frac=1.0, random_state=1)) == MetDataset(frame)


def test_unregistered_columns_are_dropped_by_rule():
    dataset = MetDataset(_frame(some_provider_flag=np.zeros(48)))

    assert "some_provider_flag" not in dataset.met_data.columns


def test_the_callers_frame_is_never_mutated():
    frame = _frame(some_provider_flag=np.zeros(48))
    MetDataset(frame)

    assert "some_provider_flag" in frame.columns


# --- structural rejections -----------------------------------------------------------

def test_duplicate_calendar_rows_raise_and_name_the_dates():
    """Already fatal inside pivot; here it says which rows and why."""
    frame = pd.concat([_frame(24), _frame(24)], ignore_index=True)

    with pytest.raises(ValueError) as excinfo:
        MetDataset(frame)

    message = str(excinfo.value)
    assert "duplicate calendar instant" in message
    assert "2011-01-01" in message


def test_an_impossible_month_raises_at_the_front_door():
    frame = _frame()
    frame.loc[3, "month"] = 13

    with pytest.raises(ValueError, match="month must be in 1..12"):
        MetDataset(frame)


def test_an_impossible_hour_raises():
    frame = _frame()
    frame.loc[3, "hour"] = 24

    with pytest.raises(ValueError, match="hour must be in 0..23"):
        MetDataset(frame)


def test_a_day_out_of_range_for_its_month_raises():
    frame = _frame()
    frame.loc[3, "month"] = 4
    frame.loc[3, "day"] = 31           # April has 30

    with pytest.raises(ValueError, match="day is out of range"):
        MetDataset(frame)


def test_feb_29_is_an_ordinary_date():
    """The all_leap calendar the whole package pools on -- not a special case."""
    frame = _frame(24)
    frame["month"] = 2
    frame["day"] = 29

    assert len(MetDataset(frame).met_data) == 24


def test_a_missing_calendar_value_raises():
    frame = _frame()
    frame.loc[3, "hour"] = np.nan

    with pytest.raises(ValueError, match="contain missing values"):
        MetDataset(frame)


def test_a_frame_with_no_modellable_column_raises():
    frame = _frame().drop(columns=["poa_global", "temp_air", "wind_speed"])

    with pytest.raises(ValueError, match="no modellable column"):
        MetDataset(frame)


def test_a_frame_missing_the_calendar_raises():
    with pytest.raises(ValueError, match="missing required index columns"):
        MetDataset(_frame().drop(columns=["hour"]))


# --- physical support is repaired, not refused ---------------------------------------

def test_out_of_support_values_are_clipped_and_counted():
    """A 19-year record must not be refused over four noisy night readings."""
    frame = _frame()
    frame.loc[0, "poa_global"] = -2.0
    frame.loc[1, "poa_global"] = -0.5

    with pytest.warns(UserWarning, match="clipped"):
        dataset = MetDataset(frame)

    assert dataset.met_data["poa_global"].min() == 0.0
    assert dataset.clipped == {"poa_global": 2}
    assert dataset.describe()["clipped"] == {"poa_global": 2}


def test_a_clean_frame_warns_about_nothing():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dataset = MetDataset(_frame())

    assert dataset.clipped == {}


def test_clipping_does_not_break_round_trip_identity(tmp_path):
    """`clipped` reports this construction, so it takes no part in equality.

    Reloading an already-clipped dataset has nothing left to repair, so including the
    report in __eq__ would mean a dataset never equalled the one that wrote it.
    """
    frame = _frame()
    frame.loc[0, "poa_global"] = -2.0

    with pytest.warns(UserWarning):
        dataset = MetDataset(frame)

    path = tmp_path / "clipped.parquet"
    dataset.save(path)
    reloaded = MetDataset.load(path)

    assert reloaded.clipped == {}          # nothing left to clip
    assert reloaded == dataset             # and yet equal


# --- what it holds -------------------------------------------------------------------

def test_variables_lists_only_registered_columns():
    assert MetDataset(_frame()).variables == ("poa_global", "temp_air", "wind_speed")


def test_describe_reports_the_whole_record_not_the_training_subset():
    """Two different numbers with two different homes -- see FEAT-5's first caution."""
    described = MetDataset(_frame(48)).describe()

    assert described["rows"] == 48
    assert described["dates"] == 2
    assert described["incomplete_dates"] == 0
    assert described["years"] == (2011, 2011)
    assert described["schema_version"] == SCHEMA_VERSION


def test_incomplete_dates_are_reported_not_refused():
    """Sparse records are legitimate input."""
    frame = _frame(30)                      # 24 hours + 6, so day two is partial

    described = MetDataset(frame).describe()

    assert described["dates"] == 2
    assert described["incomplete_dates"] == 1


# --- provenance ----------------------------------------------------------------------

def test_a_hand_built_frame_gets_user_provenance_not_none():
    """Invents nothing -- records that nobody claimed a source."""
    provenance = MetDataset(_frame()).provenance

    assert provenance.source == "user"
    assert provenance.latitude is None


def test_provenance_survives_a_round_trip(tmp_path):
    provenance = Provenance(
        source="pvgis_hourly", site="paris", latitude=48.86, longitude=2.35,
        start_year=2011, end_year=2012, fetched="2026-07-29",
    )
    dataset = MetDataset(_frame(), provenance=provenance)

    path = tmp_path / "paris.parquet"
    dataset.save(path)

    assert MetDataset.load(path).provenance == provenance


def test_unknown_provenance_fields_are_tolerated_with_a_warning():
    """A future `elevation` must not make a dataset unreadable: nothing models it."""
    with pytest.warns(UserWarning, match="unknown provenance field"):
        provenance = Provenance.from_dict(
            {"source": "pvgis_hourly", "elevation": 145.0, "timezone": "UTC"}
        )

    assert provenance.source == "pvgis_hourly"


def test_a_plain_splat_would_have_broken_where_from_dict_does_not():
    """Why from_dict exists at all, asserted rather than asserted in a comment."""
    with pytest.raises(TypeError):
        Provenance(**{"source": "pvgis_hourly", "elevation": 145.0})


# --- I/O -----------------------------------------------------------------------------

def test_save_load_is_lossless(tmp_path):
    """The property the format exists to guarantee."""
    dataset = MetDataset(_frame())
    path = tmp_path / "record.parquet"
    dataset.save(path)

    reloaded = MetDataset.load(path)

    assert reloaded == dataset
    pd.testing.assert_frame_equal(reloaded.met_data, dataset.met_data)   # dtypes too


def test_a_saved_dataset_is_still_plain_parquet(tmp_path):
    """Readable by anything that speaks parquet; only we need to know about the metadata."""
    dataset = MetDataset(_frame())
    path = tmp_path / "record.parquet"
    dataset.save(path)

    plain = pd.read_parquet(path)

    assert list(plain.columns) == list(dataset.met_data.columns)


def test_a_future_schema_version_is_refused_rather_than_guessed(tmp_path):
    """The schema governs the data, so a reader that cannot understand it must stop."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    dataset = MetDataset(_frame())
    path = tmp_path / "future.parquet"
    dataset.save(path)

    table = pq.read_table(path)
    metadata = dict(table.schema.metadata)
    metadata[b"meteosynth"] = json.dumps(
        {"schema_version": SCHEMA_VERSION + 1, "provenance": {"source": "user"}}
    ).encode()
    pq.write_table(table.replace_schema_metadata(metadata), path)

    with pytest.raises(ValueError, match="schema_version"):
        MetDataset.load(path)


def test_a_parquet_without_our_metadata_reads_with_a_warning(tmp_path):
    """Someone else's parquet is usable data; it just cannot say where it came from."""
    path = tmp_path / "foreign.parquet"
    _frame().to_parquet(path, index=False)

    with pytest.warns(UserWarning, match="no meteosynth metadata"):
        dataset = MetDataset.load(path)

    assert dataset.provenance.source == "user"


def test_csv_export_warns_that_it_is_lossy(tmp_path):
    dataset = MetDataset(_frame())

    with pytest.warns(UserWarning, match="lossy"):
        dataset.to_csv(tmp_path / "record.csv")


def test_csv_import_recovers_the_schema_but_not_the_provenance(tmp_path):
    """read_csv/to_csv are two conveniences, not a pair that round-trips."""
    dataset = MetDataset(_frame(), provenance=Provenance(source="pvgis_hourly"))
    path = tmp_path / "record.csv"
    with pytest.warns(UserWarning):
        dataset.to_csv(path)

    reloaded = MetDataset.read_csv(path)

    pd.testing.assert_frame_equal(reloaded.met_data, dataset.met_data)   # schema restored
    assert reloaded.provenance.source == "user"                          # provenance not
    assert reloaded != dataset


# --- views -----------------------------------------------------------------------

def test_month_and_window_subsets_agree_on_date_id(synthetic_ds):
    """The two slicing strategies must not drift on what downstream groups by."""
    month = synthetic_ds.get_month_subset(5)
    window = synthetic_ds.get_day_window_subset(5, 16, n_days=2)

    assert "date_id" in month.columns
    assert "date_id" in window.columns
    assert set(window["date_id"]) <= set(month["date_id"])


# --- period subsetting ---------------------------------------------------------------
#
# The property that makes one download per site enough: a wide record answers a narrow
# request by narrowing, rather than by being re-fetched at the width someone happened to
# want first.

def test_a_period_subset_holds_only_the_requested_years(synthetic_ds):
    subset = synthetic_ds.get_period_subset(2012, 2012)

    assert set(subset.met_data["year"]) == {2012}
    assert len(subset.met_data) < len(synthetic_ds.met_data)


def test_a_period_subset_is_the_same_data(synthetic_ds):
    """Narrowing selects rows; it must not touch a value."""
    subset = synthetic_ds.get_period_subset(2012, 2012)
    expected = synthetic_ds.met_data[synthetic_ds.met_data["year"] == 2012]

    pd.testing.assert_frame_equal(
        subset.met_data, expected.reset_index(drop=True)
    )


def test_a_full_width_subset_is_the_whole_record(synthetic_ds):
    subset = synthetic_ds.get_period_subset(2011, 2012)

    pd.testing.assert_frame_equal(subset.met_data, synthetic_ds.met_data)


def test_a_period_subset_records_the_period_it_now_holds():
    """Not the one it was cut from -- otherwise the record describes a file, not itself."""
    dataset = MetDataset(
        _frame(n=48),
        provenance=Provenance(source="pvgis_hourly", site="paris",
                              start_year=2005, end_year=2023),
    )

    subset = dataset.get_period_subset(2011, 2011)

    assert (subset.provenance.start_year, subset.provenance.end_year) == (2011, 2011)
    assert subset.provenance.site == "paris"          # identity survives
    assert subset.provenance.source == "pvgis_hourly"


def test_a_period_subset_notes_where_it_came_from():
    dataset = MetDataset(
        _frame(n=48),
        provenance=Provenance(source="pvgis_hourly", start_year=2005, end_year=2023),
    )

    subset = dataset.get_period_subset(2011, 2011, origin="heraklion_2005_2023.parquet")

    assert "subset from heraklion_2005_2023.parquet" in subset.provenance.notes


def test_a_period_subset_keeps_any_note_already_there():
    """A derived-column note must not be erased by a narrowing note."""
    dataset = MetDataset(
        _frame(n=48),
        provenance=Provenance(source="pvgis_hourly", start_year=2005, end_year=2023,
                              notes="poa_global summed from components"),
    )

    subset = dataset.get_period_subset(2011, 2011)

    assert "poa_global summed from components" in subset.provenance.notes
    assert "subset from" in subset.provenance.notes


def test_an_uncontained_period_raises_rather_than_returning_the_overlap(synthetic_ds):
    """The overlap answers a different question, silently and plausibly."""
    with pytest.raises(ValueError, match="does not contain"):
        synthetic_ds.get_period_subset(2010, 2012)

    with pytest.raises(ValueError, match="does not contain"):
        synthetic_ds.get_period_subset(2012, 2015)


def test_a_reversed_period_raises(synthetic_ds):
    with pytest.raises(ValueError, match="is after"):
        synthetic_ds.get_period_subset(2012, 2011)


def test_a_period_subset_round_trips_to_disk(tmp_path, synthetic_ds):
    """It is a dataset, not a frame -- so it must survive save/load like one."""
    subset = synthetic_ds.get_period_subset(2012, 2012)
    path = tmp_path / "narrowed.parquet"
    subset.save(path)

    assert MetDataset.load(path) == subset


def test_narrowing_a_real_record_matches_fetching_it_narrow(real_ds):
    """Skipped without the optional real record; exact where it is available."""
    held_start = int(real_ds.met_data["year"].min())
    subset = real_ds.get_period_subset(held_start, held_start)

    assert set(subset.met_data["year"]) == {held_start}
    for col in subset.variables:
        expected = real_ds.met_data.loc[
            real_ds.met_data["year"] == held_start, col
        ].reset_index(drop=True)
        pd.testing.assert_series_equal(subset.met_data[col], expected)
