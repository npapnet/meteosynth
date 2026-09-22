"""
Temporal fidelity at M:N -- autocorrelation to 10 days, against the observed year-to-year band.

Reads the two files already in this folder's ``data/`` and answers the question a
knowledgeable reviewer goes to first: **the chain is first order in the hour index, so does
multi-day persistence emerge correctly, or does it decay too fast?** Nothing in the model
fits memory beyond one hour. Lag 1 is preserved by construction; lags 6-240 are not, and
are where the method either works or does not.

    M = 19 observed years (2005-2023)  vs  N = 1000 synthetic realisations

The test is specified in ``paper/metrics-prompt.md`` (Test 2). Four choices in it are not
obvious:

**The ACF is computed within a realisation, then averaged -- never on a concatenated
series.** Stringing independent realisations end to end injects a discontinuity at every
join and manufactures a decay that is an artefact of the layout.

**Both a raw and an anomaly ACF are reported, and they answer different questions.** The
raw ACF of an hourly series is dominated by the cycles in it, so it largely measures whether
the *shape* of the average day and the average year is reproduced. Subtracting the
climatology first leaves the weather, and the anomaly ACF is what actually tests the Markov
assumption. Reporting either alone invites the wrong conclusion.

**The climatology is two-dimensional and smoothed** -- a mean per (day-of-year, hour-of-day)
over a +/-15-day circular window, estimated from the observed record and subtracted from
*both* sides so each gets the same treatment. An hour-of-day mean alone would leave the
seasonal cycle in, and at lags out to 240 h that seasonal slope is not negligible. The
+/-15-day half-width matches the model's own training window, so the climatology is pooled
exactly as the generator's inputs were.

**The control band comes free here.** Each observed year gives its own ACF, so the
year-to-year spread of those 19 curves *is* the natural scale -- no splitting needed, unlike
the marginal test. A synthetic curve inside that spread is indistinguishable from a real
year; outside it is not.

Feb 29 is **kept** on the observed side, unlike ``leros_metric_marginal.py``, which drops it.
An autocorrelation needs a contiguous series far more than it needs a matching day count,
and four extra days in 166 536 move nothing. The difference between the two scripts is
deliberate, not an oversight.

Everything lands beside this file:

    <this folder>/data/    the two inputs, found by what they are rather than by name
    <this folder>/output/  temporal_acf_leros_<attr>.csv  and  .png

Standalone: imports nothing from ``examples/``. Written as ``#%%`` cells.

Runtime: a minute or two. Peak memory ~150 MB: the ensemble's values are streamed row group
by row group into one preallocated ``(N, 8760)`` array (70 MB at N = 1000), and the FFTs run
in batches so no intermediate is larger. Loading the same data through pandas would cost
several times that.

Not implemented here, and specified in the same plan: the **midnight-seam** test (does the
cross-midnight model join days without a step?) and the **calm-spell run-length**
distribution. Both are cheap additions to this file when wanted.
"""

#%%
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.fft import next_fast_len, irfft, rfft

import matplotlib.pyplot as plt

from meteosynth import MetDataset, workspace
from meteosynth.day_window import day_slots

WS = workspace(globals().get("__file__"))

#%%
# --- Configuration -------------------------------------------------------------------

#: The quantity to test. Must be a column of both inputs.
ATTR = "wind_speed"

#: Longest lag, in hours. 240 h = 10 days, which spans the synoptic band a storage study
#: cares about. The figure also zooms on 0-72 h, where the divergence usually starts.
MAX_LAG = 240
ZOOM_LAG = 72

#: Half-width of the climatology smoothing window, in days. Matched to the generator's own
#: training window so the climatology pools the record exactly as the model's inputs were.
CLIM_HALF_WIDTH = 15

#: Percentiles of the observed year-to-year band. The spread of the M per-year ACFs is the
#: control: a synthetic curve inside it is indistinguishable from a real year.
BAND_LO, BAND_HI = 5, 95

#: How many realisations to use. The mean ACF is saturated long before 1000 -- the script
#: reports the standard error so you can see that rather than take it on trust. Lower this
#: to cut memory proportionally: N x 8760 x 8 bytes.
N_USE = 1000

#: Realisations per FFT batch. Caps the transform's working set independently of N_USE.
BATCH = 100

#%%
# --- 1. Find the inputs by what they are ---------------------------------------------
# A training record carries a `meteosynth` key in its parquet footer and an ensemble
# carries `meteosynth_ensemble`, so the folder is readable without a naming convention.


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
# --- 2. The climatology: mean per (day-of-year, hour), smoothed ----------------------
# Built once from the observed record and subtracted from both sides. Slots are the
# package's own `all_leap` 366-day calendar, so Feb 29 is an ordinary slot rather than a
# special case, and the smoothing window wraps across New Year.

dataset = MetDataset.load(training_path)
observed = dataset.met_data[["year", "month", "day", "hour", ATTR]].copy()
observed["slot"] = day_slots(observed["month"].values, observed["day"].values)

