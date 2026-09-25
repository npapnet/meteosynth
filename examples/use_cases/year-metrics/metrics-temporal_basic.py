#%%
"""Temporal fidelity: autocorrelation to 10 days, observed years vs synthetic realisations.

Same test as ``year-leros/leros_metric_temporal.py`` (raw and anomaly ACF, the observed
year-to-year spread as control band, integral decorrelation time), laid out as constants,
functions and invocation cells.
"""
from typing import List, Optional, Tuple, Union
import pathlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.fft import irfft, next_fast_len, rfft
#%%
ROOT_DIR = pathlib.Path("")
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
TRAINING_DATA_PARQUET = DATA_DIR /"pvgis_hourly_heraklion_2005_2023.parquet"
SYNTHETIC_DATA_PARQUET = DATA_DIR/"ensemble_heraklion_2023_n1000_w15_3attr.parquet"

ATTRS = ["poa_global", "temp_air", "wind_speed"]
ATTRS_UNITS =  ["W/m²", "°C", "m/s"]
ATTRS_LABELS = ["Horizontal Irradiance", "Air Temperature", "Wind Speed"]
ATTR_IDX = 2

variable = ATTRS[ATTR_IDX]
variable_label = ATTRS_LABELS[ATTR_IDX]
variable_unit = ATTRS_UNITS[ATTR_IDX]

MAX_LAG = 240          # longest lag in hours (10 days)
ZOOM_LAG = 72          # the lower panel zooms on 0..ZOOM_LAG
CLIM_HALF_WIDTH = 15   # +/- days of the circular climatology smoothing window
BAND_LO, BAND_HI = 5, 95  # percentiles of the observed year-to-year band
N_USE = 1000           # realisations to use; memory is N_USE x 8760 x 8 bytes
BATCH = 100            # realisations per FFT batch
REPORT_LAGS = [1, 3, 6, 12, 24, 48, 72, 120, 240]

