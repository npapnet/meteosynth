"""
Daily synthetic-series generators built on top of the Markov-chain simulators.

The main entry point is :class:`EnvSeriesGenerator`, which manages an initial
distribution plus 23 hourly
:class:`~meteosynth.markov_chain_simulator_kde2d.MarkovChainSimulator2dKDE`
transition models, and stitches them together into a
complete 24-hour profile of a meteorological attribute (e.g. plane-of-array
direct irradiance ``poa_direct``, air temperature, wind speed).

This is the piece intended for Monte-Carlo studies of energy-project output and
requirements: loop :meth:`EnvSeriesGenerator.gen_day` for independent synthetic days,
or call :meth:`DayWindowGenerator.generate_series` for a continuous chained series.

Training data can be sliced two ways, and both are supported:

* by calendar month, via
  :meth:`~meteosynth.dataset.MetDataset.get_month_subset`;
* by a rolling window of +/- n days centred on a target day, via
  :meth:`~meteosynth.dataset.MetDataset.get_day_window_subset` --
  wrapped ergonomically by :class:`DayWindowGenerator`, which builds each day's
  generator lazily rather than holding all 366 in memory at once.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd

from .day_window import DAYS_IN_YEAR, day_slot, slot_to_month_day
from .markov_chain_simulator_kde2d import MarkovChainSimulator2dKDE, _as_rng
from .dataset import MetDataset, convert_to_daily_wide
from .variables import get_spec, registered

HOURS_PER_DAY = 24

#: Slot of Feb 29 on the ``all_leap`` calendar. A synthetic non-leap year skips it.
FEB29_SLOT = day_slot(2, 29)


def _check_attr(attr_str: str) -> None:
    """Validate ``attr_str`` against the spec registry.

    The registry, not a fixed list, is what decides whether a column can be modelled:
    register a spec for ``rel_humidity`` and it becomes modellable with no change to
    this package. The old ``MET_DATA_COLS`` whitelist is what made ``Int`` -- a PVGIS
    quality flag -- modellable in the first place.
    """
    if attr_str not in registered():
        raise ValueError(
            f"attr_str must be a registered variable, got {attr_str!r}. "
            f"Registered: {registered()}. Use meteosynth.register() to add one."
        )


def build_transition_pairs(wide: pd.DataFrame, hour: int) -> pd.DataFrame:
    """
    Build ``previous``/``current`` transition pairs for one hour from a wide frame.

    ``wide`` is a days-by-hours frame as produced by
    :func:`~meteosynth.dataset.convert_to_daily_wide`: one row per day, one
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
        Target hour of the day (1-23). Hour 0 is not a valid target -- see Notes.

    Returns
    -------
    pd.DataFrame
        Frame with ``previous`` and ``current`` float columns, one row per day.

    Raises
    ------
    ValueError
        If ``hour`` is outside 1-23.

    Notes
    -----
    Valid for hours **1-23** only. Hour 0 has no previous hour within the same day, and
    the chain no longer fakes one: it is started from an initial distribution
    (:func:`build_initial_values`) or continued from the previous calendar day
    (:func:`build_cross_midnight_pairs`). The old behaviour used
    ``hour_prev = (hour - 1) % 24``, making hour 0's "previous" hour 23 of the *same*
    day -- a 23-hour backwards jump rather than a 1-hour step. Measured on the shipped
    2011-2012 record, those same-day pairs correlate at 0.360 for ``wind_speed`` and
    0.890 for ``temp_air``, against 0.981 and 0.998 for the real cross-midnight step.

    On data with no missing values -- which is what PVGIS supplies -- this returns pairs
    bit-for-bit identical to the positional construction it replaced. It deviates in one
    respect, deliberately: where the source has a NaN, the positional version emitted a
    pair containing it (poisoning the KDE), whereas this drops that day.
    """
    hour = int(hour)
    if not 1 <= hour < HOURS_PER_DAY:
        raise ValueError(
            f"hour must be in 1..{HOURS_PER_DAY - 1}, got {hour}. Hour 0 has no "
            f"within-day predecessor; use build_initial_values or "
            f"build_cross_midnight_pairs."
        )

    pairs = pd.DataFrame(
        {
            "previous": wide[hour - 1],
            "current": wide[hour],
        }
    ).dropna()

    return pairs.reset_index(drop=True)


def build_initial_values(wide: pd.DataFrame) -> pd.DataFrame:
    """
    Build the sample that the initial distribution pi(x0) is fitted to.

    pi(x0) is the distribution of the *first* value of the chain. Unlike a transition it
    is unconditional -- hour 0 has no previous hour, so there is nothing to condition on.
    It is simply the observed 00:00 value of every training day.

    The frame is returned in ``previous``/``current`` form, with a constant ``previous``,
    so it can be fitted by the ordinary
    :class:`~meteosynth.markov_chain_simulator_kde2d.MarkovChainSimulator2dKDE`. That is
    not a trick: a constant ``previous`` is exactly the ``Kind.KDE_1D`` case, which
    already means "there is no information in the previous value, sample the marginal".
    When the 00:00 values are themselves constant -- as they are for irradiance, which
    is zero every midnight -- it degenerates one step further to ``Kind.CONSTANT`` and
    returns that constant. **"Irradiance starts at zero" therefore falls out of the data
    rather than being hard-coded.**

    Parameters
    ----------
    wide : pd.DataFrame
        Days-by-hours frame, as produced by
        :func:`~meteosynth.dataset.convert_to_daily_wide`.

    Returns
    -------
    pd.DataFrame
        Frame with constant ``previous`` and the observed 00:00 values as ``current``.
    """
    values = wide[0].dropna()
    return pd.DataFrame(
        {"previous": np.zeros(len(values)), "current": values.to_numpy()}
    )


def build_cross_midnight_pairs(
    wide_full: pd.DataFrame, target_index: pd.Index
) -> pd.DataFrame:
    """
    Build 23:00(d-1) -> 00:00(d) pairs from *actual consecutive dates*.

    This is the model that carries a series across midnight, and the one place where
    the climatological window and the calendar must not be confused.

    Parameters
    ----------
    wide_full : pd.DataFrame
        Days-by-hours frame over the **full record**, indexed by ``YYYYMMDD`` strings.
        Must be the whole record, not the window: the previous day of a target day may
        legitimately fall outside the window.
    target_index : pd.Index
        The ``YYYYMMDD`` index of the target days -- typically a window subset's days.

    Returns
    -------
    pd.DataFrame
        ``previous`` (23:00 of the preceding calendar day) and ``current`` (00:00 of the
        target day), one row per target day that has a real predecessor in the record.

    Notes
    -----
    Target days whose predecessor is absent drop out -- the first day of the record
    always does, since its predecessor precedes the record.

    **The trap this avoids:** the training window wraps climatologically, so a Jan 2
    window contains late-December days. Pairing on the calendar *slot* rather than the
    actual date would then pair Dec 31 **2012** with Jan 1 **2012** -- a 364-day
    backwards jump presented as a one-hour step. Looking the predecessor up by real
    date makes that impossible.
    """
    target = pd.to_datetime(pd.Index(target_index), format="%Y%m%d")
    previous_day = (target - pd.Timedelta(days=1)).strftime("%Y%m%d")
    target_str = target.strftime("%Y%m%d")

    exists = previous_day.isin(wide_full.index)
    if not exists.any():
        return pd.DataFrame({"previous": [], "current": []}, dtype=float)

    # .to_numpy() on both sides: pandas would otherwise align on the index and the two
    # lookups are keyed by different dates by construction.
    pairs = pd.DataFrame(
        {
            "previous": wide_full.loc[previous_day[exists], HOURS_PER_DAY - 1].to_numpy(),
            "current": wide_full.loc[target_str[exists], 0].to_numpy(),
        }
    ).dropna()

    return pairs.reset_index(drop=True)


def _simulator_from_wide(
    wide: pd.DataFrame,
    hour: int,
    bandwidth: Optional[float] = 0.1,
    spec=None,
) -> MarkovChainSimulator2dKDE:
    """Fit the ``hour-1 -> hour`` simulator from an already-pivoted wide frame."""
    pairs = build_transition_pairs(wide, hour)
    if pairs.empty:
        raise ValueError(
            f"no complete transition pairs for hour {hour}: the training subset has no "
            f"day with values at both hour {hour - 1} and hour {hour}"
        )
    return MarkovChainSimulator2dKDE(pairs, bandwidth=bandwidth, spec=spec)


def _to_wide(met_data: pd.DataFrame, attr_str: str) -> pd.DataFrame:
    """Pivot to a days-by-hours frame with a full 0-23 column set."""
    _check_attr(attr_str)

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
        Attribute to model. Must have a registered
        :class:`~meteosynth.variables.VariableSpec`.
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
    One day's worth of model for a meteorological attribute. Date-blind.

    Holds the 25 models that describe a single day:

    * **pi(x0)** -- the initial distribution, fitted to observed 00:00 values. Used when
      the day starts a chain.
    * **23 within-day transitions** ``h-1 -> h`` for h = 1..23.
    * **one cross-midnight transition** ``23:00(d-1) -> 00:00(d)``, used when the day
      continues a chain. Only built when ``wide_full`` is supplied, since it needs the
      full record rather than the training subset.

    This class deliberately knows nothing about *which* day it models: the caller chose
    the season by choosing the subset. Trajectories therefore live on
    :class:`DayWindowGenerator`, which does know the calendar. See
    ``docs/design/variable-specs-and-initialisation.md``.

    Parameters
    ----------
    met_data : pd.DataFrame
        Processed meteorological data with ``hour`` and ``attr_str`` columns. Typically
        a month subset
        (:meth:`~meteosynth.dataset.MetDataset.get_month_subset`) or a
        rolling day window
        (:meth:`~meteosynth.dataset.MetDataset.get_day_window_subset`);
        both are accepted unchanged.
    attr_str : str
        Attribute to model. Must have a registered
        :class:`~meteosynth.variables.VariableSpec`.
    bandwidth : float, optional
        KDE bandwidth forwarded to every simulator.
    wide_full : pd.DataFrame, optional
        The **full record** pivoted to days-by-hours, used to build the cross-midnight
        model. Without it :meth:`gen_day_from` is unavailable. :class:`DayWindowGenerator`
        pivots this once and shares it across all 366 days.
    """

    def __init__(
        self,
        met_data: pd.DataFrame,
        attr_str: str,
        bandwidth: Optional[float] = 0.1,
        wide_full: Optional[pd.DataFrame] = None,
    ) -> None:
        self.attr_str = attr_str
        self.met_data = met_data
        self.spec = get_spec(attr_str) if attr_str in registered() else None
        self._dic_simulator: dict[int, MarkovChainSimulator2dKDE] = {}

        logging.info("Initializing hourly simulators for attribute '%s'...", attr_str)
        # Pivot once and share: per-hour pivoting would cost ~12x the KDE fitting it
        # feeds (635 ms vs 20 ms, against 58 ms to fit all hours).
        wide = _to_wide(met_data, attr_str)

        # Hour 0 has no within-day predecessor, so the loop starts at 1.
        for hour in range(1, HOURS_PER_DAY):
            self._dic_simulator[hour] = _simulator_from_wide(
                wide, hour, bandwidth=bandwidth, spec=self.spec
            )

        initial = build_initial_values(wide)
        if initial.empty:
            raise ValueError(
                "no observed 00:00 values in the training subset: cannot fit pi(x0)"
            )
        self._initial = MarkovChainSimulator2dKDE(
            initial, bandwidth=bandwidth, spec=self.spec
        )

        self._cross_midnight: Optional[MarkovChainSimulator2dKDE] = None
        if wide_full is not None:
            pairs = build_cross_midnight_pairs(wide_full, wide.index)
            if not pairs.empty:
                self._cross_midnight = MarkovChainSimulator2dKDE(
                    pairs, bandwidth=bandwidth, spec=self.spec
                )

    @property
    def simulators(self) -> dict[int, MarkovChainSimulator2dKDE]:
        """The within-day hourly simulators, keyed by hour of day (1-23)."""
        return self._dic_simulator

    @property
    def initial(self) -> MarkovChainSimulator2dKDE:
        """The fitted initial distribution pi(x0)."""
        return self._initial

    @property
    def cross_midnight(self) -> Optional[MarkovChainSimulator2dKDE]:
        """The fitted 23:00(d-1) -> 00:00(d) model, or None if not built."""
        return self._cross_midnight

    def _walk_from(self, hour_0: float, rng) -> np.ndarray:
        """Fill hours 1-23 by walking the within-day transitions from ``hour_0``."""
        seq_vals = np.empty(HOURS_PER_DAY)
        seq_vals[0] = hour_0
        for hour in range(1, HOURS_PER_DAY):
            seq_vals[hour] = self._dic_simulator[hour].get_next_state(
                seq_vals[hour - 1], rng=rng
            )
        return seq_vals

    def gen_day(self, rng=None, seed: Optional[int] = None) -> np.ndarray:
        """
        Generate one synthetic day, starting the chain from pi(x0).

        Parameters
        ----------
        rng : None, int or np.random.Generator, optional
            Source of randomness. Pass a ``Generator`` to draw many days from one
            stream; pass an int for a self-contained reproducible day.
        seed : int, optional
            Convenience alias for ``rng``, when ``rng`` is not given.

        Returns
        -------
        np.ndarray
            Array of shape ``(24,)`` with one value per hour.
        """
        rng = _as_rng(seed if rng is None else rng)
        return self._walk_from(self._initial.get_next_state(0.0, rng=rng), rng)

    def gen_day_from(self, previous_2300: float, rng=None) -> np.ndarray:
        """
        Generate one synthetic day continuing from the previous day's 23:00 value.

        Hour 0 is drawn from this day's **cross-midnight** model conditioned on
        ``previous_2300``; hours 1-23 then follow the ordinary within-day transitions.

        Parameters
        ----------
        previous_2300 : float
            The 23:00 value of the preceding day.
        rng : None, int or np.random.Generator, optional
            Source of randomness.

        Returns
        -------
        np.ndarray
            Array of shape ``(24,)``.

        Raises
        ------
        ValueError
            If no cross-midnight model was built (no ``wide_full`` at construction, or
            no target day in the window had a predecessor in the record).
        """
        if self._cross_midnight is None:
            raise ValueError(
                "no cross-midnight model: construct with wide_full=, or use "
                "DayWindowGenerator.generate_series which supplies it."
            )
        rng = _as_rng(rng)
        return self._walk_from(
            self._cross_midnight.get_next_state(previous_2300, rng=rng), rng
        )