raw_clim = (
    observed.groupby(["slot", "hour"])[ATTR].mean()
    .unstack("hour").reindex(index=range(1, 367), columns=range(24))
    .to_numpy()
)

slots = np.arange(366)
circular_gap = np.abs(((slots[None, :] - slots[:, None] + 183) % 366) - 183)
window = circular_gap <= CLIM_HALF_WIDTH
clim = np.vstack([np.nanmean(raw_clim[window[s]], axis=0) for s in range(366)])

print(f"\nclimatology: (366, 24), +/-{CLIM_HALF_WIDTH}-day circular smoothing")
print(f"  annual mean {np.nanmean(clim):.2f}, "
      f"seasonal range of the daily mean "
      f"{clim.mean(axis=1).min():.2f} .. {clim.mean(axis=1).max():.2f}")

#%%
# --- 3. Autocorrelation, by FFT, in batches ------------------------------------------
# One ACF per row, all lags at once. The biased estimator (dividing by T at every lag) is
# used deliberately: it is what gives a smoothly decaying, positive-definite curve, and the
# alternative inflates long lags exactly where the sample is thinnest.


def acf_rows(matrix: np.ndarray, max_lag: int, batch: int = BATCH) -> np.ndarray:
    """ACF of each row of ``matrix``, lags 0..max_lag. Shape ``(n_rows, max_lag + 1)``."""
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
    """Integral decorrelation time in hours: 1 + 2*sum(rho) up to the first zero crossing.

    Truncating at the crossing rather than at MAX_LAG matters -- past it the terms are
    noise around zero and summing them adds variance without adding signal. This is the
    number the annual-dispersion test needs to predict how far an annual mean should
    spread if the generator has no memory between synoptic blocks.
    """
    negative = np.flatnonzero(acf[1:] <= 0)
    cut = int(negative[0]) + 1 if negative.size else len(acf)
    return float(1 + 2 * acf[1:cut].sum())


#%%
# --- 4. The observed side: one contiguous series per year ----------------------------
# Each year gives its own ACF, and the spread across the M of them is the control band.

obs_raw, obs_anom = [], []
for year, group in observed.groupby("year"):
    series = group.sort_values(["month", "day", "hour"])
    values = series[ATTR].to_numpy()
    if len(values) < MAX_LAG * 4:
        print(f"  skipping {year}: only {len(values)} hours")
        continue
    baseline = clim[series["slot"].to_numpy() - 1, series["hour"].to_numpy()]
    obs_raw.append(values)
    obs_anom.append(values - baseline)

acf_obs_raw = np.vstack([acf_rows(v[None, :], MAX_LAG) for v in obs_raw])
acf_obs_anom = np.vstack([acf_rows(v[None, :], MAX_LAG) for v in obs_anom])
M = len(obs_raw)
print(f"\nobserved: {M} years, {min(len(v) for v in obs_raw)}-"
      f"{max(len(v) for v in obs_raw)} hours each (Feb 29 kept)")

#%%
# --- 5. The synthetic side: streamed into one preallocated array ---------------------
# Row group i is calendar day i+1: N x 24 rows in realisation-major hour-minor order. Each
# is written straight into its slice of an (N_USE, n_days * 24) array, so the peak is that
# array plus one day -- never the 8.76 M-row frame a full read would produce.

md = ens_file.metadata
n_days = md.num_row_groups
N_total = int(ens_meta["n_realisations"])
N = min(N_USE, N_total)

cols = [md.schema.column(i).name for i in range(md.num_columns)]
MONTH_COL, DAY_COL = cols.index("month"), cols.index("day")

series = np.empty((N, n_days * 24))
ens_slots = np.empty(n_days * 24, dtype=int)
ens_hours = np.tile(np.arange(24), n_days)

started = time.perf_counter()
for d in range(n_days):
    stats_m = md.row_group(d).column(MONTH_COL).statistics
    stats_d = md.row_group(d).column(DAY_COL).statistics
    ens_slots[d * 24:(d + 1) * 24] = day_slots([stats_m.min], [stats_d.min])[0]
    block = ens_file.read_row_group(d, columns=[ATTR])[ATTR].to_numpy().reshape(N_total, 24)
    series[:, d * 24:(d + 1) * 24] = block[:N]

print(f"synthetic: {N} realisations x {series.shape[1]} hours, "
      f"{series.nbytes / 1024**2:.0f} MB, read in {time.perf_counter() - started:.1f}s")

baseline = clim[ens_slots - 1, ens_hours]
acf_syn_raw = acf_rows(series, MAX_LAG)
acf_syn_anom = acf_rows(series - baseline, MAX_LAG)

#%%
# --- 6. What it says ------------------------------------------------------------------

