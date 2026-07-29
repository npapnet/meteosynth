"""
Compare a synthetic day against the cloud of days actually observed on that date.

The three ``use_cases/day/day_envelope_*.py`` scripts ask the same question of three
different quantities -- *does a synthetic 21 May look like a real 21 May?* -- so the
machinery for answering it lives here and each script keeps only what is specific to
its variable.

What "the observed cloud" means here is two nested things, and the distinction matters:

* the **exact-date days** -- every 21 May in the record, one line each. Eleven years
  gives eleven of them: an honest sample of what that date does, but far too small to
  read a percentile off.
* the **pooled window** -- every day within +/- ``n_days`` of 21 May, across all years.
  That is a few hundred days, enough for a percentile envelope, and it is (near enough)
  the same data the generator was trained on. A synthetic day should sit inside *this*
  envelope; the exact-date lines are there to show that the envelope is not wider than
  the date itself.

A synthetic day matching the envelope is not a forecast of any particular 21 May. It is
the claim the generator actually makes: *this is a plausible draw from that date's
climate*.
"""

from __future__ import annotations

from typing import Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patheffects

from meteosynth import DayWindowGenerator, MetDataset, convert_to_daily_wide

HOURS = np.arange(24)

#: Two entities, two hues: everything observed is blue, everything synthetic is orange.
#: Lighter blue steps are still "observed" -- shade carries emphasis, hue carries
#: identity, so the pair survives a colour-blind reader. Validated (CVD dE 24.7,
#: normal-vision dE 33.6, both >= 3:1 on the surface).
OBSERVED = "#2a78d6"
OBSERVED_LIGHT = "#86b6ef"
OBSERVED_BAND = "#cde2fb"
SYNTHETIC = "#eb6834"
SURFACE = "#fcfcfb"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"


def apply_chart_style() -> None:
    """Set the rcParams the example figures are drawn with. Idempotent."""
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_SECONDARY,
            "axes.titlecolor": INK,
            "axes.grid": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "text.color": INK,
            "xtick.color": INK_SECONDARY,
            "ytick.color": INK_SECONDARY,
            "legend.frameon": False,
            "font.size": 10,
        }
    )


def day_matrix(
    ds: MetDataset, attr: str, month: int, day: int, n_days: int = 0
) -> pd.DataFrame:
    """
    Observed days as a days-by-hours matrix, for one calendar day or a window round it.

    ``n_days=0`` selects that calendar day alone -- one row per year in the record.
    ``n_days=7`` pools every day within a week of it, across all years.

    Returns
    -------
    pd.DataFrame
        Indexed by ``YYYYMMDD``, with integer hour columns 0-23.
    """
    subset = ds.get_day_window_subset(month, day, n_days=n_days)
    return convert_to_daily_wide(subset, value_col=attr).reindex(columns=range(24))


def synthetic_ensemble(
    generator: DayWindowGenerator, month: int, day: int, n: int, seed: int = 42
) -> np.ndarray:
    """
    Draw ``n`` independent synthetic days for one calendar date.

    Every day is a *separate* call, so each one starts from its own draw of that date's
    fitted initial distribution pi(x0) rather than continuing the previous day -- which
    is what makes these draws independent samples of the same date rather than a
    366-day walk. One generator drives them all, so the ensemble is reproducible as a
    whole without any two members sharing a seed.

    Returns
    -------
    np.ndarray
        Shape ``(n, 24)``.
    """
    rng = np.random.default_rng(seed)
    day_generator = generator.for_day(month, day)
    return np.vstack([day_generator.gen_day(rng=rng) for _ in range(n)])


def _percentiles(matrix, lo: float, hi: float):
    values = np.asarray(matrix, dtype=float)
    return (
        np.nanpercentile(values, lo, axis=0),
        np.nanpercentile(values, 50, axis=0),
        np.nanpercentile(values, hi, axis=0),
    )


