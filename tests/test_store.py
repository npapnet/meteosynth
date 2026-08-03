"""Finding a cached record without opening it.

The package already validates a cache you *name*; this covers the other direction --
given a folder, which file answers the question. Two properties carry the design:

* **containment**, so one wide download serves every narrower training period, and
* **refusal**, so a request two files could answer is an error rather than a coin toss.

The second is the one worth guarding. Which record a result was trained on is part of
the result, and any rule that picks for the caller makes that depend on what else
happens to be sitting in the folder.

Network-free and fixture-built throughout: every record here is written by
``MetDataset.save`` into ``tmp_path``.
"""

import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from meteosynth.store import (
    StoredRecord,
    AmbiguousRecordError,
    record_filename,
    record_path_for,
    candidates,
    default_data_dir,
    describe_store,
    read_provenance,
    resolve,
    scan,
)
from meteosynth.dataset import MetDataset
from meteosynth.paths import workspace
from meteosynth.provenance import Provenance


def _write(directory, *, site, start, end, columns=("poa_global",), source="pvgis_hourly",
           latitude=35.3387, longitude=25.1442, name=None):
    """Save a small record covering ``start``-``end`` inclusive, one row group a year."""
    frames = []
    for year in range(start, end + 1):
        index = pd.date_range(f"{year}-06-01", periods=48, freq="h")
        frame = pd.DataFrame({
            "year": index.year, "month": index.month,
            "day": index.day, "hour": index.hour,
            "temp_air": np.linspace(10, 25, len(index)),
            "wind_speed": np.linspace(1, 5, len(index)),
        })
        for col in columns:
            frame[col] = np.clip(np.linspace(0, 700, len(index)), 0, None)
        frames.append(frame)

    provenance = Provenance(
        source=source, site=site, latitude=latitude, longitude=longitude,
        start_year=start, end_year=end,
    )
    dataset = MetDataset(pd.concat(frames, ignore_index=True), provenance=provenance)
    path = pathlib.Path(directory) / (name or record_filename(provenance))
    dataset.save(path)
    return path


# --- the filename convention ---------------------------------------------------------

def test_filename_is_source_site_period():
    prov = Provenance(source="pvgis_hourly", site="heraklion",
                      start_year=2005, end_year=2023)
    assert record_filename(prov) == "pvgis_hourly_heraklion_2005_2023.parquet"


def test_the_existing_examples_convention_is_reproduced_exactly():
    """``examples/tools/site_data.py`` already writes this shape, so nothing migrates."""
    for site, start, end in [("heraklion", 2005, 2023), ("heraklion", 2010, 2020),
                             ("paris", 2011, 2012)]:
        prov = Provenance(source="pvgis_hourly", site=site,
                          start_year=start, end_year=end)
        assert record_filename(prov) == f"pvgis_hourly_{site}_{start}_{end}.parquet"


def test_coordinates_stand_in_for_a_missing_site_label():
    prov = Provenance(source="pvgis_hourly", latitude=35.3387, longitude=25.1442,
                      start_year=2011, end_year=2012)
    assert record_filename(prov) == "pvgis_hourly_35.3387_25.1442_2011_2012.parquet"


def test_a_tmy_carries_no_period_in_its_name():
    """A TMY genuinely has no single year; writing one would be fabrication."""
    prov = Provenance(source="pvgis_tmy", site="heraklion")
    assert record_filename(prov) == "pvgis_tmy_heraklion.parquet"


def test_a_site_label_is_normalised_into_a_filename():
    prov = Provenance(source="pvgis_hourly", site="Heraklion Crete",
                      start_year=2011, end_year=2012)
    assert record_filename(prov) == "pvgis_hourly_heraklion-crete_2011_2012.parquet"


# --- the default location ------------------------------------------------------------

def test_default_data_dir_is_data_under_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert default_data_dir() == tmp_path / "data"


