"""
Step 4 -- figures, drawn from the summary tables step 3 wrote.

Reads ``results/summary_*.csv`` only, so a figure can be redrawn without re-running
anything. Four figures, each answering one question:

1. ``deviation_vs_years``    -- does the bias depend on how many years were trained on?
2. ``distribution_comparison`` -- do synthetic and observed daily totals share a shape?
3. ``hourly_bias``           -- where in the day does any bias accumulate?
4. ``reference_gap``         -- how much does the choice of reference alone move the answer?

Palette and chart style come from ``examples/tools/envelope.py``, which already carries
a CVD-validated observed/synthetic pair. Training-set size is **ordinal**, so it is
encoded on a single-hue light-to-dark ramp from that same blue rather than on
categorical hues -- rank is magnitude here, not identity.

Run::

    uv run python examples/diagnostics-overshoot/step4_figures.py
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config as cfg

from tools.envelope import (  # noqa: E402  (needs cfg's sys.path insert)
    AXIS,
    GRID,
    INK,
    INK_SECONDARY,
    OBSERVED,
    SYNTHETIC,
    apply_chart_style,
)

#: Single-hue ramp for the ordinal size axis, light (few years) to dark (many).
#: Steps taken from the same blue ramp the observed colour comes from.
SIZE_RAMP = ["#b9d5f7", "#86b6ef", "#2a78d6", "#123f75"]


def size_colours(sizes: list[int]) -> dict[int, str]:
    """Map training-set sizes to ramp steps, smallest = lightest."""
    ordered = sorted(sizes)
    step = max(1, len(SIZE_RAMP) // max(1, len(ordered)))
    return {
        k: SIZE_RAMP[min(len(SIZE_RAMP) - 1, i * step)]
        for i, k in enumerate(ordered)
    }


def _save(fig, name: str) -> None:
    path = cfg.FIGURES_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  wrote {path.relative_to(cfg.HERE)}")


# ======================================================================================


def figure_deviation_vs_years(per_config: pd.DataFrame) -> None:
    """
    The headline, split by what the deviation is measured *against*.

    Two panels because they answer different questions. The generator is fitted to the
    **pooled window**, so measuring against the pool tests the machinery. The centre day
    is the target a user actually asks for, so measuring against it tests the machinery
    *and* the window-width choice together. Keeping them side by side is what stops the
    second being read as the first.
    """
    n = int(per_config["n"].iloc[0])
    month, day = cfg.DAYS[0]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), sharey=True)

    panels = (
        ("pool_mean", "vs the pooled window it was trained on\n(tests the machinery)"),
        (cfg.PRIMARY_REFERENCE, "vs the target day\n(machinery + window width)"),
    )

    for ax, (reference, subtitle) in zip(axes, panels):
        frame = per_config.query("reference == @reference")
        # Jitter draws apart horizontally so overlapping intervals stay readable. The
        # jitter is cosmetic only -- k is the actual x value.
        for k, group in frame.groupby("k"):
            offsets = np.linspace(-0.16, 0.16, len(group)) if len(group) > 1 else [0.0]
            for offset, (_, row) in zip(offsets, group.iterrows()):
                x = np.log2(k) + offset
                ax.plot(
                    [x, x], [100 * row["ci_low"], 100 * row["ci_high"]],
                    color=SYNTHETIC, lw=2, alpha=0.45, solid_capstyle="round",
                )
                ax.plot(
                    x, 100 * row["mean_dev"], "o", ms=8, color=SYNTHETIC,
                    mec="white", mew=1.6, zorder=3,
                )

        ax.axhline(0, color=AXIS, lw=1.6, zorder=1)
        sizes = sorted(frame["k"].unique())
        ax.set_xticks([np.log2(k) for k in sizes])
        ax.set_xticklabels([f"{k}\nyear{'s' if k > 1 else ''}" for k in sizes])
        ax.set_xlabel("Years in the training record", color=INK_SECONDARY)
        ax.set_title(subtitle, color=INK, loc="left", fontsize=10)
        ax.grid(axis="x", visible=False)

    axes[0].set_ylabel("Mean deviation of daily total (%)", color=INK_SECONDARY)
    axes[0].annotate(
        "no bias", xy=(axes[0].get_xlim()[1], 0), xytext=(-6, 5),
        textcoords="offset points", ha="right", va="bottom",
        color=INK_SECONDARY, fontsize=9,
    )
    fig.suptitle(
        f"Does the bias depend on how many years were trained on?  "
        f"{month:02d}-{day:02d}, n = {n} per draw\n"
        f"one point per year-subset draw; bars are 95 % two-sample bootstrap intervals",
        color=INK, x=0.01, ha="left", fontsize=12,
    )
    fig.tight_layout()
    _save(fig, "deviation_vs_years")


def figure_distribution(raw_syn: pd.DataFrame, raw_obs: pd.DataFrame,
                        per_config: pd.DataFrame) -> None:
    """ECDF overlay and Q-Q, for the largest training set."""
    k_max = int(per_config["k"].max())
    config_id = per_config.query("k == @k_max")["config_id"].iloc[0]

    synthetic = np.sort(raw_syn.query("config_id == @config_id")["total_kwh_m2"].to_numpy())
    observed = np.sort(raw_obs.query("config_id == @config_id")["total_kwh_m2"].to_numpy())

    fig, (ax_ecdf, ax_qq, ax_tail) = plt.subplots(1, 3, figsize=(16, 5.0))

    for values, colour, label in (
        (observed, OBSERVED, f"observed pool  (m = {observed.size})"),
        (synthetic, SYNTHETIC, f"synthetic  (n = {synthetic.size})"),
    ):
        ax_ecdf.step(
            values, np.arange(1, values.size + 1) / values.size,
            where="post", color=colour, lw=2, label=label,
        )
    ax_ecdf.set_xlabel(f"Daily total ({cfg.DAILY_UNIT})", color=INK_SECONDARY)
    ax_ecdf.set_ylabel("Cumulative probability", color=INK_SECONDARY)
    ax_ecdf.set_title("Distribution of daily totals", color=INK, loc="left", fontsize=11)
    ax_ecdf.legend(frameon=False, loc="lower right", fontsize=9)

    # Common quantile grid, since the two samples differ in size.
    probs = np.linspace(0.005, 0.995, 200)
    ax_qq.plot(
        np.quantile(observed, probs), np.quantile(synthetic, probs),
        "o", ms=4, color=SYNTHETIC, alpha=0.65, mec="none",
    )
    lo = min(observed.min(), synthetic.min())
    hi = max(observed.max(), synthetic.max())
    ax_qq.plot([lo, hi], [lo, hi], color=AXIS, lw=1.6, zorder=1)
    ax_qq.annotate(
        "equal distributions", xy=(hi, hi), xytext=(-8, 8),
        textcoords="offset points", ha="right", color=INK_SECONDARY, fontsize=9,
    )
    ax_qq.set_xlabel(f"Observed quantile ({cfg.DAILY_UNIT})", color=INK_SECONDARY)
    ax_qq.set_ylabel(f"Synthetic quantile ({cfg.DAILY_UNIT})", color=INK_SECONDARY)
    ax_qq.set_title("Q-Q against the observed pool", color=INK, loc="left", fontsize=11)
    ax_qq.set_aspect("equal", adjustable="box")

    # The lower tail is where the two actually part company, and an ECDF at these
    # probabilities is too compressed to read. Exceedance fractions state it directly.
    thresholds = [0.5, 1.0, 1.5, 2.0, 2.5]
    width = 0.36
    x = np.arange(len(thresholds))
    for offset, values, colour, label in (
        (-width / 2 - 0.01, observed, OBSERVED, "observed pool"),
        (width / 2 + 0.01, synthetic, SYNTHETIC, "synthetic"),
    ):
        fractions = [100 * (values < t).mean() for t in thresholds]
        ax_tail.bar(x + offset, fractions, width, color=colour, label=label)
        for xi, value in zip(x + offset, fractions):
            ax_tail.annotate(
                f"{value:.1f}", xy=(xi, value), xytext=(0, 3),
                textcoords="offset points", ha="center",
                color=INK_SECONDARY, fontsize=8,
            )
    ax_tail.set_xticks(x)
    ax_tail.set_xticklabels([f"< {t}" for t in thresholds])
    ax_tail.set_xlabel(f"Daily total ({cfg.DAILY_UNIT})", color=INK_SECONDARY)
    ax_tail.set_ylabel("Share of days (%)", color=INK_SECONDARY)
    ax_tail.set_title(
        "Overcast days: how often each is produced", color=INK, loc="left", fontsize=11
    )
    ax_tail.legend(frameon=False, fontsize=9)
    ax_tail.grid(axis="x", visible=False)

    month, day = cfg.DAYS[0]
    fig.suptitle(
        f"Synthetic vs observed daily totals -- {k_max}-year record, {month:02d}-{day:02d}",
        color=INK, x=0.01, ha="left", fontsize=12,
    )
    fig.tight_layout()
    _save(fig, "distribution_comparison")


def figure_hourly_bias(hourly: pd.DataFrame) -> None:
    """Relative bias hour by hour, one line per training-set size."""
    fig, ax = plt.subplots(figsize=(9, 5.0))
    sizes = sorted(hourly["k"].unique())
    colours = size_colours(sizes)

    for k in sizes:
        profile = hourly.query("k == @k").groupby("hour")["bias"].mean()
        ax.plot(
            profile.index, 100 * profile.to_numpy(),
            color=colours[k], lw=2, label=f"{k} years", solid_capstyle="round",
        )
        # Direct label at the curve's right-hand end, so identity is not colour-alone.
        valid = profile.dropna()
        if not valid.empty:
            ax.annotate(
                f"{k} yr", xy=(valid.index[-1], 100 * valid.iloc[-1]),
                xytext=(6, 0), textcoords="offset points", va="center",
                color=INK_SECONDARY, fontsize=9,
            )

    ax.axhline(0, color=AXIS, lw=1.6, zorder=1)
    ax.set_xlabel("Hour of day", color=INK_SECONDARY)
    ax.set_ylabel("Synthetic vs observed hourly mean (%)", color=INK_SECONDARY)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(-0.5, 25.5)
    month, day = cfg.DAYS[0]
    ax.set_title(
        f"Where in the day any bias sits -- {month:02d}-{day:02d}\n"
        "hours with an observed mean below 1 W/m2 are omitted: a ratio there is noise",
        color=INK, loc="left", fontsize=11,
    )
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    _save(fig, "hourly_bias")


def figure_reference_gap(gap: pd.DataFrame) -> None:
    """How far the three reference estimators sit from one another."""
    fig, ax = plt.subplots(figsize=(9, 4.6))
    sizes = sorted(gap["k"].unique())
    x = np.arange(len(sizes))

    for offset, column, colour, label in (
        (-0.14, "pool_vs_detrended", OBSERVED, "pool mean vs detrended centre"),
        (0.14, "centre_vs_detrended", SYNTHETIC, "centre-day mean vs detrended centre"),
    ):
        means = [100 * gap.query("k == @k")[column].mean() for k in sizes]
        spread = [100 * gap.query("k == @k")[column].std(ddof=1) for k in sizes]
        ax.errorbar(
            x + offset, means, yerr=spread, fmt="o", ms=8, lw=2, capsize=0,
            color=colour, mec="white", mew=1.6, label=label, alpha=0.9,
        )

    ax.axhline(0, color=AXIS, lw=1.6, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{k} years" for k in sizes])
    ax.set_xlabel("Years in the training record", color=INK_SECONDARY)
    ax.set_ylabel("Difference from detrended centre (%)", color=INK_SECONDARY)
    ax.set_title(
        "Reference gap -- how much the choice of reference alone moves the answer\n"
        "bars are the spread across year-subset draws",
        color=INK, loc="left", fontsize=11,
    )
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="x", visible=False)
    _save(fig, "reference_gap")


def main() -> None:
    cfg.ensure_dirs()
    apply_chart_style()
    plt.rcParams.update({"grid.color": GRID, "axes.edgecolor": AXIS})

    per_config = pd.read_csv(cfg.RESULTS_DIR / "summary_by_config.csv")
    gap = pd.read_csv(cfg.RESULTS_DIR / "summary_references.csv")
    hourly = pd.read_csv(cfg.RESULTS_DIR / "summary_hourly_bias.csv")
    raw_syn = pd.read_csv(cfg.RAW_DIR / "synthetic_daily_totals.csv")
    raw_obs = pd.read_csv(cfg.RAW_DIR / "observed_daily_totals.csv")

    print("Drawing figures...")
    figure_deviation_vs_years(per_config)
    figure_distribution(raw_syn, raw_obs, per_config)
    figure_hourly_bias(hourly)
    figure_reference_gap(gap)


if __name__ == "__main__":
    main()
