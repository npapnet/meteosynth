"""
Does the sampler still produce weather that looks like the weather it learned from?

**The gap this closes (`CHORE-12`).** Every other test here checks a *rule*: that a seed
reproduces, that a shared generator advances, that values stay inside physical support,
that degenerate hours are classified correctly. None of them looks at the numbers. When
``PERF-1`` replaced the whole sampling path with a cached quantile grid, **all 271 tests
passed unmodified** -- and would have passed had the new path been wrong.

``tests/test_conditional_quantile_grid.py`` since compares the two paths against *each
other*. This file is the other half: it compares what comes out against **the training
pool it went in with**, so a defect present in both paths still fails something.

It is a miniature of ``examples/diagnostics-overshoot/``, which does the same comparison
properly on a 19-year record and cannot be a unit test because it needs a network fetch
and several minutes.

The fixture is arithmetic, not a place
--------------------------------------
``synthetic_ds`` has **no coordinates and never touches the network** -- irradiance is
``800 x daylight x seasonal`` plus noise, with ``daylight`` a half-sine over the day and
``seasonal`` a sine over the year. That is deliberate: this file must run on a fresh clone
and in CI, where no collected record exists.

The consequence to know, because it looks like a bug and is not: **the fixture's winter is
darker than any real mid-latitude site.** Its seasonal term reaches exactly zero, so late
December irradiance is flat zero all day -- 0.7 W/m2 daily mean against 86 for real
Heraklion, which still gets ~30 % of its June figure in December. Midsummer is realistic
(236 against 285); autumn and winter are not. Wind runs ~2.4x fast throughout.

So this file tests **that the sampler reproduces whatever it was given**, which is the
property `CHORE-12` is about, and makes no claim that the input resembles Crete. Claims
about real-data accuracy belong to ``examples/diagnostics-overshoot/``, which is fitted to
the real record and is what `FIX-1` cites.

What is asserted, and why each threshold is what it is
------------------------------------------------------
**Level, against the pool.** The sharpest signal available: measured at ratio 0.999-1.005
across every attribute, and it moves only +/-0.1-0.6 % across seeds. The tolerance is
``MEAN_TOL``, several times that floor. This is the ``FIX-1`` class of defect -- a
generator that quietly drifts off the level it was fitted to.

**Spread, against a recorded reference -- not against the pool.** Comparing spread to the
observed pool does *not* work, and the reason is worth stating so nobody re-derives it:

======================  ================  ====================================
attribute               syn sd / pool sd  why, with nothing wrong
======================  ================  ====================================
``wind_speed``          ~1.01             pure noise, no seasonal structure
``poa_direct``          ~0.95             mild
``temp_air``            **~0.61**         seasonal drift *within* the window
======================  ================  ====================================

The window is +/-15 days, and the test fixture's temperature drifts through the season.
That drift is real, it is in the pool's spread, and the model deliberately does **not**
reproduce it -- pooling the window is the whole point of a rolling window, and what
position within it costs is ``CHORE-1``'s open question. Narrowing the window fixes
``temp_air`` (0.61 -> 0.78 at +/-3) and breaks ``poa_direct`` (0.95 -> 0.75), because a
thinner pool under-disperses the fit. There is no window at which all three sit near 1.

So spread is checked against **its own measured value**, recorded below. That catches the
failure mode a pool comparison was wanted for -- a dispersion collapse from a mis-built
grid, which is a factor, not a few per cent -- while tolerating the +/-3-9 % seed wobble
and any RNG change a future ``numpy`` brings. The cost is that these numbers must be
re-measured when the model legitimately changes, which is exactly when someone should be
made to look.

**Support and finiteness, exactly.** Free, and between them they cover the two defects
that have actually shipped: 1.29 % negative irradiance (``FIX-1``'s padding bug) and the
NaN cascade of ``FIX-2``.

Deliberately *not* a golden-value test
--------------------------------------
No individual drawn number is pinned. A golden test on a sampler breaks whenever
``numpy`` or ``scipy`` changes generator internals, without anything being wrong. Every
assertion here is on a **statistic over hundreds of draws**, whose Monte-Carlo noise was
measured before the tolerance was chosen.

Does it actually catch anything? Measured
-----------------------------------------
A test that cannot fail is what `CHORE-12` exists to complain about, so this one was
checked by injecting faults into the drawn values and counting which cells went red:

=========================  =======================
injected fault             cells that caught it
=========================  =======================
level +10 %                **6 of 6**
level -6 %                 **6 of 6**
spread halved              **6 of 6**
spread x1.6                **6 of 6**
healthy (control)          0 of 6
=========================  =======================

Measured 2026-08-03. The control is the point: the tolerances are loose enough that an
untouched sampler passes every cell, and tight enough that a defect smaller than the ones
this repo has actually shipped fails every cell.
"""