def test_the_store_follows_the_working_directory(tmp_path, monkeypatch):
    """Two projects side by side keep two independent stores."""
    (tmp_path / "project_a").mkdir()
    (tmp_path / "project_b").mkdir()

    monkeypatch.chdir(tmp_path / "project_a")
    first = default_data_dir()
    monkeypatch.chdir(tmp_path / "project_b")
    second = default_data_dir()

    assert first != second
    assert first == tmp_path / "project_a" / "data"


def test_no_environment_variable_can_relocate_the_store(tmp_path, monkeypatch):
    """The store is project-local by construction, with no ambient escape hatch.

    Asserted rather than assumed: an env var was tried during development and removed,
    because it lets a script read a different store depending on which shell launched it.
    """
    monkeypatch.chdir(tmp_path)
    for name in ("METEOSYNTH_CACHE_DIR", "METEOSYNTH_DATA_DIR", "METEOSYNTH_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "elsewhere"))

    assert default_data_dir() == tmp_path / "data"


def test_default_data_dir_is_the_working_directory_workspace(tmp_path, monkeypatch):
    """One definition behind two names, so the store and `FEAT-21`'s rule cannot drift."""
    monkeypatch.chdir(tmp_path)
    assert default_data_dir() == workspace().data_dir


def test_record_path_for_combines_directory_and_convention(tmp_path):
    prov = Provenance(source="pvgis_hourly", site="paris",
                      start_year=2011, end_year=2012)
    assert record_path_for(prov, tmp_path) == tmp_path / "pvgis_hourly_paris_2011_2012.parquet"


# --- scanning ------------------------------------------------------------------------

def test_scan_reads_provenance_and_columns_from_the_footer(tmp_path):
    _write(tmp_path, site="paris", start=2011, end=2012)

    records = scan(tmp_path)

    assert len(records) == 1
    assert isinstance(records[0], StoredRecord)
    assert records[0].provenance.site == "paris"
    assert records[0].provenance.start_year == 2011
    assert "poa_global" in records[0].columns


def test_a_missing_folder_is_empty_not_an_error(tmp_path):
    """"Nothing is cached yet" is the normal first-run state."""
    assert scan(tmp_path / "never-created") == []


def test_a_foreign_parquet_file_is_skipped_not_an_error(tmp_path):
    """A cache folder is allowed to hold files this package did not write."""
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(tmp_path / "something_else.parquet")
    _write(tmp_path, site="paris", start=2011, end=2012)

    records = scan(tmp_path)

    assert [r.provenance.site for r in records] == ["paris"]
    assert read_provenance(tmp_path / "something_else.parquet") is None


def test_a_future_schema_version_is_still_listed(tmp_path):
    """It cannot be *loaded*, but hiding it would make a listing version-dependent."""
    import pyarrow.parquet as pq
    from meteosynth.dataset import _METADATA_KEY

    path = _write(tmp_path, site="paris", start=2011, end=2012)
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata)
    payload = json.loads(metadata[_METADATA_KEY].decode())
    payload["schema_version"] = 99
    metadata[_METADATA_KEY] = json.dumps(payload).encode()
    pq.write_table(table.replace_schema_metadata(metadata), path)

    assert len(scan(tmp_path)) == 1
    with pytest.raises(ValueError, match="schema_version"):
        MetDataset.load(path)


# --- containment ---------------------------------------------------------------------

def test_a_wider_record_answers_a_narrower_request(tmp_path):
    """The property that makes one download per site enough."""
    wide = _write(tmp_path, site="heraklion", start=2005, end=2023)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2010, end=2020) == wide


def test_an_exact_period_still_matches(tmp_path):
    exact = _write(tmp_path, site="heraklion", start=2010, end=2012)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2010, end=2012) == exact


def test_a_narrower_record_does_not_answer_a_wider_request(tmp_path):
    _write(tmp_path, site="heraklion", start=2010, end=2012)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2005, end=2020) is None


def test_a_disjoint_period_does_not_match(tmp_path):
    _write(tmp_path, site="heraklion", start=2010, end=2012)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2015, end=2016) is None


def test_a_request_with_no_period_matches_anything_of_that_site(tmp_path):
    wide = _write(tmp_path, site="heraklion", start=2005, end=2023)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion") == wide


