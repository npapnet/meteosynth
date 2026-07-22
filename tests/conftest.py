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

DATA_FILE = pathlib.Path(__file__).parent.parent / "data" / "pvgis_hourly_data.xlsx"


@pytest.fixture
def synthetic_mdp():
    """Two years (2011-2012) of hourly data with a plausible diurnal + seasonal cycle.

    Irradiance is exactly zero at night, so its night hours degenerate and its pi(x0) is
    a spike at zero -- the same structure the real PVGIS record has, which is what makes
    this a usable stand-in for it.
    """
    from meteosynth.met_data_processor import MetDataProcessor

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
    return MetDataProcessor(df)


@pytest.fixture
def real_mdp():
    """The shipped PVGIS record (Paris, 2011-2012), skipped if absent."""
    from meteosynth.met_data_processor import MetDataProcessor

    if not DATA_FILE.exists():
        pytest.skip(f"{DATA_FILE} not present")
    return MetDataProcessor(pd.read_excel(DATA_FILE))
