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
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .markov_chain_simulator_kde2d import MarkovChainSimulator2dKDE

# Meteorological attributes available in a processed PVGIS hourly frame.
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
    """
    if attr_str not in MET_DATA_COLS:
        raise ValueError(f"attr_str must be one of {MET_DATA_COLS}, got {attr_str!r}")

    hour_prev = (hour - 1) % HOURS_PER_DAY
    cur_hour = met_data[met_data["hour"] == hour]
    prev_hour = met_data[met_data["hour"] == hour_prev]

    # Combine previous and current hour values into a single transition frame.
    transition_data = pd.DataFrame(
        {
            "previous": prev_hour[attr_str].values,
            "current": cur_hour[attr_str].values,
        }
    )

    return MarkovChainSimulator2dKDE(transition_data, bandwidth=bandwidth)


class EnvSeriesGenerator:
    """
    Generate synthetic 24-hour daily profiles of a meteorological attribute.

    The generator fits one hourly transition simulator per hour of the day and
    chains them: starting from ``start_value`` at hour 0, each hour's value is
    sampled from the conditional distribution given the previous hour's value.

    Parameters
    ----------
    met_data : pd.DataFrame
        Processed meteorological data (typically a single month subset) with
        ``hour`` and ``attr_str`` columns.
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
        for hour in range(HOURS_PER_DAY):
            self._dic_simulator[hour] = generate_hr_simulator(
                met_data, hour, attr_str=attr_str, bandwidth=bandwidth
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
