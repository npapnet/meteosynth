#%%
"""Temporal fidelity: autocorrelation to 10 days, reference years vs synthetic realisations.

Raw and anomaly ACF, the reference year-to-year spread as control band, integral
decorrelation time -- computed by ``meteosynth.metrics``. This script only reads the
files, prints the report and draws the figure.

The ensemble is streamed row group by row group (one calendar day each) into a
preallocated ``(N, 8760)`` array -- ~70 MB at N = 1000, against ~276 MB+ for a full
pandas read of the file.

The climatology half-width is fixed at 15 days for **every** ensemble, including the
w7 one. It is estimated from the reference only, so holding it fixed means the w7 and w15
ensembles are measured against the identical baseline.

Feb 29 is dropped from the reference, so every year has the ensemble's 8 760 hours.
Measured against the earlier Feb-29-keeping version on Heraklion: tau moves by at most
0.08 h, and 2 of 1 446 lag flags flip, both on the band edge.

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

from meteosynth import workspace
from meteosynth.metrics import Climatology, SeriesSet, TemporalFidelity, TemporalResult

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
N_USE = 1000              # realisations to use; memory is N_USE x 8760 x 8 bytes
REPORT_LAGS = [1, 3, 6, 12, 24, 48, 72, 120, 240]

TEST = TemporalFidelity(max_lag=MAX_LAG)
#%%

def read_ensemble_meta(path: pathlib.Path) -> dict:
    """The ``meteosynth_ensemble`` block of the parquet footer."""
    meta = pq.ParquetFile(path).schema_arrow.metadata or {}
    if b"meteosynth_ensemble" not in meta:
        raise ValueError(f"{path.name} is not a meteosynth ensemble (no footer block)")
    return json.loads(meta[b"meteosynth_ensemble"].decode("utf-8"))


def read_reference(path: pathlib.Path, attr: str) -> SeriesSet:
    """One member per complete observed year, Feb 29 dropped."""
    frame = pd.read_parquet(path, columns=["year", "month", "day", "hour", attr])
    reference = SeriesSet.from_reference_frame(frame, attr)
    if reference.dropped:
        print(f"  reference: left out incomplete years {reference.dropped}")
    return reference


def read_synthetic(path: pathlib.Path, attr: str, n_use: int = N_USE) -> SeriesSet:
    """One attribute of the ensemble, streamed day by day into an (n_use, n_hours) array.

    Row group d is calendar day d+1: ``N x 24`` rows, realisation-major. Its month and day
    come from the footer statistics, so the calendar costs no data read.
    """
    n_total = int(read_ensemble_meta(path)["n_realisations"])
    n = min(n_use, n_total)
    ens_file = pq.ParquetFile(path)
    md = ens_file.metadata
    n_days = md.num_row_groups
    cols = [md.schema.column(i).name for i in range(md.num_columns)]
    month_col, day_col = cols.index("month"), cols.index("day")

    values = np.empty((n, n_days * 24))
    month = np.empty(n_days * 24, dtype=int)
    day = np.empty(n_days * 24, dtype=int)
    for d in range(n_days):
        rg = md.row_group(d)
        month[d * 24:(d + 1) * 24] = rg.column(month_col).statistics.min
        day[d * 24:(d + 1) * 24] = rg.column(day_col).statistics.min
        block = ens_file.read_row_group(d, columns=[attr])[attr].to_numpy().reshape(n_total, 24)
        values[:, d * 24:(d + 1) * 24] = block[:n]

    return SeriesSet(values, month, day, np.tile(np.arange(24), n_days), attr=attr)

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
        f"Temporal fidelity, {ATTRS_LABELS[result.attr]} at {SITE} — {result.n_reference} "
        f"reference years vs {result.n_synthetic} realisations.  "
        f"Anomaly τ: reference {result.tau_reference.mean():.1f} h, "
        f"synthetic {result.tau_synthetic.mean():.1f} h",
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
    reference = read_reference(training_path, attr)
    synthetic = read_synthetic(synthetic_path, attr)
    climatology = Climatology.from_series(reference, half_width=CLIM_HALF_WIDTH)
    result = TEST.evaluate(reference, synthetic, climatology)
    del synthetic
    print(f"{attr}: ACFs computed in {time.perf_counter() - started:.1f}s")
    print_report(result)

    attr_dir = output_dir / attr
    attr_dir.mkdir(parents=True, exist_ok=True)
    stem = attr_dir / f"{synthetic_path.stem}-{attr}_temporal_acf"
    result.table.to_csv(stem.with_suffix(".csv"), index=False)
    fig = plot_temporal(result)
    fig.savefig(stem.with_suffix(".png"), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {stem}.csv / .png")

    return {"ensemble": synthetic_path.stem, "window_n_days": meta["window_n_days"],
            **result.summary()}

#%%
# --- Example One-Line Invocation ---
# summary = temporal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, "wind_speed")
# %%
print(f"reference: {TRAINING_DATA_PARQUET.name}")
print(f"ensemble:  {SYNTHETIC_DATA_PARQUET.name}")
summaries = [
    temporal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, attr) for attr in ATTRS
]
# %%
summary = pd.DataFrame(summaries)
summary.to_csv(OUTPUT_DIR / f"{SYNTHETIC_DATA_PARQUET.stem}_temporal_summary.csv", index=False)
print(summary.to_string(index=False))
# %%
