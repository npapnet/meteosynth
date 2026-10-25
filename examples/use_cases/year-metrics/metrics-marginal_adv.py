#%%
"""Marginal fidelity: Wasserstein-1 per (month, hour-of-day) cell, against a control band.

Full-power and size-matched W1, a control band from random half-splits of the reference
years, and the pre-registered pass rule -- computed by ``meteosynth.metrics``. This script
only reads the files, prints the report and draws the figure.

Cells where reference and synthetic are the same constant (``poa_global`` at night) are
flagged ``degenerate`` and left out of the pass share; their normalised columns are NaN
and show blank in the heatmaps.

Feb 29 is dropped from the reference: the ensemble was generated without it.

Outputs, per variable, named after the ensemble so the w7 and w15 runs sit side by side:

    output_adv/marginal/<attr>/<ensemble stem>-<attr>_marginal_w1.csv  and  .png
    output_adv/marginal/<ensemble stem>_marginal_summary.csv    one row per variable
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
from meteosynth.metrics import MarginalFidelity, MarginalResult, SeriesSet, YearSplitBand

WS = workspace(globals().get("__file__"))
#%%
TRAINING_DATA_PARQUET = WS.data_dir / "pvgis_hourly_heraklion_2005_2023.parquet"
SYNTHETIC_DATA_PARQUET = WS.data_dir / "ensemble_heraklion_2023_n1000_w7_3attr.parquet"
OUTPUT_DIR = WS.root / "output_adv" / "marginal"
SITE = "Heraklion"

ATTRS = ["poa_global", "temp_air", "wind_speed"]
ATTRS_UNITS = {"poa_global": "W/m²", "temp_air": "°C", "wind_speed": "m/s"}
ATTRS_LABELS = {"poa_global": "Plane-of-array Irradiance", "temp_air": "Air Temperature",
                "wind_speed": "Wind Speed"}

TEST = MarginalFidelity(
    control=YearSplitBand(n_splits=100, percentiles=(5, 95), seed=11),  # same splits everywhere
    pass_share=0.90,                                                    # pre-registered
)
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


def read_synthetic(path: pathlib.Path, attr: str) -> SeriesSet:
    """One attribute of the ensemble, streamed day by day into an (N, n_hours) array.

    Row group d is calendar day d+1: ``N x 24`` rows, realisation-major. Its month and day
    come from the footer statistics, so the calendar costs no data read.
    """
    n_total = int(read_ensemble_meta(path)["n_realisations"])
    ens_file = pq.ParquetFile(path)
    md = ens_file.metadata
    n_days = md.num_row_groups
    cols = [md.schema.column(i).name for i in range(md.num_columns)]
    month_col, day_col = cols.index("month"), cols.index("day")

    values = np.empty((n_total, n_days * 24))
    month = np.empty(n_days * 24, dtype=int)
    day = np.empty(n_days * 24, dtype=int)
    for d in range(n_days):
        rg = md.row_group(d)
        month[d * 24:(d + 1) * 24] = rg.column(month_col).statistics.min
        day[d * 24:(d + 1) * 24] = rg.column(day_col).statistics.min
        values[:, d * 24:(d + 1) * 24] = (
            ens_file.read_row_group(d, columns=[attr])[attr].to_numpy().reshape(n_total, 24))

    return SeriesSet(values, month, day, np.tile(np.arange(24), n_days), attr=attr)

#%%
def print_report(result: MarginalResult) -> None:
    """Summary distances, the pass share over scored cells, and the five worst cells."""
    unit = ATTRS_UNITS[result.attr]
    scored = result.scored

    print(f"\n{'=' * 78}")
    print(f"Marginal fidelity, {result.attr} -- M = {result.n_reference} reference years "
          f"vs N = {result.n_synthetic} realisations")
    print("=" * 78)
    print(f"  W1 / reference sd     median {scored['w1_norm'].median():.3f}   "
          f"p90 {scored['w1_norm'].quantile(0.90):.3f}   max {scored['w1_norm'].max():.3f}")
    print(f"  W1 ({unit})".ljust(24) + f"median {scored['w1'].median():.3f}   "
          f"p90 {scored['w1'].quantile(0.90):.3f}   max {scored['w1'].max():.3f}")
    print(f"  control band ({unit})".ljust(24) + f"median {scored['control_median'].median():.3f}   "
          f"upper {scored['control_hi'].median():.3f}")
    print(f"  mean bias / sd        median {scored['bias_norm'].median():+.3f}   "
          f"range {scored['bias_norm'].min():+.3f} .. {scored['bias_norm'].max():+.3f}")
    print(f"  sd ratio              median {scored['sd_ratio'].median():.3f}   "
          f"range {scored['sd_ratio'].min():.3f} .. {scored['sd_ratio'].max():.3f}")
    print(f"\n  degenerate cells (same constant both sides, not scored): "
          f"{int(result.table['degenerate'].sum())}")
    print(f"  cells within the control band: {scored['passes'].sum()}/{len(scored)} "
          f"({result.pass_share:.1%})  ->  {'PASS' if result.passed else 'FAIL'} "
          f"at the {result.pass_threshold:.0%} rule")

    worst = scored.nlargest(5, "w1_norm")[
        ["month", "hour", "w1", "w1_norm", "bias_norm", "sd_ratio", "control_hi", "passes"]
    ]
    print("\n  worst five cells by W1 / sd:")
    print(worst.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))

#%%
def plot_marginal(result: MarginalResult) -> plt.Figure:
    """Month x hour heatmaps of W1/sd and bias/sd, cells outside the band marked."""
    grid_w1 = result.grid("w1_norm")
    grid_bias = result.grid("bias_norm")
    fails = result.table.assign(fail=~result.table["passes"] & ~result.table["degenerate"])
    fails = fails[fails["fail"]]
    bias_lim = np.nanmax(np.abs(grid_bias))

    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6), constrained_layout=True)
    for ax, grid, title, cmap, kw in (
        (axes[0], grid_w1, "W₁ / reference sd", "viridis", {"vmin": 0}),
        (axes[1], grid_bias, "mean bias / reference sd", "RdBu_r",
         {"vmin": -bias_lim, "vmax": bias_lim}),
    ):
        im = ax.imshow(grid, aspect="auto", cmap=cmap, origin="lower",
                       extent=[-0.5, 23.5, 0.5, 12.5], **kw)
        ax.plot(fails["hour"], fails["month"], "x", color="white", markersize=5,
                markeredgewidth=1.2, label="outside control band")
        ax.set_xlabel("hour of day")
        ax.set_ylabel("month")
        ax.set_yticks(range(1, 13))
        ax.set_title(title)
        fig.colorbar(im, ax=ax)
        if len(fails):
            ax.legend(loc="upper right", fontsize=8, framealpha=0.85)

    fig.suptitle(
        f"Marginal fidelity, {ATTRS_LABELS[result.attr]} at {SITE} — {result.n_reference} "
        f"reference years vs {result.n_synthetic} realisations ({result.pass_share:.0%} of "
        f"scored cells within the year-split control band)",
        fontsize=11,
    )
    return fig

#%%
def marginal_fidelity(
    training_path: pathlib.Path,
    synthetic_path: pathlib.Path,
    attr: str,
    output_dir: pathlib.Path = OUTPUT_DIR,
) -> dict:
    """Run the marginal test for one variable, save its table and figure, return a summary."""
    meta = read_ensemble_meta(synthetic_path)
    if attr not in meta["attrs"]:
        raise ValueError(f"{synthetic_path.name} holds {meta['attrs']}, not {attr!r}")

    started = time.perf_counter()
    reference = read_reference(training_path, attr)
    synthetic = read_synthetic(synthetic_path, attr)
    result = TEST.evaluate(reference, synthetic)
    del synthetic
    print(f"{attr}: {len(result.table)} cells x {TEST.control.n_splits} splits in "
          f"{time.perf_counter() - started:.1f}s")
    print_report(result)

    attr_dir = output_dir / attr
    attr_dir.mkdir(parents=True, exist_ok=True)
    stem = attr_dir / f"{synthetic_path.stem}-{attr}_marginal_w1"
    result.table.to_csv(stem.with_suffix(".csv"), index=False)
    fig = plot_marginal(result)
    fig.savefig(stem.with_suffix(".png"), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {stem}.csv / .png")

    return {"ensemble": synthetic_path.stem, "window_n_days": meta["window_n_days"],
            **result.summary()}

#%%
# --- Example One-Line Invocation ---
# summary = marginal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, "wind_speed")
# %%
print(f"reference: {TRAINING_DATA_PARQUET.name}")
print(f"ensemble:  {SYNTHETIC_DATA_PARQUET.name}")
summaries = [
    marginal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, attr) for attr in ATTRS
]
# %%
summary = pd.DataFrame(summaries)
summary.to_csv(OUTPUT_DIR / f"{SYNTHETIC_DATA_PARQUET.stem}_marginal_summary.csv", index=False)
print(summary.to_string(index=False))
# %%
