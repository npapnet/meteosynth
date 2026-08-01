"""
Step 2 -- run every configuration and write the raw numbers to disk.

One configuration is *(calendar day, window half-width, bandwidth)*. For each, this fits
a generator on the pooled window from the **full** record, draws ``n`` synthetic days,
collects the observed days the model was trained on, and writes both out.

Nothing is analysed here. Step 2 produces evidence; :mod:`step3_analyse` reads it back
from disk and interprets it. Keeping the two apart means any check made by hand against
the CSVs is a check against exactly what the analysis saw.

Run::

    uv run python examples/diagnostics-overshoot/step2_simulate.py
    uv run python examples/diagnostics-overshoot/step2_simulate.py --n 200
    uv run python examples/diagnostics-overshoot/step2_simulate.py --resume

Design notes worth knowing when reading the output:

* **The pooled window is both the training data and the reference.** The model is fitted
  to exactly the observed days written to ``observed_daily.csv``, so the comparison target
  is a known quantity rather than an estimate of one. There is no reference file and no
  detrending -- both would be needed only if the target were a calendar *date*, which the
  pooled window merely approximates.
* **One training set.** The whole record, every configuration. The question is how the
  shipped code behaves, not how it degrades on a thin record.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

import config as cfg

from meteosynth import DayWindowGenerator, MetDataset
from meteosynth.day_window import DAYS_IN_YEAR, day_slot, day_slots
from meteosynth.variables import get_spec

from tools.envelope import day_matrix  # noqa: E402  (needs cfg's sys.path insert)


def signed_circular_delta(slots: np.ndarray, centre: int) -> np.ndarray:
    """
    **Signed** offset from the centre slot, negative before and positive after.

    ``meteosynth.day_window.circular_delta`` is deliberately *unsigned* -- it answers
    "how far apart", which is what window selection needs. Anything fitting a trend
    across the window needs "which side", because a curve fitted against ``|offset|``
    folds a rising season and a falling one onto each other. An earlier pass was bitten by
    exactly that, so the helper stays, and the symmetry self-check below guards it.
    """
    half = DAYS_IN_YEAR // 2
    return np.mod(np.asarray(slots) - centre + half, DAYS_IN_YEAR) - half


RAW_FILES = {
    "config_index": "config_index.csv",
    "observed_daily": "observed_daily.csv",
    "synthetic_daily": "synthetic_daily.csv",
    "observed_hourly": "observed_hourly.csv",
    "synthetic_hourly": "synthetic_hourly.csv",
}


# ======================================================================================
# Design
# ======================================================================================


def build_configs() -> list[dict]:
    """Enumerate every configuration, with its seed already resolved."""
    configs: list[dict] = []
    for month, day, n_days, bandwidth in cfg.configurations():
        # The seed depends on the cell's identity, so adding or removing a cell does not
        # reshuffle the draws of the others.
        key = (month, day, n_days, 0 if bandwidth is None else int(bandwidth * 1000))
        seed = int(
            np.random.SeedSequence(cfg.MASTER_SEED, spawn_key=key).generate_state(1)[0]
        )
        configs.append(
            {
                "config_id": cfg.config_id(month, day, n_days, bandwidth),
                "month": month,
                "day": day,
                "n_days": n_days,
                "bandwidth": bandwidth,
                "seed": seed,
                "is_anchor": (month, day, n_days, bandwidth) == cfg.ANCHOR,
            }
        )
    return configs


# ======================================================================================
# One configuration
# ======================================================================================


def _observed_frames(
    ds: MetDataset, month: int, day: int, n_days: int, config_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Observed daily sums and maxima, and the hourly values behind them."""
    window = day_matrix(ds, cfg.ATTR, month, day, n_days=n_days)

    dates = pd.to_datetime(window.index, format="%Y%m%d")
    slots = day_slots(dates.month.to_numpy(), dates.day.to_numpy())
    centre_slot = day_slot(month, day)

    daily = pd.DataFrame(
        {
            "config_id": config_id,
            "date": window.index.astype(str),
            "year": dates.year,
            "month": dates.month,
            "day": dates.day,
            "slot": slots,
            "days_from_centre": signed_circular_delta(slots, centre_slot),
            "sum_kwh_m2": window.sum(axis=1).to_numpy() / 1000.0,
            "max_w_m2": window.max(axis=1).to_numpy(),
        }
    )
    daily["is_centre"] = daily["days_from_centre"] == 0

    hourly = (
        window.rename_axis("date")
        .rename_axis("hour", axis=1)
        .stack()
        .rename(f"{cfg.ATTR}_w_m2")
        .reset_index()
    )
    hourly.insert(0, "config_id", config_id)

    return daily, hourly


