from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("meteosynth")
except PackageNotFoundError:      # running from a source tree with no install
    __version__ = "unknown"

from meteosynth import adapters
from meteosynth.constants import INDEX_COLS, SHIPPED_ATTRS, modelled_attrs
from meteosynth.variables import (
    IRRADIANCE,
    IRRADIANCE_COLUMNS,
    IRRADIANCE_HORIZONTAL,
    TEMP_AIR,
    WIND_SPEED,
    VariableSpec,
    get_spec,
    irradiance_columns,
    register,
    registered,
    resolve_irradiance,
    unregister,
)
from meteosynth.markov_chain_simulator_kde2d import Kind, MarkovChainSimulator2dKDE
from meteosynth.markov_implementations.markov_chain_simulator_continuous import ContinuousMarkovChainSimulator
from meteosynth.markov_implementations.markov_chain_simulator_discrete import MarkovChainSimulatorDiscrete
from meteosynth.provenance import Provenance
from meteosynth.dataset import (
    SCHEMA_VERSION,
    MetDataset,
    convert_to_daily_wide,
    trim_columns,
    validate_columns,
)
from meteosynth.day_window import (
    DAYS_IN_YEAR,
    circular_delta,
    day_slot,
    day_slots,
    slot_to_month_day,
    window_slots,
)
from meteosynth.generators import (
    DayWindowGenerator,
    EnvSeriesGenerator,
    build_cross_midnight_pairs,
    build_initial_values,
    build_transition_pairs,
    generate_hr_simulator,
)

__all__ = [
    "adapters",
    "INDEX_COLS",
    "SHIPPED_ATTRS",
    "modelled_attrs",
    "VariableSpec",
    "IRRADIANCE",
    "IRRADIANCE_COLUMNS",
    "IRRADIANCE_HORIZONTAL",
    "TEMP_AIR",
    "WIND_SPEED",
    "get_spec",
    "irradiance_columns",
    "resolve_irradiance",
    "register",
    "unregister",
    "registered",
    "Kind",
    "MarkovChainSimulator2dKDE",
    "ContinuousMarkovChainSimulator",
    "MarkovChainSimulatorDiscrete",
    "MetDataset",
    "Provenance",
    "SCHEMA_VERSION",
    "convert_to_daily_wide",
    "validate_columns",
    "trim_columns",
    "DAYS_IN_YEAR",
    "circular_delta",
    "day_slot",
    "day_slots",
    "slot_to_month_day",
    "window_slots",
    "DayWindowGenerator",
    "EnvSeriesGenerator",
    "build_transition_pairs",
    "build_initial_values",
    "build_cross_midnight_pairs",
    "generate_hr_simulator",
]
