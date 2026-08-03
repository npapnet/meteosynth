from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("meteosynth")
except PackageNotFoundError:      # running from a source tree with no install
    __version__ = "unknown"

from meteosynth import adapters, store
from meteosynth.store import AmbiguousRecordError, default_data_dir
from meteosynth.paths import Workspace, workspace
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
from meteosynth.markov_chain_simulator_kde2d import (
    SAMPLING_PATHS,
    Kind,
    MarkovChainSimulator2dKDE,
    resolve_sampling,
)
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
    EnsembleDay,
    EnvSeriesGenerator,
    build_cross_midnight_pairs,
    build_initial_values,
    build_transition_pairs,
    generate_hr_simulator,
    realisation_stream,
)
from meteosynth.ensemble import (
    ENSEMBLE_SCHEMA_VERSION,
    Ensemble,
    ensemble_to_xlsx,
    read_ensemble,
    write_ensemble,
)

__all__ = [
    "adapters",
    # The project data store: `store.scan`, `store.resolve`, `store.describe_store`.
    "store",
    "AmbiguousRecordError",
    "default_data_dir",
    # Where a run reads and writes: `data/` and `output/` under a chosen root.
    "Workspace",
    "workspace",
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
    # Which path answers a draw: "auto", "exact" or "grid" (FEAT-17).
    "SAMPLING_PATHS",
    "resolve_sampling",
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
    # Ensembles: many realisations in one calendar walk, and their on-disk format.
    "EnsembleDay",
    "realisation_stream",
    "ENSEMBLE_SCHEMA_VERSION",
    "Ensemble",
    "write_ensemble",
    "read_ensemble",
    "ensemble_to_xlsx",
]
