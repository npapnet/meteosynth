"""
What actually drives generation time? Leros, 4 days, timings written to JSON.

Four sweeps, each answering one question, because crossing them would cost several times
the runtime for nothing:

===========  ==========================================================================
Sweep A      Does cost scale with the number of realisations?  (``poa_global``, N 10-1000)
Sweep B      How is a day's cost split between the attributes? (each alone, one N)
Sweep C      How much does an identical run vary?              (one config, repeated)
Sweep D      Do B's three sum to one run that does all three?  (the additivity control)
===========  ==========================================================================

The answer Sweep A exists to give is **no**: cost is ``attributes x days`` and is set by a
per-day-per-attribute grid build, not by how many realisations come out. Sweep B is what
turns "a day costs X" into "a day costs X *because of* these attributes"; C sets the
threshold below which a difference between runs is machine noise; D is the only check that
the decomposition adds up.

**Read ratios, never seconds.** Every absolute duration here is a property of the machine
that produced it as much as of the code, and means nothing until set against another
measurement from *the same machine*.

Run::

    uv run python examples/benchmark/leros_timing_benchmark.py

**Roughly 14 minutes.** Nothing here is a usable ensemble -- four days, and the parquet is
deleted once its size has been recorded unless ``KEEP_PARQUET`` says otherwise. One JSON
per run lands in ``benchmarks/``, named for the machine and git-ignored; the script then
compares against the newest earlier run at a compatible ``BENCHMARK_VERSION`` and flags
rows that clear the measured noise floor.

**Why it is built this way** -- the two controls (``SAMPLING``, ``WARMUP``), the runtime
budget and which knob to turn, the noise floor's known limitation (``CHORE-22``), and how
this got from 24.7 min to 14 -- is in `README.md` beside this file. The configuration
constants below carry the rest.
"""

#%%
from __future__ import annotations

import json
import os
import platform
import statistics
import time
from datetime import datetime, timezone

import pandas as pd

import meteosynth
from meteosynth import workspace
from meteosynth.adapters import fetch_pvgis
from meteosynth.ensemble import write_ensemble

#%%
# --- Configuration -------------------------------------------------------------------

#: Recorded inside every JSON, so a comparison can tell a slower machine from a changed
#: benchmark. Bump the **major** part when a measurement changes meaning -- a different day
#: count, a different control, anything that makes an old number describe something else;
#: the history comparison then refuses that file outright rather than reporting a phantom
#: regression. Bump the **minor** part when a sweep is merely added or refined: older files
#: still compare on the rows they share.
BENCHMARK_VERSION = "4.2"

LATITUDE = 37.167
LONGITUDE = 26.800
SITE = "leros"

ATTRS = ["poa_global", "temp_air", "wind_speed"]
REFERENCE_YEAR = 2023

#: **The cheapest attribute, and what Sweep A sweeps.** Cost is
#: ``attributes x days`` and independent of N -- which is precisely what Sweep A exists to
#: show -- so sweeping N on three attributes measures the same fact three times over at
#: three times the price. Sweeping the cheapest one says it just as well.
SWEEP_ATTR = "poa_global"

#: Sweep A: one timed run per entry, on :data:`SWEEP_ATTR` alone.
REALISATION_COUNTS = [10, 100, 1000]

#: Sweep B: one timed run per attribute, all at this N. Picked at the top of Sweep A's
#: range so the split is measured where the cached path is doing real work.
ATTR_SPLIT_N = 1000

#: Sweep D: the additivity control -- all three attributes in **one** run, against the sum
#: of Sweep B's three. A gap would mean something other than fitting and drawing is on the
#: clock (the calendar walk, the parquet write). It used to fall out of Sweep A for free;
#: now that Sweep A runs one attribute, it is paid for explicitly. It is the single most
#: expensive row here, so it is also the first thing to switch off for a quick check.
CROSS_CHECK = True