# --- identity: site, coordinates, source ---------------------------------------------

def test_a_different_site_does_not_match(tmp_path):
    _write(tmp_path, site="heraklion", start=2011, end=2012)

    assert resolve(tmp_path, source="pvgis_hourly", site="paris",
                   start=2011, end=2012) is None


def test_a_site_label_is_matched_case_insensitively(tmp_path):
    path = _write(tmp_path, site="heraklion", start=2011, end=2012)

    assert resolve(tmp_path, source="pvgis_hourly", site="HERAKLION",
                   start=2011, end=2012) == path


def test_coordinates_identify_a_site_when_no_label_is_given(tmp_path):
    path = _write(tmp_path, site=None, start=2011, end=2012,
                  latitude=35.3387, longitude=25.1442)

    assert resolve(tmp_path, source="pvgis_hourly", latitude=35.3387,
                   longitude=25.1442, start=2011, end=2012) == path


def test_coordinates_match_to_four_decimals(tmp_path):
    """~11 m. Finer than any provider's grid, coarser than float noise."""
    path = _write(tmp_path, site=None, start=2011, end=2012,
                  latitude=35.3387, longitude=25.1442)

    assert resolve(tmp_path, source="pvgis_hourly", latitude=35.33870000001,
                   longitude=25.14420000001, start=2011, end=2012) == path


def test_a_label_outranks_coordinates(tmp_path):
    """A name the user chose is a stronger statement of intent than a pair of floats."""
    path = _write(tmp_path, site="heraklion", start=2011, end=2012,
                  latitude=35.3387, longitude=25.1442)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   latitude=0.0, longitude=0.0, start=2011, end=2012) == path


def test_a_different_source_does_not_match(tmp_path):
    _write(tmp_path, site="heraklion", start=2011, end=2012, source="pvgis_tmy")

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2011, end=2012) is None


# --- columns -------------------------------------------------------------------------

def test_a_record_without_the_requested_column_does_not_match(tmp_path):
    _write(tmp_path, site="heraklion", start=2011, end=2012, columns=("poa_global",))

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2011, end=2012, column="poa_direct") is None


def test_the_three_components_answer_a_poa_global_request(tmp_path):
    """Reconstruction is exact for PVGIS -- 0.01 W/m2 over 8760 hours, its own rounding.

    Right for the package, and **the reason `examples/diagnostics-overshoot/` still names
    its cache file** rather than letting discovery find it. That record is fetched with
    ``components=False`` for PVGIS's own total; a components record dropped into its folder
    would answer here, silently, and shift the numbers its dated findings cite. Discovery
    matches on site, period and quantity -- never on how a record was collected.
    """
    path = _write(tmp_path, site="heraklion", start=2011, end=2012,
                  columns=("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"))

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2011, end=2012, column="poa_global") == path


def test_a_total_does_not_answer_a_request_for_a_part(tmp_path):
    """Not symmetric: a part is never reconstructible from the total."""
    _write(tmp_path, site="heraklion", start=2011, end=2012, columns=("poa_global",))

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2011, end=2012, column="poa_direct") is None


def test_one_record_per_folder_resolves_without_a_filename(tmp_path):
    """The state `FEAT-21` puts every example folder in, and why they stopped naming files.

    `examples/data/` held two overlapping Heraklion records, so discovery refused and the
    scripts named files to get round it. One store per script folder means one record, so
    the ordinary path answers and the workaround is gone.
    """
    path = _write(tmp_path, site="heraklion", start=2005, end=2023)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2010, end=2020, column="poa_global") == path


def test_the_column_rule_can_break_a_period_tie(tmp_path):
    """Two records cover the period; only one holds the quantity, so it is unambiguous."""
    _write(tmp_path, site="heraklion", start=2005, end=2023, columns=("poa_global",))
    narrow = _write(tmp_path, site="heraklion", start=2010, end=2020,
                    columns=("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"))

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2011, end=2012, column="poa_direct") == narrow


# --- ambiguity -----------------------------------------------------------------------

