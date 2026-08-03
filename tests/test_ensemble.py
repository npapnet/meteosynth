"""Ensembles: one calendar walk for N realisations, and the file it writes.

Two families of test here, and they guard different things.

The **reproducibility** tests pin the property the whole feature turns on: a realisation is
identified by its index and its attribute, and by nothing else. Get that wrong and results
silently depend on how many realisations were asked for, or on which other attributes came
along -- failures that leave no trace in the output because a wrong weather value still
looks like a weather value.

The **cost** test (``test_a_walk_fits_each_calendar_day_exactly_once``) is the one that
guards the reason this code exists. Everything else here would still pass if the loops were
re-inverted and every realisation refitted its own models.
"""

import json
import warnings

import numpy as np
import pandas as pd
import pytest

from meteosynth import (
    DayWindowGenerator,
    Ensemble,
    MetDataset,
    ENSEMBLE_SCHEMA_VERSION,
    ensemble_to_xlsx,
    read_ensemble,
    realisation_stream,
    write_ensemble,
)
from meteosynth.day_window import day_slot
from meteosynth.generators import EnvSeriesGenerator, _walk_ensemble
from meteosynth.markov_chain_simulator_kde2d import _GRID_ACTIVATION_CALLS
from meteosynth.variables import get_spec

# Small enough to keep the suite quick, large enough that a wrapped walk and several
# realisations are genuinely exercised.
DAYS = 3
WINDOW = 15


# --- reproducibility: what identifies a realisation --------------------------------

@pytest.mark.parametrize("n", [2, 7, 30])
def test_a_realisation_does_not_depend_on_how_many_were_requested(synthetic_ds, n):
    """The failure a single shared random stream would cause.

    Realisation 0 of a 2-member ensemble must be realisation 0 of a 30-member one. Drawn
    from one stream instead of one per realisation, every member shifts when ``n`` changes
    and nothing in the output says so.

    All sizes here sit below the grid-activation threshold, so the sampler is constant
    across them; ``test_crossing_the_sampling_crossover`` covers what happens above it.
    """
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    reference = dwg.generate_ensemble((6, 15), DAYS, 2, seed=11)
    many = dwg.generate_ensemble((6, 15), DAYS, n, seed=11)

    np.testing.assert_array_equal(many[0], reference[0])
    np.testing.assert_array_equal(many[1], reference[1])


def test_realisations_within_an_ensemble_differ(synthetic_ds):
    """Independence, not just reproducibility: distinct streams must give distinct series."""
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    ens = dwg.generate_ensemble((6, 15), DAYS, 4, seed=11)

    for i in range(1, 4):
        assert not np.array_equal(ens[0], ens[i])


def test_the_same_call_twice_gives_the_same_ensemble(synthetic_ds):
    """Idempotence on a warm object.

    This is not a formality: the LRU cache holds *sampler state*, not only fitted models. A
    cached simulator remembers how often it has been sampled, so one that has already
    crossed PERF-1's threshold answers from its quantile grid where a fresh one answers
    directly. Without clearing the cache, a second identical call returns different numbers.
    """
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    first = dwg.generate_ensemble((6, 15), DAYS, 3, seed=5)
    # Warm the object hard enough to build grids, which is what used to leak.
    dwg.generate_ensemble((6, 15), DAYS, _GRID_ACTIVATION_CALLS + 5, seed=99)
    second = dwg.generate_ensemble((6, 15), DAYS, 3, seed=5)

    np.testing.assert_array_equal(first, second)


def test_an_attribute_does_not_depend_on_which_others_were_requested(synthetic_ds, tmp_path):
    """Attribute streams are keyed by *name*, not by position in the request.

    Keyed positionally -- as ``examples/use_cases/year/synthetic_year.py`` once was --
    dropping ``poa_direct`` from the list moves ``temp_air`` from index 1 to 0 and changes
    the temperature series for the same nominal seed.
    """
    alone = tmp_path / "alone.parquet"
    together = tmp_path / "together.parquet"
    write_ensemble(synthetic_ds, ("temp_air",), alone, start=(6, 15), n_days=DAYS,
                   n_realisations=3, seed=4, n_days_window=WINDOW)
    write_ensemble(synthetic_ds, ("poa_direct", "temp_air", "wind_speed"), together,
                   start=(6, 15), n_days=DAYS, n_realisations=3, seed=4,
                   n_days_window=WINDOW)

    one = read_ensemble(alone).frame["temp_air"].to_numpy()
    many = read_ensemble(together).frame["temp_air"].to_numpy()
    np.testing.assert_array_equal(one, many)


