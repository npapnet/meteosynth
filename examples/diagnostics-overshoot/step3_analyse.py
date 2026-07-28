"""
Step 3 -- read the raw files back and test them.

Reads **only** ``results/raw/``, never in-memory state from step 2, so anything checked
by hand against those CSVs is a check against exactly what this saw.

Produces, per configuration and reference:

* the mean deviation and a **two-sample bootstrap** interval for it -- each iteration
  resamples the synthetic totals *and* the observed values behind the reference, so the
  interval carries both sources of noise rather than treating the reference as exact;
* Welch's t and a permutation test as cross-checks;
* the **minimum detectable effect** at 80 % power, which is what says whether a
  non-significant cell is evidence of absence or merely an underpowered one;
* distribution comparisons -- KS, Anderson-Darling, variance ratio.

Run::

    uv run python examples/diagnostics-overshoot/step3_analyse.py

Note on power: the plan called for "achieved power". Post-hoc power computed from the
*observed* effect is a known statistical trap -- it is a monotone restatement of the
p-value and says nothing extra. The **minimum detectable effect** is the honest version
of the same question: *what size of bias could this run have found?* That is what is
reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

import config as cfg

ALPHA = 0.05
Z_ALPHA = stats.norm.ppf(1 - ALPHA / 2)   # 1.96
Z_POWER = stats.norm.ppf(0.80)            # 0.84


# ======================================================================================
# Reference estimators, resampled
# ======================================================================================


def _reference_from(observed: pd.DataFrame, reference: str) -> float:
    """Recompute one reference from an observed sample -- the same maths as step 2."""
    totals = observed["total_kwh_m2"].to_numpy(dtype=float)
    if reference == "pool_mean":
        return float(totals.mean())
    if reference == "centre_mean":
        return float(totals[observed["is_centre"].to_numpy(dtype=bool)].mean())
    if reference == "detrended_centre":
        offsets = observed["days_from_centre"].to_numpy(dtype=float)
        return float(np.polynomial.Polynomial.fit(offsets, totals, deg=2)(0.0))
    raise ValueError(f"unknown reference {reference!r}")


def _observed_sample(observed: pd.DataFrame, reference: str) -> np.ndarray:
    """The observed values a reference actually rests on, for two-sample comparisons."""
    if reference == "centre_mean":
        return observed.loc[observed["is_centre"], "total_kwh_m2"].to_numpy(dtype=float)
    return observed["total_kwh_m2"].to_numpy(dtype=float)


def bootstrap_deviation(
    synthetic: np.ndarray,
    observed: pd.DataFrame,
    reference: str,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    """
    Two-sample bootstrap interval and p-value for the mean deviation.

    Each iteration resamples **both** the ``n`` synthetic daily totals and the observed
    rows behind the reference, recomputing the reference from the resampled observations
    before forming the deviation. Holding the reference fixed instead would report an
    interval that is too tight -- badly so at small ``k``, where ``centre_mean`` rests on
    as few as two observed days.

    Returns ``(ci_low, ci_high, p_value)``; the p-value is the two-sided bootstrap
    proportion of resamples falling on the wrong side of zero.
    """
    n = synthetic.size
    m = len(observed)
    means = np.empty(n_boot)

    # Resampling detrended_centre means refitting the quadratic each iteration, which is
    # the point: its uncertainty comes from the fit, not from a plain mean.
    offsets = observed["days_from_centre"].to_numpy(dtype=float)
    totals = observed["total_kwh_m2"].to_numpy(dtype=float)
    centre = observed["is_centre"].to_numpy(dtype=bool)

    for i in range(n_boot):
        syn_mean = synthetic[rng.integers(0, n, n)].mean()
        idx = rng.integers(0, m, m)

        if reference == "pool_mean":
            ref = totals[idx].mean()
        elif reference == "centre_mean":
            centre_totals = totals[centre]
            ref = centre_totals[rng.integers(0, centre_totals.size, centre_totals.size)].mean()
        else:
            ref = np.polynomial.Polynomial.fit(offsets[idx], totals[idx], deg=2)(0.0)

        means[i] = syn_mean / ref - 1.0

    low, high = np.percentile(means, [100 * ALPHA / 2, 100 * (1 - ALPHA / 2)])
    tail = min((means <= 0).mean(), (means >= 0).mean())
    return float(low), float(high), float(min(1.0, 2 * tail))


def permutation_p(
    synthetic: np.ndarray, observed: np.ndarray, n_perm: int, rng: np.random.Generator
) -> float:
    """Two-sided permutation p-value on the difference of means."""
    pooled = np.concatenate([synthetic, observed])
    n = synthetic.size
    observed_diff = abs(synthetic.mean() - observed.mean())
    count = 0
    for _ in range(n_perm):
        shuffled = rng.permutation(pooled)
        if abs(shuffled[:n].mean() - shuffled[n:].mean()) >= observed_diff:
            count += 1
    return (count + 1) / (n_perm + 1)


def minimum_detectable_effect(
    synthetic: np.ndarray, observed: np.ndarray, reference: float
) -> float:
    """
    Smallest true bias this configuration could detect at 80 % power, as a fraction.

    Two-sample form, so it includes the uncertainty of the reference -- which is what
    makes it collapse so badly at small ``k`` when the reference is the centre day.
    """
    se = np.sqrt(synthetic.var(ddof=1) / synthetic.size + observed.var(ddof=1) / observed.size)
    return float((Z_ALPHA + Z_POWER) * se / reference)


def holm(p_values: pd.Series) -> pd.Series:
    """Holm-Bonferroni adjusted p-values, order preserved."""
    order = np.argsort(p_values.to_numpy())
    n = len(p_values)
    adjusted = np.empty(n)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (n - rank) * p_values.iloc[idx])
        adjusted[idx] = min(1.0, running)
    return pd.Series(adjusted, index=p_values.index)


# ======================================================================================
# Per-configuration analysis
# ======================================================================================


def analyse(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One row per (configuration, reference), plus a distribution table per config."""
    index = raw["config_index"].set_index("config_id")
    references = raw["references"].set_index(["config_id", "reference"])

    rows: list[dict] = []
    distribution_rows: list[dict] = []

    for config_id, meta in index.iterrows():
        observed = raw["observed_daily"].query("config_id == @config_id")
        synthetic = raw["synthetic_daily"].query("config_id == @config_id")
        syn_totals = synthetic["total_kwh_m2"].to_numpy(dtype=float)

        # Seeded from the configuration's own seed so the analysis is reproducible and
        # independent of the order configurations are processed in.
        rng = np.random.default_rng(int(meta["seed"]) + 7919)

        for reference in cfg.REFERENCES:
            ref_value = float(references.loc[(config_id, reference), "value_kwh_m2"])
            ref_m = int(references.loc[(config_id, reference), "m"])
            obs_sample = _observed_sample(observed, reference)

            deviations = synthetic[f"dev_{reference}"].to_numpy(dtype=float)
            ci_low, ci_high, p_boot = bootstrap_deviation(
                syn_totals, observed, reference, cfg.N_BOOTSTRAP, rng
            )

            # Welch and permutation compare the two samples directly, so they are only
            # meaningful where the reference IS a plain mean of an observed sample.
            if reference == "detrended_centre":
                p_welch = np.nan
                p_perm = np.nan
            else:
                p_welch = float(stats.ttest_ind(syn_totals, obs_sample, equal_var=False).pvalue)
                p_perm = permutation_p(syn_totals, obs_sample, cfg.N_PERMUTATION, rng)

            rows.append(
                {
                    "config_id": config_id,
                    "k": int(meta["k"]),
                    "draw": int(meta["draw"]),
                    "reference": reference,
                    "reference_kwh_m2": ref_value,
                    "reference_m": ref_m,
                    "n": int(meta["n"]),
                    "synthetic_mean_kwh_m2": float(syn_totals.mean()),
                    "mean_dev": float(deviations.mean()),
                    "sd_dev": float(deviations.std(ddof=1)),
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "excludes_zero": bool(ci_low > 0 or ci_high < 0),
                    "p_bootstrap": p_boot,
                    "p_welch": p_welch,
                    "p_permutation": p_perm,
                    "mde_80pc": minimum_detectable_effect(syn_totals, obs_sample, ref_value),
                }
            )

        # Distribution comparison uses the pooled window, the only observed sample large
        # enough for a shape test to mean anything.
        pool = _observed_sample(observed, "pool_mean")
        ks = stats.ks_2samp(syn_totals, pool)
        with np.errstate(all="ignore"):
            ad = stats.anderson_ksamp([syn_totals, pool])
        var_ratio = float(syn_totals.var(ddof=1) / pool.var(ddof=1))
        boot_ratio = np.array([
            syn_totals[rng.integers(0, syn_totals.size, syn_totals.size)].var(ddof=1)
            / pool[rng.integers(0, pool.size, pool.size)].var(ddof=1)
            for _ in range(2000)
        ])
        distribution_rows.append(
            {
                "config_id": config_id,
                "k": int(meta["k"]),
                "draw": int(meta["draw"]),
                "n_synthetic": syn_totals.size,
                "m_observed": pool.size,
                "syn_mean": float(syn_totals.mean()),
                "obs_mean": float(pool.mean()),
                "syn_sd": float(syn_totals.std(ddof=1)),
                "obs_sd": float(pool.std(ddof=1)),
                "syn_skew": float(stats.skew(syn_totals)),
                "obs_skew": float(stats.skew(pool)),
                "syn_p10": float(np.percentile(syn_totals, 10)),
                "obs_p10": float(np.percentile(pool, 10)),
                "syn_p50": float(np.percentile(syn_totals, 50)),
                "obs_p50": float(np.percentile(pool, 50)),
                "syn_p90": float(np.percentile(syn_totals, 90)),
                "obs_p90": float(np.percentile(pool, 90)),
                "ks_stat": float(ks.statistic),
                "ks_p": float(ks.pvalue),
                "ad_stat": float(ad.statistic),
                "ad_p": float(ad.pvalue),
                "var_ratio": var_ratio,
                "var_ratio_lo": float(np.percentile(boot_ratio, 2.5)),
                "var_ratio_hi": float(np.percentile(boot_ratio, 97.5)),
            }
        )

    per_config = pd.DataFrame(rows)
    # Holm across the family actually run, applied within each reference: the four sizes
    # x five draws are one family per reference, not one family overall.
    per_config["p_holm"] = np.nan
    for reference, group in per_config.groupby("reference"):
        per_config.loc[group.index, "p_holm"] = holm(group["p_bootstrap"])

    return per_config, pd.DataFrame(distribution_rows)


