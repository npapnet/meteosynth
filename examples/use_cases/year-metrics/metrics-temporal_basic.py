#%%
"""Temporal fidelity: autocorrelation to 10 days, reference years vs synthetic realisations.

Same test as ``metrics-temporal_adv.py`` (raw and anomaly ACF, the reference year-to-year
spread as control band, integral decorrelation time), computed by ``meteosynth.metrics``,
for one variable, laid out as constants, functions and invocation cells. The ensemble is
read with pandas here -- simple, at several times the memory of the adv script's
streaming read.
"""
from typing import List, Optional, Union
import pathlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from meteosynth.metrics import Climatology, SeriesSet, TemporalFidelity, TemporalResult
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
N_USE = 1000           # realisations to use; memory is N_USE x 8760 x 8 bytes
REPORT_LAGS = [1, 3, 6, 12, 24, 48, 72, 120, 240]

TEST = TemporalFidelity(max_lag=MAX_LAG)
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
def print_report(result: TemporalResult) -> None:
    """Print the anomaly ACF at REPORT_LAGS, the in-band fraction and tau."""
    table = result.table
    tau_ref, tau_syn = result.tau_reference, result.tau_synthetic
    p_lo, p_hi = (f"{p:g}" for p in TEST.control.percentiles)

    print(f"\n{'=' * 78}")
    print(f"Temporal fidelity, {result.attr} -- M = {result.n_reference} reference years "
          f"vs N = {result.n_synthetic} realisations")
    print("=" * 78)
    print(f"  {'lag':>6} {f'reference ({p_lo}-{p_hi}%)':>26} {'synthetic':>12} {'inside':>8}")
    for lag in REPORT_LAGS:
        if lag >= len(table):
            continue
        r = table.loc[lag]
        print(f"  {lag:4d} h  {r['ref_anomaly_mean']:7.3f} "
              f"[{r[f'ref_anomaly_p{p_lo}']:6.3f},{r[f'ref_anomaly_p{p_hi}']:6.3f}]"
              f"   {r['syn_anomaly_mean']:9.3f}   "
              f"{'yes' if r['anomaly_inside_band'] else 'NO':>6}")

    inside = table["anomaly_inside_band"]
    print(f"\n  anomaly ACF inside the reference band: {inside.sum()}/{len(table)} lags "
          f"({inside.mean():.0%})")
    print("  integral decorrelation time (anomaly):")
    print(f"    reference {tau_ref.mean():6.1f} h  (year-to-year {tau_ref.min():.1f}"
          f" .. {tau_ref.max():.1f})")
    print(f"    synthetic {tau_syn.mean():6.1f} h  (ratio {tau_syn.mean() / tau_ref.mean():.2f})")
    print(f"  largest synthetic standard error across lags: "
          f"{table['syn_anomaly_sem'].max():.4f}")

#%%
def plot_acf_panel(
    ax: plt.Axes,
    ref: np.ndarray,
    syn: np.ndarray,
    max_lag: int,
    title: str = "",
    legend: bool = False,
) -> plt.Axes:
    """Reference band and mean against the synthetic mean, lags 0..max_lag."""
    lags = np.arange(max_lag + 1)
    sl = slice(0, max_lag + 1)
    lo, hi = TEST.control.bounds(ref)
    p_lo, p_hi = TEST.control.percentiles
    ax.fill_between(
        lags, lo[sl], hi[sl], color="0.75", alpha=0.6,
        label=f"reference, {p_lo:g}-{p_hi:g}% of {ref.shape[0]} years",
    )
    ax.plot(lags, ref.mean(axis=0)[sl], color="0.25", lw=1.6, label="reference mean")
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


def plot_temporal(result: TemporalResult) -> plt.Figure:
    """2x2 figure: raw | anomaly ACF, full range on top, zoom below."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.5), constrained_layout=True)
    for col, (name, ref, syn) in enumerate((
        ("raw", result.acf_reference_raw, result.acf_synthetic_raw),
        ("anomaly", result.acf_reference_anomaly, result.acf_synthetic_anomaly),
    )):
        plot_acf_panel(axes[0, col], ref, syn, MAX_LAG, f"{name} ACF", legend=(col == 0))
        plot_acf_panel(axes[1, col], ref, syn, ZOOM_LAG, f"{name} ACF — zoom to {ZOOM_LAG} h")
    fig.suptitle(
        f"Temporal fidelity, {result.attr} — {result.n_reference} reference years vs "
        f"{result.n_synthetic} realisations.  "
        f"Anomaly τ: reference {result.tau_reference.mean():.1f} h, "
        f"synthetic {result.tau_synthetic.mean():.1f} h",
        fontsize=11,
    )
    return fig

#%%
# --- Example One-Line Invocations ---
# reference = SeriesSet.from_reference_frame(df, "wind_speed")
# result = TEST.evaluate(reference, synthetic, Climatology.from_series(reference))
# fig = plot_temporal(result)
# %%

df = load_weather_data(str(TRAINING_DATA_PARQUET.absolute()),
    columns=["year", "month", "day", "hour", variable])
reference = SeriesSet.from_reference_frame(df, variable)
clim = Climatology.from_series(reference, half_width=CLIM_HALF_WIDTH)
# %%
df_syn = load_weather_data(str(SYNTHETIC_DATA_PARQUET.absolute()),
    realisations=list(range(N_USE)),
    columns=["realisation", "day_index", "month", "day", "hour", variable])
synthetic = SeriesSet.from_ensemble_frame(df_syn, variable)
del df_syn
# %%
result = TEST.evaluate(reference, synthetic, clim)
del synthetic
print_report(result)
# %%
fig = plot_temporal(result)
# %%
OUTPUT_DIR.mkdir(exist_ok=True)
fig_name = OUTPUT_DIR/ f"{SYNTHETIC_DATA_PARQUET.stem}-{variable}_temporal_acf.png"
result.table.to_csv(fig_name.with_suffix(".csv"), index=False)
fig.savefig(fig_name,dpi=150, bbox_inches="tight", facecolor="white")
# %%
