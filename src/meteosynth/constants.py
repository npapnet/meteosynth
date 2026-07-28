"""
The canonical calendar schema, and what ships pre-registered.

"Which columns matter" is no longer a fixed list. A column is modellable **if and only
if it has a registered** :class:`~meteosynth.variables.VariableSpec`, so
:mod:`meteosynth.variables` is the authority and this module holds only the calendar
index plus a documentation-grade note of what ships registered out of the box.

That inversion is deliberate. ``MODELLED_ATTRS`` used to be a whitelist that also
doubled as the ingestion requirement, which is how ``Int`` -- a PVGIS quality flag --
became a modellable "meteorological attribute". Making the registry authoritative means
a user can model ``rel_humidity`` or ``snow_depth`` by declaring what it physically is,
with no change to this package, and means provider quirk columns fall out by rule rather
than by a hand-maintained exclusion list.

Pure data, no pandas -- mirrors the free-function style of
:mod:`meteosynth.day_window`.
"""

from __future__ import annotations

from .variables import registered

#: Chronological index columns every record must carry.
INDEX_COLS: tuple[str, ...] = ("year", "month", "day", "hour")


def modelled_attrs() -> tuple[str, ...]:
    """
    Every currently registered column name.

    Thin pass-through to :func:`meteosynth.variables.registered`, kept so callers with
    a "what can I model?" question have an obvious place to ask it. It is a *function*
    rather than a constant because the registry is extensible at runtime -- a module
    level tuple would be a stale snapshot taken at import time.
    """
    return registered()


#: What ships pre-registered, for documentation and error messages. **This gates
#: nothing**: :func:`meteosynth.variables.registered` is what generators validate
#: against, and it grows when a user calls :func:`meteosynth.variables.register`.
SHIPPED_ATTRS: tuple[str, ...] = (
    # Plane-of-array, as PVGIS hourly supplies it.
    "poa_global",
    "poa_direct",
    "poa_sky_diffuse",
    "poa_ground_diffuse",
    # Horizontal, as PVGIS TMY and most reanalysis products supply it. Same physical
    # quantity on a different surface, so the names -- and the specs -- stay distinct.
    "ghi",
    "dni",
    "dhi",
    "temp_air",
    "wind_speed",
)
