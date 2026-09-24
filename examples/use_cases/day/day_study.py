"""
The machinery the three ``day_envelope_*.py`` scripts share: one case, and a sweep.

The three scripts ask one question -- *does a synthetic 21 May look like a real
21 May?* -- of three quantities. Everything that does not depend on which quantity lives
here: collecting the record, fitting, drawing the ensemble, naming the files after the
parameters that produced them, and iterating over a parameter sweep. Each script keeps
its preamble (site, attribute, sweep lists) and the two things that are genuinely
specific to its variable, handed over as functions on :class:`DayStudy`:

* ``describe_fit`` -- the lines printed about the fitted models. Irradiance reports its
  degenerate night hours, temperature the span of observed midnights, wind its distance
  from the support bound. Same fit, three things worth saying about it.
* ``extra_report`` -- the fourth check, after shape, spread and quantity. Temperature
  adds diurnal swing, wind adds ``v^3``; irradiance has nothing to add.

Why a sibling module rather than ``examples/tools/``
---------------------------------------------------
``tools/envelope.py`` is the *comparison* -- what an observed cloud is, and how to draw
one -- and has consumers beyond this folder (``examples/diagnostics-overshoot/``). This
module is the *study*: the site, the sweep and the filenames, which are nobody else's
business. It sits beside the scripts so that copying the folder still copies a working
example.

Where things are written
------------------------
``data/`` and ``output/`` beside **this file**, which is also where the scripts are. That
holds whether a script is launched from the repository root, run as ``-m``, or executed
as ``#%%`` cells in an editor, where ``__file__`` is undefined and only an imported
module still knows where it lives.
"""

from __future__ import annotations

import itertools
import pathlib
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from meteosynth import DayWindowGenerator, EnvSeriesGenerator, MetDataset, workspace
from meteosynth.adapters import fetch_pvgis

#: This folder. Unlike a script's ``globals().get("__file__")``, a module always has one,
#: so ``data/`` and ``output/`` land here even when the caller is an editor cell whose
#: working directory is the repository root.
WS = workspace(__file__)

# Make `examples/` importable however the caller was started, for `tools.envelope`.
_EXAMPLES = next(
    p
    for c in (WS.root, *WS.root.parents)
    for p in (c, c / "examples")
    if (p / "tools" / "envelope.py").is_file()
)
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from tools.envelope import (  # noqa: E402  (needs the sys.path insert above)
    INK_SECONDARY,
    day_matrix,
    ensemble_frame,
    plot_day_envelope,
    report_day_stats,
    synthetic_ensemble,
)

#: What ``describe_fit`` is handed, and what it returns: the fitted day generator and
#: the observed pool, in exchange for lines to print. Purely for the reader -- the
#: dataclass field is what enforces it.
DescribeFit = Callable[[EnvSeriesGenerator, pd.DataFrame], Sequence[str]]

#: What ``extra_report`` is handed: the observed pool and the synthetic ensemble. It
#: prints its own block and returns ``metric``/``value`` rows to append to the stats.
ExtraReport = Callable[[pd.DataFrame, np.ndarray], pd.DataFrame]


