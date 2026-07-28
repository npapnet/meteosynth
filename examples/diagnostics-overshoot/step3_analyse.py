"""
Step 3 -- read the raw files and score the synthetic sample against its training pool.

One question per configuration: **is the synthetic sample distributed like the observed
days the model was fitted to?** Because the model was fitted to exactly that pool, the
pool is a known target rather than an estimate of one -- so only the synthetic side is
resampled, and there is no reference to choose.

Reads **only** ``results/raw/``, never in-memory state from step 2, so anything checked
by hand against those CSVs is a check against exactly what this saw.

Run::

    uv run python examples/diagnostics-overshoot/step3_analyse.py

Writes ``results/summary_statistics.csv``, ``summary_consistency.csv``,
``summary_controls.csv`` and ``summary_window.csv``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from tqdm import tqdm

import config as cfg

# Ratios of these are reported. The two share statistics are handled separately: a ratio
# of two small proportions is unstable, and the quantity of interest is the share itself.
RATIO_STATISTICS = (
    "sum_mean", "sum_sd", "sum_p10", "sum_p50", "sum_p90",
    "max_mean", "max_sd", "max_p90",
)
SHARE_STATISTICS = ("low_abs_share", "low_rel_share")

#: Printed in this order. The flag marks the statistics carrying the signal -- the lower
#: tail, which the omnibus tests cannot see.
REPORT_ORDER = (
    ("sum_mean", "mean of daily sum", False),
    ("sum_sd", "sd of daily sum", False),
    ("sum_p10", "P10 of daily sum", True),
    ("sum_p50", "P50 of daily sum", False),
    ("sum_p90", "P90 of daily sum", False),
    ("low_abs_share", f"share below {cfg.LOW_TAIL_ABS:g} kWh/m2", True),
    ("low_rel_share", f"share below {cfg.LOW_TAIL_REL:g}x obs median", True),
    ("max_mean", "mean of daily max", False),
    ("max_sd", "sd of daily max", False),
    ("max_p90", "P90 of daily max", False),
)


# ======================================================================================
# The statistics
# ======================================================================================


def estimators(sums: np.ndarray, maxima: np.ndarray, rel_threshold: float) -> dict:
    """
    Every statistic, computed on one sample.

    ``rel_threshold`` is derived from the **observed** median and passed in rather than
    recomputed, so it stays fixed across bootstrap resamples of the synthetic sample: a
    moving threshold would measure the threshold's noise rather than the model's.
    """
    return {
        "sum_mean": float(np.mean(sums)),
        "sum_sd": float(np.std(sums, ddof=1)),
        "sum_p10": float(np.percentile(sums, 10)),
        "sum_p50": float(np.percentile(sums, 50)),
        "sum_p90": float(np.percentile(sums, 90)),
        "max_mean": float(np.mean(maxima)),
        "max_sd": float(np.std(maxima, ddof=1)),
        "max_p90": float(np.percentile(maxima, 90)),
        "low_abs_share": float(np.mean(sums < cfg.LOW_TAIL_ABS)),
        "low_rel_share": float(np.mean(sums < rel_threshold)),
    }


def _bootstrap_estimators(
    sums: np.ndarray,
    maxima: np.ndarray,
    rel_threshold: float,
    n_boot: int,
    seed: int,
    chunk: int = 500,
) -> dict[str, np.ndarray]:
    """
    Resample the synthetic sample ``n_boot`` times and recompute every statistic.

    Whole rows are resampled, so a day's sum and its maximum stay paired. Chunked because
    the index matrix at n_boot = 10 000 and n = 1000 is ten million entries per array.
    """
    rng = np.random.default_rng(seed)
    n = sums.size
    out: dict[str, list[np.ndarray]] = {}

    for start in range(0, n_boot, chunk):
        size = min(chunk, n_boot - start)
        idx = rng.integers(0, n, size=(size, n))
        s, m = sums[idx], maxima[idx]

        block = {
            "sum_mean": s.mean(axis=1),
            "sum_sd": s.std(axis=1, ddof=1),
            "sum_p10": np.percentile(s, 10, axis=1),
            "sum_p50": np.percentile(s, 50, axis=1),
            "sum_p90": np.percentile(s, 90, axis=1),
            "max_mean": m.mean(axis=1),
            "max_sd": m.std(axis=1, ddof=1),
            "max_p90": np.percentile(m, 90, axis=1),
            "low_abs_share": (s < cfg.LOW_TAIL_ABS).mean(axis=1),
            "low_rel_share": (s < rel_threshold).mean(axis=1),
        }
        for key, values in block.items():
            out.setdefault(key, []).append(values)

    return {key: np.concatenate(parts) for key, parts in out.items()}


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Ratio, or NaN when the denominator is zero -- which happens for an empty tail."""
    return float(numerator / denominator) if denominator > 0 else float("nan")


