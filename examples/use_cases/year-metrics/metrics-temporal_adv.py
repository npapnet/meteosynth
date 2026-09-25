#%%
"""Temporal fidelity: autocorrelation to 10 days, observed years vs synthetic realisations.

Same test as ``year-leros/leros_metric_temporal.py`` (raw and anomaly ACF, the observed
year-to-year spread as control band, integral decorrelation time), with the inputs named
explicitly instead of discovered, and one function per variable looped over all three.

The ensemble is streamed row group by row group (one calendar day each) into a
preallocated ``(N, 8760)`` array, as in the Leros script -- ~70 MB at N = 1000, rather
than the several hundred a pandas read of the whole file would cost.

The climatology half-width is fixed at 15 days for **every** ensemble, including the
w7 one. It is estimated from the observed record only, so holding it fixed means the w7
and w15 ensembles are measured against the identical baseline and any difference between
their anomaly ACFs is theirs, not the baseline's.

Feb 29 is kept on the observed side: an ACF needs a contiguous series more than a
matching day count.

Outputs, per variable, named after the ensemble so the w7 and w15 runs sit side by side:

    output_adv/temporal/<attr>/<ensemble stem>-<attr>_temporal_acf.csv  and  .png
    output_adv/temporal/<ensemble stem>_temporal_summary.csv     one row per variable
"""
from __future__ import annotations

import json
import pathlib
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.fft import irfft, next_fast_len, rfft

from meteosynth import workspace
from meteosynth.day_window import day_slots

WS = workspace(globals().get("__file__"))
#%%
TRAINING_DATA_PARQUET = WS.data_dir / "pvgis_hourly_heraklion_2005_2023.parquet"
SYNTHETIC_DATA_PARQUET = WS.data_dir / "ensemble_heraklion_2023_n1000_w7_3attr.parquet"
OUTPUT_DIR = WS.root / "output_adv" / "temporal"
SITE = "Heraklion"

ATTRS = ["poa_global", "temp_air", "wind_speed"]
ATTRS_LABELS = {"poa_global": "Plane-of-array Irradiance", "temp_air": "Air Temperature",
                "wind_speed": "Wind Speed"}

MAX_LAG = 240             # longest lag in hours (10 days)
ZOOM_LAG = 72             # the lower panels zoom on 0..ZOOM_LAG
CLIM_HALF_WIDTH = 15      # +/- days of the circular climatology smoothing; fixed across ensembles
BAND_LO, BAND_HI = 5, 95  # percentiles of the observed year-to-year band
N_USE = 1000              # realisations to use; memory is N_USE x 8760 x 8 bytes
BATCH = 100               # realisations per FFT batch
REPORT_LAGS = [1, 3, 6, 12, 24, 48, 72, 120, 240]
#%%

def read_ensemble_meta(path: pathlib.Path) -> dict:
    """The ``meteosynth_ensemble`` block of the parquet footer."""
    meta = pq.ParquetFile(path).schema_arrow.metadata or {}
    if b"meteosynth_ensemble" not in meta:
        raise ValueError(f"{path.name} is not a meteosynth ensemble (no footer block)")
    return json.loads(meta[b"meteosynth_ensemble"].decode("utf-8"))


def compute_climatology(
    observed: pd.DataFrame,
    attr: str,
    half_width: int = CLIM_HALF_WIDTH,
) -> np.ndarray:
    """Mean per (day-of-year slot, hour), smoothed over a circular +/- half_width window.

    Returns a (366, 24) array; row ``slot - 1`` holds the 24 hourly means of that slot.
    """
    raw_clim = (
        observed.groupby(["slot", "hour"])[attr].mean()
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
    observed: pd.DataFrame,
    attr: str,
    clim: np.ndarray,
    max_lag: int = MAX_LAG,
) -> tuple[np.ndarray, np.ndarray]:
    """Raw and anomaly ACF of each observed year, one contiguous series per year.

    Returns two (M, max_lag + 1) arrays.
    """
    raw, anom = [], []
    for year, group in observed.groupby("year"):
        series = group.sort_values(["month", "day", "hour"])
        values = series[attr].to_numpy()
        if len(values) < max_lag * 4:
            print(f"  skipping {year}: only {len(values)} hours")
            continue
        baseline = clim[series["slot"].to_numpy() - 1, series["hour"].to_numpy()]
        raw.append(acf_rows(values[None, :], max_lag)[0])
        anom.append(acf_rows((values - baseline)[None, :], max_lag)[0])
    return np.vstack(raw), np.vstack(anom)