@dataclass(frozen=True, kw_only=True)
class DayStudy:
    """
    One script's question: a site, a record, a quantity and a date.

    Everything here is decided in the calling script's preamble, so the script remains
    the whole statement of what was run.

    Parameters
    ----------
    site_key : str
        Free label stored in the record's provenance, e.g. ``"heraklion"``. Once bound
        it also resolves the coordinates, so a later call can name the site alone.
    site_name : str
        What the figure is titled with.
    latitude, longitude : float
        Site coordinates, passed straight to
        :func:`meteosynth.adapters.fetch_pvgis`.
    years : (int, int) or None, optional
        Inclusive year range, or ``None`` (the default) for **everything the provider
        serves**. See :func:`load_dataset` for what that means against a folder that
        already holds a narrower record.
    attr : str
        The column to model, e.g. ``"poa_global"``.
    unit : str
        Its unit, for labels only.
    target : (int, int)
        ``(month, day)`` of the date being asked about.
    date_label : str
        How that date is written in titles and filenames, e.g. ``"21 May"``.
    aggregate : {"sum", "mean", "max"}, optional
        How a day collapses to the one number an energy model consumes.
    aggregate_scale : float, optional
        Multiplier applied to that number, e.g. ``1e-3`` for W/m2-hours to kWh/m2.
    aggregate_unit : str, optional
        Its unit after scaling. Defaults to ``unit``.
    describe_fit : callable, optional
        ``(day_generator, observed_pool) -> lines``, printed after the standard fit
        summary. This is where a variable says what is peculiar about its own models.
    extra_report : callable, optional
        ``(observed_pool, synthetic) -> frame``. Prints a fourth check of its own and
        returns ``metric``/``value`` rows, which are appended to the case's stats and so
        reach the sweep summary as columns.
    """

    site_key: str
    site_name: str
    latitude: float
    longitude: float
    years: Optional[Tuple[int, int]] = None

    attr: str
    unit: str
    target: Tuple[int, int]
    date_label: str
    aggregate: str = "mean"
    aggregate_scale: float = 1.0
    aggregate_unit: Optional[str] = None

    describe_fit: Optional[DescribeFit] = None
    extra_report: Optional[ExtraReport] = None

    @property
    def agg_unit(self) -> str:
        """``aggregate_unit`` if given, else the attribute's own unit."""
        return self.aggregate_unit or self.unit

    @property
    def date_slug(self) -> str:
        """``21 May`` -> ``21May``, for filenames."""
        return self.date_label.replace(" ", "")


def load_dataset(study: DayStudy, refresh: bool = False) -> MetDataset:
    """
    The training record, collected into ``data/`` beside this module.

    Straight onto :func:`meteosynth.adapters.fetch_pvgis` with the coordinates from the
    script's preamble, so the site lives in that script and nowhere else. The download
    happens once; later runs are answered from the folder, matched on what the stored
    record says about itself.

    Parameters
    ----------
    study : DayStudy
        Supplies the coordinates, the label and ``years``.
    refresh : bool, optional
        Re-download and overwrite, even when the folder already holds an answer.

    Returns
    -------
    MetDataset
        Holding every plane-of-array component, ``poa_global``, ``temp_air`` and
        ``wind_speed``, so one record answers all three scripts.

    Notes
    -----
    **What ``years=None`` does against a warm folder.** A request for no particular
    period means *"whatever you have"*, so a record already in ``data/`` answers it
    whatever it spans -- a folder holding 2010-2020 keeps returning 2010-2020 rather than
    collecting the provider's full range. That is why the line printed below states the
    period actually loaded rather than the one requested: read it, do not assume it.

    To widen such a folder, **delete the narrow parquet first**, then run. ``refresh=True``
    alone is not enough: it writes the wider record under its own name and leaves the
    narrow one in place, after which two records answer the same request and
    :func:`meteosynth.store.resolve` refuses to choose between them.
    """
    years = study.years
    if not (WS.data_dir.is_dir() and any(WS.data_dir.glob("*.parquet"))):
        period = "its full record" if years is None else f"{years[0]}-{years[1]}"
        print(
            f"Fetching {study.site_name} ({study.latitude}, {study.longitude}) {period} "
            f"from PVGIS -- one request, then stored in {WS.data_dir}..."
        )
    ds = fetch_pvgis(
        latitude=study.latitude,
        longitude=study.longitude,
        start=None if years is None else years[0],
        end=None if years is None else years[1],
        site=study.site_key,
        data_dir=WS.data_dir,
        force_refetch=refresh,
        # Ask the provider for everything only when no period was named; a named period
        # downloads exactly itself, which is what keeps a first run from paying for
        # nineteen years nobody reads.
        full_range=years is None,
        usehorizon=True,
        outputformat="json",
    )
    print(
        f"Loaded {study.site_name}, {ds.describe_time_range().lower()} "
        f"({len(ds.met_data)} hourly rows) from {WS.data_dir}"
    )
    return ds


def case_tag(pool_days: int, window_days: int, n_synthetic: int, seed: int) -> str:
    """
    ``pool07_win15_n0200_seed42`` -- one case's parameters, for filenames and captions.

    Zero-padded so that a directory listing sorts the way the numbers do.
    """
    return f"pool{pool_days:02d}_win{window_days:02d}_n{n_synthetic:04d}_seed{seed}"


