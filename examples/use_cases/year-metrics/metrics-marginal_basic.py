#%%
from typing import List, Optional, Tuple, Union
import pathlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
#%% 
ROOT_DIR = pathlib.Path("")
DATA_DIR = ROOT_DIR/"data"
RESULTS_DIR = ROOT_DIR/"output"
RESULTS_DIR.mkdir(exist_ok=True,parents=True)
TRAINING_DATA_PARQUET = DATA_DIR /"pvgis_hourly_heraklion_2005_2023.parquet"
SYNTHETIC_DATA_PARQUET = DATA_DIR/"ensemble_heraklion_2023_n1000_w15_3attr.parquet"


ATTRS = ["poa_global", "temp_air", "wind_speed"]
ATTRS_UNITS =  ["W/m²", "°C", "m/s"]
ATTRS_LABELS = ["Horizontal Irradiance", "Air Temperature", "Wind Speed"]
ATTR_IDX = 2    
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
    drop_na: bool = True,
    n_points: Optional[int] = 1001,
) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate the Empirical Cumulative Distribution Function (ECDF)."""
    clean_data = np.asarray(data)
    if drop_na:
        clean_data = clean_data[~np.isnan(clean_data)]

    if n_points is not None and len(clean_data) > n_points:
        y = np.linspace(0, 1.0, num=n_points)
        x = np.quantile(clean_data, y)
        return x, y

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
variable =ATTRS[ATTR_IDX]
ATTR_LABEL = ATTRS_LABELS[ATTR_IDX]
ATTR_UNIT = ATTRS_UNITS[ATTR_IDX]

df = pd.read_parquet(path = str(TRAINING_DATA_PARQUET.absolute()),
     columns = [variable]
     )
x, y = compute_ecdf ( df[variable])
# plot_ecdf (x,y, variable_name = "Wind Speed (m/s)")
# %%
df_syn = pd.read_parquet(path = str(SYNTHETIC_DATA_PARQUET.absolute()),
    columns = [variable])

x_syn, y_syn = compute_ecdf ( df_syn[variable])
#%%
# plot_ecdf(x,y, variable_name = "Wind Speed (m/s)")
# plot_ecdf (x_syn,y_syn, variable_name = "Synthetic  (m/s)")

# %%
variable_str = variable

fig, ax = plt.subplots(1,1, figsize = (7,4.5))
ax.plot(x, y,markersize=1, label=f"Original {ATTR_LABEL}")
ax.plot(x_syn, y_syn, markersize=1, label=f"Synthetic {ATTR_LABEL}")
ax.set_xlabel(f"{variable_str} ({ATTR_UNIT})")
ax.set_ylabel("Empirical Probability (CDF)")
ax.set_ylim(-0.02, 1.02)
ax.grid(True, linestyle="--", alpha=0.6)

plt.legend()
#%%
figname = RESULTS_DIR/ f"{SYNTHETIC_DATA_PARQUET.stem}-{variable_str}_ecdf.png"
fig.savefig(figname, dpi=300, bbox_inches="tight")
# %%
