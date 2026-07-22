"""
Canonical column names for a processed PVGIS-shaped hourly frame.

Single source of truth for "which columns matter". Previously this was
duplicated independently in :mod:`meteosynth.generators` (``MET_DATA_COLS``,
used to validate ``attr_str``) and in
:class:`~meteosynth.met_data_processor.MetDataProcessor` (a private
``__met_data_columns`` list, asserted on ingestion) -- two hand-maintained
copies with nothing keeping them in sync. Both now import from here instead.

Pure data, no pandas -- mirrors the free-function style of
:mod:`meteosynth.day_window`.
"""

from __future__ import annotations

#: Meteorological attributes that can be modelled -- valid ``attr_str``
#: values for :class:`~meteosynth.generators.EnvSeriesGenerator` and
#: :func:`~meteosynth.generators.generate_hr_simulator`.
MODELLED_ATTRS: tuple[str, ...] = (
    "poa_direct",
    "poa_sky_diffuse",
    "poa_ground_diffuse",
    "solar_elevation",
    "temp_air",
    "wind_speed",
    "Int",
)

#: Chronological index columns every record must carry.
INDEX_COLS: tuple[str, ...] = ("year", "month", "day", "hour")

#: Everything :class:`~meteosynth.met_data_processor.MetDataProcessor`
#: requires on ingestion: the modelled attributes plus the calendar index.
REQUIRED_COLS: tuple[str, ...] = MODELLED_ATTRS + INDEX_COLS