#: One discarded generation before any timing starts, so the first *measured* run is not
#: also the first run in the process. Without it Sweep A's baseline carries ~12 % of
#: warm-up that no other row pays -- see the warm-up section below. Off only to reproduce
#: a pre-4.1 file.
WARMUP = True

#: Sweep C: repeats of one fixed configuration, to measure run-to-run scatter. The
#: cheapest attribute, so that a useful number of repeats stays affordable -- the floor is
#: therefore measured on one configuration and assumed to carry to the others. Three is
#: the minimum that gives a spread at all; raise it if the CV itself looks unstable.
NOISE_REPEATS = 3
NOISE_ATTR = "poa_global"
NOISE_N = 1000

#: Multiple of the measured CV a difference must clear before the history comparison calls
#: it a change rather than scatter. The floor stops an unusually quiet set of repeats from
#: producing an absurdly tight threshold.
NOISE_SIGMA = 3.0
MIN_THRESHOLD_PCT = 2.0

#: Short on purpose -- the per-day cost is what is being measured, not a usable year.
#: Every timing here is linear in this, so it is the one knob that scales the whole run.
#:
#: **The first calendar day of every run costs ~16 % more than the rest** -- measured
#: 10.3 s against a steady ~8.9 s on ``poa_global`` at N = 1000, and reproduced in every
#: repeat. So a lower count inflates the reported seconds-per-day: about +4 % at 4 days
#: against +3 % at 5 and +5 % at 3. **Every row pays it identically, so no ratio moves** --
#: which is why a short count is affordable, and why this file insists on ratios over
#: seconds.
#:
#: **4 rather than 3** buys back sensitivity: the per-day mean averages one more sample and
#: the warm-up is a quarter of the run instead of a third, which narrows Sweep C's noise
#: floor -- the threshold every comparison against an earlier run is judged by.
N_DAYS = 4

WINDOW_DAYS = 15
SEED = 2026

#: Forced for every run, so the 64-realisation crossover cannot confound the comparison:
#: left on ``"auto"``, a 10-realisation run would take the exact path and a 1000-realisation
#: run the cached grid, and the two would differ by *which algorithm ran* as much as by
#: size. Named explicitly since `FEAT-17` replaced ``precompute=True``; same behaviour.
SAMPLING = "grid"

FORCE_REFETCH = False
PROGRESS = True

#: The parquet files are byproducts; their only interesting property is their size, and
#: that is recorded before they go. True keeps them for inspection.
KEEP_PARQUET = False

#: This script's own folder. Everything it touches -- the training record in `data/`, the
#: timings in `benchmarks/` -- sits beside it rather than under the working directory: a
#: benchmark belongs with the benchmark that produced it.
WS = workspace(globals().get("__file__"))

#: Timing results, and the throwaway parquets whose only interesting property is size.
#: Its own folder rather than `output/`, because these are machine-specific measurements
#: compared against each other over time, not a product of a run.
BENCHMARK_DIR = WS.root / "benchmarks"

#: Hostname, lowercased and stripped to something safe in a filename.
MACHINE_SLUG = "".join(
    c if c.isalnum() else "-" for c in platform.node().strip().lower()
).strip("-") or "unknown-machine"

#%%
# --- Machine and environment ---------------------------------------------------------
# Recorded because a timing without them is not a measurement of anything transferable.