# all_leap calendar: Feb 29 is an ordinary slot, so every (month, day) maps to 1..366
MONTH_LENGTHS = np.array([31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
MONTH_OFFSETS = np.concatenate([[0], np.cumsum(MONTH_LENGTHS)[:-1]])
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


def day_slots(months: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Day-of-year slot (1..366) in the all_leap calendar."""
    months = np.asarray(months, dtype=np.int64)
    days = np.asarray(days, dtype=np.int64)
    return MONTH_OFFSETS[months - 1] + days

#%%
def compute_climatology(
    df: pd.DataFrame,
    variable: str,
    half_width: int = CLIM_HALF_WIDTH,
) -> np.ndarray:
    """Mean per (day-of-year slot, hour), smoothed over a circular +/- half_width window.

    Returns a (366, 24) array; row ``slot - 1`` holds the 24 hourly means of that slot.
    """
    slots = day_slots(df["month"].values, df["day"].values)
    raw_clim = (
        df.assign(slot=slots)
        .groupby(["slot", "hour"])[variable].mean()
        .unstack("hour").reindex(index=range(1, 367), columns=range(24))
        .to_numpy()
    )
    idx = np.arange(366)
    circular_gap = np.abs(((idx[None, :] - idx[:, None] + 183) % 366) - 183)
    window = circular_gap <= half_width
    return np.vstack([np.nanmean(raw_clim[window[s]], axis=0) for s in range(366)])


def acf_rows(matrix: np.ndarray, max_lag: int = MAX_LAG, batch: int = BATCH) -> np.ndarray:
    """Biased ACF of each row of ``matrix`` by FFT, lags 0..max_lag."""
    n_rows, T = matrix.shape
    nfft = next_fast_len(2 * T)
    out = np.empty((n_rows, max_lag + 1))
    for start in range(0, n_rows, batch):
        chunk = matrix[start:start + batch]
        centred = chunk - chunk.mean(axis=1, keepdims=True)
        spectrum = rfft(centred, n=nfft, axis=1)
        acov = irfft(spectrum * np.conj(spectrum), n=nfft, axis=1)[:, :max_lag + 1]
        out[start:start + batch] = acov / acov[:, :1]
    return out


def integral_time(acf: np.ndarray) -> float:
    """Integral decorrelation time in hours: 1 + 2*sum(rho) up to the first zero crossing."""
    negative = np.flatnonzero(acf[1:] <= 0)
    cut = int(negative[0]) + 1 if negative.size else len(acf)
    return float(1 + 2 * acf[1:cut].sum())

#%%
def observed_acfs(
    df: pd.DataFrame,
    variable: str,
    clim: np.ndarray,
    max_lag: int = MAX_LAG,
) -> Tuple[np.ndarray, np.ndarray]:
    """Raw and anomaly ACF of each observed year, one contiguous series per year.

    Feb 29 is kept: an ACF needs a contiguous series more than a matching day count.
    Returns two (M, max_lag + 1) arrays.
    """
    raw, anom = [], []
    for year, group in df.groupby("year"):
        series = group.sort_values(["month", "day", "hour"])
        values = series[variable].to_numpy()
        if len(values) < max_lag * 4:
            print(f"  skipping {year}: only {len(values)} hours")
            continue
        slots = day_slots(series["month"].values, series["day"].values)
        baseline = clim[slots - 1, series["hour"].to_numpy()]
        raw.append(acf_rows(values[None, :], max_lag)[0])
        anom.append(acf_rows((values - baseline)[None, :], max_lag)[0])
    return np.vstack(raw), np.vstack(anom)


def synthetic_acfs(
    df: pd.DataFrame,
    variable: str,
    clim: np.ndarray,
    max_lag: int = MAX_LAG,
) -> Tuple[np.ndarray, np.ndarray]:
    """Raw and anomaly ACF of each realisation, computed within it, never across joins.

    Returns two (N, max_lag + 1) arrays.
    """
    df = df.sort_values(["realisation", "day_index", "hour"])
    n_real = df["realisation"].nunique()
    series = df[variable].to_numpy().reshape(n_real, -1)

    # the calendar is the same for every realisation, so take it from the first one
    first = df[df["realisation"] == df["realisation"].iloc[0]]
    slots = day_slots(first["month"].values, first["day"].values)
    baseline = clim[slots - 1, first["hour"].to_numpy()]

    return acf_rows(series, max_lag), acf_rows(series - baseline, max_lag)


def summarise_acfs(
    acf_obs_raw: np.ndarray,
    acf_obs_anom: np.ndarray,
    acf_syn_raw: np.ndarray,
    acf_syn_anom: np.ndarray,
) -> pd.DataFrame:
    """Per-lag table: observed mean and band, synthetic mean and SEM, inside-band flag."""
    table = pd.DataFrame({"lag_hours": np.arange(acf_obs_raw.shape[1])})
    for name, obs, syn in (
        ("raw", acf_obs_raw, acf_syn_raw),
        ("anomaly", acf_obs_anom, acf_syn_anom),
    ):
        lo = np.percentile(obs, BAND_LO, axis=0)
        hi = np.percentile(obs, BAND_HI, axis=0)
        syn_mean = syn.mean(axis=0)
        table[f"obs_{name}_mean"] = obs.mean(axis=0)
        table[f"obs_{name}_p{BAND_LO}"] = lo
        table[f"obs_{name}_p{BAND_HI}"] = hi
        table[f"syn_{name}_mean"] = syn_mean
        table[f"syn_{name}_sem"] = syn.std(axis=0, ddof=1) / np.sqrt(syn.shape[0])
        table[f"{name}_inside_band"] = (syn_mean >= lo) & (syn_mean <= hi)
    return table


def print_report(
    table: pd.DataFrame,
    tau_obs: np.ndarray,
    tau_syn: np.ndarray,
    variable: str,
    M: int,
    N: int,
) -> None:
    """Print the anomaly ACF at REPORT_LAGS, the in-band fraction and tau."""
    print(f"\n{'=' * 78}")
    print(f"Temporal fidelity, {variable} -- M = {M} observed years vs N = {N} realisations")
    print("=" * 78)
    print(f"  {'lag':>6} {'observed (5-95%)':>26} {'synthetic':>12} {'inside':>8}")
    for lag in REPORT_LAGS:
        if lag >= len(table):
            continue
        r = table.loc[lag]
        print(f"  {lag:4d} h  {r['obs_anomaly_mean']:7.3f} "
              f"[{r[f'obs_anomaly_p{BAND_LO}']:6.3f},{r[f'obs_anomaly_p{BAND_HI}']:6.3f}]"
              f"   {r['syn_anomaly_mean']:9.3f}   "
              f"{'yes' if r['anomaly_inside_band'] else 'NO':>6}")

    inside = table["anomaly_inside_band"]
    print(f"\n  anomaly ACF inside the observed band: {inside.sum()}/{len(table)} lags "
          f"({inside.mean():.0%})")
    print(f"  integral decorrelation time (anomaly):")
    print(f"    observed  {tau_obs.mean():6.1f} h  (year-to-year {tau_obs.min():.1f}"
          f" .. {tau_obs.max():.1f})")
    print(f"    synthetic {tau_syn.mean():6.1f} h  (ratio {tau_syn.mean() / tau_obs.mean():.2f})")
    print(f"  largest synthetic standard error across lags: "
          f"{table['syn_anomaly_sem'].max():.4f}")

#%%
def plot_acf_panel(
    ax: plt.Axes,
    obs: np.ndarray,
    syn: np.ndarray,
    max_lag: int,
    title: str = "",
    legend: bool = False,
) -> plt.Axes:
    """Observed band and mean against the synthetic mean, lags 0..max_lag."""
    lags = np.arange(max_lag + 1)
    sl = slice(0, max_lag + 1)
    ax.fill_between(
        lags, np.percentile(obs, BAND_LO, axis=0)[sl], np.percentile(obs, BAND_HI, axis=0)[sl],
        color="0.75", alpha=0.6,
        label=f"observed, {BAND_LO}-{BAND_HI}% of {obs.shape[0]} years",
    )
    ax.plot(lags, obs.mean(axis=0)[sl], color="0.25", lw=1.6, label="observed mean")
    ax.plot(lags, syn.mean(axis=0)[sl], color="tab:red", lw=1.6,
            label=f"synthetic mean, N={syn.shape[0]}")
    ax.axhline(0, color="0.6", lw=0.7)
    for day in range(24, max_lag + 1, 24):
        ax.axvline(day, color="0.9", lw=0.6, zorder=0)
    ax.set_xlim(0, max_lag)
    ax.set_xlabel("lag (hours)")
    ax.set_ylabel("autocorrelation")
    ax.set_title(title)
    if legend:
        ax.legend(fontsize=8)
    return ax


def plot_temporal(
    acf_obs_raw: np.ndarray,
    acf_obs_anom: np.ndarray,
    acf_syn_raw: np.ndarray,
    acf_syn_anom: np.ndarray,
    variable: str,
    tau_obs: np.ndarray,
    tau_syn: np.ndarray,
) -> plt.Figure:
    """2x2 figure: raw | anomaly ACF, full range on top, zoom below."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.5), constrained_layout=True)
    for col, (name, obs, syn) in enumerate((
        ("raw", acf_obs_raw, acf_syn_raw),
        ("anomaly", acf_obs_anom, acf_syn_anom),
    )):
        plot_acf_panel(axes[0, col], obs, syn, MAX_LAG, f"{name} ACF", legend=(col == 0))
        plot_acf_panel(axes[1, col], obs, syn, ZOOM_LAG, f"{name} ACF — zoom to {ZOOM_LAG} h")
    fig.suptitle(
        f"Temporal fidelity, {variable} — {acf_obs_raw.shape[0]} observed years vs "
        f"{acf_syn_raw.shape[0]} realisations.  "
        f"Anomaly τ: observed {tau_obs.mean():.1f} h, synthetic {tau_syn.mean():.1f} h",
        fontsize=11,
    )
    return fig

#%%
# --- Example One-Line Invocations ---
# clim = compute_climatology(df, "wind_speed")
# acf_obs_raw, acf_obs_anom = observed_acfs(df, "wind_speed", clim)
# fig = plot_temporal(acf_obs_raw, acf_obs_anom, acf_syn_raw, acf_syn_anom, "wind_speed", tau_obs, tau_syn)
# %%

df = load_weather_data(str(TRAINING_DATA_PARQUET.absolute()),
    columns=["year", "month", "day", "hour", variable])
# %%
clim = compute_climatology(df, variable)
acf_obs_raw, acf_obs_anom = observed_acfs(df, variable, clim)
# %%
df_syn = load_weather_data(str(SYNTHETIC_DATA_PARQUET.absolute()),
    realisations=list(range(N_USE)),
    columns=["realisation", "day_index", "month", "day", "hour", variable])
# %%
acf_syn_raw, acf_syn_anom = synthetic_acfs(df_syn, variable, clim)
del df_syn
# %%
table = summarise_acfs(acf_obs_raw, acf_obs_anom, acf_syn_raw, acf_syn_anom)
tau_obs = np.array([integral_time(a) for a in acf_obs_anom])
tau_syn = np.array([integral_time(a) for a in acf_syn_anom])
print_report(table, tau_obs, tau_syn, variable, M=acf_obs_raw.shape[0], N=acf_syn_raw.shape[0])
# %%
fig = plot_temporal(acf_obs_raw, acf_obs_anom, acf_syn_raw, acf_syn_anom,
    variable, tau_obs, tau_syn)
# %%
OUTPUT_DIR.mkdir(exist_ok=True)
fig_name = OUTPUT_DIR/ f"{SYNTHETIC_DATA_PARQUET.stem}-{variable}_temporal_acf.png"
table.to_csv(fig_name.with_suffix(".csv"), index=False)
fig.savefig(fig_name,dpi=150, bbox_inches="tight", facecolor="white")
# %%
