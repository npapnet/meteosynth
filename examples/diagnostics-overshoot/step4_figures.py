"""
Step 4 -- figures.

Three, each answering one question:

1. ``distribution_comparison`` -- do synthetic and observed daily sums share a shape,
   and what happens in the lower tail? Top row is the whole ECDF, bottom row the same
   curves zoomed into the bottom 15 % where the defect lives. The zoom is the
   point: at full scale a fourfold overcast-day deficit is a few pixels.
2. ``statistic_ratios`` -- every ratio with its bootstrap interval, against the line at
   1.0 that means "matches the pool".
3. ``low_tail`` -- the two tail shares, synthetic against observed, per date.

Palette and chart style come from ``examples/tools/envelope.py``: **blue is observed,
orange is synthetic**, throughout the repo. Bandwidth is a second dimension inside the
synthetic entity, so it is carried by line style and marker fill rather than a third
hue -- shade and texture for emphasis, hue for identity. Validated: CVD dE 24.7,
normal-vision dE 33.6, both >= 3:1 on the surface.

Reads ``results/summary_statistics.csv`` and ``results/raw/*_daily.csv``. Redraws in
seconds without re-running anything.

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
    INK,
    INK_SECONDARY,
    OBSERVED,
    SYNTHETIC,
    apply_chart_style,
)

MONTH_NAMES = {3: "21 March", 5: "21 May", 6: "21 June", 9: "21 September", 12: "21 December"}

#: Bandwidth is a level *within* the synthetic entity, so it varies line style and
#: marker fill, never hue. Scott is the intended default and gets the solid line.
BANDWIDTH_STYLE = {"scott": ("-", "full"), "0.1": ("--", "none")}


def _label(bandwidth: str) -> str:
    return "synthetic, Scott" if bandwidth == "scott" else f"synthetic, bw {bandwidth}"


def _ecdf(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Empirical CDF as a step: sorted values against cumulative proportion."""
    ordered = np.sort(np.asarray(values, dtype=float))
    return ordered, np.arange(1, ordered.size + 1) / ordered.size


def _primary(index: pd.DataFrame) -> pd.DataFrame:
    """The 4x2 grid, anchor excluded -- the anchor is a control, not a result."""
    return index[~index["is_anchor"]]


# ======================================================================================
# 1. Distribution comparison
# ======================================================================================


def figure_distribution(index: pd.DataFrame, observed: pd.DataFrame, synthetic: pd.DataFrame) -> None:
    grid = _primary(index)
    dates = sorted(grid[["month", "day"]].drop_duplicates().itertuples(index=False))

    fig, axes = plt.subplots(2, len(dates), figsize=(4.0 * len(dates), 7.2), sharey="row")
    if len(dates) == 1:
        axes = axes.reshape(2, 1)

    for column, (month, day) in enumerate(dates):
        cells = grid[(grid["month"] == month) & (grid["day"] == day)]
        obs_id = cells["config_id"].iloc[0]
        obs_values = observed.loc[observed["config_id"] == obs_id, "sum_kwh_m2"].to_numpy()

        for row in range(2):
            ax = axes[row, column]
            x, y = _ecdf(obs_values)
            ax.step(x, y, where="post", color=OBSERVED, linewidth=2.0,
                    label="observed pool" if (row, column) == (0, 0) else None)

            for cell in cells.itertuples():
                values = synthetic.loc[
                    synthetic["config_id"] == cell.config_id, "sum_kwh_m2"
                ].to_numpy()
                style, _ = BANDWIDTH_STYLE[str(cell.bandwidth)]
                x, y = _ecdf(values)
                ax.step(x, y, where="post", color=SYNTHETIC, linewidth=2.0,
                        linestyle=style,
                        label=_label(str(cell.bandwidth)) if (row, column) == (0, 0) else None)

            if row == 0:
                ax.set_title(MONTH_NAMES.get(month, f"{month:02d}-{day:02d}"),
                             color=INK, fontsize=11)
                ax.set_ylim(0, 1)
            else:
                # The lower tail, at a scale where it is legible. The defect lives
                # entirely inside this box: 0.6 % of synthetic days against 2.4 %
                # observed is invisible on the panel above.
                ax.set_ylim(0, 0.15)
                upper = float(np.percentile(obs_values, 20))
                ax.set_xlim(float(obs_values.min()) * 0.9, upper)
                ax.axvline(cfg.LOW_TAIL_ABS, color=AXIS, linewidth=1.0, zorder=0)
            if column == 0:
                ax.set_ylabel("cumulative share of days" if row == 0 else "lower tail, zoomed",
                              color=INK_SECONDARY)
            ax.set_xlabel(f"daily total, {cfg.DAILY_UNIT}", color=INK_SECONDARY)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.0))
    fig.suptitle("Daily totals: synthetic ensembles against the pool they were fitted to",
                 y=1.06, fontsize=13, color=INK)
    fig.tight_layout()
    path = cfg.FIGURES_DIR / "distribution_comparison.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path.name}")


# ======================================================================================
# 2. Ratios with intervals
# ======================================================================================


def figure_ratios(statistics: pd.DataFrame) -> None:
    from step3_analyse import RATIO_STATISTICS, REPORT_ORDER

    labels = {name: label for name, label, _ in REPORT_ORDER}
    order = [name for name, _, _ in REPORT_ORDER if name in RATIO_STATISTICS]

    data = statistics[(~statistics["is_anchor"]) & (statistics["statistic"].isin(order))]
    dates = sorted(data[["month", "day"]].drop_duplicates().itertuples(index=False))

    fig, axes = plt.subplots(1, len(dates), figsize=(3.6 * len(dates), 5.2), sharey=True)
    axes = np.atleast_1d(axes)

    positions = {name: len(order) - i for i, name in enumerate(order)}
    offsets = {"scott": 0.16, "0.1": -0.16}

    # One x-scale across all four panels. Per-panel autoscaling would silently rescale
    # each date, and a 5 % miss at one date would look the same size as a 35 % miss at
    # another -- the whole point of the figure is that they are comparable.
    pad = 0.02
    span = (float(data["ci_lo"].min()) - pad, float(data["ci_hi"].max()) + pad)

    for ax, (month, day) in zip(axes, dates):
        block = data[(data["month"] == month) & (data["day"] == day)]
        ax.axvline(1.0, color=AXIS, linewidth=1.2, zorder=0)

        for cell in block.itertuples():
            bandwidth = str(cell.bandwidth)
            _, fillstyle = BANDWIDTH_STYLE[bandwidth]
            y = positions[cell.statistic] + offsets[bandwidth]
            ax.plot([cell.ci_lo, cell.ci_hi], [y, y], color=SYNTHETIC, linewidth=2.0,
                    solid_capstyle="round", zorder=2)
            ax.plot([cell.effect], [y], marker="o", markersize=8, color=SYNTHETIC,
                    fillstyle=fillstyle, markeredgewidth=2.0, linestyle="none", zorder=3)

        ax.set_title(MONTH_NAMES.get(month, f"{month:02d}-{day:02d}"), color=INK, fontsize=11)
        ax.set_xlabel("synthetic / observed", color=INK_SECONDARY)
        ax.set_yticks([positions[name] for name in order])
        ax.set_yticklabels([labels[name] for name in order])
        ax.set_ylim(0.4, len(order) + 0.6)
        ax.set_xlim(*span)
        ax.grid(axis="y", visible=False)

    marker_legend = [
        plt.Line2D([], [], color=SYNTHETIC, marker="o", markersize=8, linestyle="none",
                   fillstyle=BANDWIDTH_STYLE[bw][1], markeredgewidth=2.0, label=_label(bw))
        for bw in ("scott", "0.1")
    ]
    fig.legend(handles=marker_legend, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.0))
    fig.suptitle("Every statistic as a ratio to the training pool, with 95 % bootstrap intervals",
                 y=1.07, fontsize=13, color=INK)
    fig.tight_layout()
    path = cfg.FIGURES_DIR / "statistic_ratios.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path.name}")


# ======================================================================================
# 3. The lower tail
# ======================================================================================


def figure_low_tail(statistics: pd.DataFrame) -> None:
    """
    The overcast-day deficit, as a ratio.

    Plotted as synthetic/observed rather than as two shares, because the shares are not
    comparable between dates: 15 % of December days fall below 1 kWh/m2 against 1.4 % of
    March days, so on a shared axis December's bar is the only one visible and the
    fourfold March deficit disappears. The ratio is the quantity that travels.

    Dates whose observed tail is empty are omitted -- with nothing below the threshold,
    a deficit cannot be measured there, and a missing point says that more honestly than
    a zero would.
    """
    names = {"low_abs_share": f"below {cfg.LOW_TAIL_ABS:g} kWh/m2",
             "low_rel_share": f"below {cfg.LOW_TAIL_REL:g}x median"}
    data = statistics[
        (~statistics["is_anchor"])
        & (statistics["statistic"].isin(names))
        & (statistics["observed"] > 0)
    ].copy()

    rows = sorted(
        data[["month", "day", "statistic"]].drop_duplicates().itertuples(index=False),
        key=lambda r: (r.month, r.statistic),
    )
    positions = {(r.month, r.statistic): len(rows) - i for i, r in enumerate(rows)}

    fig, ax = plt.subplots(figsize=(9.0, 0.9 * len(rows) + 2.2))
    ax.axvline(1.0, color=OBSERVED, linewidth=2.0, zorder=0)
    ax.text(1.0, len(rows) + 0.55, "  observed pool", color=OBSERVED, fontsize=9, va="center")

    offsets = {"scott": 0.15, "0.1": -0.15}
    for cell in data.itertuples():
        bandwidth = str(cell.bandwidth)
        _, fillstyle = BANDWIDTH_STYLE[bandwidth]
        y = positions[(cell.month, cell.statistic)] + offsets[bandwidth]
        lo, hi = cell.ci_lo / cell.observed, cell.ci_hi / cell.observed
        ax.plot([lo, hi], [y, y], color=SYNTHETIC, linewidth=2.0,
                solid_capstyle="round", zorder=2)
        ax.plot([cell.ratio], [y], marker="o", markersize=8, color=SYNTHETIC,
                fillstyle=fillstyle, markeredgewidth=2.0, linestyle="none", zorder=3)
        ax.text(hi + 0.03, y, f"{cell.synthetic * 100:.1f} % vs {cell.observed * 100:.1f} %",
                color=INK_SECONDARY, fontsize=8.5, va="center")

    ax.set_yticks([positions[(r.month, r.statistic)] for r in rows])
    ax.set_yticklabels([f"{MONTH_NAMES.get(r.month, r.month)}\n{names[r.statistic]}"
                        for r in rows])
    ax.set_xlim(0, max(1.35, float((data["ci_hi"] / data["observed"]).max()) + 0.55))
    ax.set_ylim(0.4, len(rows) + 0.9)
    ax.set_xlabel("synthetic share / observed share", color=INK_SECONDARY)
    ax.set_title("Overcast days: the model produces too few, wherever there are any",
                 color=INK, fontsize=12)
    ax.grid(axis="y", visible=False)

    marker_legend = [
        plt.Line2D([], [], color=SYNTHETIC, marker="o", markersize=8, linestyle="none",
                   fillstyle=BANDWIDTH_STYLE[bw][1], markeredgewidth=2.0, label=_label(bw))
        for bw in ("scott", "0.1")
    ]
    ax.legend(handles=marker_legend, loc="lower right")
    fig.tight_layout()
    path = cfg.FIGURES_DIR / "low_tail.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path.name}")


def main() -> None:
    cfg.ensure_dirs()
    apply_chart_style()

    index = pd.read_csv(cfg.RAW_DIR / "config_index.csv")
    observed = pd.read_csv(cfg.RAW_DIR / "observed_daily.csv")
    synthetic = pd.read_csv(cfg.RAW_DIR / "synthetic_daily.csv")
    statistics = pd.read_csv(cfg.RESULTS_DIR / "summary_statistics.csv")

    print(f"Drawing into {cfg.FIGURES_DIR}")
    figure_distribution(index, observed, synthetic)
    figure_ratios(statistics)
    figure_low_tail(statistics)


if __name__ == "__main__":
    main()