from __future__ import annotations

import numpy as np
import pytest

from meteosynth import DayWindowGenerator
from meteosynth.variables import get_spec

#: One seed for the whole file. Deterministic given a library version, and every tolerance
#: below is sized to cover the seed-to-seed spread, so an RNG change does not fail it.
SEED = 20260803

#: Realisations per cell. 300 puts the Monte-Carlo noise on the mean at ~0.5 % and on the
#: standard deviation at ~4 %, both comfortably inside the tolerances.
N_REALISATIONS = 300

#: Training window half-width, matching the package default.
WINDOW_DAYS = 15

#: Level must land within this of the pool it was trained on. The measured seed wobble is
#: +/-0.1-0.6 %, so this is several times the floor and still tight enough to catch a
#: drift the diagnostics harness would call real.
MEAN_TOL = 0.05

#: Spread must land within this of its recorded reference. Seed wobble is +/-3-9 %; a
#: dispersion collapse is a factor. 25 % sits between the two with room on both sides.
SD_TOL = 0.25

#: Two dates, because a low sun is not a high one: shorter days mean more degenerate night
#: hours and a different path through the sampler.
#:
#: **October rather than December, and the reason is the fixture, not the model.** This
#: fixture's seasonal term reaches exactly zero around 19 December, so ``poa_direct`` there
#: is flat zero for all 24 hours -- peak 0.1 W/m2 against 194 in October and 747 in May. A
#: level ratio between two near-zero numbers is meaningless, and it duly measured 1.19. The
#: real 19-year record has genuine winter sun, so nothing about that reading is a defect.
#: October keeps what the second date is *for* -- a low sun and a long night -- while
#: leaving all three attributes measurable.
DATES = {"may": (5, 21), "oct": (10, 21)}

#: The three shipped attributes. ``poa_direct`` rather than ``poa_global`` because that is
#: what the fixture carries; it is the bounded-below, degenerate-at-night case either way.
ATTRS = ("poa_direct", "temp_air", "wind_speed")

#: **Measured, not chosen.** Standard deviation of the per-realisation daily mean, on the
#: two-year fixture at the settings above. Re-measure and update deliberately when the
#: model changes; a diff here is a prompt to check what moved and why.
#:
#: Recorded 2026-08-03, against the tree at 0.3.2 + `CHORE-12`.
REFERENCE_SD = {
    ("may", "poa_direct"): 9.2065,
    ("may", "temp_air"): 0.2435,
    ("may", "wind_speed"): 0.3006,
    ("oct", "poa_direct"): 16.0781,
    ("oct", "temp_air"): 0.3560,
    ("oct", "wind_speed"): 0.2898,
}

#: Seed-to-seed spread of each figure above, measured over six seeds at the same settings:
#: 2.4-9.5 %. :data:`SD_TOL` has to clear that, and does.
REFERENCE_SD_WOBBLE_PCT = 9.5


#: Fitting a generator and drawing 300 realisations costs ~3 s, and the three assertions
#: below all need the same draw. Cached across them, which takes this file from ~50 s to
#: ~18 s. Safe because ``synthetic_ds`` is built from a fixed seed, so every function-scoped
#: instance of it is byte-identical -- a cache keyed on (attribute, date) cannot go stale
#: within a session.
_CACHE: dict = {}


