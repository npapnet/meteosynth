"""
Marginal fidelity at M:N -- Wasserstein-1 per (month, hour-of-day) cell, with a control band.

Reads the two files already in this folder's ``data/`` and answers one question: **does the
synthetic ensemble reproduce the observed distribution of wind speed, hour by hour, month
by month?** It generates nothing; the ensemble comes from ``leros_year_ensemble.py``.

    M = 19 observed years (2005-2023)  vs  N = 1000 synthetic realisations

The test is specified in ``paper/metrics-prompt.md`` (Test 3). Three choices in it are not
obvious and all three change the answer:

**Wasserstein-1, not Kolmogorov-Smirnov.** W1 carries physical units -- the number is in
m/s and can be read without a table -- is more sensitive in the tails, and is comparatively
stable against sample size. A KS *p*-value at n = 570 against m = 30 000 measures N, not
fidelity. The KS statistic is reported anyway, as an effect size, and never its *p*.

**A raw distance means nothing on its own.** W1 = 0.4 m/s is neither good nor bad until you
know how far apart *two real samples* of the same climate are. So the observed years are
repeatedly split into two halves and W1 computed between them; the 5th-95th percentile of
that is the natural scale, and the pass rule is pre-registered against its upper end.

**Two W1 numbers, for two different jobs.** The *full-power* one uses all 570 observed and
all ~30 000 synthetic values and is the best estimate of the true distance -- it is the
number to quote. The *size-matched* one compares a synthetic subsample of the same size as
half the observed record against the other half, so it sits on identical footing to the
control band -- it is the number to judge. Quoting the first against the second's threshold
would be comparing two different measurements.

Feb 29 is dropped from the observed side, because the ensemble was generated with
``include_feb29=False`` and does not have it. (``leros_metric_temporal.py`` deliberately
*keeps* it -- there, contiguity of the series matters more than matching the day count.)

Everything lands beside this file:

    <this folder>/data/    the two inputs, found by what they are rather than by name
    <this folder>/output/  marginal_w1_leros_<attr>.csv  and  .png

Standalone: imports nothing from ``examples/``. Written as ``#%%`` cells.

Runtime: a couple of minutes, nearly all of it in the control-band splits. Memory stays
under ~100 MB -- the ensemble is read one calendar month at a time, never as a whole.
"""

#%%
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import ks_2samp, wasserstein_distance

import matplotlib.pyplot as plt

from meteosynth import MetDataset, workspace

WS = workspace(globals().get("__file__"))

#%%
# --- Configuration -------------------------------------------------------------------

#: The quantity to test. Must be a column of both inputs.
ATTR = "wind_speed"

#: How many random half-splits of the observed years build the control band. The band
#: settles well before 100; more only smooths its edges.
N_SPLITS = 100

#: Percentiles of the control band. The upper one is the pass threshold.
BAND_LO, BAND_HI = 5, 95

#: A cell passes when its size-matched W1 is at or below the band's upper end. An attribute
#: passes overall when at least this share of its cells do. Pre-registered: fixed here,
#: before any number is produced, so the threshold cannot be chosen to fit the result.
PASS_SHARE = 0.90

#: Root entropy for the splits and the synthetic subsampling, so the run is reproducible.
SEED = 11

#%%
# --- 1. Find the inputs by what they are ---------------------------------------------
# Not by filename. A training record carries a `meteosynth` key in its parquet footer and
# an ensemble carries `meteosynth_ensemble`, so the folder can be read without a naming
# convention -- and without opening either file.


def _footer_keys(path):
    return set((pq.ParquetFile(path).schema_arrow.metadata or {}).keys())


training_path = ensemble_path = None
for candidate in sorted(WS.data_dir.glob("*.parquet")):
    keys = _footer_keys(candidate)
    if b"meteosynth_ensemble" in keys:
        ensemble_path = candidate
    elif b"meteosynth" in keys:
        training_path = candidate

if training_path is None or ensemble_path is None:
    raise FileNotFoundError(
        f"need both a training record and an ensemble in {WS.data_dir}. "
        f"Found training={training_path}, ensemble={ensemble_path}. "
        f"Run leros_year_ensemble.py first."
    )

ens_file = pq.ParquetFile(ensemble_path)
ens_meta = json.loads(
    ens_file.schema_arrow.metadata[b"meteosynth_ensemble"].decode("utf-8")
)

