"""
Run the whole diagnostic, start to finish.

Executes the four steps in order -- fetch, simulate, analyse, draw -- announcing what each
one is about to do and how long it is likely to take, so a sixteen-minute simulation does
not look like a hung terminal.

Run::

    uv run python examples/diagnostics-overshoot/run_all.py
    uv run python examples/diagnostics-overshoot/run_all.py --n 100      # a quick pass
    uv run python examples/diagnostics-overshoot/run_all.py --skip-figures
    uv run python examples/diagnostics-overshoot/run_all.py --from analyse

Each step is also runnable on its own -- see ``README.md``. This wrapper exists for the
common case of wanting all of it, and for the ETA.

Interrupting is safe. Step 2 writes incrementally, so a run stopped part-way can be picked
up with ``--resume``; the analysis and figures re-derive from the CSVs in seconds.
"""

from __future__ import annotations

import argparse
import time

import config as cfg

STEPS = ("fetch", "simulate", "analyse", "figures")


def _rule(title: str, detail: str = "") -> None:
    """A labelled section break, so the four steps are visually separable in a log."""
    print("\n" + "=" * 78)
    print(f"  {title}")
    if detail:
        print(f"  {detail}")
    print("=" * 78, flush=True)


def _describe_fetch() -> str:
    """Say up front whether this will hit the network or read a file."""
    matches = sorted(cfg.RECORD_CACHE.parent.glob("pvgis_hourly_heraklion_*.parquet"))
    if matches:
        newest = max(matches, key=lambda p: p.stat().st_mtime)
        size_mb = newest.stat().st_size / 1e6
        return f"cache is warm -- reading {newest.name} ({size_mb:.1f} MB), no download"
    return "cache is cold -- downloading from PVGIS, one request, ~1-2 min"


def _describe_simulate(n: int) -> str:
    configs = len(cfg.configurations())
    # Two regimes, both measured on this record: the first ~64 draws of a configuration
    # evaluate the KDE directly at ~92 ms/day, after which the cached conditional
    # quantile grid takes over at ~11 ms/day. Estimating with one number would be wrong
    # by 8x at whichever end of the range it was not fitted to.
    direct = min(n, 64)
    seconds = configs * (direct * 0.092 + max(0, n - direct) * 0.011) * 1.25
    eta = f"~{seconds / 60:.0f} min" if seconds >= 60 else "under a minute"
    return f"{configs} configurations x {n:,} realisations -- {eta}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=cfg.N_REALISATIONS,
                        help=f"realisations per configuration (default {cfg.N_REALISATIONS})")
    parser.add_argument("--from", dest="start", choices=STEPS, default="fetch",
                        help="start from this step instead of the beginning")
    parser.add_argument("--resume", action="store_true",
                        help="skip configurations already present in the raw output")
    parser.add_argument("--skip-figures", action="store_true",
                        help="stop after the analysis")
    args = parser.parse_args()

    cfg.ensure_dirs()
    selected = STEPS[STEPS.index(args.start):]
    if args.skip_figures and "figures" in selected:
        selected = tuple(s for s in selected if s != "figures")

    print(f"Running: {' -> '.join(selected)}")
    started = time.perf_counter()

    if "fetch" in selected:
        import step1_fetch

        _rule("STEP 1/4  fetch the record", _describe_fetch())
        step1_fetch.main()

    if "simulate" in selected:
        import step2_simulate

        _rule("STEP 2/4  simulate", _describe_simulate(args.n))
        step2_simulate.run(n_realisations=args.n, resume=args.resume)

    if "analyse" in selected:
        import step3_analyse

        _rule("STEP 3/4  analyse",
              f"{cfg.N_BOOTSTRAP:,} bootstrap resamples per configuration")
        step3_analyse.main()

    if "figures" in selected:
        import step4_figures

        _rule("STEP 4/4  figures", f"written to {cfg.FIGURES_DIR}")
        step4_figures.main()

    elapsed = time.perf_counter() - started
    _rule(f"DONE in {elapsed / 60:.1f} min",
          f"results in {cfg.RESULTS_DIR}, figures in {cfg.FIGURES_DIR}")


if __name__ == "__main__":
    main()
