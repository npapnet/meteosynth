"""
Step 2 -- run every configuration and write the raw numbers to disk.

One configuration is *(training-set size k, year-subset draw, calendar day)*. For each,
this fits a generator on that year subset, draws ``n`` synthetic days for the target
date, collects the observed days the model was trained on, and writes both out.

Nothing is analysed here. Step 2 produces evidence; :mod:`step3_analyse` reads it back
from disk and interprets it. Keeping the two apart means any check made by hand against
the CSVs is a check against exactly what the analysis saw.

Run::

    uv run python examples/diagnostics-overshoot/step2_simulate.py
    uv run python examples/diagnostics-overshoot/step2_simulate.py --n 500
    uv run python examples/diagnostics-overshoot/step2_simulate.py --resume

Design notes worth knowing when reading the output:

* **Year subsets are nested.** For a given draw index the k=3 subset is a subset of the
  k=9 one, which is a subset of the full record. The size effect is therefore a
  *within-draw* comparison, not a comparison between unrelated year sets.
* **Common random numbers.** The seed depends on (day, draw) but **not** on k, so the
  same stochastic draws drive every size. Much of the Monte-Carlo noise cancels when
  sizes are compared.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

import config as cfg

from meteosynth import DayWindowGenerator, MetDataProcessor
from meteosynth.day_window import DAYS_IN_YEAR, day_slot, day_slots
from meteosynth.variables import get_spec

from tools.envelope import day_matrix  # noqa: E402  (needs cfg's sys.path insert)

def signed_circular_delta(slots: np.ndarray, centre: int) -> np.ndarray:
    """
    **Signed** offset from the centre slot, negative before and positive after.

    ``meteosynth.day_window.circular_delta`` is deliberately *unsigned* -- it answers
    "how far apart", which is what window selection needs. Detrending needs "which
    side", because a quadratic fitted against ``|offset|`` cannot represent a seasonal
    trend at all: it is symmetric by construction, so it folds a rising season and a
    falling one onto the same curve. Hence this local helper rather than the library's.
    """
    half = DAYS_IN_YEAR // 2
    return np.mod(np.asarray(slots) - centre + half, DAYS_IN_YEAR) - half


RAW_FILES = {
    "config_index": "config_index.csv",
    "observed_daily": "observed_daily_totals.csv",
    "synthetic_daily": "synthetic_daily_totals.csv",
    "observed_hourly": "observed_hourly.csv",
    "synthetic_hourly": "synthetic_hourly.csv",
    "references": "references.csv",
}


# ======================================================================================
# Design
# ======================================================================================


def build_configs(
    years: list[int], days: list[tuple[int, int]], n_draws: int
) -> list[dict]:
    """
    Enumerate every configuration, with its year subset and seed already resolved.

    Year subsets are **nested within a draw**: one random permutation of the record's
    years per draw index, then the first k of it. So draw 2's three-year subset sits
    inside draw 2's nine-year subset, and the size comparison is paired.

    The full record admits only one subset, so it is run once however many draws the
    smaller sizes get.
    """
    sizes = cfg.training_sizes(len(years))
    n_years = len(years)

    # One permutation per draw, drawn from a stream that depends only on the draw index
    # -- so the nesting is reproducible and independent of which sizes are run.
    permutations = {
        draw: np.random.default_rng(
            np.random.SeedSequence(cfg.MASTER_SEED, spawn_key=(1, draw))
        ).permutation(years)
        for draw in range(n_draws)
    }

    configs: list[dict] = []
    for month, day in days:
        day_index = cfg.DAYS.index((month, day)) if (month, day) in cfg.DAYS else 0
        for k in sizes:
            draws = [0] if k == n_years else list(range(n_draws))
            for draw in draws:
                subset = sorted(int(y) for y in permutations[draw][:k])
                configs.append(
                    {
                        "config_id": cfg.config_id(k, draw, month, day),
                        "k": k,
                        "draw": draw,
                        "month": month,
                        "day": day,
                        "years": subset,
                        # Seed depends on (day, draw) but NOT on k: common random
                        # numbers across sizes.
                        "seed": int(
                            np.random.SeedSequence(
                                cfg.MASTER_SEED, spawn_key=(2, day_index, draw)
                            ).generate_state(1)[0]
                        ),
                    }
                )
    return configs


# ======================================================================================
# References
# ======================================================================================


def compute_references(observed: pd.DataFrame) -> dict[str, tuple[float, int]]:
    """
    The three reference estimates of the target day's mean daily total.

    Returns ``{name: (value, m)}`` where ``m`` is how many observed values the estimate
    rests on -- which is the number that matters when its uncertainty is propagated,
    and which differs by an order of magnitude between the three.

    * ``pool_mean`` -- mean over the whole +/-15-day window. Lowest variance, but
      seasonally biased: the window is centred on the target, and where the seasonal
      curve bends, its mean is not the centre day's mean.
    * ``centre_mean`` -- mean over that exact calendar date only. Unbiased, but rests on
      one value per year, so ``m == k``.
    * ``detrended_centre`` -- quadratic fit of daily total against signed distance from
      the centre, evaluated at zero. Targets the same quantity as ``centre_mean`` while
      using every day in the window, so it is the low-variance estimator of it.
    """
    totals = observed["total_kwh_m2"].to_numpy(dtype=float)
    offsets = observed["days_from_centre"].to_numpy(dtype=float)
    centre = observed["is_centre"].to_numpy(dtype=bool)

    pool_mean = float(np.mean(totals))
    centre_mean = float(np.mean(totals[centre]))

    # Degree 2 in the signed offset; the constant term is the value at the centre.
    # Fitted on the window, so it uses 31x more data than centre_mean does.
    fit = np.polynomial.Polynomial.fit(offsets, totals, deg=2)
    detrended_centre = float(fit(0.0))

    return {
        "pool_mean": (pool_mean, int(totals.size)),
        "centre_mean": (centre_mean, int(centre.sum())),
        "detrended_centre": (detrended_centre, int(totals.size)),
    }


# ======================================================================================
# One configuration
# ======================================================================================


def _observed_frames(
    mdp: MetDataProcessor, month: int, day: int, config_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Observed daily totals and hourly values for the training window."""
    window = day_matrix(mdp, cfg.ATTR, month, day, n_days=cfg.WINDOW_N_DAYS)

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
            "total_kwh_m2": window.sum(axis=1).to_numpy() / 1000.0,
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
    ensemble: np.ndarray, references: dict[str, tuple[float, int]], config_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic daily totals -- with a deviation per reference -- and hourly values."""
    totals = ensemble.sum(axis=1) / 1000.0

    daily = pd.DataFrame(
        {
            "config_id": config_id,
            "realisation": np.arange(ensemble.shape[0]),
            "total_kwh_m2": totals,
        }
    )
    for name in cfg.REFERENCES:
        value, _ = references[name]
        daily[f"dev_{name}"] = (totals - value) / value

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


def run_config(record: pd.DataFrame, spec: dict, n_realisations: int) -> dict:
    """Fit, sample and collect one configuration. Returns one frame per raw file."""
    subset = record[record["year"].isin(spec["years"])]
    mdp = MetDataProcessor(subset)

    observed_daily, observed_hourly = _observed_frames(
        mdp, spec["month"], spec["day"], spec["config_id"]
    )
    references = compute_references(observed_daily)

    generator = DayWindowGenerator(
        mdp, cfg.ATTR, n_days=cfg.WINDOW_N_DAYS, bandwidth=cfg.BANDWIDTH
    )
    day_generator = generator.for_day(spec["month"], spec["day"])

    # One Generator drives the whole ensemble, so the draws are independent of one
    # another but the ensemble as a whole is reproducible from the single seed.
    rng = np.random.default_rng(spec["seed"])
    ensemble = np.vstack([day_generator.gen_day(rng=rng) for _ in range(n_realisations)])

    synthetic_daily, synthetic_hourly = _synthetic_frames(
        ensemble, references, spec["config_id"]
    )

    reference_rows = pd.DataFrame(
        [
            {
                "config_id": spec["config_id"],
                "reference": name,
                "value_kwh_m2": value,
                "m": m,
            }
            for name, (value, m) in references.items()
        ]
    )

    observed_totals = observed_daily["total_kwh_m2"]
    index_row = pd.DataFrame(
        [
            {
                "config_id": spec["config_id"],
                "k": spec["k"],
                "draw": spec["draw"],
                "years": ",".join(str(y) for y in spec["years"]),
                "month": spec["month"],
                "day": spec["day"],
                "seed": spec["seed"],
                "n": n_realisations,
                "n_obs_window": len(observed_daily),
                "n_obs_centre": int(observed_daily["is_centre"].sum()),
                "obs_sd_kwh_m2": float(observed_totals.std(ddof=1)),
                "obs_cv": float(observed_totals.std(ddof=1) / observed_totals.mean()),
            }
        ]
    )

    return {
        "config_index": index_row,
        "observed_daily": observed_daily,
        "synthetic_daily": synthetic_daily,
        "observed_hourly": observed_hourly,
        "synthetic_hourly": synthetic_hourly,
        "references": reference_rows,
    }


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


def sanity_checks(configs: list[dict]) -> bool:
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

    # 1. Hourly values reconcile with the daily totals they were summed into.
    for label, hourly, daily, keys in (
        ("observed", obs_hourly, obs_daily, ["config_id", "date"]),
        ("synthetic", syn_hourly, syn_daily, ["config_id", "realisation"]),
    ):
        recomputed = hourly.groupby(keys)[value_col].sum() / 1000.0
        stated = daily.set_index(keys)["total_kwh_m2"]
        aligned = recomputed.reindex(stated.index)
        worst = float((aligned - stated).abs().max())
        check(f"{label}: sum(hourly)/1000 == daily total", worst < 1e-9, f"max |diff| {worst:.3e}")

    # 2. Row counts follow from k: one centre day per year, 31 slots per year in window.
    counts = obs_daily.groupby("config_id").agg(
        n_window=("total_kwh_m2", "size"), n_centre=("is_centre", "sum")
    )
    merged = index.set_index("config_id").join(counts)
    check(
        "observed: centre-day count == k",
        bool((merged["n_centre"] == merged["k"]).all()),
        f"{int((merged['n_centre'] != merged['k']).sum())} mismatched",
    )
    expected_window = merged["k"] * (2 * cfg.WINDOW_N_DAYS + 1)
    check(
        "observed: window count == k x 31",
        bool((merged["n_window"] == expected_window).all()),
        f"{int((merged['n_window'] != expected_window).sum())} mismatched",
    )

    # 2b. Offsets are signed and symmetric about the centre. An unsigned offset column
    #     silently turns the detrending fit into something that cannot represent a
    #     seasonal trend at all, and nothing else downstream would have complained.
    offsets = obs_daily.groupby("config_id")["days_from_centre"]
    check(
        "observed: days_from_centre is signed and symmetric",
        bool(
            (offsets.min() == -cfg.WINDOW_N_DAYS).all()
            and (offsets.max() == cfg.WINDOW_N_DAYS).all()
            and offsets.mean().abs().max() < 1e-9
        ),
        f"range [{obs_daily['days_from_centre'].min()}, {obs_daily['days_from_centre'].max()}]",
    )

    # 3. The year subsetting did what the index claims -- the direct test that a
    #    configuration trained on the years it says it did.
    declared = {
        row.config_id: {int(y) for y in str(row.years).split(",")}
        for row in index.itertuples()
    }
    actual = obs_daily.groupby("config_id")["year"].apply(lambda s: set(s.astype(int)))
    leaked = {cid: actual[cid] - declared[cid] for cid in declared if actual[cid] - declared[cid]}
    check("observed: no year outside the declared subset", not leaked, f"{len(leaked)} leaking")

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

    # 6. Daily totals plausible against the observed record. A soft check: a synthetic
    #    day far above anything the site has ever recorded is a red flag, not proof of a
    #    bug, so it warns rather than fails.
    obs_max = obs_daily["total_kwh_m2"].max()
    syn_max = syn_daily["total_kwh_m2"].max()
    check(
        "synthetic: daily max within 1.5x the observed max",
        syn_max <= 1.5 * obs_max,
        f"synthetic {syn_max:.2f} vs observed {obs_max:.2f} {cfg.DAILY_UNIT}",
    )

    # 7. Every configuration asked for is present, exactly once. A duplicate config_id
    #    means two runs appended to the same files -- the output is interleaved from
    #    two different simulations and cannot be interpreted.
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=cfg.N_REALISATIONS,
                        help=f"realisations per configuration (default {cfg.N_REALISATIONS})")
    parser.add_argument("--draws", type=int, default=cfg.N_DRAWS,
                        help=f"year-subset draws per size (default {cfg.N_DRAWS})")
    parser.add_argument("--resume", action="store_true",
                        help="skip configurations already present in the raw output")
    args = parser.parse_args()

    cfg.ensure_dirs()

    meta = json.loads(cfg.RECORD_META.read_text(encoding="utf-8"))
    record = pd.read_csv(meta["cache"])
    years = [int(y) for y in meta["years"]]

    configs = build_configs(years, cfg.DAYS, args.draws)
    done = _done_config_ids() if args.resume else set()
    pending = [c for c in configs if c["config_id"] not in done]

    print(f"Record : {meta['site_name']} {meta['start_year']}-{meta['end_year']}, "
          f"{len(years)} years, {len(record):,} rows")
    print(f"Days   : {[f'{m:02d}-{d:02d}' for m, d in cfg.DAYS]}")
    print(f"Sizes  : {cfg.training_sizes(len(years))} years")
    print(f"Configs: {len(configs)}" + (f" ({len(done)} already done, {len(pending)} pending)" if done else ""))
    print(f"n      : {args.n} realisations per configuration\n")

    first = not done
    started = time.perf_counter()
    with RunLock(cfg.RAW_DIR / ".run_lock"):
        for i, spec in enumerate(pending, start=1):
            config_started = time.perf_counter()
            frames = run_config(record, spec, args.n)
            for name, frame in frames.items():
                _append(name, frame, first=first)
            first = False
            elapsed = time.perf_counter() - config_started

            if i == 1 and len(pending) > 1:
                print(f"  first configuration took {elapsed:.1f} s -- "
                      f"estimated total {elapsed * len(pending) / 60:.1f} min\n", flush=True)
            print(f"  [{i:2d}/{len(pending)}] {spec['config_id']}  "
                  f"k={spec['k']:2d} draw={spec['draw']}  "
                  f"years {spec['years'][0]}-{spec['years'][-1]}  ({elapsed:.1f} s)",
                  flush=True)

    print(f"\nDone in {(time.perf_counter() - started) / 60:.1f} min. Wrote:")
    for name, filename in RAW_FILES.items():
        path = cfg.RAW_DIR / filename
        if path.exists():
            print(f"  {filename:<30} {len(pd.read_csv(path)):>8,} rows")

    sanity_checks(configs)


if __name__ == "__main__":
    main()
