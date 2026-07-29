API Reference
=============

Everything below is importable from the top-level ``meteosynth`` package.

Daily Series Generators
-----------------------

The entry point for ordinary use: :class:`~meteosynth.generators.DayWindowGenerator`
for a day, a month or a year on the rolling-window base, and
:class:`~meteosynth.generators.EnvSeriesGenerator` for a single date-blind training
subset.

.. automodule:: meteosynth.generators
   :members:
   :undoc-members:
   :show-inheritance:

Data Ingestion and Processing
-----------------------------

.. automodule:: meteosynth.met_data_processor
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: meteosynth.adapters
   :members:
   :undoc-members:
   :show-inheritance:

Variables and the Spec Registry
-------------------------------

What each column physically is. A column is modellable if and only if it has a
registered :class:`~meteosynth.variables.VariableSpec`.

.. automodule:: meteosynth.variables
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: meteosynth.constants
   :members:
   :undoc-members:
   :show-inheritance:

Seasonal Day Windows
--------------------

The circular ``all_leap`` calendar the rolling windows are indexed on.

.. automodule:: meteosynth.day_window
   :members:
   :undoc-members:
   :show-inheritance:

Simulators
----------

The transition models underneath the generators. All three share a
``get_next_state`` / ``generate_sequence`` interface.

.. automodule:: meteosynth.markov_chain_simulator_kde2d
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: meteosynth.markov_implementations.markov_chain_simulator_continuous
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: meteosynth.markov_implementations.markov_chain_simulator_discrete
   :members:
   :undoc-members:
   :show-inheritance:

Plotting Utilities
------------------

.. automodule:: meteosynth.sup_plot_lib
   :members:
   :undoc-members:
   :show-inheritance:
