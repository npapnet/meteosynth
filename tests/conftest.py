"""
Force a headless matplotlib backend for the whole test session.

Several modules (``markov_chain_simulator_kde2d.py``, ``sup_plot_lib.py``, ...)
import ``matplotlib.pyplot`` at module level. Without a non-interactive
backend, collecting those modules on a machine with no display can hang or
error. This used to be documented-only (``MPLBACKEND=Agg`` in README.md /
quickstart.md) and had to be set by hand before invoking pytest; setting it
here means the test suite is headless by construction, for every entry point
(``pytest``, an IDE's test runner, CI) instead of only the documented CLI
invocation.

Must happen at import time, before any test module pulls in ``pyplot``.
"""

import matplotlib

matplotlib.use("Agg")
