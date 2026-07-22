"""
What each quantity physically is -- support, units, a human-readable name.

A :class:`VariableSpec` carries **constraints, not an identity**. It has no ``name``
field: several column names may legitimately share one spec, and a spec that owned a
name could not honestly serve four columns at once. The name lives on the registry key
instead.

All plane-of-array irradiance components share :data:`IRRADIANCE` -- same support, same
units, same night-time degeneracy. They differ in *which part of the incoming radiation
they count*, which is a fact about the data rather than about the constraints.

The names stay distinct even though the spec is shared, because
``poa_global`` is roughly ``poa_direct + poa_sky_diffuse + poa_ground_diffuse``.
Collapsing them into one generic ``irradiance`` column would let a global series train
under a name meaning direct: same units, same support, passing every validation, and
wrong by roughly a factor of two. Keeping the names distinct makes **the column name the
provenance**, which is why nothing in this package needs a metadata sidecar.

The registry is what makes the package variable-agnostic: a column is modellable **if and
only if it has a spec**. Register one and it works, with no change to the package::

    >>> register("rel_humidity", VariableSpec((0.0, 100.0), "%", "Relative humidity"))
    >>> get_spec("rel_humidity").support
    (0.0, 100.0)

Pure data, no pandas -- mirrors the free-function style of :mod:`meteosynth.day_window`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

__all__ = [
    "VariableSpec",
    "IRRADIANCE",
    "TEMP_AIR",
    "WIND_SPEED",
    "get_spec",
    "register",
    "unregister",
    "registered",
]


@dataclass(frozen=True)
class VariableSpec:
    """
    The physical constraints of a quantity, independent of what a column calls it.

    Parameters
    ----------
    support : tuple of (float or None, float or None)
        ``(lower, upper)`` physical bounds. ``None`` means unbounded on that side.
        Sampling is truncated to this range, so an out-of-support value becomes
        unsamplable by construction rather than merely unlikely.
    units : str
        The units the data is expected to already be in. Declarative for now:
        ingestion validates against :attr:`support`, it does not convert.
    long_name : str
        Human-readable description, for plots and error messages.

    Notes
    -----
    Specs are **declared, not inferred**. Inference reads the sample rather than the
    physics and gets both hard cases wrong: ``wind_speed``'s observed minimum is 0.07 in
    the shipped record, so inference would call it unbounded below; a July-only
    ``temp_air`` subset is entirely positive, so inference would call it non-negative.
    Both wrong, and silently so.
    """

    support: Tuple[Optional[float], Optional[float]] = (None, None)
    units: str = ""
    long_name: str = ""

    def clamp_domain(self, data_min: float, data_max: float) -> Tuple[float, float]:
        """
        Intersect an observed data range with this spec's physical support.

        This is the whole of support enforcement: restrict the evaluation domain
        *before* building a CDF, and ``np.interp`` cannot then return a value outside
        it. Truncation is applied to the observed range rather than replacing it -- the
        data still governs where the mass is, the support only says where it may not go.

        Parameters
        ----------
        data_min, data_max : float
            The observed range of the values being fitted.

        Returns
        -------
        tuple of (float, float)
            The clamped ``(min, max)`` domain.

        Examples
        --------
        >>> IRRADIANCE.clamp_domain(-8.1, 81.0)     # negative tail cut at the bound
        (0.0, 81.0)
        >>> TEMP_AIR.clamp_domain(5.9, 20.1)        # nothing to clamp
        (5.9, 20.1)
        """
        lower, upper = self.support
        if lower is not None:
            data_min = max(data_min, lower)
        if upper is not None:
            data_max = min(data_max, upper)
        return data_min, data_max


#: Plane-of-array irradiance. Shared by every component -- see the module docstring for
#: why the component names stay distinct despite sharing one spec.
IRRADIANCE = VariableSpec((0.0, None), "W/m2", "Plane-of-array irradiance")

#: Air temperature. Bounded below by absolute zero; unbounded in practice.
TEMP_AIR = VariableSpec((-273.15, None), "degC", "Air temperature")

#: Wind speed. Non-negative, but unlike irradiance it never touches the bound.
WIND_SPEED = VariableSpec((0.0, None), "m/s", "Wind speed")


#: Column name -> spec. Several names may map to the same spec object.
_REGISTRY: dict[str, VariableSpec] = {
    "poa_global": IRRADIANCE,
    "poa_direct": IRRADIANCE,
    "poa_sky_diffuse": IRRADIANCE,
    "poa_ground_diffuse": IRRADIANCE,
    "temp_air": TEMP_AIR,
    "wind_speed": WIND_SPEED,
}


def get_spec(name: str) -> VariableSpec:
    """
    Look up the spec registered for a column name.

    Parameters
    ----------
    name : str
        Column name, e.g. ``"poa_direct"``.

    Returns
    -------
    VariableSpec

    Raises
    ------
    KeyError
        If nothing is registered under ``name``, with the registered set and a pointer
        to :func:`register` in the message -- an unregistered column is a normal thing
        for a user to hit, so the error has to say what to do about it.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"no VariableSpec registered for {name!r}. Registered: "
            f"{registered()}. Use register({name!r}, VariableSpec(...)) to add it."
        ) from None


def register(name: str, spec: VariableSpec, overwrite: bool = False) -> None:
    """
    Register a spec under a column name, making that column modellable.

    Parameters
    ----------
    name : str
        Column name to register.
    spec : VariableSpec
        Its physical constraints. May be an object already registered under another
        name -- sharing is the intended usage for related quantities.
    overwrite : bool, optional
        Permit replacing an existing registration. Defaults to ``False`` so that a
        typo'd re-registration is an error rather than a silent redefinition of what a
        column physically is.

    Raises
    ------
    ValueError
        If ``name`` is already registered and ``overwrite`` is False.
    """
    if name in _REGISTRY and not overwrite:
        raise ValueError(
            f"{name!r} is already registered as {_REGISTRY[name]!r}. "
            f"Pass overwrite=True to replace it."
        )
    _REGISTRY[name] = spec


def unregister(name: str) -> None:
    """
    Remove a registration.

    Mainly for tests, which must be able to restore the registry to its shipped state;
    a leaked registration would otherwise make one test's columns modellable in another.

    Raises
    ------
    KeyError
        If ``name`` is not registered.
    """
    del _REGISTRY[name]


def registered() -> tuple[str, ...]:
    """
    Every registered column name, sorted.

    This is the authoritative answer to "what can be modelled?" -- generators validate
    ``attr_str`` against it, and ingestion keeps exactly these columns.
    """
    return tuple(sorted(_REGISTRY))