def score(
    syn_sums: np.ndarray,
    syn_maxima: np.ndarray,
    obs_sums: np.ndarray,
    obs_maxima: np.ndarray,
    seed: int,
    n_boot: int = cfg.N_BOOTSTRAP,
) -> pd.DataFrame:
    """
    Score one synthetic sample against its training pool.

    Returns one row per statistic: the observed value, the synthetic value, the ratio (or
    the share itself, for the two tail statistics), a 95 % bootstrap interval from
    resampling the synthetic sample, and whether that interval excludes the observed
    value.
    """
    rel_threshold = cfg.LOW_TAIL_REL * float(np.median(obs_sums))

    observed = estimators(obs_sums, obs_maxima, rel_threshold)
    synthetic = estimators(syn_sums, syn_maxima, rel_threshold)
    booted = _bootstrap_estimators(syn_sums, syn_maxima, rel_threshold, n_boot, seed)

    rows = []
    for name in RATIO_STATISTICS + SHARE_STATISTICS:
        obs_value, syn_value = observed[name], synthetic[name]
        draws = booted[name]

        if name in SHARE_STATISTICS:
            # Compared on their own scale: the interval is on the synthetic share, and
            # the test is whether it covers the observed share.
            lo, hi = np.percentile(draws, [2.5, 97.5])
            if syn_value == 0.0:
                # A bootstrap of zero events resamples zeros forever and returns the
                # degenerate interval [0, 0], which "excludes" every observed share
                # however small the sample. The rule of three gives the honest 95 %
                # upper bound for no events in n trials.
                hi = max(float(hi), 3.0 / syn_sums.size)
            excludes = not (lo <= obs_value <= hi)
            effect, effect_lo, effect_hi = syn_value, float(lo), float(hi)
            ratio = _safe_ratio(syn_value, obs_value)
        else:
            ratios = draws / obs_value if obs_value > 0 else np.full_like(draws, np.nan)
            lo, hi = np.percentile(ratios, [2.5, 97.5])
            excludes = not (lo <= 1.0 <= hi)
            effect = _safe_ratio(syn_value, obs_value)
            effect_lo, effect_hi = float(lo), float(hi)
            ratio = effect

        rows.append(
            {
                "statistic": name,
                "observed": obs_value,
                "synthetic": syn_value,
                "ratio": ratio,
                "effect": effect,
                "ci_lo": effect_lo,
                "ci_hi": effect_hi,
                "excludes_null": bool(excludes),
                # A tail statistic against an empty observed tail can detect an excess
                # but not a deficit, so it is not evidence either way about the deficit
                # being tested. June and September have no overcast days at all, and
                # counting them as "did not confirm" would understate the finding.
                "informative": bool(obs_value > 0) if name in SHARE_STATISTICS else True,
                "direction": int(np.sign(syn_value - obs_value)),
                "rel_threshold_kwh_m2": rel_threshold,
            }
        )

    ks = stats.ks_2samp(syn_sums, obs_sums)
    rows.append(
        {
            "statistic": "ks_daily_sum",
            "observed": float("nan"),
            "synthetic": float(ks.statistic),
            "ratio": float("nan"),
            "effect": float(ks.pvalue),
            "ci_lo": float("nan"),
            "ci_hi": float("nan"),
            # Reported, never relied on: KS has been seen accepting (p = 0.55) a sample
            # with a fourfold overcast-day deficit. Flagged False so it cannot be counted
            # into the consistency rule by accident.
            "excludes_null": False,
            "informative": False,
            "direction": 0,
            "rel_threshold_kwh_m2": rel_threshold,
        }
    )
    return pd.DataFrame(rows)


# ======================================================================================
# Window structure -- the CHORE-1 by-product
# ======================================================================================