def describe_machine() -> dict:
    """Identity of the box these numbers were produced on."""
    return {
        "node": platform.node(),
        "slug": MACHINE_SLUG,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def describe_environment() -> dict:
    """Versions that could move a timing without the hardware changing."""
    versions = {"python": platform.python_version(), "meteosynth": meteosynth.__version__}
    for name in ("numpy", "scipy", "pandas", "pyarrow"):
        try:
            versions[name] = __import__(name).__version__
        except Exception:                                    # pragma: no cover
            versions[name] = None
    return versions


MACHINE = describe_machine()
ENVIRONMENT = describe_environment()

print(f"machine: {MACHINE['node']}  ({MACHINE['cpu_count']} CPUs)")
print(f"  {MACHINE['platform']}")
print(f"  {MACHINE['processor']}")
print(f"  python {ENVIRONMENT['python']}, meteosynth {ENVIRONMENT['meteosynth']}")
print(f"benchmark version {BENCHMARK_VERSION}, results -> {BENCHMARK_DIR}")

#%%
# --- 1. The training record ----------------------------------------------------------
# Fetched once into the default store and reused by every run, so no row pays for
# collection and every row trains on identical data.

print(f"\nTraining record for {SITE} ({LATITUDE}, {LONGITUDE})")
print(f"  {WS.describe()}")

dataset = fetch_pvgis(
    LATITUDE, LONGITUDE, site=SITE, data_dir=WS.data_dir, force_refetch=FORCE_REFETCH
)

print(f"  {dataset.describe_time_range()}, {len(dataset.met_data):,} hourly rows")

missing = [a for a in ATTRS if a not in dataset.met_data.columns]
if missing:
    raise ValueError(
        f"the record does not hold {missing}. Available: {list(dataset.variables)}."
    )

#%%
# --- 2. One timed run ----------------------------------------------------------------


def timed_run(
    sweep: str, attrs: list, n_realisations: int, repeat: int | None = None
) -> dict:
    """
    Generate once and record what it cost.

    Parameters
    ----------
    sweep : str
        Which experiment this row belongs to: ``"n_scaling"``, ``"per_attribute"`` or
        ``"noise_floor"``.
    attrs : list of str
        Attributes to generate in this run.
    n_realisations : int
        Realisations to draw.
    repeat : int, optional
        Which repeat of an identical configuration this is. Only Sweep C sets it.

    Returns
    -------
    dict
        One JSON-serialisable row.
    """
    label = "+".join(attrs)
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if repeat is None else f"_r{repeat}"
    path = BENCHMARK_DIR / (
        f"bench_{SITE}_n{n_realisations}_d{N_DAYS}_{label}{suffix}.parquet"
    )

    tag = "" if repeat is None else f" repeat {repeat}"
    print(
        f"\n=== [{sweep}{tag}] {n_realisations} realisations x {N_DAYS} days x "
        f"{len(attrs)} attr ({label}) ==="
    )

    start_dt = datetime.now(timezone.utc)
    start_perf = time.perf_counter()

    write_ensemble(
        dataset, attrs, path,
        start=(1, 1),
        n_days=N_DAYS,
        n_realisations=n_realisations,
        seed=SEED,
        n_days_window=WINDOW_DAYS,
        include_feb29=False,
        progress=PROGRESS,
        sampling=SAMPLING,
    )

    total_seconds = time.perf_counter() - start_perf
    end_dt = datetime.now(timezone.utc)
    output_mb = round(path.stat().st_size / 1024**2, 3)

    if not KEEP_PARQUET:
        path.unlink()

    row = {
        "sweep": sweep,
        "repeat": repeat,
        "attrs": list(attrs),
        "attrs_label": label,
        "n_attrs": len(attrs),
        "n_realisations": n_realisations,
        "n_days": N_DAYS,
        "window_days": WINDOW_DAYS,
        "sampling": SAMPLING,
        "seed": SEED,
        "start_time": start_dt.isoformat(timespec="seconds"),
        "end_time": end_dt.isoformat(timespec="seconds"),
        "total_seconds": round(total_seconds, 2),
        "seconds_per_day": round(total_seconds / N_DAYS, 2),
        "seconds_per_realisation_day": round(
            total_seconds / (N_DAYS * n_realisations), 6
        ),
        "output_mb": output_mb,
    }
    print(f"  -> {total_seconds:.1f} s total, {row['seconds_per_day']:.1f} s/day")
    return row


#%%
# --- 2b. Warm-up: one run, timed by nobody -------------------------------------------
# **The first generation in a process is systematically slow**, over and above the
# first-*day* effect every run pays. Measured at 4 days: Sweep A's opening row came in at
# 11.1 s/day against 9.8 and 10.1 for the two after it -- a 12 % inflation landing squarely
# on the baseline every other Sweep A row is divided by, which read as "100x the
# realisations runs 0.91x the time". The same fingerprint sits in Sweep C, whose first
# repeat is the slowest of the three in every run recorded.
#
# It was invisible before `BENCHMARK_VERSION` 3.0 only because Sweep A's rows were then
# 330 s of three-attribute work, which amortised it away. At 40 s rows it exceeds the
# noise floor the benchmark reports, so it has to be paid off rather than measured.
#
# One day at the cheapest attribute, discarded: enough to touch every code path a timed
# run touches, for ~3 % of the total.

if WARMUP:
    print("\nWarm-up run (discarded) -- paying off first-in-process overhead...")
    _warm_started = time.perf_counter()
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    _warm_path = BENCHMARK_DIR / f"warmup_{SITE}.parquet"
    # Deliberately the same call `timed_run` makes, so the warm-up touches every path a
    # measured run touches. One day only: this is a payment, not a measurement.
    write_ensemble(
        dataset, [SWEEP_ATTR], _warm_path,
        start=(1, 1),
        n_days=1,
        n_realisations=NOISE_N,
        seed=SEED,
        n_days_window=WINDOW_DAYS,
        include_feb29=False,
        progress=False,
        sampling=SAMPLING,
    )
    _warm_path.unlink(missing_ok=True)
    print(f"  discarded after {time.perf_counter() - _warm_started:.1f} s")

#%%
# --- 3. Sweep A: does cost scale with N? ---------------------------------------------
# One attribute, the cheapest; only N changes. Three attributes would answer the same
# question three times over -- see SWEEP_ATTR.

benchmark_started = time.perf_counter()
benchmark_start_dt = datetime.now(timezone.utc)

runs = []
for n_realisations in REALISATION_COUNTS:
    runs.append(timed_run("n_scaling", [SWEEP_ATTR], n_realisations))

#%%
# --- 4. Sweep B: where does the total go? --------------------------------------------
# One attribute at a time, all at the same N, so the only thing changing is which
# quantity is being generated.

for attr in ATTRS:
    runs.append(timed_run("per_attribute", [attr], ATTR_SPLIT_N))

#%%
# --- 4b. Sweep C: how much does an identical run vary? --------------------------------
# The same configuration, repeated. Nothing changes between these rows, so everything that
# separates them is machine noise -- which is the only yardstick that makes a comparison
# against an earlier run mean anything.

for repeat in range(1, NOISE_REPEATS + 1):
    runs.append(timed_run("noise_floor", [NOISE_ATTR], NOISE_N, repeat=repeat))

#%%
# --- 4c. Sweep D: the additivity control ----------------------------------------------
# All three attributes in one run, to be set against the sum of Sweep B's three. The one
# row here that exists to be *compared* rather than to measure something new.

if CROSS_CHECK:
    runs.append(timed_run("combined", ATTRS, ATTR_SPLIT_N))

benchmark_seconds = time.perf_counter() - benchmark_started

#%%
# --- 5. Derived comparisons ----------------------------------------------------------
# Computed here rather than left to the reader, so the JSON answers the questions the
# script was written to ask without anyone recomputing ratios by hand.

n_rows = [r for r in runs if r["sweep"] == "n_scaling"]
attr_rows = [r for r in runs if r["sweep"] == "per_attribute"]
noise_rows = [r for r in runs if r["sweep"] == "noise_floor"]
combined_rows = [r for r in runs if r["sweep"] == "combined"]

noise_samples = [r["seconds_per_day"] for r in noise_rows]
noise_mean = statistics.fmean(noise_samples)
noise_sd = statistics.stdev(noise_samples) if len(noise_samples) > 1 else 0.0
noise_cv_pct = round(100 * noise_sd / noise_mean, 2) if noise_mean else 0.0

#: Anything smaller than this, between two runs, is scatter rather than a change.
change_threshold_pct = round(
    max(NOISE_SIGMA * noise_cv_pct, MIN_THRESHOLD_PCT), 2
)

noise_floor = {
    "attr": NOISE_ATTR,
    "n_realisations": NOISE_N,
    "repeats": len(noise_rows),
    "samples_seconds_per_day": noise_samples,
    "mean_seconds_per_day": round(noise_mean, 2),
    "stdev_seconds_per_day": round(noise_sd, 3),
    "cv_pct": noise_cv_pct,
    "spread_pct": (
        round(100 * (max(noise_samples) - min(noise_samples)) / noise_mean, 2)
        if noise_mean else 0.0
    ),
    "change_threshold_pct": change_threshold_pct,
    "threshold_rule": f"{NOISE_SIGMA}x CV, floored at {MIN_THRESHOLD_PCT}%",
}

baseline = n_rows[0]
n_scaling = {
    "baseline_n": baseline["n_realisations"],
    "baseline_seconds_per_day": baseline["seconds_per_day"],
    "points": [
        {
            "n_realisations": r["n_realisations"],
            "seconds_per_day": r["seconds_per_day"],
            "time_ratio_vs_baseline": round(
                r["seconds_per_day"] / baseline["seconds_per_day"], 3
            ),
            "n_ratio_vs_baseline": round(
                r["n_realisations"] / baseline["n_realisations"], 1
            ),
            "seconds_per_realisation_day": r["seconds_per_realisation_day"],
            "output_mb": r["output_mb"],
        }
        for r in n_rows
    ],
}

attr_total_per_day = sum(r["seconds_per_day"] for r in attr_rows)
# Sweep D, when it ran. Until 3.0 this came free from Sweep A's three-attribute rows;
# Sweep A now runs one attribute, so the control is its own row and can be switched off.
combined_at_split_n = next(
    (r for r in combined_rows if r["n_realisations"] == ATTR_SPLIT_N), None
)
cheapest = min(attr_rows, key=lambda r: r["seconds_per_day"])

per_attribute = {
    "n_realisations": ATTR_SPLIT_N,
    "sum_seconds_per_day": round(attr_total_per_day, 2),
    "combined_run_seconds_per_day": (
        combined_at_split_n["seconds_per_day"] if combined_at_split_n else None
    ),
    "separate_vs_combined_overhead_ratio": (
        round(attr_total_per_day / combined_at_split_n["seconds_per_day"], 3)
        if combined_at_split_n else None
    ),
    "cheapest_attr": cheapest["attrs_label"],
    "attributes": [
        {
            "attr": r["attrs_label"],
            "seconds_per_day": r["seconds_per_day"],
            "share_of_sum": round(r["seconds_per_day"] / attr_total_per_day, 3),
            "cost_vs_cheapest": round(
                r["seconds_per_day"] / cheapest["seconds_per_day"], 2
            ),
        }
        for r in sorted(attr_rows, key=lambda r: r["seconds_per_day"])
    ],
}

#%%
# --- 6. Write the JSON ---------------------------------------------------------------

BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
stamp = benchmark_start_dt.strftime("%Y%m%d-%H%M%S")
results_path = BENCHMARK_DIR / f"{MACHINE_SLUG}_leros_timing_{stamp}.json"

payload = {
    "benchmark_version": BENCHMARK_VERSION,
    "benchmark_script": "leros_timing_benchmark.py",
    "run_started": benchmark_start_dt.isoformat(timespec="seconds"),
    "benchmark_total_seconds": round(benchmark_seconds, 2),
    "machine": MACHINE,
    "environment": ENVIRONMENT,
    "site": {
        "name": SITE,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "training_range": dataset.describe_time_range(),
        "training_rows": int(len(dataset.met_data)),
    },
    "config": {
        "attrs": ATTRS,
        "reference_year": REFERENCE_YEAR,
        "realisation_counts": REALISATION_COUNTS,
        "attr_split_n": ATTR_SPLIT_N,
        "noise_repeats": NOISE_REPEATS,
        "noise_attr": NOISE_ATTR,
        "noise_n": NOISE_N,
        "n_days": N_DAYS,
        "window_days": WINDOW_DAYS,
        "seed": SEED,
        "sampling": SAMPLING,
    },
    "runs": runs,
    "summary": {
        "n_scaling": n_scaling,
        "per_attribute": per_attribute,
        "noise_floor": noise_floor,
    },
}

results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

#%%
# --- 7. Compare against this machine's history ----------------------------------------
# Same machine, same benchmark version, or the comparison is not one. A difference inside
# the noise floor measured above is scatter, and saying so is the point -- an unqualified
# "3 % slower" invites chasing thermal state.


def _major(version: str | None) -> str:
    """Leading component of a version string, or ``""`` if there is not one."""
    return str(version).split(".")[0] if version else ""


def load_history() -> list:
    """
    Earlier results from this machine at this benchmark version, oldest first.

    Returns
    -------
    list of dict
        Payloads, excluding the run just written.
    """
    found = []
    for candidate in sorted(BENCHMARK_DIR.glob(f"{MACHINE_SLUG}_leros_timing_*.json")):
        if candidate == results_path:
            continue
        try:
            earlier = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:       # pragma: no cover
            print(f"  skipping unreadable {candidate.name}: {exc}")
            continue
        # Major version only. A minor bump adds or refines a sweep, and rows that do not
        # exist on both sides are dropped individually below -- so an older file still
        # contributes whatever it does have. A major bump means a measurement changed
        # meaning, and then nothing in the file can be trusted to line up.
        if _major(earlier.get("benchmark_version")) != _major(BENCHMARK_VERSION):
            print(
                f"  skipping {candidate.name}: benchmark version "
                f"{earlier.get('benchmark_version')} is not compatible with "
                f"{BENCHMARK_VERSION}"
            )
            continue
        earlier["_file"] = candidate.name
        found.append(earlier)
    return sorted(found, key=lambda p: p.get("run_started", ""))


def row_key(row: dict) -> tuple:
    """
    Identity of a measurement, for matching one run's rows against another's.

    Read with ``.get`` rather than ``[]``, because the whole point of matching on major
    version is that an older file is allowed through -- and an older file predates
    whatever fields the current version added. ``repeat`` arrived in 2.1; a 2.0 row has
    no such key and must still match on the three fields it does have.
    """
    return (
        row.get("sweep"),
        row.get("attrs_label"),
        row.get("n_realisations"),
        row.get("repeat"),
    )


print("\n" + "=" * 78)
print(f"Comparison against earlier runs on {MACHINE['node']}")
print("=" * 78)

history = load_history()
comparison = None

if not history:
    print("  No earlier run at this benchmark version. This one becomes the baseline.")
else:
    previous = history[-1]
    print(f"  {len(history)} earlier run(s); comparing against {previous['_file']}")
    print(
        f"  a change must exceed {change_threshold_pct:.1f} % "
        f"({noise_floor['threshold_rule']}) to count as one"
    )

    drifted = {
        k: (previous.get("environment", {}).get(k), v)
        for k, v in ENVIRONMENT.items()
        if previous.get("environment", {}).get(k) != v
    }
    if drifted:
        print("  ! environment differs -- a difference below may not be the machine:")
        for name, (was, now) in drifted.items():
            print(f"      {name}: {was} -> {now}")

    earlier_rows = {row_key(r): r for r in previous["runs"]}
    deltas = []
    for row in runs:
        was = earlier_rows.get(row_key(row))
        if was is None or was.get("seconds_per_day") is None:
            continue
        before, now = was["seconds_per_day"], row["seconds_per_day"]
        pct = 100 * (now - before) / before if before else 0.0
        deltas.append({
            "sweep": row["sweep"],
            "attrs_label": row["attrs_label"],
            "n_realisations": row["n_realisations"],
            "repeat": row["repeat"],
            "before_seconds_per_day": before,
            "now_seconds_per_day": now,
            "delta_pct": round(pct, 2),
            "beyond_noise": abs(pct) > change_threshold_pct,
        })

    print()
    for d in deltas:
        verdict = (
            f"{'SLOWER' if d['delta_pct'] > 0 else 'FASTER'}"
            if d["beyond_noise"] else "within noise"
        )
        rep = "" if d["repeat"] is None else f" r{d['repeat']}"
        print(
            f"  {d['sweep']:<13} {d['attrs_label']:<30}{rep:<4} "
            f"N={d['n_realisations']:<5} "
            f"{d['before_seconds_per_day']:>6.1f} -> {d['now_seconds_per_day']:>6.1f} "
            f"s/day  {d['delta_pct']:>+6.1f} %  {verdict}"
        )

    changed = [d for d in deltas if d["beyond_noise"]]
    print(
        f"\n  {len(changed)} of {len(deltas)} rows moved beyond the noise floor."
        if deltas else "\n  No comparable rows."
    )

    comparison = {
        "compared_against": previous["_file"],
        "compared_against_started": previous.get("run_started"),
        "earlier_runs_available": len(history),
        "change_threshold_pct": change_threshold_pct,
        "environment_drift": {k: {"was": w, "now": n} for k, (w, n) in drifted.items()},
        "rows": deltas,
    }

# Rewrite with the comparison folded in, so the file is self-contained: what was measured
# and what it meant relative to this machine's own past.
payload["comparison"] = comparison
results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

#%%
# --- 8. Report -----------------------------------------------------------------------

results = pd.DataFrame(runs)

print("\n" + "=" * 78)
print(results[[
    "sweep", "attrs_label", "n_realisations", "total_seconds", "seconds_per_day",
    "output_mb",
]].to_string(index=False))
print("=" * 78)

print(f"\nSweep A -- N scaling, {SWEEP_ATTR} alone, relative to "
      f"N={n_scaling['baseline_n']}:")
for p in n_scaling["points"]:
    print(
        f"  N={p['n_realisations']:>5}  {p['seconds_per_day']:>7.1f} s/day  "
        f"= {p['time_ratio_vs_baseline']:>5.2f}x time for "
        f"{p['n_ratio_vs_baseline']:>5.0f}x the realisations"
    )

print(f"\nSweep B -- where the total goes, at N={ATTR_SPLIT_N} "
      f"(cheapest: {per_attribute['cheapest_attr']}):")
for a in per_attribute["attributes"]:
    print(
        f"  {a['attr']:<14} {a['seconds_per_day']:>7.1f} s/day  "
        f"= {a['share_of_sum'] * 100:>4.1f}% of the sum, "
        f"{a['cost_vs_cheapest']:>4.2f}x the cheapest"
    )
if combined_at_split_n:
    print(
        f"\nSweep D -- additivity control, all {len(ATTRS)} attributes in one run:\n"
        f"  sum of the three {per_attribute['sum_seconds_per_day']:.1f} s/day vs "
        f"combined {per_attribute['combined_run_seconds_per_day']} s/day "
        f"(ratio {per_attribute['separate_vs_combined_overhead_ratio']})"
    )
else:
    print("\nSweep D -- additivity control: skipped (CROSS_CHECK = False)")

print(f"\nSweep C -- run-to-run scatter, {noise_floor['repeats']} repeats of "
      f"{NOISE_ATTR} at N={NOISE_N}:")
print(f"  {', '.join(f'{s:.1f}' for s in noise_samples)} s/day")
print(
    f"  mean {noise_floor['mean_seconds_per_day']:.1f}, "
    f"sd {noise_floor['stdev_seconds_per_day']:.2f}, "
    f"CV {noise_cv_pct:.2f} %, spread {noise_floor['spread_pct']:.2f} %"
)
print(f"  -> a run-to-run difference counts as real above "
      f"{change_threshold_pct:.1f} %")

print(f"\nBenchmark total: {benchmark_seconds / 60:.1f} min")
print(f"Written: {results_path}")
print("Seconds here describe this machine only; compare ratios across machines, "
      "seconds only against itself.")

results

#%%
