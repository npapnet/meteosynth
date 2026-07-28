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
import re
import warnings

import config as cfg

from meteosynth.adapters import fetch_pvgis

from tools.site_data import HERAKLION  # noqa: E402  (needs cfg's sys.path insert)

#: PVGIS answers an out-of-range request by naming the range it does serve, which is a
#: far more reliable probe than bisecting: one failed request gives both bounds.
_RANGE_RE = re.compile(r"between\s+(\d{4})\s+and\s+(\d{4})")


def probe_year_range(latitude: float, longitude: float) -> tuple[int, int]:
    """
    Ask PVGIS what year range it serves for a site.

    Deliberately makes a request that *should* fail -- year 1900 -- because the error
    message names both bounds. Falls back to :data:`config.REQUESTED_YEARS` if the
    message ever stops carrying them.
    """
    from pvlib.iotools import get_pvgis_hourly

    print("Probing PVGIS for the available year range...")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            get_pvgis_hourly(
                latitude=latitude, longitude=longitude, start=1900, end=1900,
                components=False,
            )
    except Exception as exc:  # noqa: BLE001 -- any failure carries the message we want
        match = _RANGE_RE.search(str(exc))
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            print(f"  PVGIS serves {start}-{end} ({end - start + 1} years)")
            return start, end
        print(f"  probe gave an unparseable error: {str(exc)[:160]}")

    print(f"  falling back to the configured range {cfg.REQUESTED_YEARS}")
    return cfg.REQUESTED_YEARS


def main() -> None:
    cfg.ensure_dirs()
    site = HERAKLION

    start, end = probe_year_range(site.latitude, site.longitude)
    cache = cfg.RECORD_CACHE.with_name(
        f"pvgis_hourly_{site.key}_{start}_{end}.csv"
    )

    if cache.exists():
        print(f"Cache is warm: {cache}")
    else:
        print(
            f"Fetching {site.name} ({site.latitude}, {site.longitude}) {start}-{end} "
            f"from PVGIS -- one request, then cached. This takes a minute or two..."
        )

    # fetch_pvgis reads the cache when it exists and fetches when it does not, so this
    # one call covers both paths. irradiance="global" asks for poa_global directly
    # rather than fetching the three components and summing them.
    frame = fetch_pvgis(
        latitude=site.latitude,
        longitude=site.longitude,
        start=start,
        end=end,
        irradiance="global",
        cache=cache,
    )

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