def test_attributes_do_not_share_a_random_stream():
    """Two attributes drawing the same uniforms would be spuriously locked together.

    Attributes are modelled independently, so one shared stream would push identical
    uniform draws through every attribute's inverse CDF -- a correlation that looks like
    physics and is an artefact of the plumbing.
    """
    a = realisation_stream(3, 0, "temp_air").random(20)
    b = realisation_stream(3, 0, "wind_speed").random(20)
    assert not np.array_equal(a, b)


def test_realisation_streams_are_keyed_by_index_not_by_count():
    """The numpy-level property the whole scheme rests on."""
    for i in (0, 3, 9):
        np.testing.assert_array_equal(
            realisation_stream(1, i, "temp_air").random(4),
            realisation_stream(1, i, "temp_air").random(4),
        )
    assert not np.array_equal(
        realisation_stream(1, 0, "temp_air").random(4),
        realisation_stream(1, 1, "temp_air").random(4),
    )


def test_crossing_the_sampling_crossover_is_documented_and_controllable(synthetic_ds):
    """Above 64 realisations `sampling="auto"` picks the grid, which changes the last digits.

    Pinned rather than fixed: the alternative is a sampler that changes part-way through an
    ensemble, leaving the first 64 members drawn differently from the rest. **Naming the
    path** -- `sampling="grid"` or `"exact"` -- is the documented way to compare across the
    crossover, and since `FEAT-17` it is the only thing that decides it.
    """
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    small = dwg.generate_ensemble((6, 15), DAYS, 3, seed=8)
    large = dwg.generate_ensemble((6, 15), DAYS, _GRID_ACTIVATION_CALLS + 3, seed=8)
    assert not np.array_equal(small[0], large[0]), (
        "expected the sampler to differ across the boundary; if this now passes, the "
        "threshold logic changed and the docstring needs revisiting"
    )

    # Forced to the same setting, the two agree exactly.
    forced_small = dwg.generate_ensemble((6, 15), DAYS, 3, seed=8, sampling="grid")
    forced_large = dwg.generate_ensemble(
        (6, 15), DAYS, _GRID_ACTIVATION_CALLS + 3, seed=8, sampling="grid"
    )
    np.testing.assert_array_equal(forced_small[0], forced_large[0])

    # And the other way: forced exact, the two also agree -- which `precompute=False`
    # never managed, because the counter built the grid anyway on the 65th draw.
    exact_small = dwg.generate_ensemble((6, 15), DAYS, 3, seed=8, sampling="exact")
    exact_large = dwg.generate_ensemble(
        (6, 15), DAYS, _GRID_ACTIVATION_CALLS + 3, seed=8, sampling="exact"
    )
    np.testing.assert_array_equal(exact_small[0], exact_large[0])


# --- agreement with the single-series path -----------------------------------------

def test_one_realisation_equals_generate_series_on_the_same_stream(synthetic_ds):
    """generate_series is the n_realisations=1 case, and must stay so.

    Both walk the same code; this pins that the ensemble wrapper adds nothing to the
    arithmetic.
    """
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    ensemble = dwg.generate_ensemble((6, 15), DAYS, 1, seed=21)[0]
    series = dwg.generate_series((6, 15), DAYS, rng=realisation_stream(21, 0, "temp_air"))

    np.testing.assert_array_equal(ensemble, series)


@pytest.mark.parametrize("index", [0, 1, 4])
def test_each_realisation_is_the_series_from_its_own_stream(synthetic_ds, index):
    """Every member is independently a correct chained series -- the strong form.

    Fixture-independent, and it is what actually proves the chaining is *per realisation*:
    if day d+1's hour 0 were conditioned on the wrong realisation's 23:00, the member would
    stop matching the single series driven by the same stream. A correlation test cannot
    show this (see ``test_an_ensemble_is_chained_within_each_realisation``), because it
    would also pass if the realisations were subtly crossed.
    """
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    ensemble = dwg.generate_ensemble((6, 15), 6, 5, seed=2)
    alone = dwg.generate_series(
        (6, 15), 6, rng=realisation_stream(2, index, "temp_air")
    )

    np.testing.assert_array_equal(ensemble[index], alone)


def test_an_ensemble_is_chained_within_each_realisation(real_ds):
    """Midnight is a link inside a realisation, not a reset.

    On the **real** record, as ``test_cross_midnight`` does for a single series: the
    synthetic fixture's ``temp_air`` is a constant plus per-hour independent noise, so its
    23:00 and the next 00:00 are genuinely uncorrelated and a model fitted to it correctly
    reproduces that. Only a record with real autocorrelation can test this.
    """
    dwg = DayWindowGenerator(real_ds, attr_str="temp_air", n_days=WINDOW)
    ens = dwg.generate_ensemble((6, 15), 20, 6, seed=2)

    within = np.corrcoef(ens[:, :-1, -1].ravel(), ens[:, 1:, 0].ravel())[0, 1]
    assert within > 0.8, "a chained midnight must carry that realisation's own 23:00"


def test_every_value_stays_inside_the_registered_support(synthetic_ds):
    """The defect class that shipped once: negative irradiance."""
    dwg = DayWindowGenerator(synthetic_ds, attr_str="poa_direct", n_days=WINDOW)
    ens = dwg.generate_ensemble((6, 15), DAYS, 8, seed=3)

    low, high = get_spec("poa_direct").support
    assert np.isfinite(ens).all()
    assert ens.min() >= low
    if high is not None:
        assert ens.max() <= high


# --- the cost this feature exists to remove ----------------------------------------

def test_a_walk_fits_each_calendar_day_exactly_once(synthetic_ds, monkeypatch):
    """**The regression guard for this whole feature.**

    Calling generate_series N times refits every day N times, because an ordered calendar
    walk never revisits a slot and so the LRU cache never hits. Measured before this
    landed: 150 fits for 30 distinct days over 5 realisations.

    Every other test in this file would still pass if that came back.
    """
    fits = []
    original = EnvSeriesGenerator.__init__

    def counting(self, *args, **kwargs):
        original(self, *args, **kwargs)
        fits.append(self.attr_str)

    monkeypatch.setattr(EnvSeriesGenerator, "__init__", counting)

    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    dwg.generate_ensemble((6, 15), DAYS, 9, seed=1)

    assert len(fits) == DAYS, (
        f"expected one fit per calendar day, got {len(fits)} for {DAYS} days -- "
        f"the per-realisation refit is back"
    )


def test_a_multi_attribute_walk_fits_each_day_once_per_attribute(synthetic_ds, monkeypatch,
                                                                tmp_path):
    """Fitting stays per-attribute; only the walk is shared."""
    fits = []
    original = EnvSeriesGenerator.__init__

    def counting(self, *args, **kwargs):
        original(self, *args, **kwargs)
        fits.append(self.attr_str)

    monkeypatch.setattr(EnvSeriesGenerator, "__init__", counting)

    attrs = ("temp_air", "wind_speed")
    write_ensemble(synthetic_ds, attrs, tmp_path / "e.parquet", start=(6, 15),
                   n_days=DAYS, n_realisations=6, seed=1, n_days_window=WINDOW)

    assert len(fits) == DAYS * len(attrs)
    assert sorted(set(fits)) == sorted(attrs)


# --- the file ----------------------------------------------------------------------

def test_written_and_read_back_matches_memory(synthetic_ds, tmp_path):
    """The round trip, against the in-memory generator, per attribute."""
    path = tmp_path / "ens.parquet"
    n = 4
    write_ensemble(synthetic_ds, ("temp_air", "wind_speed"), path, start=(6, 15),
                   n_days=DAYS, n_realisations=n, seed=13, n_days_window=WINDOW)
    ens = read_ensemble(path)

    assert len(ens.frame) == n * DAYS * 24
    assert ens.n_realisations == n
    assert ens.attrs == ("temp_air", "wind_speed")

    for attr in ("temp_air", "wind_speed"):
        expected = DayWindowGenerator(
            synthetic_ds, attr_str=attr, n_days=WINDOW
        ).generate_ensemble((6, 15), DAYS, n, seed=13)
        got = (ens.frame.sort_values(["realisation", "day_index", "hour"])[attr]
               .to_numpy().reshape(n, DAYS, 24))
        np.testing.assert_array_equal(got, expected)


