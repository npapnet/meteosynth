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

Ensembles
---------

Many realisations in **one** calendar walk, and their on-disk form. Fitting each day's
models once and sharing them across every realisation is what makes an ensemble of hundreds
affordable; :func:`~meteosynth.ensemble.write_ensemble` streams the result to a single
long-format parquet file, one row group per calendar day.

.. automodule:: meteosynth.ensemble
   :members:
   :undoc-members:
   :show-inheritance:

The Training Dataset
--------------------

:class:`~meteosynth.dataset.MetDataset` is the package's core noun: a validated,
source-agnostic training record that round-trips to disk without loss. Everything
downstream reads one, and nothing downstream cares how it was built.

.. automodule:: meteosynth.dataset
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: meteosynth.provenance
   :members:
   :undoc-members:
   :show-inheritance:

Source Adapters
---------------

Optional collection helpers. They construct a
:class:`~meteosynth.dataset.MetDataset` with its provenance filled in -- they are not a
layer the data has to pass through.

.. automodule:: meteosynth.adapters
   :members:
   :undoc-members:
   :show-inheritance:

Where a Run Reads and Writes
---------------------------

The workspace: ``data/`` for what was collected and ``output/`` for what was generated,
under a root chosen by how the code was entered -- the script's own folder for a script,
the working directory for a command.

.. automodule:: meteosynth.paths
   :members:
   :undoc-members:
   :show-inheritance:

The Download Cache
------------------

Finding a collected record without opening it. Where the adapters' cache lives, what a
cached file is called, and which one answers a given request -- read from parquet
footers, so a folder is discoverable without loading any data.

.. automodule:: meteosynth.store
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
