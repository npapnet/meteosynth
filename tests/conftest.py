"""
Force a headless matplotlib backend for the whole test session.

Several modules (``markov_chain_simulator_kde2d.py``, ``sup_plot_lib.py``, ...)
import ``matplotlib.pyplot`` at module level. Without a non-interactive
backend, collecting those modules on a machine with no display can hang or
error. This used to be documented-only (``MPLBACKEND=Agg`` in README.md /
quickstart.md) and had to be set by hand before invoking pytest; setting it
here means the test suite is headless by construction, for every entry point
(``pytest``, an IDE's test runner, CI) instead of only the documented CLI
invocation.

Must happen at import time, before any test module pulls in ``pyplot``.
"""

import pathlib

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"

#: Where the optional real record is looked for, in preference order. Parquet is the
#: canonical format, so it comes first; CSV is accepted because it is what a user is most
#: likely to already have lying around. XLSX is deliberately absent -- the package no
#: longer reads it, and `openpyxl` left the dependency list with it.
REAL_RECORD_CANDIDATES = (
    DATA_DIR / "pvgis_hourly_data.parquet",
    DATA_DIR / "pvgis_hourly_data.csv",
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Run every test from its own empty working directory.

    ``fetch_pvgis`` stores into :func:`meteosynth.store.default_data_dir` when the caller
    names no path, which is ``./data`` under the working directory. Without this, a test
    that fetches would write into the checkout -- and, worse, a *second* test could then
    find that file and pass for the wrong reason. Autouse because the failure is silent
    and the cost is nil.

    ``chdir`` rather than an environment variable, because the working directory *is* the
    mechanism: there is deliberately no ambient setting to point elsewhere, so isolating
    the tests any other way would be testing a path users do not have.

    Safe for the fixtures that read files: ``DATA_DIR`` here is derived from ``__file__``
    and is absolute, as are pytest's own ``tmp_path`` values.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def synthetic_ds():
    """Two years (2011-2012) of hourly data with a plausible diurnal + seasonal cycle.

    Irradiance is exactly zero at night, so its night hours degenerate and its pi(x0) is
    a spike at zero -- the same structure the real PVGIS record has, which is what makes
    this a usable stand-in for it.
    """
    from meteosynth.dataset import MetDataset

    rng = np.random.default_rng(42)
    index = pd.date_range("2011-01-01", "2012-12-31 23:00", freq="h")
    df = pd.DataFrame(
        {
            "year": index.year,
            "month": index.month,
            "day": index.day,
            "hour": index.hour,
        }
    )
    daylight = np.clip(np.sin((index.hour - 6) / 12 * np.pi), 0, None)
    seasonal = 0.5 + 0.5 * np.sin((index.dayofyear - 80) / 365 * 2 * np.pi)
    night = daylight == 0

    df["poa_direct"] = np.where(
        night, 0.0, np.clip(800 * daylight * seasonal + rng.normal(0, 5, len(index)), 0, None)
    )
    df["poa_sky_diffuse"] = np.where(
        night, 0.0, np.clip(100 * daylight + rng.normal(0, 2, len(index)), 0, None)
    )
    # Temperature and wind never stop, and never start at zero.
    df["temp_air"] = 15 + 10 * seasonal + 3 * daylight + rng.normal(0, 1, len(index))
    df["wind_speed"] = np.abs(rng.normal(4, 1.5, len(index))) + 0.5
    return MetDataset(df)


@pytest.fixture
def real_ds():
    """The optional real PVGIS record (Paris, 2011-2012), skipped if absent.

    Git-ignored, so most checkouts skip every test that asks for it. That is deliberate:
    the suite must be runnable without a network fetch or a large binary in the repo.
    """
    from meteosynth.dataset import MetDataset

    for path in REAL_RECORD_CANDIDATES:
        if path.exists():
            if path.suffix == ".parquet":
                return MetDataset.load(path)
            return MetDataset.read_csv(path)

    pytest.skip(
        "no real record present. Expected one of "
        f"{[p.name for p in REAL_RECORD_CANDIDATES]} in {DATA_DIR}."
    )
