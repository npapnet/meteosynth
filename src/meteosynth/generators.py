"""
Daily synthetic-series generators built on top of the Markov-chain simulators.

The main entry point is :class:`EnvSeriesGenerator`, which manages 24 hourly
:class:`~meteosynth.markov_chain_simulator_kde2d.MarkovChainSimulator2dKDE`
models (one per hour of the day) and stitches their transitions together into a
complete 24-hour profile of a meteorological attribute (e.g. plane-of-array
direct irradiance ``poa_direct``, air temperature, wind speed).

This is the piece intended for Monte-Carlo studies of energy-project output and
requirements: call :meth:`EnvSeriesGenerator.generate_ensemble` to draw many
independent synthetic days.

Training data can be sliced two ways, and both are supported:

* by calendar month, via
  :meth:`~meteosynth.met_data_processor.MetDataProcessor.get_month_subset`;
* by a rolling window of +/- n days centred on a target day, via
  :meth:`~meteosynth.met_data_processor.MetDataProcessor.get_day_window_subset` --
  wrapped ergonomically by :class:`DayWindowGenerator`, which builds each day's
  generator lazily rather than holding all 366 in memory at once.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd

from .day_window import day_slot, slot_to_month_day
from .markov_chain_simulator_kde2d import MarkovChainSimulator2dKDE
from .met_data_processor import MetDataProcessor, convert_to_daily_wide

# Meteorological attributes available in a processed PVGIS hourly frame.
# TODO: there is duplication in multiple levels for MET_DATA_COLS (try to remov it)
MET_DATA_COLS = [
    "poa_direct",
    "poa_sky_diffuse",
    "poa_ground_diffuse",
    "solar_elevation",
    "temp_air",
    "wind_speed",
    "Int",
]

HOURS_PER_DAY = 24


def build_transition_pairs(wide: pd.DataFrame, hour: int) -> pd.DataFrame:
    """
    Build ``previous``/``current`` transition pairs for one hour from a wide frame.

    ``wide`` is a days-by-hours frame as produced by
    :func:`~meteosynth.met_data_processor.convert_to_daily_wide`: one row per day, one
    column per hour. Both values of a pair are therefore read from the *same row*, which
    is what guarantees they come from the same day.

    That guarantee is the whole point of taking the wide frame rather than two
    hour-filtered slices of the long frame. Slicing and zipping by position is only
    correct while both slices happen to share a day ordering; it fails silently -- same
    lengths, no exception, ~27k mispaired rows -- as soon as anything re-sorts the input.
    Here, alignment is keyed on the date index, so it holds under any ordering. See
    ``docs/design/completed/transition-pair-alignment.md``.

    Days with a missing value at either hour are dropped, and only those days.

    Parameters
    ----------
    wide : pd.DataFrame
        Days-by-hours frame, indexed by date, with integer hour columns.
    hour : int
        Target hour of the day (0-23).

    Returns
    -------
    pd.DataFrame
        Frame with ``previous`` and ``current`` float columns, one row per day.

    Raises
    ------
    ValueError
        If ``hour`` is outside 0-23.

    Notes
    -----
    ``hour_prev = (hour - 1) % 24`` means hour 0's ``previous`` is hour **23 of the same
    day**, not 23:00 of the previous calendar day. This reproduces the long-standing
    behaviour of this package exactly; changing it would alter output for every existing
    user, so it is deliberately preserved here.

    On data with no missing values -- which is what PVGIS supplies -- this returns pairs
    bit-for-bit identical to the positional construction it replaced. It deviates in one
    respect, deliberately: where the source has a NaN, the positional version emitted a
    pair containing it (poisoning the KDE), whereas this drops that day.
    """
    hour = int(hour)
    if not 0 <= hour < HOURS_PER_DAY:
        raise ValueError(f"hour must be in 0..{HOURS_PER_DAY - 1}, got {hour}")

    hour_prev = (hour - 1) % HOURS_PER_DAY

    pairs = pd.DataFrame(
        {
            "previous": wide[hour_prev],
            "current": wide[hour],
        }
    ).dropna()

    return pairs.reset_index(drop=True)


def _simulator_from_wide(
    wide: pd.DataFrame,
    hour: int,
    bandwidth: Optional[float] = 0.1,
) -> MarkovChainSimulator2dKDE:
    """Fit the ``hour-1 -> hour`` simulator from an already-pivoted wide frame."""
    pairs = build_transition_pairs(wide, hour)
    if pairs.empty:
        raise ValueError(
            f"no complete transition pairs for hour {hour}: the training subset has no "
            f"day with values at both hour {(hour - 1) % HOURS_PER_DAY} and hour {hour}"
        )
    return MarkovChainSimulator2dKDE(pairs, bandwidth=bandwidth)


def _to_wide(met_data: pd.DataFrame, attr_str: str) -> pd.DataFrame:
    """Pivot to a days-by-hours frame with a full 0-23 column set."""
    if attr_str not in MET_DATA_COLS:
        raise ValueError(f"attr_str must be one of {MET_DATA_COLS}, got {attr_str!r}")

    wide = convert_to_daily_wide(met_data, value_col=attr_str)
    # Guarantee every hour column exists, so a subset missing an hour entirely fails
    # with the clear message from _simulator_from_wide rather than a bare KeyError.
    return wide.reindex(columns=range(HOURS_PER_DAY))


def generate_hr_simulator(
    met_data: pd.DataFrame,
    hour: int,
    attr_str: str,
    bandwidth: Optional[float] = 0.1,
) -> MarkovChainSimulator2dKDE:
    """
    Build a Markov-chain simulator for the transition into a specific hour.

    The current hour's values (``current``) are conditioned on the previous
    hour's values (``previous``), so the resulting simulator models the
    hour-to-hour transition ``hour-1 -> hour``.

    Parameters
    ----------
    met_data : pd.DataFrame
        Processed meteorological data containing at least an ``hour`` column
        and the requested ``attr_str`` column.
    hour : int
        Target hour of the day (0-23) for which to build the transition model.
    attr_str : str
        Meteorological attribute to model (one of :data:`MET_DATA_COLS`).
    bandwidth : float, optional
        KDE bandwidth passed to the simulator. Defaults to ``0.1`` for smooth
        transitions; use ``None`` for Scott's rule.

    Returns
    -------
    MarkovChainSimulator2dKDE
        A fitted simulator for the ``hour-1 -> hour`` transition.

    Notes
    -----
    This pivots ``met_data`` on every call. Building all 24 hourly simulators this way
    costs ~12x more in pivoting than in KDE fitting, so
    :class:`EnvSeriesGenerator` pivots once and shares the result instead. This function
    remains as the convenient single-hour entry point.
    """
    return _simulator_from_wide(_to_wide(met_data, attr_str), hour, bandwidth=bandwidth)


class EnvSeriesGenerator:
    """
    Generate synthetic 24-hour daily profiles of a meteorological attribute.

    The generator fits one hourly transition simulator per hour of the day and
    chains them: starting from ``start_value`` at hour 0, each hour's value is
    sampled from the conditional distribution given the previous hour's value.

    Parameters
    ----------
    met_data : pd.DataFrame
        Processed meteorological data with ``hour`` and ``attr_str`` columns. Typically
        a month subset
        (:meth:`~meteosynth.met_data_processor.MetDataProcessor.get_month_subset`) or a
        rolling day window
        (:meth:`~meteosynth.met_data_processor.MetDataProcessor.get_day_window_subset`);
        both are accepted unchanged.
    attr_str : str
        Meteorological attribute to model (one of :data:`MET_DATA_COLS`).
    bandwidth : float, optional
        KDE bandwidth forwarded to every hourly simulator.
    """

    def __init__(
        self,
        met_data: pd.DataFrame,
        attr_str: str,
        bandwidth: Optional[float] = 0.1,
    ) -> None:
        self.attr_str = attr_str
        self.met_data = met_data
        self._dic_simulator: dict[int, MarkovChainSimulator2dKDE] = {}

        logging.info("Initializing %d hourly simulators for attribute '%s'...",
                     HOURS_PER_DAY, attr_str)
        # Pivot once and share: per-hour pivoting would cost ~12x the KDE fitting it
        # feeds (635 ms vs 20 ms, against 58 ms to fit all 24 hours).
        wide = _to_wide(met_data, attr_str)
        for hour in range(HOURS_PER_DAY):
            self._dic_simulator[hour] = _simulator_from_wide(
                wide, hour, bandwidth=bandwidth
            )

    @property
    def simulators(self) -> dict[int, MarkovChainSimulator2dKDE]:
        """The dictionary of hourly simulators, keyed by hour of day (0-23)."""
        return self._dic_simulator

    def gen_day_sequence(self, start_value: float = 0.0, seed: Optional[int] = None) -> np.ndarray:
        """
        Generate a single synthetic 24-hour profile.

        Parameters
        ----------
        start_value : float
            The value at hour 0 (e.g. ``0.0`` irradiance at midnight).
        seed : int, optional
            If provided, seeds the generator once so the whole day is
            reproducible while each hour still transitions stochastically.

        Returns
        -------
        np.ndarray
            Array of shape ``(24,)`` with one value per hour.
        """
        if seed is not None:
            np.random.seed(seed)

        seq_vals = np.zeros(HOURS_PER_DAY)
        current_val = start_value
        for k in range(HOURS_PER_DAY):
            sim_k = self._dic_simulator[k]
            # Do not forward the seed to each step: that would reseed to the
            # same value every hour and yield an identical draw. Seeding once
            # above already makes the whole day reproducible.
            current_val = sim_k.get_next_state(current_val)
            seq_vals[k] = current_val
        return seq_vals

    def generate_ensemble(
        self,
        n_days: int,
        start_value: float = 0.0,
        seed: Optional[int] = None,
    ) -> np.ndarray:
        """
        Generate an ensemble of independent synthetic days for Monte-Carlo use.

        Parameters
        ----------
        n_days : int
            Number of synthetic daily profiles to draw.
        start_value : float
            The value at hour 0 for every profile.
        seed : int, optional
            If provided, seeds the whole ensemble once so the full draw is
            reproducible.

        Returns
        -------
        np.ndarray
            Array of shape ``(n_days, 24)``; row ``i`` is the ``i``-th
            synthetic day.
        """
        if seed is not None:
            np.random.seed(seed)

        return np.vstack(
            [self.gen_day_sequence(start_value=start_value) for _ in range(n_days)]
        )


class DayWindowGenerator:
    """
    Seasonal generator built on rolling day windows, fitted lazily per target day.

    Wraps a :class:`~meteosynth.met_data_processor.MetDataProcessor` and hands out an
    :class:`EnvSeriesGenerator` for any calendar day, trained on the +/- ``n_days``
    window centred on that day. Unlike a month-based split, the training data is centred
    on the target and varies smoothly from day to day.

    Generators are built **on demand** and held in a small LRU cache rather than
    precomputed. Holding all 366 days costs ~126 MB for one attribute (~880 MB across
    all seven), while fitting one costs only ~58 ms -- a ``gaussian_kde`` "fit" just
    stores its 992 bytes of points and a 2x2 covariance. Since callers walk the calendar
    in order, a small cache hits nearly always, and a whole synthetic year costs ~21 s of
    fitting while holding a few hundred KB.

    Persisting fitted generators to disk is deliberately *not* offered: it would write
    numbers already present in the source data, ~31x duplicated across overlapping
    windows, to save 58 ms -- and it does not work at the default ``bandwidth=0.1``
    anyway, since ``scipy``'s ``gaussian_kde`` stores an unpicklable local lambda in
    ``covariance_factor``. See ``docs/design/completed/rolling-day-window.md``.

    Parameters
    ----------
    mdp : MetDataProcessor
        Processor holding the source meteorological data.
    attr_str : str
        Meteorological attribute to model (one of :data:`MET_DATA_COLS`).
    n_days : int, optional
        Half-width of the training window in days. Defaults to 15 (a 31-day window).
    bandwidth : float, optional
        KDE bandwidth forwarded to every hourly simulator.
    cache_size : int, optional
        Number of fitted generators to keep in memory. Defaults to 8 (~2.8 MB).

    Examples
    --------
    >>> dwg = DayWindowGenerator(mdp, attr_str='poa_direct')      # doctest: +SKIP
    >>> profile = dwg.for_day(2, 29).gen_day_sequence()           # doctest: +SKIP
    """

    def __init__(
        self,
        mdp: MetDataProcessor,
        attr_str: str,
        n_days: int = 15,
        bandwidth: Optional[float] = 0.1,
        cache_size: int = 8,
    ) -> None:
        if attr_str not in MET_DATA_COLS:
            raise ValueError(f"attr_str must be one of {MET_DATA_COLS}, got {attr_str!r}")
        if cache_size < 1:
            raise ValueError(f"cache_size must be at least 1, got {cache_size}")

        self.mdp = mdp
        self.attr_str = attr_str
        self.n_days = n_days
        self.bandwidth = bandwidth
        self.cache_size = cache_size
        self._cache: "OrderedDict[int, EnvSeriesGenerator]" = OrderedDict()

    def for_day(self, month: int, day: int) -> EnvSeriesGenerator:
        """
        Get the generator trained on the window centred on ``(month, day)``.

        Feb 29 is an ordinary target and needs no special handling.

        Parameters
        ----------
        month : int
            Month of the target day (1-12).
        day : int
            Day of the target month.

        Returns
        -------
        EnvSeriesGenerator
            Fitted generator, built on first request and cached thereafter.
        """
        return self.for_slot(day_slot(month, day))

    def for_slot(self, slot: int) -> EnvSeriesGenerator:
        """
        Get the generator for an ``all_leap`` calendar slot (1-366).

        Parameters
        ----------
        slot : int
            Calendar slot, as produced by
            :func:`~meteosynth.day_window.day_slot`.

        Returns
        -------
        EnvSeriesGenerator
            Fitted generator, built on first request and cached thereafter.
        """
        if slot in self._cache:
            self._cache.move_to_end(slot)
            return self._cache[slot]

        month, day = slot_to_month_day(slot)
        logging.info("Fitting window generator for %02d-%02d (slot %d, n_days=%d)...",
                     month, day, slot, self.n_days)
        generator = EnvSeriesGenerator(
            self.mdp.get_day_window_subset(month, day, n_days=self.n_days),
            attr_str=self.attr_str,
            bandwidth=self.bandwidth,
        )

        self._cache[slot] = generator
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)  # evict least-recently used
        return generator

    def gen_day_sequence(
        self,
        month: int,
        day: int,
        start_value: float = 0.0,
        seed: Optional[int] = None,
    ) -> np.ndarray:
        """
        Generate a single synthetic 24-hour profile for a calendar day.

        Parameters
        ----------
        month : int
            Month of the target day (1-12).
        day : int
            Day of the target month.
        start_value : float
            The value at hour 0 (e.g. ``0.0`` irradiance at midnight).
        seed : int, optional
            Seeds the draw once, so the whole day is reproducible.

        Returns
        -------
        np.ndarray
            Array of shape ``(24,)`` with one value per hour.
        """
        return self.for_day(month, day).gen_day_sequence(
            start_value=start_value, seed=seed
        )

    def clear_cache(self) -> None:
        """Drop every cached generator, releasing their memory."""
        self._cache.clear()