def synthetic_acfs(
    path: pathlib.Path,
    attr: str,
    clim: np.ndarray,
    n_use: int = N_USE,
    max_lag: int = MAX_LAG,
) -> tuple[np.ndarray, np.ndarray]:
    """Raw and anomaly ACF of each realisation, computed within it, never across joins.

    Row group d is calendar day d+1: ``N x 24`` rows, realisation-major. Each is written
    straight into its slice of an (n_use, n_days * 24) array. Returns two
    (n_use, max_lag + 1) arrays.
    """
    n_total = int(read_ensemble_meta(path)["n_realisations"])
    n = min(n_use, n_total)
    ens_file = pq.ParquetFile(path)
    md = ens_file.metadata
    n_days = md.num_row_groups
    cols = [md.schema.column(i).name for i in range(md.num_columns)]
    month_col, day_col = cols.index("month"), cols.index("day")

    series = np.empty((n, n_days * 24))
    slots = np.empty(n_days * 24, dtype=int)
    hours = np.tile(np.arange(24), n_days)
    for d in range(n_days):
        rg = md.row_group(d)
        slots[d * 24:(d + 1) * 24] = day_slots(
            [rg.column(month_col).statistics.min], [rg.column(day_col).statistics.min])[0]
        block = ens_file.read_row_group(d, columns=[attr])[attr].to_numpy().reshape(n_total, 24)
        series[:, d * 24:(d + 1) * 24] = block[:n]

    baseline = clim[slots - 1, hours]
    return acf_rows(series, max_lag), acf_rows(series - baseline, max_lag)

#%%
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
    attr: str,
    M: int,
    N: int,
) -> None:
    """Print the anomaly ACF at REPORT_LAGS, the in-band fraction and tau."""
    print(f"\n{'=' * 78}")
    print(f"Temporal fidelity, {attr} -- M = {M} observed years vs N = {N} realisations")
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
    attr: str,
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
        f"Temporal fidelity, {ATTRS_LABELS[attr]} at {SITE} — {acf_obs_raw.shape[0]} observed "
        f"years vs {acf_syn_raw.shape[0]} realisations.  "
        f"Anomaly τ: observed {tau_obs.mean():.1f} h, synthetic {tau_syn.mean():.1f} h",
        fontsize=11,
    )
    return fig

#%%
def temporal_fidelity(
    training_path: pathlib.Path,
    synthetic_path: pathlib.Path,
    attr: str,
    output_dir: pathlib.Path = OUTPUT_DIR,
) -> dict:
    """Run the temporal test for one variable, save its table and figure, return a summary."""
    meta = read_ensemble_meta(synthetic_path)
    if attr not in meta["attrs"]:
        raise ValueError(f"{synthetic_path.name} holds {meta['attrs']}, not {attr!r}")

    started = time.perf_counter()
    observed = pd.read_parquet(training_path, columns=["year", "month", "day", "hour", attr])
    observed["slot"] = day_slots(observed["month"].values, observed["day"].values)
    clim = compute_climatology(observed, attr)
    acf_obs_raw, acf_obs_anom = observed_acfs(observed, attr, clim)
    acf_syn_raw, acf_syn_anom = synthetic_acfs(synthetic_path, attr, clim)
    print(f"{attr}: ACFs computed in {time.perf_counter() - started:.1f}s")

    table = summarise_acfs(acf_obs_raw, acf_obs_anom, acf_syn_raw, acf_syn_anom)
    tau_obs = np.array([integral_time(a) for a in acf_obs_anom])
    tau_syn = np.array([integral_time(a) for a in acf_syn_anom])
    M, N = acf_obs_raw.shape[0], acf_syn_raw.shape[0]
    print_report(table, tau_obs, tau_syn, attr, M, N)

    attr_dir = output_dir / attr
    attr_dir.mkdir(parents=True, exist_ok=True)
    stem = attr_dir / f"{synthetic_path.stem}-{attr}_temporal_acf"
    table.to_csv(stem.with_suffix(".csv"), index=False)
    fig = plot_temporal(acf_obs_raw, acf_obs_anom, acf_syn_raw, acf_syn_anom,
                        attr, tau_obs, tau_syn)
    fig.savefig(stem.with_suffix(".png"), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {stem}.csv / .png")

    return {
        "ensemble": synthetic_path.stem, "window_n_days": meta["window_n_days"],
        "attr": attr, "M": M, "N": N,
        "anomaly_lags_inside": int(table["anomaly_inside_band"].sum()),
        "anomaly_share_inside": table["anomaly_inside_band"].mean(),
        "raw_share_inside": table["raw_inside_band"].mean(),
        "tau_obs_h": tau_obs.mean(), "tau_syn_h": tau_syn.mean(),
        "tau_ratio": tau_syn.mean() / tau_obs.mean(),
    }

#%%
# --- Example One-Line Invocation ---
# summary = temporal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, "wind_speed")
# %%
print(f"training: {TRAINING_DATA_PARQUET.name}")
print(f"ensemble: {SYNTHETIC_DATA_PARQUET.name}")
summaries = [
    temporal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, attr) for attr in ATTRS
]
# %%
summary = pd.DataFrame(summaries)
summary.to_csv(OUTPUT_DIR / f"{SYNTHETIC_DATA_PARQUET.stem}_temporal_summary.csv", index=False)
print(summary.to_string(index=False))
# %%