def test_two_records_answering_the_same_request_refuse(tmp_path):
    """The decision this module exists to *not* take on the caller's behalf."""
    _write(tmp_path, site="heraklion", start=2005, end=2023)
    _write(tmp_path, site="heraklion", start=2010, end=2020)

    with pytest.raises(AmbiguousRecordError) as excinfo:
        resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                start=2011, end=2012)

    message = str(excinfo.value)
    assert "2 stored records" in message
    assert "pvgis_hourly_heraklion_2005_2023.parquet" in message
    assert "pvgis_hourly_heraklion_2010_2020.parquet" in message


def test_the_ambiguity_message_names_the_request(tmp_path):
    """So the reader can see which constraint to tighten."""
    _write(tmp_path, site="heraklion", start=2005, end=2023)
    _write(tmp_path, site="heraklion", start=2010, end=2020)

    with pytest.raises(AmbiguousRecordError, match="site=heraklion"):
        resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                start=2011, end=2012)


def test_candidates_reports_all_of_them_without_raising(tmp_path):
    """`resolve` refuses; `candidates` is how a caller inspects the ambiguity."""
    _write(tmp_path, site="heraklion", start=2005, end=2023)
    _write(tmp_path, site="heraklion", start=2010, end=2020)

    found = candidates(tmp_path, source="pvgis_hourly", site="heraklion",
                       start=2011, end=2012)

    assert len(found) == 2


def test_a_neighbouring_site_does_not_create_ambiguity(tmp_path):
    """Two files, one question: the other site is simply not a candidate."""
    heraklion = _write(tmp_path, site="heraklion", start=2005, end=2023)
    _write(tmp_path, site="paris", start=2005, end=2023,
           latitude=48.8566, longitude=2.3522)

    assert resolve(tmp_path, source="pvgis_hourly", site="heraklion",
                   start=2011, end=2012) == heraklion


# --- listing -------------------------------------------------------------------------

def test_describe_store_lists_what_is_there(tmp_path):
    _write(tmp_path, site="heraklion", start=2005, end=2023)
    _write(tmp_path, site="paris", start=2011, end=2012, latitude=48.8566, longitude=2.3522)

    text = describe_store(tmp_path)

    assert "2 record(s)" in text
    assert "2005-2023" in text
    assert "pvgis_hourly_paris_2011_2012.parquet" in text


def test_describe_store_says_so_when_empty(tmp_path):
    assert "nothing cached" in describe_store(tmp_path)


# --- one definition of "wide enough" -------------------------------------------------

def test_no_period_requested_means_whatever_you_have():
    """The case that broke when discovery and validation each had their own rule."""
    from meteosynth.store import period_contains

    assert period_contains(2005, 2023, None, None) is True
    assert period_contains(None, None, None, None) is True


def test_a_record_without_a_period_covers_nothing_specific():
    """A TMY has no single year; only `source` keeps it out of an hourly request."""
    from meteosynth.store import period_contains

    assert period_contains(None, None, 2011, 2012) is False


def test_containment_is_inclusive_on_both_bounds():
    from meteosynth.store import period_contains

    assert period_contains(2010, 2020, 2010, 2020) is True
    assert period_contains(2010, 2020, 2009, 2020) is False
    assert period_contains(2010, 2020, 2010, 2021) is False


def test_discovery_and_validation_agree_on_coverage(tmp_path):
    """Guards the two paths against drifting apart again.

    `resolve` finds a file; `_use_cache` judges one it was handed. They were written
    separately and disagreed on the no-period case, which showed up as a covering cache
    being refused.
    """
    from meteosynth.adapters import _covers_period

    path = _write(tmp_path, site="heraklion", start=2005, end=2023)
    record = read_provenance(path)
    held = record.provenance

    for start, end in [(None, None), (2010, 2020), (2005, 2023),
                       (2000, 2010), (2015, 2030)]:
        wanted = Provenance(source="pvgis_hourly", start_year=start, end_year=end)
        assert record.covers(start, end) == _covers_period(held, wanted), (start, end)
