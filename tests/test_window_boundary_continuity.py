"""Measure the window-boundary mismatch rather than asserting it away.

A rolling series is time-inhomogeneous at daily resolution: day d's 23:00 value comes
from day d's window fit, while day d+1's cross-midnight model comes from day d+1's fit.
The two windows overlap in 29 of 31 days, so the mismatch *should* be negligible -- but
"should be" is not a measurement, and it interacts directly with support truncation: a
conditioning value outside the fitted domain is the path to the historical
``ValueError: array must not contain infs or NaNs``.

This module therefore asserts only what must hold (finite, in-support output) and
**records** the boundary statistic. If the recorded fraction ever turns out to be
non-trivial, that is a finding, and the choice to let the later day own the boundary
step reopens.
"""

import numpy as np
import pytest

from meteosynth.generators import DayWindowGenerator
from meteosynth.variables import get_spec


@pytest.mark.parametrize("attr", ["temp_air", "wind_speed", "poa_direct"])
def test_a_long_series_stays_finite_and_in_support(real_mdp, attr):
    """The guarantee. Nothing else in this file is an assertion about magnitude."""
    generator = DayWindowGenerator(real_mdp, attr_str=attr, n_days=15)
    series = generator.generate_series((1, 1), 365, seed=1)

    lower = get_spec(attr).support[0]
    assert np.isfinite(series).all(), f"{attr} produced a non-finite value"
    assert series.min() >= lower, f"{attr} left its support"


def test_boundary_conditioning_values_land_inside_the_next_days_domain(real_mdp, capsys):
    """Record what fraction of 23:00 values fall outside the next day's fitted range.

    The conditioning value is day d's generated 23:00; the model it is fed to is day
    d+1's cross-midnight fit, whose ``previous`` column spans a different (overlapping)
    sample. Where they disagree, the KDE is being asked to extrapolate.
    """
    attr = "temp_air"
    generator = DayWindowGenerator(real_mdp, attr_str=attr, n_days=15, cache_size=400)
    series = generator.generate_series((1, 1), 365, seed=1)

    outside = 0
    checked = 0
    slot = 1
    for i in range(1, len(series)):
        slot += 1
        day = generator.for_slot(slot)
        if day.cross_midnight is None:
            continue
        fitted = day.cross_midnight.previous_values
        value = series[i - 1, -1]
        checked += 1
        if value < fitted.min() or value > fitted.max():
            outside += 1

    fraction = outside / max(checked, 1)
    with capsys.disabled():
        print(
            f"\n  boundary extrapolation ({attr}, 365 days): "
            f"{outside}/{checked} = {fraction:.2%} of conditioning values fell "
            f"outside the next day's fitted range"
        )

    # Deliberately loose. This is a recorded measurement with a smoke alarm on it, not
    # a tuned threshold: it fires only if the mismatch stops being a tail effect.
    assert fraction < 0.25, (
        f"{fraction:.1%} of boundary steps extrapolate -- the window-overlap assumption "
        f"no longer holds and the boundary-owner choice should be revisited"
    )


def test_extrapolated_boundaries_still_produce_in_support_values(real_mdp):
    """Even where the conditioning value is out of range, truncation must hold.

    This is the interaction that used to crash: an out-of-domain conditioning value gave
    an all-zero density, 0/0 -> NaN, and the next hour died.
    """
    generator = DayWindowGenerator(real_mdp, attr_str="wind_speed", n_days=15)
    day = generator.for_day(6, 15)
    fitted = day.cross_midnight.previous_values

    rng = np.random.default_rng(0)
    for value in [fitted.min() - 5.0, fitted.max() + 5.0, fitted.max() + 50.0]:
        profile = day.gen_day_from(value, rng=rng)
        assert np.isfinite(profile).all(), f"conditioning on {value} produced NaN"
        assert profile.min() >= 0.0