def seasonal_share(observed: pd.DataFrame) -> float:
    """
    Fraction of the pool's variance explained by position within the window.

    A quadratic in the **signed** offset from the centre day. This is the cost of pooling
    a window rather than a date -- 10.4 % at +/-15 on 21 March. What CHORE-1 asks is
    whether that is an acceptable price for the sample size it buys.
    """
    offsets = observed["days_from_centre"].to_numpy(dtype=float)
    sums = observed["sum_kwh_m2"].to_numpy(dtype=float)
    fitted = np.polynomial.Polynomial.fit(offsets, sums, deg=2)(offsets)
    total = float(np.var(sums))
    return float(np.var(fitted) / total) if total > 0 else float("nan")


# ======================================================================================
# Controls
# ======================================================================================


def run_controls(
    syn_sums: np.ndarray,
    syn_maxima: np.ndarray,
    obs_sums: np.ndarray,
    obs_maxima: np.ndarray,
    seed: int,
) -> pd.DataFrame:
    """
    Null and positive controls, on one configuration.

    * **Null** -- the synthetic sample is replaced by a resample of the observed pool, so
      every interval must cover the observed value. If one does not, the harness carries
      a bias of its own and nothing it says about the model can be trusted.
    * **Positive** -- the synthetic sample is inflated by 10 %, so the mean ratio must
      come back at 1.10 with an interval excluding 1. This is what says the instrument
      can see the effect it is looking for.
    """
    # Drawn at the size of the synthetic sample, so the control is checked at exactly
    # the resolution the real comparison runs at.
    rng = np.random.default_rng(seed + 1)
    idx = rng.integers(0, obs_sums.size, size=syn_sums.size)

    null = score(obs_sums[idx], obs_maxima[idx], obs_sums, obs_maxima, seed=seed + 2)
    null.insert(0, "control", "null")

    positive = score(syn_sums * 1.10, syn_maxima * 1.10, obs_sums, obs_maxima, seed=seed + 3)
    positive.insert(0, "control", "positive")

    return pd.concat([null, positive], ignore_index=True)


# ======================================================================================
# Reporting
# ======================================================================================


def _format_row(row: pd.Series) -> str:
    """One statistic, as a line of the per-configuration table."""
    mark = "  <--" if row["excludes_null"] else ""
    if row["statistic"] in SHARE_STATISTICS:
        return (
            f"    {row['label']:<32} {row['synthetic'] * 100:6.2f} % vs "
            f"{row['observed'] * 100:5.2f} % obs      "
            f"[{row['ci_lo'] * 100:5.2f}, {row['ci_hi'] * 100:5.2f}]{mark}"
        )
    return (
        f"    {row['label']:<32} {row['effect']:6.3f}   "
        f"({row['synthetic']:8.3f} vs {row['observed']:8.3f})   "
        f"[{row['ci_lo']:5.3f}, {row['ci_hi']:5.3f}]{mark}"
    )