def plot_day_envelope(
    observed_pool: pd.DataFrame,
    observed_exact: pd.DataFrame,
    synthetic: np.ndarray,
    *,
    attr: str,
    unit: str,
    date_label: str,
    site_label: str,
    window_days: int,
    aggregate: str = "mean",
    aggregate_scale: float = 1.0,
    aggregate_unit: Optional[str] = None,
    n_shown: int = 6,
) -> plt.Figure:
    """
    Two panels: the diurnal envelope, and the distribution of the daily aggregate.

    Left, the hour-by-hour comparison -- observed percentile band, the individual
    observed days for that exact date, and the synthetic ensemble's own band and median.
    Right, one number per day (total or mean, per ``aggregate``), which is what an
    energy calculation actually consumes: a synthetic day can trace a plausible shape
    and still deliver the wrong quantity.

    Returns the figure; the caller decides whether to save or show it.
    """
    apply_chart_style()
    fig, (ax, ax_agg) = plt.subplots(
        1, 2, figsize=(13.5, 5.4), gridspec_kw={"width_ratios": [2.1, 1]}
    )

    obs_lo, obs_med, obs_hi = _percentiles(observed_pool, 10, 90)
    syn_lo, syn_med, syn_hi = _percentiles(synthetic, 10, 90)

    # --- left: diurnal envelope -------------------------------------------------
    ax.fill_between(
        HOURS, obs_lo, obs_hi, color=OBSERVED_BAND, zorder=1,
        label=f"observed p10-p90 (+/-{window_days} d pool, n={len(observed_pool)})",
    )
    for i, (_, row) in enumerate(observed_exact.iterrows()):
        ax.plot(
            HOURS, row.to_numpy(), color=OBSERVED_LIGHT, lw=0.9, alpha=0.75, zorder=2,
            label=f"observed {date_label}, each year (n={len(observed_exact)})" if i == 0 else None,
        )

    for i, profile in enumerate(synthetic[:n_shown]):
        ax.plot(HOURS, profile, color=SYNTHETIC, lw=1.0, alpha=0.35, zorder=3,
                label=f"synthetic days (showing {min(n_shown, len(synthetic))} of {len(synthetic)})" if i == 0 else None)
    # Unfilled envelope rather than a second wash: two translucent fills stacked read as
    # a third colour that means nothing.
    ax.plot(HOURS, syn_lo, color=SYNTHETIC, lw=1.2, ls=":", zorder=5)
    ax.plot(HOURS, syn_hi, color=SYNTHETIC, lw=1.2, ls=":", zorder=5,
            label="synthetic p10-p90")
    ax.plot(HOURS, syn_med, color=SYNTHETIC, lw=2.5, zorder=6, label="synthetic median",
            path_effects=[patheffects.withStroke(linewidth=4.5, foreground=SURFACE)])
    # Drawn last, and dashed: when the generator is doing well the two medians sit on
    # top of each other, and whichever is painted second is the one you can see.
    ax.plot(HOURS, obs_med, color=OBSERVED, lw=2.2, ls=(0, (5, 4)), zorder=7,
            label="observed median",
            path_effects=[patheffects.withStroke(linewidth=4.2, foreground=SURFACE)])

    peak = int(np.nanargmax(syn_med))
    ax.annotate(
        f"synthetic median peak\n{syn_med[peak]:.1f} {unit} at {peak:02d}:00",
        xy=(peak, syn_med[peak]), xytext=(12, 16), textcoords="offset points",
        color=SYNTHETIC, fontsize=9, va="bottom", zorder=8,
        bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.85, pad=2),
        arrowprops=dict(arrowstyle="-", color=SYNTHETIC, lw=1),
    )

    ax.set_xlim(0, 23)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("Hour of day")
    ax.set_ylabel(f"{attr} ({unit})")
    ax.set_title(f"{date_label} at {site_label}: synthetic days against the observed cloud",
                 fontsize=12, loc="left")
    # Below the axes: six entries in a corner would sit on top of the data, and which
    # corner is free depends on the variable.
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.13), ncols=3, fontsize=8.5,
              columnspacing=1.4, handlelength=1.8)

    # --- right: daily aggregate -------------------------------------------------
    aggregate_unit = aggregate_unit or unit
    obs_agg = _daily_aggregate(observed_exact.to_numpy(), aggregate) * aggregate_scale
    pool_agg = _daily_aggregate(observed_pool.to_numpy(), aggregate) * aggregate_scale
    syn_agg = _daily_aggregate(synthetic, aggregate) * aggregate_scale

    bins = np.histogram_bin_edges(np.concatenate([pool_agg, syn_agg]), bins=24)
    ax_agg.hist(pool_agg, bins=bins, color=OBSERVED_BAND, zorder=1, density=True,
                label=f"observed, +/-{window_days} d pool")
    # A step outline rather than a second translucent fill: overlapping washes blend
    # into a third colour that means nothing.
    ax_agg.hist(syn_agg, bins=bins, color=SYNTHETIC, histtype="step", lw=2, zorder=3,
                density=True, label="synthetic ensemble")
    for i, value in enumerate(obs_agg):
        ax_agg.axvline(value, color=OBSERVED, lw=1.4, ymax=0.1, zorder=4,
                       label=f"observed {date_label} (one per year)" if i == 0 else None)

    ax_agg.set_xlabel(f"daily {aggregate} ({aggregate_unit})")
    ax_agg.set_ylabel("density")
    ax_agg.set_title("Daily aggregate: one number per day", fontsize=12, loc="left")
    ax_agg.legend(loc="upper left", bbox_to_anchor=(0, -0.13), ncols=1, fontsize=8.5)

    fig.tight_layout()
    return fig


