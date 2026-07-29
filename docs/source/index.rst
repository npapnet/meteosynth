Welcome to meteosynth's documentation!
======================================

``meteosynth`` generates **synthetic environmental time-series** (solar
irradiance, air temperature, wind speed, ...) from historical meteorological
data using Markov-chain models driven by kernel density estimation. Its primary
target is **Monte-Carlo simulation of energy-project output and requirements**,
where many statistically-plausible weather years are needed rather than a
single deterministic profile.

Each calendar day is modelled from a **rolling window** of the record centred on
it, so one object serves every time scale: draw a single day, chain a month, or
walk a complete 8760-hour year. See :doc:`quickstart` for all three.

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   quickstart
   concepts
   workflow
   theory
   examples

.. toctree::
   :maxdepth: 2
   :caption: API reference

   api

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
