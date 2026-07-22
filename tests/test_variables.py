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
    TEMP_AIR,
    WIND_SPEED,
    VariableSpec,
    get_spec,
    register,
    registered,
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