def _daily_aggregate(matrix: np.ndarray, aggregate: str) -> np.ndarray:
    """Collapse a days-by-hours matrix to one value per day."""
    values = np.asarray(matrix, dtype=float)
    if aggregate == "sum":
        return np.nansum(values, axis=1)
    if aggregate == "mean":
        return np.nanmean(values, axis=1)
    if aggregate == "max":
        return np.nanmax(values, axis=1)
    raise ValueError(f"aggregate must be 'sum', 'mean' or 'max', got {aggregate!r}")


def report_day_stats(
    observed_pool: pd.DataFrame,
    observed_exact: pd.DataFrame,
    synthetic: np.ndarray,
    *,
    attr: str,
    unit: str,
    date_label: str,
    aggregate: str = "mean",
    aggregate_scale: float = 1.0,
    aggregate_unit: Optional[str] = None,
) -> pd.DataFrame:
    """
    Print the numbers behind the picture, and return them as a frame.

    Three questions, in the order they are worth asking:

    1. **Shape** -- does the synthetic median trace the observed diurnal cycle?
       Reported as the correlation of the two 24-hour medians.
    2. **Spread** -- is the synthetic ensemble as wide as the weather? Coverage is the
       share of synthetic hourly values falling inside the observed p10-p90 band; a
       well-calibrated ensemble sits near 80%, well above means it is too narrow and
       well below means too wide.
    3. **Quantity** -- does the daily aggregate land in the right place? This is the
       number an energy model consumes, and it is the one that can be wrong while the
       shape looks right.
    """
    aggregate_unit = aggregate_unit or unit
    pool = observed_pool.to_numpy(dtype=float)
    obs_med = np.nanpercentile(pool, 50, axis=0)
    obs_lo = np.nanpercentile(pool, 10, axis=0)
    obs_hi = np.nanpercentile(pool, 90, axis=0)
    syn_med = np.nanpercentile(synthetic, 50, axis=0)

    inside = ((synthetic >= obs_lo) & (synthetic <= obs_hi)).mean()
    inside_full = (
        (synthetic >= np.nanmin(pool, axis=0)) & (synthetic <= np.nanmax(pool, axis=0))
    ).mean()
    shape = float(np.corrcoef(obs_med, syn_med)[0, 1])

    obs_agg = _daily_aggregate(observed_exact.to_numpy(), aggregate) * aggregate_scale
    pool_agg = _daily_aggregate(pool, aggregate) * aggregate_scale
    syn_agg = _daily_aggregate(synthetic, aggregate) * aggregate_scale

    print(f"\n  {date_label} -- {attr} ({unit})")
    print(f"    observed on {date_label:>10} : {len(observed_exact):4d} days "
          f"(one per year in the record)")
    print(f"    observed in the pool       : {len(observed_pool):4d} days")
    print(f"    synthetic drawn            : {len(synthetic):4d} days")
    print(f"\n    1. shape   median-profile correlation : {shape:6.3f}   (1.0 = same diurnal cycle)")
    print(f"    2. spread  synthetic hours inside observed p10-p90 : {inside:6.1%}   "
          f"(~80% = calibrated)")
    print(f"               synthetic hours inside observed min-max : {inside_full:6.1%}")
    print(f"    3. quantity  daily {aggregate} ({aggregate_unit}):")
    print(f"               {'':22}{'mean':>9}{'sd':>9}{'min':>9}{'max':>9}")
    rows = {
        f"observed {date_label}": obs_agg,
        "observed pool": pool_agg,
        "synthetic": syn_agg,
    }
    for label, values in rows.items():
        print(f"               {label:<22}{np.mean(values):9.2f}{np.std(values):9.2f}"
              f"{np.min(values):9.2f}{np.max(values):9.2f}")

    within = np.mean((syn_agg >= pool_agg.min()) & (syn_agg <= pool_agg.max()))
    bias = np.mean(syn_agg) / np.mean(pool_agg) - 1
    print(f"               synthetic days inside the observed range : {within:6.1%}")
    print(f"               bias against the pool it was trained on  : {bias:+6.1%}")

    return pd.DataFrame(
        {
            "metric": [
                "shape_correlation", "coverage_p10_p90", "coverage_min_max",
                f"observed_{aggregate}_mean", f"pool_{aggregate}_mean",
                f"synthetic_{aggregate}_mean", "synthetic_within_observed_range",
                "aggregate_bias_vs_pool",
            ],
            "value": [
                shape, inside, inside_full, np.mean(obs_agg), np.mean(pool_agg),
                np.mean(syn_agg), within, bias,
            ],
        }
    )


def ensemble_frame(synthetic: np.ndarray, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Lay a ``(n_days, 24)`` ensemble out as a saveable frame, one row per day."""
    frame = pd.DataFrame(synthetic, columns=columns or [f"h{h:02d}" for h in HOURS])
    frame.index.name = "realisation"
    return frame