def test_the_file_carries_dtypes_and_its_own_provenance(synthetic_ds, tmp_path):
    path = tmp_path / "ens.parquet"
    meta = write_ensemble(synthetic_ds, ("temp_air",), path, start=(6, 15), n_days=DAYS,
                          n_realisations=2, seed=6, n_days_window=WINDOW, bandwidth=0.1)
    ens = read_ensemble(path)

    assert ens.frame["realisation"].dtype == np.int32
    assert ens.frame["day_index"].dtype == np.int16
    assert ens.frame["hour"].dtype == np.int8
    assert ens.frame["temp_air"].dtype == np.float64

    for key in ("seed", "n_realisations", "n_days", "start", "window_n_days",
                "bandwidth", "attrs", "include_feb29", "sampling",
                "meteosynth_version", "source_provenance", "notes"):
        assert key in meta, f"{key} missing from the embedded metadata"
    assert ens.meta["seed"] == 6
    assert ens.meta["start"] == [6, 15]
    # The independence caveat must travel with the file: a multi-column ensemble looks
    # like a weather record and is not one.
    assert "independently" in ens.meta["notes"]


def test_day_index_orders_a_walk_that_wraps_new_year(synthetic_ds, tmp_path):
    """(month, day) alone cannot order a circular walk; day_index is why it exists."""
    path = tmp_path / "wrap.parquet"
    write_ensemble(synthetic_ds, ("temp_air",), path, start=(12, 30), n_days=4,
                   n_realisations=2, seed=1, n_days_window=WINDOW)
    one = read_ensemble(path).realisation(0)

    calendar = one.groupby("day_index")[["month", "day"]].first()
    assert list(calendar.index) == [1, 2, 3, 4]
    assert list(zip(calendar["month"], calendar["day"])) == [(12, 30), (12, 31), (1, 1), (1, 2)]


def test_a_365_day_ensemble_walk_skips_feb29(synthetic_ds):
    """Same calendar rule as generate_series, because it is the same walk."""
    dwg = DayWindowGenerator(synthetic_ds, attr_str="temp_air", n_days=WINDOW)
    visited = []
    for step in _walk_ensemble(
        {"temp_air": dwg}, start=(2, 26), n_days=6,
        streams={"temp_air": [realisation_stream(1, 0, "temp_air")]},
    ):
        visited.append((step.month, step.day))

    assert (2, 29) not in visited
    assert (2, 28) in visited and (3, 1) in visited


def test_a_newer_schema_version_is_refused(synthetic_ds, tmp_path):
    """Refuse rather than guess, as MetDataset.load does.

    A future writer may have changed the row identity; a reader that guesses returns a
    plausible-looking wrong ensemble.
    """
    pq = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "ens.parquet"
    write_ensemble(synthetic_ds, ("temp_air",), path, start=(6, 15), n_days=DAYS,
                   n_realisations=2, seed=1, n_days_window=WINDOW)

    table = pq.read_table(path)
    metadata = dict(table.schema.metadata)
    payload = json.loads(metadata[b"meteosynth_ensemble"])
    payload["ensemble_schema_version"] = ENSEMBLE_SCHEMA_VERSION + 1
    metadata[b"meteosynth_ensemble"] = json.dumps(payload).encode("utf-8")
    future = tmp_path / "future.parquet"
    pq.write_table(table.replace_schema_metadata(metadata), future)

    with pytest.raises(ValueError, match="refusing rather than guessing"):
        read_ensemble(future)