def case_stem(
    study: DayStudy, pool_days: int, window_days: int, n_synthetic: int, seed: int
) -> str:
    """Filename stem for one case: the date, the attribute, then the parameters."""
    tag = case_tag(pool_days, window_days, n_synthetic, seed)
    return f"day_{study.date_slug}_{study.attr}_{tag}"


def save_frame(frame: pd.DataFrame, name: str, index: bool = True) -> pathlib.Path:
    """Write a frame to this folder's ``output/`` and report where it went."""
    path = WS.output(name)
    frame.to_csv(path, index=index)
    print(f"  wrote {frame.shape[0]:6d} rows x {frame.shape[1]} cols -> {path}")
    return path


def save_figure(fig: plt.Figure, name: str, dpi: int = 150) -> pathlib.Path:
    """Write a figure to this folder's ``output/`` and report where it went."""
    path = WS.output(name)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"  wrote figure -> {path}")
    return path


def run_case(
    study: DayStudy,
    ds: MetDataset,
    pool_days: int,
    window_days: int,
    n_synthetic: int,
    seed: int = 42,
    generator: Optional[DayWindowGenerator] = None,
) -> Dict[str, object]:
    """
    One parameter combination: one figure, one ensemble CSV, one stats CSV.

    Parameters
    ----------
    study : DayStudy
        What is being asked, from the calling script's preamble.
    ds : MetDataset
        The training record, from :func:`load_dataset`.
    pool_days : int
        Half-width of the *observed* comparison window, in days. It sets the blue
        p10-p90 band and the blue histogram only -- it never touches the synthetic draws.
        ``7`` pools 14-28 May across every year in the record.
    window_days : int
        Half-width of the *training* window the hourly models are fitted on. This is the
        one that changes the synthetic days.
    n_synthetic : int
        How many independent synthetic days to draw for ``study.target``.
    seed : int, optional
        Seeds the whole ensemble, so a case is reproducible as a whole.
    generator : DayWindowGenerator, optional
        A generator already fitted with this ``window_days``. Fitting depends on the
        training window alone, so a sweep over ``pool_days`` can reuse one fit; pass
        nothing and the case fits its own.

    Returns
    -------
    dict
        The parameters, the ``stats`` frame, the figure, and where the figure went.
    """
    attr, target = study.attr, study.target
    tag = case_tag(pool_days, window_days, n_synthetic, seed)
    stem = case_stem(study, pool_days, window_days, n_synthetic, seed)
    print(f"\n{'=' * 78}\n  {tag}\n{'=' * 78}")

    # The observed cloud: the exact date, and the window around it.
    observed_exact = day_matrix(ds, attr, *target, n_days=0)
    observed_pool = day_matrix(ds, attr, *target, n_days=pool_days)

    if generator is None:
        print(
            f"\nFitting the +/-{window_days} day window generator "
            f"for {study.date_label}..."
        )
        generator = DayWindowGenerator(ds, attr_str=attr, n_days=window_days)
    day_generator = generator.for_day(*target)
    training_days = len(day_matrix(ds, attr, *target, n_days=window_days))
    print(f"  observed pool days   : {len(observed_pool)} (+/-{pool_days} d, all years)")
    print(f"  training days pooled : {training_days} (+/-{window_days} d, all years)")
    if study.describe_fit is not None:
        for line in study.describe_fit(day_generator, observed_pool):
            print(f"  {line}")

    print(
        f"\nDrawing {n_synthetic} independent synthetic {study.date_label} profiles..."
    )
    synthetic = synthetic_ensemble(
        generator, *target, n=n_synthetic, seed=seed, show_progress=True
    )

    stats = report_day_stats(
        observed_pool,
        observed_exact,
        synthetic,
        attr=attr,
        unit=study.unit,
        date_label=study.date_label,
        aggregate=study.aggregate,
        aggregate_scale=study.aggregate_scale,
        aggregate_unit=study.agg_unit,
    )
    if study.extra_report is not None:
        stats = pd.concat(
            [stats, study.extra_report(observed_pool, synthetic)], ignore_index=True
        )
    # Carry the parameters in the frame as well as in the filename: stats from several
    # cases are meant to be concatenated, and a metric without its case is unreadable.
    stats = stats.assign(
        pool_days=pool_days,
        window_days=window_days,
        n_synthetic=n_synthetic,
        seed=seed,
    )

    print("\nSaving...")
    save_frame(ensemble_frame(synthetic), f"{stem}_ensemble.csv")
    save_frame(stats, f"{stem}_stats.csv", index=False)

    fig = plot_day_envelope(
        observed_pool,
        observed_exact,
        synthetic,
        attr=attr,
        unit=study.unit,
        date_label=study.date_label,
        site_label=study.site_name,
        window_days=pool_days,  # labels the observed pool, which is what it describes
        aggregate=study.aggregate,
        aggregate_scale=study.aggregate_scale,
        aggregate_unit=study.agg_unit,
    )
    # The figure states which case it is: an image pasted into a document has left its
    # filename behind.
    fig.text(
        0.995,
        0.005,
        tag.replace("_", "  "),
        ha="right",
        va="bottom",
        fontsize=8,
        color=INK_SECONDARY,
    )
    figure_path = save_figure(fig, f"{stem}.png")

    return {
        "pool_days": pool_days,
        "window_days": window_days,
        "n_synthetic": n_synthetic,
        "seed": seed,
        "tag": tag,
        "stats": stats,
        "figure": fig,
        "figure_path": figure_path,
    }


