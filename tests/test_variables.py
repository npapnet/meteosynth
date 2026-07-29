"""The spec registry: what makes the package variable-agnostic.

A column is modellable if and only if it has a registered spec. That inversion -- from a
fixed MODELLED_ATTRS whitelist to an extensible registry -- is what lets a user model a
quantity this package has never heard of without changing it.
"""

import numpy as np
import pandas as pd
import pytest

from meteosynth.variables import (
    IRRADIANCE,
    IRRADIANCE_HORIZONTAL,
    TEMP_AIR,
    WIND_SPEED,
    VariableSpec,
    get_spec,
    register,
    IRRADIANCE_COLUMNS,
    irradiance_columns,
    registered,
    resolve_irradiance,
    unregister,
)


@pytest.fixture
def temporary_registration():
    """Register names during a test and remove them afterwards.

    The registry is module-level, so a leaked registration would make one test's columns
    modellable in another and the suite would pass for the wrong reason.
    """
    added = []

    def _register(name, spec, **kwargs):
        register(name, spec, **kwargs)
        added.append(name)

    yield _register

    for name in added:
        try:
            unregister(name)
        except KeyError:
            pass


# --- the shared-spec design -------------------------------------------------------

def test_all_irradiance_components_share_one_spec():
    """One constraints object, several names.

    All plane-of-array components have the same support, units and night-degeneracy;
    they differ only in which part of the incoming radiation they count, which is a fact
    about the data rather than about the physics.
    """
    names = ["poa_global", "poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"]
    specs = [get_spec(n) for n in names]

    assert all(spec is IRRADIANCE for spec in specs)
    assert len({id(spec) for spec in specs}) == 1


def test_the_names_stay_distinct_even_though_the_spec_is_shared():
    """Provenance lives in the column name, which is why no metadata sidecar exists.

    poa_global is roughly the sum of the three components, so collapsing the names would
    let a global series train under a name meaning direct -- same units, same support,
    passing every validation, wrong by roughly a factor of two.
    """
    assert "poa_global" in registered()
    assert "poa_direct" in registered()
    assert get_spec("poa_global") is get_spec("poa_direct")


def test_horizontal_irradiance_has_its_own_spec_despite_identical_constraints():
    """`ghi` and `poa_global` are the same quantity on different surfaces.

    The support and units coincide, so one shared object would validate identically. The
    long_name does not coincide, and that string is what validate_support quotes back to
    a user who is by construction debugging where their numbers came from -- calling GHI
    "Plane-of-array irradiance" would misinform at precisely the wrong moment.
    """
    horizontal = [get_spec(n) for n in ("ghi", "dni", "dhi")]

    assert all(spec is IRRADIANCE_HORIZONTAL for spec in horizontal)
    assert get_spec("ghi") is not get_spec("poa_global")
    assert IRRADIANCE_HORIZONTAL.support == IRRADIANCE.support
    assert IRRADIANCE_HORIZONTAL.units == IRRADIANCE.units
    assert IRRADIANCE_HORIZONTAL.long_name != IRRADIANCE.long_name


def test_spec_carries_no_name():
    """A spec that owned a name could not honestly serve four columns at once."""
    assert not hasattr(IRRADIANCE, "name")
    assert set(VariableSpec.__dataclass_fields__) == {"support", "units", "long_name"}


def test_specs_are_frozen():
    with pytest.raises(Exception):
        IRRADIANCE.support = (1.0, 2.0)


# --- the registry ------------------------------------------------------------------

def test_shipped_registrations():
    assert set(registered()) == {
        "poa_global", "poa_direct", "poa_sky_diffuse", "poa_ground_diffuse",
        "ghi", "dni", "dhi",
        "temp_air", "wind_speed",
    }


def test_register_round_trip(temporary_registration):
    spec = VariableSpec((0.0, 100.0), "%", "Relative humidity")
    temporary_registration("rel_humidity", spec)

    assert get_spec("rel_humidity") is spec
    assert "rel_humidity" in registered()


def test_register_rejects_duplicates_without_overwrite(temporary_registration):
    temporary_registration("snow_depth", VariableSpec((0.0, None), "m"))
    with pytest.raises(ValueError, match="already registered"):
        register("snow_depth", VariableSpec((0.0, None), "cm"))


def test_register_overwrite_is_explicit(temporary_registration):
    temporary_registration("snow_depth", VariableSpec((0.0, None), "m"))
    replacement = VariableSpec((0.0, 10.0), "m")
    register("snow_depth", replacement, overwrite=True)
    assert get_spec("snow_depth") is replacement


def test_unknown_name_says_what_to_do_about_it():
    with pytest.raises(KeyError) as excinfo:
        get_spec("not_a_variable")

    message = str(excinfo.value)
    assert "not_a_variable" in message
    assert "register" in message          # the fix is named
    assert "temp_air" in message          # and so is the registered set


def test_registered_is_sorted_and_immutable():
    names = registered()
    assert isinstance(names, tuple)
    assert list(names) == sorted(names)


# --- support clamping --------------------------------------------------------------

def test_clamp_domain_cuts_at_the_physical_bound():
    """The negative tail that produced -8.10 W/m2 at the dawn hour is cut at zero."""
    assert IRRADIANCE.clamp_domain(-8.1, 81.0) == (0.0, 81.0)


def test_clamp_domain_leaves_an_in_support_range_alone():
    """Truncation constrains the observed range, it does not replace it."""
    assert TEMP_AIR.clamp_domain(5.92, 20.14) == (5.92, 20.14)
    assert WIND_SPEED.clamp_domain(0.62, 5.31) == (0.62, 5.31)


def test_clamp_domain_handles_unbounded_sides():
    unbounded = VariableSpec((None, None))
    assert unbounded.clamp_domain(-1e9, 1e9) == (-1e9, 1e9)

    capped = VariableSpec((None, 100.0))
    assert capped.clamp_domain(-50.0, 200.0) == (-50.0, 100.0)


def test_specs_are_declared_not_inferred():
    """Inference reads the sample rather than the physics, and gets both cases wrong.

    wind_speed's observed minimum in the shipped record is 0.07, so inference would call
    it unbounded below; a July-only temp_air subset is entirely positive, so inference
    would call it non-negative. The declared specs disagree with both, correctly.
    """
    assert WIND_SPEED.support[0] == 0.0        # not "unbounded, since 0.07 > 0"
    assert TEMP_AIR.support[0] == -273.15      # not "non-negative, since July is warm"


# --- resolving "which column here is the irradiance?" --------------------------------
#
# What lets a caller stop caring whether their record came from PVGIS hourly
# (poa_global) or a TMY (ghi). The resolver renames and converts nothing: it returns a
# name the caller then uses everywhere, so the quantity and its plane travel with it.

def test_the_preferred_total_wins_over_a_component_in_the_same_frame():
    assert resolve_irradiance(["poa_direct", "poa_global", "temp_air"]) == "poa_global"


def test_a_tmy_resolves_to_ghi_rather_than_erroring():
    assert resolve_irradiance(["ghi", "dni", "dhi", "temp_air"]) == "ghi"


def test_plane_of_array_outranks_horizontal_when_both_are_present():
    """poa_global is what this package models; ghi is a different surface."""
    assert resolve_irradiance(["ghi", "poa_global"]) == "poa_global"


def test_a_lone_component_resolves_to_itself():
    """One candidate is not ambiguous, so refusing it would be unhelpful."""
    assert resolve_irradiance(["poa_direct", "temp_air", "wind_speed"]) == "poa_direct"


def test_components_without_a_total_raise_and_name_all_of_them():
    """A component is a part of a total, never the total.

    poa_direct is roughly 70 % of poa_global, so answering with it would be the
    factor-of-two error the distinct names exist to prevent.
    """
    with pytest.raises(LookupError) as excinfo:
        resolve_irradiance(
            ["poa_direct", "poa_sky_diffuse", "poa_ground_diffuse", "temp_air"]
        )

    message = str(excinfo.value)
    for name in ("poa_direct", "poa_sky_diffuse", "poa_ground_diffuse"):
        assert name in message


def test_no_irradiance_at_all_raises_and_says_what_it_looked_for():
    with pytest.raises(LookupError) as excinfo:
        resolve_irradiance(["temp_air", "wind_speed"])

    assert "poa_global" in str(excinfo.value)


def test_a_user_registered_irradiance_column_is_discovered(temporary_registration):
    """Sharing a spec object is how a column joins the group -- no second list."""
    temporary_registration("poa_reflected", IRRADIANCE)

    assert "poa_reflected" in irradiance_columns()
    assert resolve_irradiance(["poa_reflected", "temp_air"]) == "poa_reflected"


def test_preference_order_can_be_overridden():
    assert resolve_irradiance(["poa_global", "ghi"], prefer=("ghi",)) == "ghi"


def test_only_totals_ship_in_the_preference_order():
    assert IRRADIANCE_COLUMNS == ("poa_global", "ghi")