def _synthetic_frames(
    ensemble: np.ndarray, config_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic daily sums and maxima, and the hourly values behind them."""
    daily = pd.DataFrame(
        {
            "config_id": config_id,
            "realisation": np.arange(ensemble.shape[0]),
            "sum_kwh_m2": ensemble.sum(axis=1) / 1000.0,
            "max_w_m2": ensemble.max(axis=1),
        }
    )

    n, n_hours = ensemble.shape
    hourly = pd.DataFrame(
        {
            "config_id": config_id,
            "realisation": np.repeat(np.arange(n), n_hours),
            "hour": np.tile(np.arange(n_hours), n),
            f"{cfg.ATTR}_w_m2": ensemble.ravel(),
        }
    )
    return daily, hourly


def run_config(ds: MetDataset, spec: dict, n_realisations: int) -> dict:
    """Fit, sample and collect one configuration. Returns one frame per raw file."""
    observed_daily, observed_hourly = _observed_frames(
        ds, spec["month"], spec["day"], spec["n_days"], spec["config_id"]
    )

    generator = DayWindowGenerator(
        ds, cfg.ATTR, n_days=spec["n_days"], bandwidth=spec["bandwidth"]
    )
    day_generator = generator.for_day(spec["month"], spec["day"])

    # One Generator drives the whole ensemble, so the draws are independent of one
    # another but the ensemble as a whole is reproducible from the single seed.
    # Sampling still dominates the runtime, so the inner bar is where the wait actually
    # is -- a per-configuration bar alone would sit still for tens of seconds at a time.
    # It is also where the cached quantile grid kicks in: the first ~64 draws of each
    # configuration are visibly slower than the rest.
    rng = np.random.default_rng(spec["seed"])
    draws = tqdm(
        range(n_realisations),
        desc=f"    {spec['config_id']}",
        unit="day",
        leave=False,
        position=1,
        dynamic_ncols=True,
        # None auto-disables when stdout is not a terminal, so a redirected log holds
        # the printed lines and not several thousand redraws of a bar.
        disable=None,
    )
    ensemble = np.vstack([day_generator.gen_day(rng=rng) for _ in draws])

    synthetic_daily, synthetic_hourly = _synthetic_frames(ensemble, spec["config_id"])

    observed_sums = observed_daily["sum_kwh_m2"]
    index_row = pd.DataFrame(
        [
            {
                "config_id": spec["config_id"],
                "month": spec["month"],
                "day": spec["day"],
                "n_days": spec["n_days"],
                "bandwidth": "scott" if spec["bandwidth"] is None else spec["bandwidth"],
                "is_anchor": spec["is_anchor"],
                "seed": spec["seed"],
                "n": n_realisations,
                "m": len(observed_daily),
                "n_obs_centre": int(observed_daily["is_centre"].sum()),
                "obs_mean_kwh_m2": float(observed_sums.mean()),
                "obs_sd_kwh_m2": float(observed_sums.std(ddof=1)),
                "obs_cv": float(observed_sums.std(ddof=1) / observed_sums.mean()),
                # What Scott's rule actually chose, so the factor's two levels can be
                # compared on a common scale rather than by name.
                "kde_factor_h12": _kde_factor(day_generator),
            }
        ]
    )

    return {
        "config_index": index_row,
        "observed_daily": observed_daily,
        "synthetic_daily": synthetic_daily,
        "observed_hourly": observed_hourly,
        "synthetic_hourly": synthetic_hourly,
    }


def _kde_factor(day_generator) -> Optional[float]:
    """
    The covariance multiplier the noon transition's KDE ended up using.

    Recorded because ``bandwidth=None`` means "whatever Scott's rule picks for this
    sample size", and comparing that level against a hand-set 0.1 needs the number it
    actually picked. Noon is chosen because it is never degenerate.
    """
    simulator = day_generator.simulators.get(12)
    kde = getattr(simulator, "joint_kde", None)
    return float(kde.factor) if kde is not None else None


# ======================================================================================
# Incremental writing
# ======================================================================================


def _append(name: str, frame: pd.DataFrame, first: bool) -> None:
    """Append a frame to its raw file, writing the header only on the first config."""
    path = cfg.RAW_DIR / RAW_FILES[name]
    frame.to_csv(path, mode="w" if first else "a", header=first, index=False)


class RunLock:
    """
    Refuse to start while another run is writing the same files.

    The raw files are appended to, so two concurrent runs interleave their rows into
    one another's output and the result looks plausible while being nonsense. That is
    exactly the failure this guards: a stale lock naming a dead process is cleared
    automatically, a live one aborts the run.
    """

    def __init__(self, path) -> None:
        self.path = path

    def __enter__(self) -> "RunLock":
        import os

        if self.path.exists():
            try:
                pid = int(self.path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pid = None
            if pid is not None and _pid_alive(pid):
                raise SystemExit(
                    f"another run (pid {pid}) is writing {self.path.parent}.\n"
                    f"Wait for it, or stop it and delete {self.path}."
                )
            print(f"  clearing stale lock from pid {pid}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        return self

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """True if a process with this id is running. Best-effort, cross-platform."""
    import subprocess
    import sys

    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, check=False,
        ).stdout
        return str(pid) in out
    try:
        import os

        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _done_config_ids() -> set[str]:
    """Configurations already on disk, for ``--resume``."""
    path = cfg.RAW_DIR / RAW_FILES["config_index"]
    if not path.exists():
        return set()
    return set(pd.read_csv(path)["config_id"].astype(str))


# ======================================================================================
# Self-checks
# ======================================================================================


def sanity_checks(configs: list[dict], record_years: list[int]) -> bool:
    """
    Re-read what was written and assert it hangs together.

    Run against the files rather than in-memory state, so this checks the artefact the
    analysis will actually consume. Returns True if everything passed.
    """
    print("\n" + "=" * 78)
    print("SANITY CHECKS  (run against the files on disk, not memory)")
    print("=" * 78)

    index = pd.read_csv(cfg.RAW_DIR / RAW_FILES["config_index"])
    obs_daily = pd.read_csv(cfg.RAW_DIR / RAW_FILES["observed_daily"])
    syn_daily = pd.read_csv(cfg.RAW_DIR / RAW_FILES["synthetic_daily"])
    obs_hourly = pd.read_csv(cfg.RAW_DIR / RAW_FILES["observed_hourly"])
    syn_hourly = pd.read_csv(cfg.RAW_DIR / RAW_FILES["synthetic_hourly"])

    value_col = f"{cfg.ATTR}_w_m2"
    results: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        results.append((label, bool(ok), detail))

    # 1. Hourly values reconcile with the daily sums and maxima taken from them.
    for label, hourly, daily, keys in (
        ("observed", obs_hourly, obs_daily, ["config_id", "date"]),
        ("synthetic", syn_hourly, syn_daily, ["config_id", "realisation"]),
    ):
        grouped = hourly.groupby(keys)[value_col]
        stated = daily.set_index(keys)
        worst_sum = float(
            (grouped.sum().reindex(stated.index) / 1000.0 - stated["sum_kwh_m2"]).abs().max()
        )
        worst_max = float(
            (grouped.max().reindex(stated.index) - stated["max_w_m2"]).abs().max()
        )
        check(f"{label}: sum(hourly)/1000 == daily sum", worst_sum < 1e-9, f"max |diff| {worst_sum:.3e}")
        check(f"{label}: max(hourly) == daily max", worst_max < 1e-9, f"max |diff| {worst_max:.3e}")

    # 2. Row counts follow from the window: one centre day per year, (2n+1) slots a year.
    counts = obs_daily.groupby("config_id").agg(
        n_window=("sum_kwh_m2", "size"), n_centre=("is_centre", "sum")
    )
    merged = index.set_index("config_id").join(counts)
    n_years = len(record_years)
    check(
        "observed: centre-day count == years in record",
        bool((merged["n_centre"] == n_years).all()),
        f"{int((merged['n_centre'] != n_years).sum())} mismatched, expected {n_years}",
    )
    expected_window = n_years * (2 * merged["n_days"] + 1)
    check(
        "observed: window count == years x (2n+1)",
        bool((merged["n_window"] == expected_window).all()),
        f"{int((merged['n_window'] != expected_window).sum())} mismatched",
    )

    # 2b. Offsets are signed and symmetric about the centre. An unsigned offset column
    #     silently folds the season's two sides together, and nothing downstream would
    #     have complained -- a defect an earlier pass actually hit.
    grouped_offsets = obs_daily.groupby("config_id")["days_from_centre"]
    half_widths = index.set_index("config_id")["n_days"]
    check(
        "observed: days_from_centre is signed and symmetric",
        bool(
            (grouped_offsets.min().reindex(half_widths.index) == -half_widths).all()
            and (grouped_offsets.max().reindex(half_widths.index) == half_widths).all()
            and grouped_offsets.mean().abs().max() < 1e-9
        ),
        f"range [{obs_daily['days_from_centre'].min()}, {obs_daily['days_from_centre'].max()}]",
    )

    # 3. Every configuration trained on the whole record. There is no year-subsetting in
    #    this run, so a missing year is a data defect rather than a design choice.
    declared = set(int(y) for y in record_years)
    actual = obs_daily.groupby("config_id")["year"].apply(lambda s: set(s.astype(int)))
    missing = {cid: declared - years for cid, years in actual.items() if declared - years}
    check("observed: every year of the record present", not missing, f"{len(missing)} short")

    # 4. Synthetic ensemble size.
    syn_counts = syn_daily.groupby("config_id").size()
    expected_n = index.set_index("config_id")["n"]
    check(
        "synthetic: row count == n",
        bool((syn_counts.reindex(expected_n.index) == expected_n).all()),
        "",
    )

    # 5. Physical support. The library enforces this on the observed side at ingestion;
    #    the synthetic side is the one that could actually violate it.
    lower, upper = get_spec(cfg.ATTR).support
    for label, hourly in (("observed", obs_hourly), ("synthetic", syn_hourly)):
        values = hourly[value_col]
        in_support = bool(values.min() >= (lower or -np.inf) and values.max() <= (upper or np.inf))
        check(
            f"{label}: hourly inside physical support",
            in_support,
            f"[{values.min():.1f}, {values.max():.1f}] vs [{lower}, {upper}]",
        )

    # 6. Daily sums plausible against the observed record. A soft check: a synthetic day
    #    far above anything the site has recorded is a red flag, not proof of a bug.
    per_config = syn_daily.groupby("config_id")["sum_kwh_m2"].max().to_dict()
    obs_per_config = obs_daily.groupby("config_id")["sum_kwh_m2"].max().to_dict()
    worst = max(
        (per_config[cid] / obs_per_config[cid], cid) for cid in per_config
    )
    check(
        "synthetic: daily sum within 1.5x the observed max",
        worst[0] <= 1.5,
        f"worst {worst[1]} at {worst[0]:.2f}x",
    )

    # 7. Every configuration asked for is present, exactly once. A duplicate config_id
    #    means two runs appended to the same files -- which has happened.
    duplicated = index["config_id"][index["config_id"].duplicated()].unique()
    check(
        "no duplicate configurations",
        len(duplicated) == 0,
        f"{len(duplicated)} duplicated: {list(duplicated)[:3]}" if len(duplicated) else "",
    )
    check(
        "all configurations written",
        len(index) == len(configs),
        f"{len(index)} of {len(configs)}",
    )

    width = max(len(label) for label, _, _ in results)
    all_ok = True
    for label, ok, detail in results:
        all_ok &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<{width}}  {detail}")
    print("=" * 78)
    print("All checks passed." if all_ok else "SOME CHECKS FAILED -- do not interpret these results.")
    return all_ok


# ======================================================================================
# Entry point
# ======================================================================================


def run(n_realisations: int = cfg.N_REALISATIONS, resume: bool = False) -> bool:
    """
    Run every pending configuration and self-check the output.

    Split out from :func:`main` so ``run_all.py`` can call it without going through
    ``argparse``. Returns whether the self-checks passed.
    """
    cfg.ensure_dirs()

    meta = json.loads(cfg.RECORD_META.read_text(encoding="utf-8"))

    # Load through MetDataset rather than pd.read_csv: the cache is parquet, so it
    # carries exact dtypes and the provenance step1 checked. Reading it as a frame would
    # also silently discard the record of which site and period this instrument measured.
    ds = MetDataset.load(meta["cache"])
    record = ds.met_data
    years = [int(y) for y in meta["years"]]

    configs = build_configs()
    done = _done_config_ids() if resume else set()
    pending = [c for c in configs if c["config_id"] not in done]

    print(f"Record : {meta['site_name']} {meta['start_year']}-{meta['end_year']}, "
          f"{len(years)} years, {len(record):,} rows")
    print(f"Days   : {[f'{m:02d}-{d:02d}' for m, d in cfg.DAYS]}")
    print(f"Window : +/-{cfg.WINDOW_N_DAYS} days  ({len(years) * (2 * cfg.WINDOW_N_DAYS + 1)} pooled days)")
    print(f"Bandw. : {[cfg.bandwidth_tag(b) for b in cfg.BANDWIDTHS]}  (+ anchor cell "
          f"{cfg.config_id(*cfg.ANCHOR)})")
    print(f"Configs: {len(configs)}" + (f" ({len(done)} already done, {len(pending)} pending)" if done else ""))
    print(f"n      : {n_realisations} realisations per configuration\n")

    first = not done
    started = time.perf_counter()
    with RunLock(cfg.RAW_DIR / ".run_lock"):
        outer = tqdm(pending, desc="configurations", unit="cfg", position=0,
                     dynamic_ncols=True, disable=None)
        for spec in outer:
            outer.set_postfix_str(
                spec["config_id"] + (" (anchor)" if spec["is_anchor"] else "")
            )
            frames = run_config(ds, spec, n_realisations)
            for name, frame in frames.items():
                _append(name, frame, first=first)
            first = False

    print(f"\nDone in {(time.perf_counter() - started) / 60:.1f} min. Wrote:")
    for name, filename in RAW_FILES.items():
        path = cfg.RAW_DIR / filename
        if path.exists():
            print(f"  {filename:<30} {len(pd.read_csv(path)):>8,} rows")

    return sanity_checks(configs, years)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=cfg.N_REALISATIONS,
                        help=f"realisations per configuration (default {cfg.N_REALISATIONS})")
    parser.add_argument("--resume", action="store_true",
                        help="skip configurations already present in the raw output")
    args = parser.parse_args()

    run(n_realisations=args.n, resume=args.resume)


if __name__ == "__main__":
    main()