def sweep_summary(results: Sequence[Dict[str, object]]) -> pd.DataFrame:
    """One row per case: its parameters, then every reported metric as a column."""
    rows = []
    for result in results:
        stats = result["stats"]
        row = {
            key: result[key]
            for key in ("pool_days", "window_days", "n_synthetic", "seed")
        }
        row.update(dict(zip(stats["metric"], stats["value"])))
        rows.append(row)
    return pd.DataFrame(rows)


def run_sweep(
    study: DayStudy,
    ds: Optional[MetDataset] = None,
    pool_days: Sequence[int] = (7,),
    window_days: Sequence[int] = (15,),
    n_synthetic: Sequence[int] = (200,),
    seed: int = 42,
    close_figures: Optional[bool] = None,
) -> Tuple[pd.DataFrame, List[Dict[str, object]]]:
    """
    Run :func:`run_case` over every combination of the three parameter lists.

    ``window_days`` is the outer loop on purpose: fitting is the expensive half and
    depends on the training window alone, so one fit serves every ``pool_days`` and
    ``n_synthetic`` beneath it.

    Parameters
    ----------
    study : DayStudy
        What is being asked, from the calling script's preamble.
    ds : MetDataset, optional
        The record to use. Loaded via :func:`load_dataset` when omitted -- pass one in an
        interactive session to avoid re-reading it per sweep.
    pool_days, window_days, n_synthetic : sequence of int, optional
        The axes to sweep; the scripts pass the lists from their preamble. Sequences even
        for a single value: ``[7]`` is one case, where a bare ``7`` would iterate nothing.
    seed : int, optional
        Shared by every case, so cases differ only in the parameter being swept.
    close_figures : bool, optional
        Close each figure once it is written. Defaults to closing whenever there is more
        than one case, which keeps matplotlib from warning about twenty open windows
        while still leaving a single run on screen in an interactive session.

    Returns
    -------
    (pd.DataFrame, list of dict)
        The summary table -- also written to ``output/`` -- and every case's own result.
    """
    ds = load_dataset(study) if ds is None else ds
    cases = list(itertools.product(window_days, pool_days, n_synthetic))
    if close_figures is None:
        close_figures = len(cases) > 1
    print(
        f"\n{len(cases)} case(s): pool_days={list(pool_days)}, "
        f"window_days={list(window_days)}, n_synthetic={list(n_synthetic)}"
    )

    results: List[Dict[str, object]] = []
    generator, fitted_window = None, None
    for window, pool, n in cases:
        if window != fitted_window:
            print(
                f"\nFitting the +/-{window} day window generator "
                f"for {study.date_label}..."
            )
            generator = DayWindowGenerator(ds, attr_str=study.attr, n_days=window)
            fitted_window = window
        result = run_case(study, ds, pool, window, n, seed=seed, generator=generator)
        results.append(result)
        if close_figures:
            plt.close(result["figure"])

    summary = sweep_summary(results)
    print(f"\n{'=' * 78}\n  sweep summary, one row per case\n{'=' * 78}")
    save_frame(
        summary, f"day_{study.date_slug}_{study.attr}_sweep_summary.csv", index=False
    )
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    return summary, results
