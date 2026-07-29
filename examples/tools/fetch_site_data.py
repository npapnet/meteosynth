#%%
"""
Tool: prime the local PVGIS cache.

Downloads the records the examples train on and caches them under ``examples/data/``,
so the first use case you run does not pay for the download. Running it twice costs
nothing -- an existing cache is left alone unless ``--refresh`` is passed.

Run with::

    uv run python examples/tools/fetch_site_data.py
    uv run python examples/tools/fetch_site_data.py --refresh
"""

import argparse
import pathlib
import sys

# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path.cwd()
_EXAMPLES = next(p for c in (_HERE, *_HERE.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

from tools.site_data import (
    HERAKLION,
    HERAKLION_YEARS,
    PARIS,
    PARIS_YEARS,
    load_site,
)


def report(site, years, data) -> None:
    """One line per cached record: what it holds and what can be modelled from it."""
    modellable = [c for c in data.columns
                  if c.startswith("poa") or c in ("temp_air", "wind_speed")]
    print(f"  {site.name:18} {years[0]}-{years[1]}  {len(data):6d} hourly rows  "
          f"columns: {modellable}")


def main(refresh: bool = False) -> None:
    # Heraklion 2010-2020 is what the use cases train on.
    report(HERAKLION, HERAKLION_YEARS, load_site(HERAKLION, *HERAKLION_YEARS, refresh=refresh))

    # Paris 2011-2012 is what the concept scripts use.
    paris = load_site(PARIS, *PARIS_YEARS, refresh=refresh)
    report(PARIS, PARIS_YEARS, paris)

    print(f"\nCache lives in {HERAKLION.cache_path(*HERAKLION_YEARS).parent} "
          f"(git-ignored).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true",
                        help="re-download even if the cache is warm")
    main(**vars(parser.parse_args()))

# %%
