#%%
"""Marginal fidelity: Wasserstein-1 per (month, hour-of-day) cell, against a control band.

Same test as ``year-leros/leros_metric_marginal.py`` (full-power and size-matched W1, a
control band from random half-splits of the observed years, pre-registered pass rule),
with the inputs named explicitly instead of discovered, and one function per variable
looped over all three.

Two changes from the Leros script, both about night-time irradiance:

* A cell where observed and synthetic are **the same constant** (``poa_global`` at night:
  0 on both sides) is flagged ``trivial`` and left out of the pass share. It would
  otherwise pass as 0 <= 0 and inflate the share by roughly the fraction of dark hours.
* ``w1_norm`` and ``bias_norm`` are NaN where the observed sd is zero, and the heatmap
  colour limits ignore NaN, so those cells show blank rather than breaking the scale.

Feb 29 is dropped from the observed side: the ensemble was generated without it.

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
from scipy.stats import ks_2samp, wasserstein_distance

from meteosynth import workspace

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

N_SPLITS = 100            # random half-splits of the observed years for the control band
BAND_LO, BAND_HI = 5, 95  # control band percentiles; the upper one is the pass threshold
PASS_SHARE = 0.90         # pre-registered: share of scored cells that must pass
SEED = 11                 # same splits for every variable and every ensemble
#%%

def read_ensemble_meta(path: pathlib.Path) -> dict:
    """The ``meteosynth_ensemble`` block of the parquet footer."""
    meta = pq.ParquetFile(path).schema_arrow.metadata or {}
    if b"meteosynth_ensemble" not in meta:
        raise ValueError(f"{path.name} is not a meteosynth ensemble (no footer block)")
    return json.loads(meta[b"meteosynth_ensemble"].decode("utf-8"))


def observed_cells(
    path: pathlib.Path,
    attr: str,
) -> tuple[dict[tuple[int, int], list[np.ndarray]], np.ndarray]:
    """Observed values per (month, hour) cell, split by year, Feb 29 dropped.

    Kept separated by year because the control-band halves must be whole years: days
    inside one year are not independent of each other.
    """
    df = pd.read_parquet(path, columns=["year", "month", "day", "hour", attr])
    df = df[~((df["month"] == 2) & (df["day"] == 29))]
    years = np.sort(df["year"].unique())

    cells = {}
    for (m, h), group in df.groupby(["month", "hour"], sort=True):
        by_year = group.groupby("year")[attr]
        cells[(int(m), int(h))] = [
            by_year.get_group(y).to_numpy() if y in by_year.groups else np.empty(0)
            for y in years
        ]
    return cells, years


def synthetic_cells(path: pathlib.Path, attr: str, n_real: int) -> dict[tuple[int, int], np.ndarray]:
    """Synthetic values per (month, hour) cell, read one calendar month at a time.

    Row group i is calendar day i+1, ``n_real x 24`` rows realisation-major; its month
    comes from the footer statistics, so the mapping costs no data read.
    """
    ens_file = pq.ParquetFile(path)
    md = ens_file.metadata
    month_col = [md.schema.column(i).name for i in range(md.num_columns)].index("month")
    rg_month = np.array([
        md.row_group(i).column(month_col).statistics.min for i in range(md.num_row_groups)
    ])

    cells = {}
    for m in range(1, 13):
        days = [
            ens_file.read_row_group(int(g), columns=[attr])[attr].to_numpy().reshape(n_real, 24)
            for g in np.flatnonzero(rg_month == m)
        ]
        stacked = np.concatenate(days, axis=0)          # (n_days * n_real, 24)
        for h in range(24):
            cells[(m, h)] = stacked[:, h]
    return cells

#%%
def score_cells(
    obs_cells: dict[tuple[int, int], list[np.ndarray]],
    syn_cells: dict[tuple[int, int], np.ndarray],
    n_splits: int = N_SPLITS,
    seed: int = SEED,
) -> pd.DataFrame:
    """Full-power W1, size-matched W1 and the control band, one row per cell.

    Per random half-split of the years:
      control = W1(half A observed, half B observed)             -- two REAL samples
      matched = W1(half A observed, synthetic subsample of |B|)  -- same footing
    """
    rng = np.random.default_rng(seed)
    M = len(next(iter(obs_cells.values())))
    half = M // 2
    splits = [rng.permutation(M) for _ in range(n_splits)]

    rows = []
    for (m, h), by_year in obs_cells.items():
        obs_all = np.concatenate(by_year)
        syn_all = syn_cells[(m, h)]
        obs_sd = obs_all.std(ddof=1)
        syn_sd = syn_all.std(ddof=1)

        control = np.empty(n_splits)
        matched = np.empty(n_splits)
        for s, order in enumerate(splits):
            a = np.concatenate([by_year[i] for i in order[:half]])
            b = np.concatenate([by_year[i] for i in order[half:]])
            control[s] = wasserstein_distance(a, b)
            sub = rng.choice(syn_all, size=len(b), replace=False)
            matched[s] = wasserstein_distance(a, sub)

        w1 = wasserstein_distance(obs_all, syn_all)
        lo, hi = np.percentile(control, [BAND_LO, BAND_HI])
        matched_med = float(np.median(matched))
        trivial = obs_sd == 0 and syn_sd == 0 and w1 == 0

        rows.append({
            "month": m, "hour": h,
            "n_obs": obs_all.size, "n_syn": syn_all.size,
            "obs_mean": obs_all.mean(), "obs_sd": obs_sd,
            "syn_mean": syn_all.mean(), "syn_sd": syn_sd,
            "w1": w1,
            "w1_norm": w1 / obs_sd if obs_sd > 0 else np.nan,
            "bias_norm": (syn_all.mean() - obs_all.mean()) / obs_sd if obs_sd > 0 else np.nan,
            "sd_ratio": syn_sd / obs_sd if obs_sd > 0 else np.nan,
            "w1_matched": matched_med,
            "control_lo": lo, "control_hi": hi,
            "control_median": float(np.median(control)),
            "trivial": trivial,
            "passes": matched_med <= hi,
            "ks_d": ks_2samp(obs_all, syn_all).statistic,
        })
    return pd.DataFrame(rows).sort_values(["month", "hour"]).reset_index(drop=True)


def print_report(table: pd.DataFrame, attr: str, M: int, N: int) -> None:
    """Summary distances, the pass share over scored cells, and the five worst cells."""
    unit = ATTRS_UNITS[attr]
    scored = table[~table["trivial"]]
    share = scored["passes"].mean()

    print(f"\n{'=' * 78}")
    print(f"Marginal fidelity, {attr} -- M = {M} observed years vs N = {N} realisations")
    print("=" * 78)
    print(f"  W1 / observed sd      median {scored['w1_norm'].median():.3f}   "
          f"p90 {scored['w1_norm'].quantile(0.90):.3f}   max {scored['w1_norm'].max():.3f}")
    print(f"  W1 ({unit})".ljust(24) + f"median {scored['w1'].median():.3f}   "
          f"p90 {scored['w1'].quantile(0.90):.3f}   max {scored['w1'].max():.3f}")
    print(f"  control band ({unit})".ljust(24) + f"median {scored['control_median'].median():.3f}   "
          f"upper {scored['control_hi'].median():.3f}")
    print(f"  mean bias / sd        median {scored['bias_norm'].median():+.3f}   "
          f"range {scored['bias_norm'].min():+.3f} .. {scored['bias_norm'].max():+.3f}")
    print(f"  sd ratio              median {scored['sd_ratio'].median():.3f}   "
          f"range {scored['sd_ratio'].min():.3f} .. {scored['sd_ratio'].max():.3f}")
    print(f"\n  trivial cells (same constant both sides, not scored): {table['trivial'].sum()}")
    print(f"  cells within the control band: {scored['passes'].sum()}/{len(scored)} "
          f"({share:.1%})  ->  {'PASS' if share >= PASS_SHARE else 'FAIL'} "
          f"at the {PASS_SHARE:.0%} rule")

    worst = scored.nlargest(5, "w1_norm")[
        ["month", "hour", "w1", "w1_norm", "bias_norm", "sd_ratio", "control_hi", "passes"]
    ]
    print("\n  worst five cells by W1 / sd:")
    print(worst.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))

#%%
def plot_marginal(table: pd.DataFrame, attr: str, M: int, N: int) -> plt.Figure:
    """Month x hour heatmaps of W1/sd and bias/sd, cells outside the band marked."""
    grid_w1 = table.pivot(index="month", columns="hour", values="w1_norm").to_numpy()
    grid_bias = table.pivot(index="month", columns="hour", values="bias_norm").to_numpy()
    fails = table.assign(fail=~table["passes"] & ~table["trivial"]).pivot(
        index="month", columns="hour", values="fail").to_numpy()
    bias_lim = np.nanmax(np.abs(grid_bias))
    share = table.loc[~table["trivial"], "passes"].mean()

    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6), constrained_layout=True)
    for ax, grid, title, cmap, kw in (
        (axes[0], grid_w1, "W₁ / observed sd", "viridis", {"vmin": 0}),
        (axes[1], grid_bias, "mean bias / observed sd", "RdBu_r",
         {"vmin": -bias_lim, "vmax": bias_lim}),
    ):
        im = ax.imshow(grid, aspect="auto", cmap=cmap, origin="lower",
                       extent=[-0.5, 23.5, 0.5, 12.5], **kw)
        ys, xs = np.nonzero(fails)
        ax.plot(xs, ys + 1, "x", color="white", markersize=5, markeredgewidth=1.2,
                label="outside control band")
        ax.set_xlabel("hour of day")
        ax.set_ylabel("month")
        ax.set_yticks(range(1, 13))
        ax.set_title(title)
        fig.colorbar(im, ax=ax)
        if len(xs):
            ax.legend(loc="upper right", fontsize=8, framealpha=0.85)

    fig.suptitle(
        f"Marginal fidelity, {ATTRS_LABELS[attr]} at {SITE} — {M} observed years vs "
        f"{N} realisations ({share:.0%} of scored cells within the year-split control band)",
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
    N = int(meta["n_realisations"])

    started = time.perf_counter()
    obs, years = observed_cells(training_path, attr)
    syn = synthetic_cells(synthetic_path, attr, N)
    table = score_cells(obs, syn)
    M = len(years)
    print(f"{attr}: {len(table)} cells x {N_SPLITS} splits in "
          f"{time.perf_counter() - started:.1f}s")
    print_report(table, attr, M, N)

    attr_dir = output_dir / attr
    attr_dir.mkdir(parents=True, exist_ok=True)
    stem = attr_dir / f"{synthetic_path.stem}-{attr}_marginal_w1"
    table.to_csv(stem.with_suffix(".csv"), index=False)
    fig = plot_marginal(table, attr, M, N)
    fig.savefig(stem.with_suffix(".png"), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {stem}.csv / .png")

    scored = table[~table["trivial"]]
    return {
        "ensemble": synthetic_path.stem, "window_n_days": meta["window_n_days"],
        "attr": attr, "M": M, "N": N,
        "cells_scored": len(scored), "cells_pass": int(scored["passes"].sum()),
        "pass_share": scored["passes"].mean(),
        "verdict": "PASS" if scored["passes"].mean() >= PASS_SHARE else "FAIL",
        "w1_norm_median": scored["w1_norm"].median(),
        "bias_norm_median": scored["bias_norm"].median(),
        "sd_ratio_median": scored["sd_ratio"].median(),
    }

#%%
# --- Example One-Line Invocation ---
# summary = marginal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, "wind_speed")
# %%
print(f"training: {TRAINING_DATA_PARQUET.name}")
print(f"ensemble: {SYNTHETIC_DATA_PARQUET.name}")
summaries = [
    marginal_fidelity(TRAINING_DATA_PARQUET, SYNTHETIC_DATA_PARQUET, attr) for attr in ATTRS
]
# %%
summary = pd.DataFrame(summaries)
summary.to_csv(OUTPUT_DIR / f"{SYNTHETIC_DATA_PARQUET.stem}_marginal_summary.csv", index=False)
print(summary.to_string(index=False))
# %%
