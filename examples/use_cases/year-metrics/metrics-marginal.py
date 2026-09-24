#%%
from typing import List, Optional, Tuple, Union
import pathlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
#%% 
ROOT_DIR = pathlib.Path("")
DATA_DIR = ROOT_DIR/"data"
TRAINING_DATA_PARQUET = DATA_DIR /"pvgis_hourly_leros_2005_2023.parquet"
SYNTHETIC_DATA_PARQUET = DATA_DIR/"ensemble_leros_2023_n1000_3attr.parquet"


ATTRS = ["poa_global", "temp_air", "wind_speed"]
#%%

def load_weather_data(
    file_path: str,
    realisations: Optional[Union[int, List[int]]] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Selectively load columns and realizations from Parquet using pyarrow filters."""
    filters = None
    if realisations is not None:
        if isinstance(realisations, (int, np.integer)):
            filters = [("realisation", "==", realisations)]
        elif isinstance(realisations, (list, tuple, np.ndarray)):
            filters = [("realisation", "in", list(realisations))]

    return pd.read_parquet(file_path, columns=columns, filters=filters)

#%%
def compute_ecdf(
    data: Union[pd.Series, np.ndarray], 
    drop_na: bool = True
) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate the Empirical Cumulative Distribution Function (ECDF)."""
    clean_data = np.asarray(data)
    if drop_na:
        clean_data = clean_data[~np.isnan(clean_data)]

    x = np.sort(clean_data)
    y = np.arange(1, len(x) + 1, dtype=np.float64) / len(x)
    return x, y


def plot_ecdf(
    x: np.ndarray,
    y: np.ndarray,
    variable_name: str = "Variable",
    label: Optional[str] = None,
    ax: Optional[plt.Axes] = None,
    **plot_kwargs,
) -> plt.Axes:
    """Plot an ECDF as a step function with labeled axes and gridlines."""
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 4.5))

    ax.step(x, y, where="post", label=label or variable_name, **plot_kwargs)
    ax.set_xlabel(variable_name)
    ax.set_ylabel("Empirical Probability (CDF)")
    ax.set_ylim(-0.02, 1.02)
    ax.grid(True, linestyle="--", alpha=0.6)
    if label is not None:
        ax.legend()

    return ax

#%%
# --- Example One-Line Invocations ---
# df = load_weather_data("weather_sim.parquet", realisations=[0, 1], columns=["realisation", "wind", "irradiance"])
# x, y = compute_ecdf(df["wind"])
# ax = plot_ecdf(x, y, variable_name="Wind Speed (m/s)")
# %%
variable =ATTRS[1]
df = pd.read_parquet(path = str(TRAINING_DATA_PARQUET.absolute()),
     columns = [variable]
     )
# %%
x, y = compute_ecdf ( df[variable])
# plot_ecdf (x,y, variable_name = "Wind Speed (m/s)")
# %%
df_syn = pd.read_parquet(path = str(SYNTHETIC_DATA_PARQUET.absolute()),
    columns = [variable])
# %%
x_syn, y_syn = compute_ecdf ( df_syn[variable])
#%%
# plot_ecdf(x,y, variable_name = "Wind Speed (m/s)")
# plot_ecdf (x_syn,y_syn, variable_name = "Synthetic  (m/s)")

# %%
variable_str = variable
units_str = "m/s"
fig, ax = plt.subplots(1,1, figsize = (7,4.5))
ax.step(x, y, where="post", label="Original Wind Speed")
ax.step(x_syn, y_syn, where="post", label="Synthetic Wind Speed")
ax.set_xlabel(f"{variable_str} ({units_str})")
ax.set_ylabel("Empirical Probability (CDF)")
ax.set_ylim(-0.02, 1.02)
ax.grid(True, linestyle="--", alpha=0.6)

plt.legend()
# %%
