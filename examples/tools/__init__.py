"""
Shared helpers for the example scripts -- not part of the ``meteosynth`` package.

Anything here exists to keep the examples short and comparable: data loading and
caching (:mod:`tools.site_data`) and the observed-vs-synthetic comparison used by the
day use cases (:mod:`tools.envelope`). Nothing in ``src/meteosynth`` imports it.

Scripts reach it by putting ``examples/`` on ``sys.path``; see the three-line block at
the top of any script in ``use_cases/``.
"""