print(f"training: {training_path.name}")
print(f"ensemble: {ensemble_path.name}")
print(f"  attrs={ens_meta['attrs']}  N={ens_meta['n_realisations']}  "
      f"seed={ens_meta['seed']}  window=+/-{ens_meta['window_n_days']}d")

if ATTR not in ens_meta["attrs"]:
    raise ValueError(
        f"this ensemble holds {ens_meta['attrs']}, not {ATTR!r}. Either pick one of those "
        f"or point at the three-attribute ensemble from use_cases/year-metrics/."
    )

#%%
# --- 2. The observed side ------------------------------------------------------------

dataset = MetDataset.load(training_path)
observed = dataset.met_data[["year", "month", "day", "hour", ATTR]].copy()

n_feb29 = int(((observed["month"] == 2) & (observed["day"] == 29)).sum())
observed = observed[~((observed["month"] == 2) & (observed["day"] == 29))]

YEARS = np.sort(observed["year"].unique())
M = len(YEARS)
print(f"\nobserved: {dataset.describe_time_range()}, M = {M} years, "
      f"{len(observed):,} rows after dropping {n_feb29 // 24} Feb-29 days")

# Per (month, hour) cell, the observed values split by year -- a list of M arrays. Keeping
# them separated by year is what makes the control band possible: the halves have to be
# whole years, because days inside one year are not independent of each other.
cells: dict[tuple[int, int], list[np.ndarray]] = {}
for (m, h), group in observed.groupby(["month", "hour"], sort=True):
    by_year = group.groupby("year")[ATTR]
    cells[(int(m), int(h))] = [
        by_year.get_group(y).to_numpy() if y in by_year.groups else np.empty(0)
        for y in YEARS
    ]

print(f"cells: {len(cells)} (12 months x 24 hours), "
      f"~{len(cells[(1, 0)][0]) * M:.0f} observed values each")

#%%
# --- 3. The synthetic side, one month at a time --------------------------------------
# Row group i of the ensemble is calendar day i+1: N_REALISATIONS x 24 rows, in
# realisation-major hour-minor order. Which month each row group belongs to is in the
# parquet footer statistics, so the mapping costs no data read at all.
#
# A month is ~31 x 1000 x 24 = 744 000 values, about 6 MB. The whole ensemble would be
# 8.76 M values; it is never held.

md = ens_file.metadata
MONTH_COL = [md.schema.column(i).name for i in range(md.num_columns)].index("month")
rg_month = np.array([
    md.row_group(i).column(MONTH_COL).statistics.min for i in range(md.num_row_groups)
])
N = int(ens_meta["n_realisations"])

synthetic: dict[tuple[int, int], np.ndarray] = {}
started = time.perf_counter()
for m in range(1, 13):
    groups = np.flatnonzero(rg_month == m)
    days = [
        ens_file.read_row_group(int(g), columns=[ATTR])[ATTR].to_numpy().reshape(N, 24)
        for g in groups
    ]
    stacked = np.concatenate(days, axis=0)          # (n_days * N, 24)
    for h in range(24):
        synthetic[(m, h)] = stacked[:, h]
    print(f"  month {m:2d}: {len(groups):2d} days -> {stacked.shape[0]:,} values per hour")

print(f"read in {time.perf_counter() - started:.1f}s")

#%%
# --- 4. The control band, and the two W1 numbers --------------------------------------
# For each random half-split of the years:
#   control  = W1(half A observed, half B observed)     -- how far apart two REAL samples are
#   matched  = W1(half A observed, synthetic subsample of |half B|)  -- same footing
# and separately, once, the full-power W1 against everything.

rng = np.random.default_rng(SEED)
half = M // 2
splits = [rng.permutation(M) for _ in range(N_SPLITS)]