def test_a_file_without_metadata_warns_rather_than_failing(synthetic_ds, tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "ens.parquet"
    write_ensemble(synthetic_ds, ("temp_air",), path, start=(6, 15), n_days=DAYS,
                   n_realisations=2, seed=1, n_days_window=WINDOW)
    plain = tmp_path / "plain.parquet"
    pq.write_table(pq.read_table(path).replace_schema_metadata({}), plain)

    with pytest.warns(UserWarning, match="no meteosynth ensemble metadata"):
        ensemble = read_ensemble(plain)
    assert len(ensemble.frame) == 2 * DAYS * 24


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (dict(attrs=()), "at least one attribute"),
        (dict(attrs=("temp_air", "temp_air")), "duplicates"),
        (dict(n_realisations=0), "n_realisations must be at least 1"),
        (dict(n_days=0), "n_days must be at least 1"),
        (dict(start=(2, 29)), "include_feb29"),
    ],
)
def test_write_ensemble_rejects_malformed_requests(synthetic_ds, tmp_path, kwargs, match):
    call = dict(attrs=("temp_air",), start=(6, 15), n_days=DAYS, n_realisations=2,
                seed=1, n_days_window=WINDOW)
    call.update(kwargs)
    with pytest.raises(ValueError, match=match):
        write_ensemble(synthetic_ds, path=tmp_path / "x.parquet", **call)


# --- views and export ---------------------------------------------------------------

def test_to_wide_pivots_to_hours_by_realisations(synthetic_ds, tmp_path):
    path = tmp_path / "ens.parquet"
    n = 4
    write_ensemble(synthetic_ds, ("temp_air",), path, start=(6, 15), n_days=DAYS,
                   n_realisations=n, seed=1, n_days_window=WINDOW)
    ens = read_ensemble(path)

    wide = ens.to_wide("temp_air")
    assert wide.shape == (DAYS * 24, n)
    assert list(wide.columns) == [f"realisation_{i}" for i in range(n)]
    # Column i of the wide form is realisation i of the long form.
    np.testing.assert_array_equal(
        wide["realisation_2"].to_numpy(), ens.realisation(2)["temp_air"].to_numpy()
    )


def test_realisation_and_to_wide_reject_what_is_not_there(synthetic_ds, tmp_path):
    path = tmp_path / "ens.parquet"
    write_ensemble(synthetic_ds, ("temp_air",), path, start=(6, 15), n_days=DAYS,
                   n_realisations=2, seed=1, n_days_window=WINDOW)
    ens = read_ensemble(path)

    with pytest.raises(KeyError, match="no realisation 99"):
        ens.realisation(99)
    with pytest.raises(KeyError, match="not in this ensemble"):
        ens.to_wide("wind_speed")


def test_xlsx_export_writes_one_sheet_per_attribute(synthetic_ds, tmp_path):
    pytest.importorskip("openpyxl")
    path = tmp_path / "ens.parquet"
    write_ensemble(synthetic_ds, ("temp_air", "wind_speed"), path, start=(6, 15),
                   n_days=DAYS, n_realisations=3, seed=1, n_days_window=WINDOW)

    out = tmp_path / "ens.xlsx"
    with pytest.warns(UserWarning, match="lossy"):
        ensemble_to_xlsx(path, out)

    sheets = pd.read_excel(out, sheet_name=None)
    assert set(sheets) == {"temp_air", "wind_speed"}
    assert sheets["temp_air"].shape[0] == DAYS * 24


def test_xlsx_export_refuses_past_the_column_limit(synthetic_ds, tmp_path, monkeypatch):
    """Refuse rather than truncate.

    Silently dropping realisations from an ensemble is undetectable downstream, and the
    limit is real: a long-format ensemble of 1000 realisations is 8.76 M rows against
    Excel's 1 048 576, which is why the export pivots to wide in the first place.
    """
    pytest.importorskip("openpyxl")
    from meteosynth import ensemble as ensemble_module

    path = tmp_path / "ens.parquet"
    write_ensemble(synthetic_ds, ("temp_air",), path, start=(6, 15), n_days=DAYS,
                   n_realisations=5, seed=1, n_days_window=WINDOW)
    ens = read_ensemble(path)

    monkeypatch.setattr(ensemble_module, "_EXCEL_MAX_COLS", 4)
    with pytest.raises(ValueError, match="exceeds the 4-column worksheet limit"):
        ensemble_to_xlsx(ens, tmp_path / "too_wide.xlsx")

    monkeypatch.setattr(ensemble_module, "_EXCEL_MAX_COLS", 16_384)
    monkeypatch.setattr(ensemble_module, "_EXCEL_MAX_ROWS", 10)
    with pytest.raises(ValueError, match="exceeds the 10-row worksheet limit"):
        ensemble_to_xlsx(ens, tmp_path / "too_tall.xlsx")
