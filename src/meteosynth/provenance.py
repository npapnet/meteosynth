"""
Where a training record came from -- source, site, period.

A column name says *which quantity* it holds: ``poa_global`` is not ``poa_direct``, and
``ghi`` is not ``poa_global``. That is deliberate and load-bearing. What it cannot say is
**which site, which years, and which of a provider's mutually exclusive fetch modes**
produced it, which is what this record adds.

Note the record deliberately carries **no** ``irradiance_form`` field. The column list of
the dataset answers that, because the column name *is* the quantity -- one less field able
to contradict the data it describes.

Pure data, no pandas -- mirrors the free-function style of :mod:`meteosynth.variables`.
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Optional

__all__ = ["Provenance"]


@dataclass(frozen=True)
class Provenance:
    """
    What is known about where a dataset came from.

    Parameters
    ----------
    source : str
        Who supplied it: ``"pvgis_hourly"``, ``"pvgis_tmy"``, ``"open_meteo"``, or
        ``"user"`` for a frame the caller built or read themselves.
    site : str, optional
        Free label, e.g. ``"heraklion"``. Never inferred from coordinates.
    latitude, longitude : float, optional
        Site coordinates as *requested*, not as the provider snapped them.
    start_year, end_year : int, optional
        Inclusive year range. Both ``None`` for a TMY, which genuinely has no single
        year -- see :func:`meteosynth.adapters.fetch_pvgis_tmy`, whose twelve months came
        from nine distinct years at Heraklion. Writing a range there would be fabrication.
    fetched : str, optional
        ISO-8601 date, set when a network fetch produced the data.
    meteosynth_version : str, optional
        The version that wrote it.
    notes : str, optional
        Anything a caller wants to carry along.

    Notes
    -----
    **Always present, never ``None``.** A hand-built frame gets ``source="user"`` with
    everything else absent. That invents nothing -- it records that nobody claimed a
    source -- while sparing every downstream caller an ``Optional`` branch.
    """

    source: str = "user"
    site: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    fetched: Optional[str] = None
    meteosynth_version: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """This record as a plain dict, ready for JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Provenance":
        """
        Build from a dict, **tolerating keys this version does not know**.

        This is not sugar: ``Provenance(**data)`` on a frozen dataclass raises
        ``TypeError`` on the first unrecognised key, which would make every provenance
        field ever added a breaking change for readers. A future ``elevation`` or
        ``timezone`` must not render a dataset unreadable, because nothing in the
        modelling path depends on it.

        Unknown keys are dropped after a single warning; missing keys take their
        defaults.

        Note the asymmetry with the dataset's ``schema_version``, which is checked
        strictly and *raises* on a future file. The schema governs the data, so a reader
        that cannot understand it must refuse rather than guess; provenance is
        descriptive, so a reader that cannot understand part of it can still work.
        """
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            warnings.warn(
                f"ignoring unknown provenance field(s) {unknown} -- this record was "
                f"probably written by a newer meteosynth. The data itself is unaffected.",
                stacklevel=2,
            )
        return cls(**{k: v for k, v in data.items() if k in known})
