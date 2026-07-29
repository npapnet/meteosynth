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

The same argument runs across *planes*, which is why :data:`IRRADIANCE_HORIZONTAL` is a
separate object despite carrying identical constraints. ``ghi`` and ``poa_global`` are
the same physical quantity measured on different surfaces, and they differ by however
much the array is tilted -- so a horizontal series trained under a plane-of-array name is
the factor-of-two error again, in a second dimension. The constraints coincide; the
:attr:`~VariableSpec.long_name` does not, and that string is what
:func:`meteosynth.adapters.validate_support` quotes back to a user who is, by
construction, in the middle of debugging where their numbers came from.

The registry is what makes the package variable-agnostic: a column is modellable **if and
only if it has a spec**. Register one and it works, with no change to the package::

    >>> register("rel_humidity", VariableSpec((0.0, 100.0), "%", "Relative humidity"))
    >>> get_spec("rel_humidity").support
    (0.0, 100.0)

Pure data, no pandas -- mirrors the free-function style of :mod:`meteosynth.day_window`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

__all__ = [
    "VariableSpec",
    "IRRADIANCE",
    "IRRADIANCE_HORIZONTAL",
    "IRRADIANCE_COLUMNS",
    "TEMP_AIR",
    "WIND_SPEED",
    "get_spec",
    "register",
    "unregister",
    "registered",
    "irradiance_columns",
    "resolve_irradiance",
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

#: Horizontal-plane irradiance -- ``ghi``, ``dni``, ``dhi``, as PVGIS TMY and most
#: reanalysis products supply it. Physically identical constraints to :data:`IRRADIANCE`,
#: deliberately a distinct object: the ``long_name`` reaches the user in
#: :func:`meteosynth.adapters.validate_support`'s error text, and naming a horizontal
#: quantity "plane-of-array" would misinform at precisely the wrong moment.
IRRADIANCE_HORIZONTAL = VariableSpec((0.0, None), "W/m2", "Horizontal-plane irradiance")

#: Air temperature. Bounded below by absolute zero; unbounded in practice.
TEMP_AIR = VariableSpec((-273.15, None), "degC", "Air temperature")

#: Wind speed. Non-negative, but unlike irradiance it never touches the bound.
WIND_SPEED = VariableSpec((0.0, None), "m/s", "Wind speed")

#: Irradiance **totals**, most preferred first -- the answer to "which column here is the
#: irradiance?" when a caller has not named one.
#:
#: Only totals appear. A component is a *part* of a total, never "the irradiance":
#: ``poa_direct`` is roughly 70 % of ``poa_global``, so returning it for a caller who asked
#: for the irradiance would be the factor-of-two error the naming scheme exists to prevent,
#: arrived at from a new direction. :func:`resolve_irradiance` therefore raises rather than
#: guessing when only components are present.
#:
#: ``poa_global`` outranks ``ghi`` because plane-of-array is what this package models --
#: but a record holding only ``ghi`` resolves to ``ghi`` rather than erroring, and the
#: *returned name* is what every caller then uses, so the plane is never silently lost.
IRRADIANCE_COLUMNS: Tuple[str, ...] = ("poa_global", "ghi")

#: The specs that make a column an irradiance. Membership is by **identity**, which is what
#: :data:`IRRADIANCE_HORIZONTAL` being "deliberately a distinct object" is for: register a
#: column against one of these and :func:`resolve_irradiance` discovers it, with no change
#: to this package and no second list to keep in step.
_IRRADIANCE_SPECS = (IRRADIANCE, IRRADIANCE_HORIZONTAL)


#: Column name -> spec. Several names may map to the same spec object.
_REGISTRY: dict[str, VariableSpec] = {
    "poa_global": IRRADIANCE,
    "poa_direct": IRRADIANCE,
    "poa_sky_diffuse": IRRADIANCE,
    "poa_ground_diffuse": IRRADIANCE,
    "ghi": IRRADIANCE_HORIZONTAL,
    "dni": IRRADIANCE_HORIZONTAL,
    "dhi": IRRADIANCE_HORIZONTAL,
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


def irradiance_columns() -> Tuple[str, ...]:
    """
    Every registered column name whose spec is an irradiance spec, sorted.

    Derived from the registry rather than hand-listed, so a user who registers
    ``poa_reflected`` against :data:`IRRADIANCE` -- the sharing that
    :func:`register` already documents as intended -- becomes resolvable with no change
    here.
    """
    return tuple(
        sorted(name for name, spec in _REGISTRY.items() if spec in _IRRADIANCE_SPECS)
    )


def resolve_irradiance(
    columns: Iterable[str],
    prefer: Sequence[str] = IRRADIANCE_COLUMNS,
) -> str:
    """
    Pick the one irradiance column to model, by what is available.

    This is what lets a caller stop caring whether their record came from PVGIS hourly
    (``poa_global``) or a TMY (``ghi``). It **never renames or converts anything**: it
    returns a name that the caller then uses everywhere -- ``attr_str``, plot labels,
    saved output -- so the quantity and its plane travel with the result.

    Parameters
    ----------
    columns : iterable of str
        Column names to choose from, e.g. ``dataset.frame.columns``.
    prefer : sequence of str, optional
        Preference order over *totals*. Defaults to :data:`IRRADIANCE_COLUMNS`.

    Returns
    -------
    str
        The chosen column name.

    Raises
    ------
    LookupError
        If no irradiance column is present, or if the only ones present are components
        of a total that is itself absent. Both messages name what was found and what
        was looked for, because a user hitting this is by construction trying to work
        out what their data holds.

    Examples
    --------
    >>> resolve_irradiance(["poa_global", "temp_air", "wind_speed"])
    'poa_global'
    >>> resolve_irradiance(["ghi", "dni", "dhi"])
    'ghi'
    >>> resolve_irradiance(["poa_direct", "temp_air"])       # sole candidate, no ambiguity
    'poa_direct'
    """
    present = [col for col in columns if col in irradiance_columns()]

    for name in prefer:
        if name in present:
            return name

    if not present:
        raise LookupError(
            f"no irradiance column found. Looked for {irradiance_columns()}; "
            f"register one against IRRADIANCE or IRRADIANCE_HORIZONTAL to add it."
        )

    if len(present) == 1:
        return present[0]

    raise LookupError(
        f"cannot choose an irradiance column: {sorted(present)} are all components, and "
        f"none of the totals {tuple(prefer)} is present. A component is a part of a "
        f"total, not the total -- name one explicitly, or build the total first."
    )