def _daily_means(dataset, attr, month, day):
    """Per-realisation daily means, and the observed pool's daily means for the same window.

    Both sides are a *daily mean per day*, so the two are the same quantity measured on
    synthetic and observed days -- which is what makes the ratio meaningful.
    """
    key = (attr, month, day)
    if key in _CACHE:
        return _CACHE[key]

    generator = DayWindowGenerator(dataset, attr_str=attr, n_days=WINDOW_DAYS)
    drawn = generator.generate_ensemble(
        start=(month, day),
        n_days=1,
        n_realisations=N_REALISATIONS,
        seed=SEED,
    )
    synthetic = drawn.squeeze(axis=1).mean(axis=1)

    observed = dataset.get_day_window_subset(month, day, n_days=WINDOW_DAYS)
    pool = observed.groupby("date_id")[attr].mean().to_numpy()

    _CACHE[key] = (synthetic, pool, drawn)
    return _CACHE[key]


@pytest.mark.parametrize("date_key", sorted(DATES))
@pytest.mark.parametrize("attr", ATTRS)
def test_the_level_matches_the_pool_it_was_fitted_to(synthetic_ds, attr, date_key):
    """A generator that drifts off its training level is the `FIX-1` class of defect."""
    synthetic, pool, _ = _daily_means(synthetic_ds, attr, *DATES[date_key])

    ratio = synthetic.mean() / pool.mean()
    assert abs(ratio - 1.0) < MEAN_TOL, (
        f"{attr} on {date_key}: synthetic daily mean is {ratio:.3f}x the pool it was "
        f"trained on (tolerance {MEAN_TOL:.0%}). Either the sampler drifted or the "
        f"training pool changed."
    )


@pytest.mark.parametrize("date_key", sorted(DATES))
@pytest.mark.parametrize("attr", ATTRS)
def test_the_spread_matches_its_recorded_reference(synthetic_ds, attr, date_key):
    """Catches a dispersion collapse -- a mis-built grid halves the spread, or worse.

    Against a recorded number rather than the pool, for the reason in the module
    docstring: the pool ratio is a healthy 0.61 for ``temp_air`` and a healthy 0.95 for
    ``poa_direct``, so it cannot be thresholded.
    """
    synthetic, _, _ = _daily_means(synthetic_ds, attr, *DATES[date_key])

    reference = REFERENCE_SD[(date_key, attr)]
    ratio = synthetic.std() / reference
    assert abs(ratio - 1.0) < SD_TOL, (
        f"{attr} on {date_key}: spread is {synthetic.std():.4f} against a recorded "
        f"{reference:.4f} ({ratio:.2f}x, tolerance {SD_TOL:.0%}). If the model changed "
        f"on purpose, re-measure REFERENCE_SD and say so in the commit."
    )


@pytest.mark.parametrize("date_key", sorted(DATES))
@pytest.mark.parametrize("attr", ATTRS)
def test_every_drawn_value_is_finite_and_inside_support(synthetic_ds, attr, date_key):
    """The two defects that have actually shipped: negative irradiance, and a NaN cascade.

    Covered elsewhere too, and deliberately repeated here -- this file is the one that
    looks at bulk output, so it is where a failure of either kind will show first.
    """
    _, _, drawn = _daily_means(synthetic_ds, attr, *DATES[date_key])

    assert np.isfinite(drawn).all(), f"{attr} on {date_key}: non-finite values drawn"

    low, high = get_spec(attr).support
    if low is not None:
        assert drawn.min() >= low, (
            f"{attr} on {date_key}: drew {drawn.min():.4f}, below its support bound {low}"
        )
    if high is not None:
        assert drawn.max() <= high, (
            f"{attr} on {date_key}: drew {drawn.max():.4f}, above its support bound {high}"
        )