def main() -> None:
    cfg.ensure_dirs()

    index = pd.read_csv(cfg.RAW_DIR / "config_index.csv")
    observed = pd.read_csv(cfg.RAW_DIR / "observed_daily.csv")
    synthetic = pd.read_csv(cfg.RAW_DIR / "synthetic_daily.csv")

    labels = {name: label for name, label, _ in REPORT_ORDER}
    signals = {name for name, _, is_signal in REPORT_ORDER if is_signal}

    all_stats: list[pd.DataFrame] = []
    all_controls: list[pd.DataFrame] = []
    window_rows: list[dict] = []

    print("=" * 94)
    print("SYNTHETIC SAMPLE vs THE TRAINING POOL IT WAS FITTED TO")
    print("  ratio = synthetic / observed;  interval = 95 % bootstrap, synthetic side only")
    print("  '<--' marks an interval that excludes the observed value")
    print("=" * 94)

    # Each configuration is scored three times over -- the result, then the null and
    # positive controls -- so the bar counts configurations, not bootstraps.
    scoring = tqdm(total=len(index), desc="scoring configurations", unit="cfg",
                   dynamic_ncols=True, leave=False, disable=None)

    for row in index.itertuples():
        scoring.set_postfix_str(row.config_id)
        obs = observed[observed["config_id"] == row.config_id]
        syn = synthetic[synthetic["config_id"] == row.config_id]

        scored = score(
            syn["sum_kwh_m2"].to_numpy(),
            syn["max_w_m2"].to_numpy(),
            obs["sum_kwh_m2"].to_numpy(),
            obs["max_w_m2"].to_numpy(),
            seed=int(row.seed),
        )
        scored.insert(0, "config_id", row.config_id)
        scored["month"], scored["day"] = row.month, row.day
        scored["n_days"], scored["bandwidth"] = row.n_days, row.bandwidth
        scored["is_anchor"] = row.is_anchor
        all_stats.append(scored)

        share = seasonal_share(obs)
        window_rows.append(
            {
                "config_id": row.config_id,
                "month": row.month,
                "day": row.day,
                "n_days": row.n_days,
                "bandwidth": row.bandwidth,
                "m": row.m,
                "obs_cv": row.obs_cv,
                "seasonal_share_of_variance": share,
                "kde_factor_h12": row.kde_factor_h12,
            }
        )

        print(
            f"\n{row.config_id}   {row.month:02d}-{row.day:02d}, +/-{row.n_days} d, "
            f"bandwidth {row.bandwidth}"
            f"{'   [ANCHOR -- the earlier pass configuration]' if row.is_anchor else ''}"
        )
        print(f"    m = {row.m} observed days, n = {row.n} synthetic;  "
              f"observed CV {row.obs_cv * 100:.1f} %;  "
              f"KDE factor {row.kde_factor_h12:.3f};  "
              f"seasonal variance {share * 100:.1f} %")

        printable = scored[scored["statistic"] != "ks_daily_sum"].copy()
        printable = printable.set_index("statistic").loc[list(labels)].reset_index()
        printable["label"] = printable["statistic"].map(labels)
        for _, stat_row in printable.iterrows():
            print(_format_row(stat_row))

        ks_row = scored[scored["statistic"] == "ks_daily_sum"].iloc[0]
        print(f"    {'KS on daily sums (not relied on)':<32} p = {ks_row['effect']:.3f}")

        controls = run_controls(
            syn["sum_kwh_m2"].to_numpy(),
            syn["max_w_m2"].to_numpy(),
            obs["sum_kwh_m2"].to_numpy(),
            obs["max_w_m2"].to_numpy(),
            seed=int(row.seed),
        )
        controls.insert(0, "config_id", row.config_id)
        all_controls.append(controls)
        scoring.update(1)

    scoring.close()
    statistics = pd.concat(all_stats, ignore_index=True)
    controls = pd.concat(all_controls, ignore_index=True)
    window = pd.DataFrame(window_rows)

    # ----------------------------------------------------------------------------------
    # Controls
    # ----------------------------------------------------------------------------------
    print("\n" + "=" * 94)
    print("CONTROLS")
    print("=" * 94)

    null = controls[(controls["control"] == "null") & (controls["statistic"] != "ks_daily_sum")]
    null_failures = null[null["excludes_null"]]
    print(f"  null control     : {len(null) - len(null_failures)}/{len(null)} statistics "
          f"cover the observed value")
    if len(null_failures):
        for _, bad in null_failures.iterrows():
            print(f"      FAIL {bad['config_id']:<20} {bad['statistic']:<16} "
                  f"effect {bad['effect']:.3f} [{bad['ci_lo']:.3f}, {bad['ci_hi']:.3f}]")
    else:
        print("      -> the harness reports no difference where there is none")

    # The injection multiplies the sample, so the control's mean ratio is the baseline
    # ratio times 1.10 -- not 1.10 itself. Reporting the lift is what makes it readable.
    positive = controls[
        (controls["control"] == "positive") & (controls["statistic"] == "sum_mean")
    ].set_index("config_id")
    baseline = statistics[statistics["statistic"] == "sum_mean"].set_index("config_id")
    lift = (positive["effect"] / baseline["effect"].reindex(positive.index)).mean()
    detected = int(positive["excludes_null"].sum())
    print(f"  positive control : +10 % injection recovered as a lift of {lift:.3f}, "
          f"detected in {detected}/{len(positive)} configurations")

    # ----------------------------------------------------------------------------------
    # Anchor
    # ----------------------------------------------------------------------------------
    anchor = statistics[statistics["is_anchor"]]
    if not anchor.empty:
        print("\n" + "=" * 94)
        print("ANCHOR -- against the earlier pass's figures for this configuration")
        print("=" * 94)
        got = {
            "mean_ratio": float(anchor[anchor["statistic"] == "sum_mean"]["effect"].iloc[0]),
            "sd_ratio": float(anchor[anchor["statistic"] == "sum_sd"]["effect"].iloc[0]),
            "low_abs_share_syn": float(
                anchor[anchor["statistic"] == "low_abs_share"]["synthetic"].iloc[0]
            ),
        }
        for key, expected in cfg.ANCHOR_EXPECTED.items():
            print(f"  {key:<20} before {expected:8.4f}   now {got[key]:8.4f}   "
                  f"delta {got[key] - expected:+.4f}")
        print("  (a different seed, so agreement is expected within Monte-Carlo error, "
              "not to the digit)")

    # ----------------------------------------------------------------------------------
    # Consistency across dates -- what replaces a multiplicity correction
    # ----------------------------------------------------------------------------------
    primary = statistics[
        (~statistics["is_anchor"]) & (statistics["statistic"] != "ks_daily_sum")
    ]
    primary = primary[primary["informative"]]
    consistency = (
        primary.groupby(["bandwidth", "statistic"])
        .agg(
            dates=("config_id", "nunique"),
            excluding=("excludes_null", "sum"),
            direction_sum=("direction", "sum"),
            mean_effect=("effect", "mean"),
            min_effect=("effect", "min"),
            max_effect=("effect", "max"),
        )
        .reset_index()
    )
    # A finding counts when every informative date excludes *and* they agree on which
    # way. Four dates disagreeing in sign is not one effect measured four times.
    consistency["agreed_direction"] = (
        consistency["direction_sum"].abs() == consistency["dates"]
    )
    consistency["consistent"] = (
        (consistency["excluding"] == consistency["dates"]) & consistency["agreed_direction"]
    )

    print("\n" + "=" * 94)
    print("CONSISTENCY  (a finding counts when every informative date excludes, same sign)")
    print("  a tail statistic against an empty observed tail is not informative and is excluded")
    print("=" * 94)
    for bandwidth, block in consistency.groupby("bandwidth"):
        print(f"\n  bandwidth {bandwidth}")
        block = block.set_index("statistic").reindex(list(labels)).dropna(subset=["dates"]).reset_index()
        for _, stat_row in block.iterrows():
            name = stat_row["statistic"]
            flag = "CONSISTENT" if stat_row["consistent"] else ""
            if stat_row["excluding"] == stat_row["dates"] and not stat_row["agreed_direction"]:
                flag = "signs disagree"
            signal = " *" if name in signals else "  "
            print(f"    {labels.get(name, name):<32}{signal} "
                  f"{int(stat_row['excluding'])}/{int(stat_row['dates'])} dates exclude   "
                  f"effect {stat_row['min_effect']:.3f}-{stat_row['max_effect']:.3f}   {flag}")

    # ----------------------------------------------------------------------------------
    # Window structure
    # ----------------------------------------------------------------------------------
    print("\n" + "=" * 94)
    print("WINDOW STRUCTURE  (CHORE-1 by-product)")
    print("=" * 94)
    for _, w in window.drop_duplicates(subset=["month", "day", "n_days"]).iterrows():
        print(f"  {int(w['month']):02d}-{int(w['day']):02d}  +/-{int(w['n_days']):2d} d   "
              f"m = {int(w['m']):3d}   observed CV {w['obs_cv'] * 100:5.1f} %   "
              f"seasonal share of pool variance {w['seasonal_share_of_variance'] * 100:5.1f} %")

    statistics.to_csv(cfg.RESULTS_DIR / "summary_statistics.csv", index=False)
    consistency.to_csv(cfg.RESULTS_DIR / "summary_consistency.csv", index=False)
    controls.to_csv(cfg.RESULTS_DIR / "summary_controls.csv", index=False)
    window.to_csv(cfg.RESULTS_DIR / "summary_window.csv", index=False)

    print("\nWrote summary_statistics.csv, summary_consistency.csv, summary_controls.csv "
          "and summary_window.csv")


if __name__ == "__main__":
    main()