rows = []
started = time.perf_counter()
for (m, h), by_year in cells.items():
    obs_all = np.concatenate(by_year)
    syn_all = synthetic[(m, h)]
    obs_sd = obs_all.std(ddof=1)

    control = np.empty(N_SPLITS)
    matched = np.empty(N_SPLITS)
    for s, order in enumerate(splits):
        a = np.concatenate([by_year[i] for i in order[:half]])
        b = np.concatenate([by_year[i] for i in order[half:]])
        control[s] = wasserstein_distance(a, b)
        sub = rng.choice(syn_all, size=len(b), replace=False)
        matched[s] = wasserstein_distance(a, sub)

    w1 = wasserstein_distance(obs_all, syn_all)
    ks = ks_2samp(obs_all, syn_all)
    lo, hi = np.percentile(control, [BAND_LO, BAND_HI])
    matched_med = float(np.median(matched))

    rows.append({
        "month": m, "hour": h,
        "n_obs": obs_all.size, "n_syn": syn_all.size,
        "obs_mean": obs_all.mean(), "obs_sd": obs_sd,
        "syn_mean": syn_all.mean(), "syn_sd": syn_all.std(ddof=1),
        "w1": w1,
        "w1_norm": w1 / obs_sd,
        "bias_norm": (syn_all.mean() - obs_all.mean()) / obs_sd,
        "sd_ratio": syn_all.std(ddof=1) / obs_sd,
        "w1_matched": matched_med,
        "control_lo": lo, "control_hi": hi,
        "control_median": float(np.median(control)),
        "passes": matched_med <= hi,
        "ks_d": ks.statistic,
    })

table = pd.DataFrame(rows).sort_values(["month", "hour"]).reset_index(drop=True)
print(f"computed {len(table)} cells x {N_SPLITS} splits in "
      f"{time.perf_counter() - started:.1f}s")

#%%
# --- 5. What it says ------------------------------------------------------------------

share = table["passes"].mean()
verdict = "PASS" if share >= PASS_SHARE else "FAIL"

print(f"\n{'=' * 78}")
print(f"Marginal fidelity, {ATTR} -- M = {M} observed years vs N = {N} realisations")
print("=" * 78)
print(f"  W1 / observed sd      median {table['w1_norm'].median():.3f}   "
      f"p90 {table['w1_norm'].quantile(0.90):.3f}   max {table['w1_norm'].max():.3f}")
print(f"  W1 (m/s)              median {table['w1'].median():.3f}   "
      f"p90 {table['w1'].quantile(0.90):.3f}   max {table['w1'].max():.3f}")
print(f"  control band (m/s)    median {table['control_median'].median():.3f}   "
      f"upper {table['control_hi'].median():.3f}")
print(f"  mean bias / sd        median {table['bias_norm'].median():+.3f}   "
      f"range {table['bias_norm'].min():+.3f} .. {table['bias_norm'].max():+.3f}")
print(f"  sd ratio              median {table['sd_ratio'].median():.3f}   "
      f"range {table['sd_ratio'].min():.3f} .. {table['sd_ratio'].max():.3f}")
print(f"\n  cells within the control band: {table['passes'].sum()}/{len(table)} "
      f"({share:.1%})  ->  {verdict} at the {PASS_SHARE:.0%} rule")

worst = table.nlargest(5, "w1_norm")[
    ["month", "hour", "w1", "w1_norm", "bias_norm", "sd_ratio", "control_hi", "passes"]
]
print("\n  worst five cells by W1 / sd:")
print(worst.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))

print("\n  Read `bias_norm` and `sd_ratio` next to `w1_norm`: W1 conflates a shift in level")
print("  with a change in shape, and those are different defects. A cell with w1_norm high")
print("  and bias_norm near zero is a spread or skew problem, not a calibration one.")

#%%
# --- 6. Save ---------------------------------------------------------------------------

csv_path = WS.output(f"marginal_w1_leros_{ATTR}.csv")
table.to_csv(csv_path, index=False)
print(f"\nwrote {len(table)} rows -> {csv_path}")

grid_w1 = table.pivot(index="month", columns="hour", values="w1_norm").to_numpy()
grid_bias = table.pivot(index="month", columns="hour", values="bias_norm").to_numpy()
fails = table.pivot(index="month", columns="hour", values="passes").to_numpy() == False

fig, axes = plt.subplots(1, 2, figsize=(14, 4.6), constrained_layout=True)
for ax, grid, title, cmap, kw in (
    (axes[0], grid_w1, "W₁ / observed sd", "viridis", {"vmin": 0}),
    (axes[1], grid_bias, "mean bias / observed sd", "RdBu_r",
     {"vmin": -np.abs(grid_bias).max(), "vmax": np.abs(grid_bias).max()}),
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
    f"Marginal fidelity, {ATTR} at Leros — {M} observed years vs {N} realisations "
    f"({share:.0%} of cells within the year-split control band)",
    fontsize=11,
)

png_path = WS.output(f"marginal_w1_leros_{ATTR}.png")
fig.savefig(png_path, dpi=150, bbox_inches="tight", facecolor="white")
print(f"wrote figure -> {png_path}")

plt.show()

#%%