class DayWindowGenerator:
    """
    Seasonal generator built on rolling day windows, fitted lazily per target day.

    Wraps a :class:`~meteosynth.dataset.MetDataset` and hands out an
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
    dataset : MetDataset
        Processor holding the source meteorological data.
    attr_str : str
        Attribute to model. Must have a registered
        :class:`~meteosynth.variables.VariableSpec`.
    n_days : int, optional
        Half-width of the training window in days. Defaults to 15 (a 31-day window).
    bandwidth : float, optional
        KDE bandwidth forwarded to every hourly simulator.
    cache_size : int, optional
        Number of fitted generators to keep in memory. Defaults to 8 (~2.8 MB).

    Examples
    --------
    >>> dwg = DayWindowGenerator(dataset, attr_str='poa_direct')      # doctest: +SKIP
    >>> profile = dwg.gen_day(2, 29)                              # doctest: +SKIP
    >>> year = dwg.generate_series(start=(1, 1), n_days=365)      # doctest: +SKIP
    """

    def __init__(
        self,
        dataset: MetDataset,
        attr_str: str,
        n_days: int = 15,
        bandwidth: Optional[float] = 0.1,
        cache_size: int = 8,
    ) -> None:
        _check_attr(attr_str)
        if cache_size < 1:
            raise ValueError(f"cache_size must be at least 1, got {cache_size}")

        self.dataset = dataset
        self.attr_str = attr_str
        self.n_days = n_days
        self.bandwidth = bandwidth
        self.cache_size = cache_size
        self._cache: "OrderedDict[int, EnvSeriesGenerator]" = OrderedDict()
        self._wide_full_cache: Optional[pd.DataFrame] = None

    def _wide_full(self) -> pd.DataFrame:
        """The full record pivoted to days-by-hours, computed once and reused.

        Cross-midnight pairs must look up the *actual* previous calendar day, which may
        fall outside the training window, so they need the whole record. Pivoting it per
        day would repeat the single most expensive operation in the package 366 times.
        """
        if self._wide_full_cache is None:
            self._wide_full_cache = _to_wide(self.dataset.met_data, self.attr_str)
        return self._wide_full_cache

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
            self.dataset.get_day_window_subset(month, day, n_days=self.n_days),
            attr_str=self.attr_str,
            bandwidth=self.bandwidth,
            wide_full=self._wide_full(),
        )

        self._cache[slot] = generator
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)  # evict least-recently used
        return generator

    def gen_day(
        self,
        month: int,
        day: int,
        rng=None,
        seed: Optional[int] = None,
    ) -> np.ndarray:
        """
        Generate a single synthetic 24-hour profile for a calendar day.

        Hour 0 is drawn from that day's pi(x0). For a *chained* series across many days,
        use :meth:`generate_series` instead.

        Parameters
        ----------
        month : int
            Month of the target day (1-12).
        day : int
            Day of the target month.
        rng : None, int or np.random.Generator, optional
            Source of randomness.
        seed : int, optional
            Convenience alias for ``rng``.

        Returns
        -------
        np.ndarray
            Array of shape ``(24,)`` with one value per hour.
        """
        return self.for_day(month, day).gen_day(rng=rng, seed=seed)

    def generate_series(
        self,
        start: tuple,
        n_days: int,
        rng=None,
        seed: Optional[int] = None,
        include_feb29: bool = False,
        progress: bool = False,
    ) -> np.ndarray:
        """
        Generate a continuous synthetic series, chained across midnight.

        Day 1 starts from its own pi(x0). Every later day's hour 0 is drawn from **that
        day's** cross-midnight model, conditioned on the previous day's 23:00 value, and
        its hours 1-23 from that day's within-day transitions. The chain is therefore
        time-inhomogeneous at daily resolution: each calendar day uses models fitted to
        its own +/- ``n_days`` window, so the models drift smoothly through the season.

        An ensemble of independent days is ``n_days=1`` called repeatedly: pi(x0) is
        redrawn at the start of every *call*, and the cross-midnight model is used only
        *within* a call. The boundary of the call is the reset.

        Parameters
        ----------
        start : tuple of (int, int)
            ``(month, day)`` of the first day. Required: pi(x0) is a *dated* object --
            midnight temperature in January and in July are different distributions, so
            a series with no start date has no well-defined initial distribution.
        n_days : int
            Number of consecutive days to generate.
        rng : None, int or np.random.Generator, optional
            Source of randomness, resolved once for the whole series.
        seed : int, optional
            Convenience alias for ``rng``.
        include_feb29 : bool, optional
            Whether the walk visits Feb 29. Defaults to ``False``, giving a 365-day
            year: the series then steps 28 Feb 23:00 -> 1 Mar 00:00 using 1 March's
            cross-midnight model, which is fitted from real 1 March dates whose actual
            predecessor was 29 Feb in leap years and 28 Feb otherwise.
        progress : bool, optional
            Show a ``tqdm`` progress bar over the day walk. Defaults to ``False``.

            Worth it for a year (~4 minutes, since each new calendar day has to fit its
            own generators) and pointless for a single day. The bar does not persist
            once the walk finishes: an ensemble is this method called hundreds of times,
            and hundreds of leftover bars would be worse than none.

        Returns
        -------
        np.ndarray
            Array of shape ``(n_days, 24)``; row ``i`` is the ``i``-th calendar day.

        Examples
        --------
        >>> year = dwg.generate_series(start=(1, 1), n_days=365, seed=1)   # doctest: +SKIP
        >>> ens = np.vstack([dwg.generate_series((3, 14), 1, rng=rng)      # doctest: +SKIP
        ...                  for _ in range(500)])
        """
        if n_days < 1:
            raise ValueError(f"n_days must be at least 1, got {n_days}")

        rng = _as_rng(seed if rng is None else rng)
        slot = day_slot(*start)
        if not include_feb29 and slot == FEB29_SLOT:
            raise ValueError(
                "start=(2, 29) with include_feb29=False: the walk would skip its own "
                "start day. Pass include_feb29=True to generate a leap year."
            )

        out = np.empty((n_days, HOURS_PER_DAY))
        days = range(n_days)
        if progress:
            from tqdm.auto import tqdm

            days = tqdm(
                days,
                desc=f"generating {self.attr_str}",
                unit="day",
                leave=False,
            )

        for i in days:
            generator = self.for_slot(slot)
            if i == 0:
                out[i] = generator.gen_day(rng=rng)
            else:
                out[i] = generator.gen_day_from(out[i - 1, -1], rng=rng)

            slot = slot % DAYS_IN_YEAR + 1
            if not include_feb29 and slot == FEB29_SLOT:
                slot += 1
        return out

    def clear_cache(self) -> None:
        """Drop every cached generator, releasing their memory."""
        self._cache.clear()
