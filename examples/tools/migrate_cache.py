"""
One-time conversion of the legacy CSV caches to the parquet dataset format.

The examples used to cache a raw PVGIS frame as CSV, with the site and period encoded in
the *filename* and nothing inside the file saying what it held. ``MetDataset`` carries
that as provenance instead, so the filename is now a convenience rather than the record.

Run this once to avoid re-downloading::

    python examples/tools/migrate_cache.py            # convert, keep the CSVs
    python examples/tools/migrate_cache.py --delete   # convert, then remove the CSVs

Provenance is recovered from the filename, which is the only place the old format
recorded it. That is exactly the weakness this format was built to remove -- so anything
this script cannot parse is reported and skipped rather than guessed at.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from meteosynth import MetDataset, Provenance          # noqa: E402
from tools.site_data import DATA_DIR, SITES, add_poa_global   # noqa: E402

#: What the legacy filenames looked like: pvgis_hourly_<site>_<start>_<end>.csv
LEGACY = re.compile(r"^pvgis_hourly_(?P<site>[a-z_]+)_(?P<start>\d{4})_(?P<end>\d{4})$")


def convert(path: pathlib.Path) -> pathlib.Path | None:
    """Convert one legacy CSV, returning the parquet path or ``None`` if skipped."""
    match = LEGACY.match(path.stem)
    if match is None:
        print(f"  skip  {path.name}: filename does not carry a site and period")
        return None

    key, start, end = match["site"], int(match["start"]), int(match["end"])
    site = SITES.get(key)
    if site is None:
        print(f"  skip  {path.name}: {key!r} is not a known site")
        return None

    frame = pd.read_csv(path)
    # The legacy cache stored the three components as fetched; poa_global was rebuilt on
    # every read rather than stored. Do it once here instead.
    if "poa_global" not in frame.columns:
        frame = add_poa_global(frame)

    dataset = MetDataset(
        frame,
        provenance=Provenance(
            source="pvgis_hourly",
            site=key,
            latitude=site.latitude,
            longitude=site.longitude,
            start_year=start,
            end_year=end,
            notes=(
                "migrated from a legacy CSV cache; site and period recovered from the "
                "filename, and poa_global reconstructed by summing the three POA "
                "components"
            ),
        ),
    )

    target = path.with_suffix(".parquet")
    dataset.save(target)

    before = path.stat().st_size / 1e6
    after = target.stat().st_size / 1e6
    print(
        f"  ok    {path.name} -> {target.name}  "
        f"({len(dataset.met_data)} rows, {before:.1f} MB -> {after:.1f} MB)"
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove each CSV once its parquet has been written and verified",
    )
    args = parser.parse_args()

    legacy = sorted(DATA_DIR.glob("pvgis_hourly_*.csv"))
    if not legacy:
        print(f"Nothing to migrate: no legacy CSV caches in {DATA_DIR}.")
        return 0

    print(f"Migrating {len(legacy)} legacy cache file(s) in {DATA_DIR}:")
    converted = []
    for path in legacy:
        target = convert(path)
        if target is not None:
            converted.append((path, target))

    if args.delete:
        for source, target in converted:
            # Verified by reloading before anything is removed: the whole point of the
            # format is that a file can be checked rather than trusted.
            MetDataset.load(target)
            source.unlink()
            print(f"  removed {source.name}")

    print(f"\nConverted {len(converted)} of {len(legacy)}.")
    if not args.delete and converted:
        print("The CSVs were left in place. Re-run with --delete to remove them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
