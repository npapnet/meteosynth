"""
Step 1 -- probe PVGIS for the widest record it will serve, fetch it, cache it.

The analysis needs as many years as the provider has, because the whole question is how
the bias behaves as the training record grows. Rather than hard-coding a range that
silently rots when PVGIS extends its coverage, this probes the API and records what it
actually got.

Run::

    uv run python examples/diagnostics-overshoot/step1_fetch.py

Cheap and idempotent: with a warm cache it re-reads the file and re-writes the metadata
without touching the network.
"""

from __future__ import annotations

import json

import config as cfg

from meteosynth.adapters import fetch_pvgis, probe_year_range as _probe

from tools.site_data import HERAKLION  # noqa: E402  (needs cfg's sys.path insert)


def probe_year_range(latitude: float, longitude: float) -> tuple[int, int]:
    """
    Ask PVGIS what year range it serves, falling back to the configured range.

    The probe itself now lives in :func:`meteosynth.adapters.probe_year_range` -- it was
    written here first, and moved into the library when ``FEAT-4`` made "collect the
    widest range" the default rather than something this diagnostic did by hand.

    What stays here is the **fallback**: this harness would rather run on
    :data:`config.REQUESTED_YEARS` than not run at all, whereas the library refuses,
    because silently truncating someone's training record is worse than stopping.
    """
    print("Probing PVGIS for the available year range...")
    try:
        start, end = _probe(latitude, longitude)
    except RuntimeError as exc:
        print(f"  {exc}")
        print(f"  falling back to the configured range {cfg.REQUESTED_YEARS}")
        return cfg.REQUESTED_YEARS

    print(f"  PVGIS serves {start}-{end} ({end - start + 1} years)")
    return start, end


def main() -> None:
    cfg.ensure_dirs()
    site = HERAKLION

    start, end = probe_year_range(site.latitude, site.longitude)
    cache = cfg.RECORD_CACHE.with_name(
        f"pvgis_hourly_{site.key}_{start}_{end}.parquet"
    )

    if cache.exists():
        print(f"Cache is warm: {cache}")
    else:
        print(
            f"Fetching {site.name} ({site.latitude}, {site.longitude}) {start}-{end} "
            f"from PVGIS -- one request, then cached. This takes a minute or two..."
        )

    # fetch_pvgis reads the cache when it exists and fetches when it does not, so this
    # one call covers both paths.
    #
    # `components=False` asks PVGIS for its own poa_global rather than the three
    # components, which is deliberate and load-bearing here: the shipped cache was
    # collected that way, and the summed alternative differs by up to 0.01 W/m2. That is
    # far below anything this harness can resolve, but it is not *nothing*, and a
    # measuring instrument should not quietly change what it measures. `full_range=False`
    # for the same reason -- the probe above already fixed the range.
    dataset = fetch_pvgis(
        latitude=site.latitude,
        longitude=site.longitude,
        start=start,
        end=end,
        irradiance="global",
        components=False,
        full_range=False,
        site=site.key,
        cache=cache,
    )
    frame = dataset.met_data

    years = sorted(frame["year"].unique().tolist())
    rows_per_year = frame.groupby("year").size()

    print(f"\nRecord: {len(frame):,} hourly rows, {len(years)} years {years[0]}-{years[-1]}")
    print(f"  {cfg.ATTR}: min {frame[cfg.ATTR].min():.1f}, max {frame[cfg.ATTR].max():.1f} {cfg.ATTR_UNIT}")

    # A short year means a partial fetch, which would quietly bias any window drawn from
    # it. Name it here rather than letting it through into the training pool.
    short = rows_per_year[rows_per_year < 8760]
    if not short.empty:
        print(f"  WARNING: {len(short)} year(s) with fewer than 8760 rows: {dict(short)}")

    meta = {
        "site": site.key,
        "site_name": site.name,
        "latitude": site.latitude,
        "longitude": site.longitude,
        "source": "PVGIS",
        "irradiance": "global",
        "attr": cfg.ATTR,
        "start_year": int(years[0]),
        "end_year": int(years[-1]),
        "n_years": len(years),
        "years": [int(y) for y in years],
        "n_rows": int(len(frame)),
        "cache": str(cache),
    }
    cfg.RECORD_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nWrote {cfg.RECORD_META}")
    print(f"Pooled days per configuration: {len(years) * (2 * cfg.WINDOW_N_DAYS + 1)} "
          f"(+/-{cfg.WINDOW_N_DAYS} days x {len(years)} years)")


if __name__ == "__main__":
    main()