lags = np.arange(MAX_LAG + 1)
table = pd.DataFrame({"lag_hours": lags})
for name, obs, syn in (
    ("raw", acf_obs_raw, acf_syn_raw),
    ("anomaly", acf_obs_anom, acf_syn_anom),
):
    table[f"obs_{name}_mean"] = obs.mean(axis=0)
    table[f"obs_{name}_p{BAND_LO}"] = np.percentile(obs, BAND_LO, axis=0)
    table[f"obs_{name}_p{BAND_HI}"] = np.percentile(obs, BAND_HI, axis=0)
    table[f"syn_{name}_mean"] = syn.mean(axis=0)
    table[f"syn_{name}_sem"] = syn.std(axis=0, ddof=1) / np.sqrt(syn.shape[0])
    table[f"{name}_inside_band"] = (
        (syn.mean(axis=0) >= np.percentile(obs, BAND_LO, axis=0))
        & (syn.mean(axis=0) <= np.percentile(obs, BAND_HI, axis=0))
    )

tau_obs = np.array([integral_time(a) for a in acf_obs_anom])
tau_syn = np.array([integral_time(a) for a in acf_syn_anom])

print(f"\n{'=' * 78}")
print(f"Temporal fidelity, {ATTR} -- M = {M} observed years vs N = {N} realisations")
print("=" * 78)
print(f"  {'lag':>6} {'observed (5-95%)':>26} {'synthetic':>12} {'inside':>8}")
for lag in (1, 3, 6, 12, 24, 48, 72, 120, 240):
    if lag > MAX_LAG:
        continue
    r = table.loc[lag]
    print(f"  {lag:4d} h  {r['obs_anomaly_mean']:7.3f} "
          f"[{r[f'obs_anomaly_p{BAND_LO}']:6.3f},{r[f'obs_anomaly_p{BAND_HI}']:6.3f}]"
          f"   {r['syn_anomaly_mean']:9.3f}   "
          f"{'yes' if r['anomaly_inside_band'] else 'NO':>6}")

inside = table["anomaly_inside_band"].mean()
print(f"\n  anomaly ACF inside the observed year-to-year band: "
      f"{table['anomaly_inside_band'].sum()}/{len(table)} lags ({inside:.0%})")
print(f"  integral decorrelation time (anomaly):")
print(f"    observed  {tau_obs.mean():6.1f} h  (year-to-year {tau_obs.min():.1f}"
      f" .. {tau_obs.max():.1f})")
print(f"    synthetic {tau_syn.mean():6.1f} h  (ratio {tau_syn.mean() / tau_obs.mean():.2f})")
print(f"  Monte-Carlo noise on the synthetic curve is negligible: largest standard error "
      f"across lags is {table['syn_anomaly_sem'].max():.4f}, so N = {N} is saturated and")
print(f"  every error bar in this figure belongs to the M = {M} observed years.")
print("\n  Lag 1 matching is not evidence -- it is fitted. Read lags 6-48 h, where the")
print("  first-order chain has to produce persistence it was never shown, and tau, which")
print("  is the number the annual-dispersion test needs to predict how far a synthetic")
print("  annual mean should spread if nothing carries between synoptic blocks.")

#%%
# --- 7. Save ---------------------------------------------------------------------------

csv_path = WS.output(f"temporal_acf_leros_{ATTR}.csv")
table.to_csv(csv_path, index=False)
print(f"\nwrote {len(table)} rows -> {csv_path}")

fig, axes = plt.subplots(2, 2, figsize=(13, 7.5), constrained_layout=True)
for col, (name, obs, syn) in enumerate((
    ("raw", acf_obs_raw, acf_syn_raw),
    ("anomaly", acf_obs_anom, acf_syn_anom),
)):
    for row, top in enumerate((MAX_LAG, ZOOM_LAG)):
        ax = axes[row, col]
        sl = slice(0, top + 1)
        ax.fill_between(
            lags[sl], np.percentile(obs, BAND_LO, axis=0)[sl],
            np.percentile(obs, BAND_HI, axis=0)[sl],
            color="0.75", alpha=0.6, label=f"observed, {BAND_LO}-{BAND_HI}% of {M} years",
        )
        ax.plot(lags[sl], obs.mean(axis=0)[sl], color="0.25", lw=1.6, label="observed mean")
        ax.plot(lags[sl], syn.mean(axis=0)[sl], color="tab:red", lw=1.6,
                label=f"synthetic mean, N={N}")
        ax.axhline(0, color="0.6", lw=0.7)
        for day in range(24, top + 1, 24):
            ax.axvline(day, color="0.9", lw=0.6, zorder=0)
        ax.set_xlim(0, top)
        ax.set_xlabel("lag (hours)")
        ax.set_ylabel("autocorrelation")
        ax.set_title(f"{name} ACF" + ("" if row == 0 else f" — zoom to {top} h"))
        if row == 0 and col == 0:
            ax.legend(fontsize=8)

fig.suptitle(
    f"Temporal fidelity, {ATTR} at Leros — {M} observed years vs {N} realisations.  "
    f"Anomaly τ: observed {tau_obs.mean():.1f} h, synthetic {tau_syn.mean():.1f} h",
    fontsize=11,
)

png_path = WS.output(f"temporal_acf_leros_{ATTR}.png")
fig.savefig(png_path, dpi=150, bbox_inches="tight", facecolor="white")
print(f"wrote figure -> {png_path}")

plt.show()

#%%