def hourly_bias(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per-hour relative bias, synthetic mean against observed window mean."""
    syn = (
        raw["synthetic_hourly"]
        .groupby(["config_id", "hour"])[f"{cfg.ATTR}_w_m2"].mean()
        .rename("synthetic_mean")
    )
    obs = (
        raw["observed_hourly"]
        .groupby(["config_id", "hour"])[f"{cfg.ATTR}_w_m2"].mean()
        .rename("observed_mean")
    )
    frame = pd.concat([syn, obs], axis=1).reset_index()
    frame["bias"] = np.where(
        frame["observed_mean"] > 1.0,  # below 1 W/m2 a ratio is noise, not a bias
        frame["synthetic_mean"] / frame["observed_mean"] - 1.0,
        np.nan,
    )
    meta = raw["config_index"][["config_id", "k", "draw"]]
    return frame.merge(meta, on="config_id")


def reference_gap(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """How far apart the three reference estimators are -- the window-mean bias."""
    wide = raw["references"].pivot(
        index="config_id", columns="reference", values="value_kwh_m2"
    )
    meta = raw["config_index"].set_index("config_id")[["k", "draw"]]
    out = meta.join(wide)
    out["pool_vs_detrended"] = out["pool_mean"] / out["detrended_centre"] - 1.0
    out["centre_vs_detrended"] = out["centre_mean"] / out["detrended_centre"] - 1.0
    return out.reset_index()


# ======================================================================================
# Reporting
# ======================================================================================


def _pct(x: float) -> str:
    return "     n/a" if pd.isna(x) else f"{100 * x:+7.2f}%"


def report(per_config: pd.DataFrame, distribution: pd.DataFrame, gap: pd.DataFrame) -> None:
    primary = per_config.query("reference == @cfg.PRIMARY_REFERENCE")

    print("\n" + "=" * 100)
    print(f"MEAN DEVIATION BY TRAINING-SET SIZE   reference = {cfg.PRIMARY_REFERENCE}, "
          f"n = {int(primary['n'].iloc[0])} per configuration")
    print("=" * 100)
    print(f"{'k (yr)':>7} {'draw':>5} {'mean dev':>9} {'95% CI':>19} {'excl 0':>7} "
          f"{'p(boot)':>9} {'p(holm)':>9} {'MDE@80%':>9}")
    print("-" * 100)
    for _, row in primary.sort_values(["k", "draw"], ascending=[False, True]).iterrows():
        ci = f"[{100*row['ci_low']:+6.2f},{100*row['ci_high']:+6.2f}]%"
        print(f"{row['k']:>7.0f} {row['draw']:>5.0f} {_pct(row['mean_dev']):>9} {ci:>19} "
              f"{'YES' if row['excludes_zero'] else '  .':>7} "
              f"{row['p_bootstrap']:>9.4f} {row['p_holm']:>9.4f} {_pct(row['mde_80pc']):>9}")

    print("\n" + "=" * 100)
    print("AGGREGATED BY SIZE   (mean across draws; spread is the between-draw sd)")
    print("=" * 100)
    print(f"{'k (yr)':>7} {'draws':>6} {'mean dev':>9} {'sd across draws':>16} "
          f"{'min':>9} {'max':>9} {'n excl 0':>9}")
    print("-" * 100)
    for k, group in primary.groupby("k", sort=False):
        sd = group["mean_dev"].std(ddof=1) if len(group) > 1 else np.nan
        sd_text = "        n/a" if pd.isna(sd) else f"{100 * sd:10.2f}%"
        print(f"{k:>7} {len(group):>6} {_pct(group['mean_dev'].mean()):>9} {sd_text:>16} "
              f"{_pct(group['mean_dev'].min()):>9} {_pct(group['mean_dev'].max()):>9} "
              f"{int(group['excludes_zero'].sum()):>6}/{len(group)}")

    print("\n" + "=" * 100)
    print("THE SAME QUESTION, THREE REFERENCES   (mean deviation, averaged across draws)")
    print("=" * 100)
    pivot = per_config.pivot_table(index="k", columns="reference", values="mean_dev")
    print(f"{'k (yr)':>7} " + " ".join(f"{ref:>18}" for ref in cfg.REFERENCES))
    print("-" * 100)
    for k in sorted(pivot.index, reverse=True):
        print(f"{k:>7} " + " ".join(f"{_pct(pivot.loc[k, ref]):>18}" for ref in cfg.REFERENCES))

    print("\n" + "=" * 100)
    print("REFERENCE GAP   how much the choice of reference alone moves the answer")
    print("=" * 100)
    print(f"{'k (yr)':>7} {'pool vs detrended':>19} {'centre vs detrended':>21}")
    print("-" * 100)
    for k, group in gap.groupby("k", sort=False):
        print(f"{k:>7} {_pct(group['pool_vs_detrended'].mean()):>19} "
              f"{_pct(group['centre_vs_detrended'].mean()):>21}")

    print("\n" + "=" * 100)
    print("DISTRIBUTION COMPARISON   synthetic vs the pooled observed window")
    print("=" * 100)
    print(f"{'k (yr)':>7} {'syn mean':>9} {'obs mean':>9} {'syn sd':>8} {'obs sd':>8} "
          f"{'var ratio':>10} {'95% CI':>16} {'KS p':>8} {'AD p':>8}")
    print("-" * 100)
    for k, group in distribution.groupby("k", sort=False):
        ci = f"[{group['var_ratio_lo'].mean():.2f},{group['var_ratio_hi'].mean():.2f}]"
        print(f"{k:>7} {group['syn_mean'].mean():>9.3f} {group['obs_mean'].mean():>9.3f} "
              f"{group['syn_sd'].mean():>8.3f} {group['obs_sd'].mean():>8.3f} "
              f"{group['var_ratio'].mean():>10.3f} {ci:>16} "
              f"{group['ks_p'].mean():>8.4f} {group['ad_p'].mean():>8.4f}")


def main() -> None:
    cfg.ensure_dirs()
    raw = {
        "config_index": pd.read_csv(cfg.RAW_DIR / "config_index.csv"),
        "observed_daily": pd.read_csv(cfg.RAW_DIR / "observed_daily_totals.csv"),
        "synthetic_daily": pd.read_csv(cfg.RAW_DIR / "synthetic_daily_totals.csv"),
        "observed_hourly": pd.read_csv(cfg.RAW_DIR / "observed_hourly.csv"),
        "synthetic_hourly": pd.read_csv(cfg.RAW_DIR / "synthetic_hourly.csv"),
        "references": pd.read_csv(cfg.RAW_DIR / "references.csv"),
    }

    print(f"Analysing {len(raw['config_index'])} configurations, "
          f"{cfg.N_BOOTSTRAP:,} bootstrap resamples each...")
    per_config, distribution = analyse(raw)
    gap = reference_gap(raw)
    hourly = hourly_bias(raw)

    per_config.to_csv(cfg.RESULTS_DIR / "summary_by_config.csv", index=False)
    distribution.to_csv(cfg.RESULTS_DIR / "summary_distribution.csv", index=False)
    gap.to_csv(cfg.RESULTS_DIR / "summary_references.csv", index=False)
    hourly.to_csv(cfg.RESULTS_DIR / "summary_hourly_bias.csv", index=False)

    report(per_config, distribution, gap)

    print("\nWrote:")
    for name in ("summary_by_config", "summary_distribution",
                 "summary_references", "summary_hourly_bias"):
        print(f"  results/{name}.csv")


if __name__ == "__main__":
    main()
