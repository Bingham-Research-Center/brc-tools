#!/usr/bin/env python3
"""Stage Natural-Earth reference shapefiles for the WRF figure-engine overlays.

The figure engine is deliberately cartopy-free so it renders on offline compute nodes,
but the optional highway / river / lake / border overlays (case ``[map]`` table, drawn
by ``brc_tools.visualize.basemap``) need the Natural-Earth 10 m shapefiles cached on a
path the batch job can read.  Compute nodes have no outbound network, so run this ONCE
on a login / DTN node with internet; the SLURM figure job then reads the cache offline.

The stage target resolves ``BRC_TOOLS_BASEMAP_DIR`` (a persistent cache — e.g. group
storage that survives scratch purges) → ``CARTOPY_DATA_DIR`` (cartopy-native) → a
per-user scratch dir, so a one-time stage into durable storage keeps every later figure
job wired with no re-fetch::

    export BRC_TOOLS_BASEMAP_DIR=/uufs/.../lawson-group6/jrlawson/brc-tools-data/cartopy
    python scripts/fetch_basemap.py

A DTN has both internet *and* read-write group storage, so it can fetch straight into a
persistent dir in one shot — see ``scripts/fetch_basemap.dtn.slurm``.  (Login nodes may
mount group storage read-only; compute nodes lack internet — hence the DTN.)

Idempotent: cartopy skips layers already present.  Fail-soft consumer side — a missing
layer just means that overlay is absent, never a crash.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# (category, dataset name) for each layer the overlays can draw.
_LAYERS = [
    ("cultural", "admin_1_states_provinces_lakes"),
    ("cultural", "roads"),
    ("cultural", "populated_places"),  # city labels (forecast-funnel + opt-in overlays)
    ("physical", "rivers_lake_centerlines"),
    ("physical", "lakes"),
]

_SCRATCH_DIR = f"/scratch/general/vast/{os.environ.get('USER', 'user')}/cartopy"


def _default_dir() -> str:
    """Resolve the stage target: persistent ``BRC_TOOLS_BASEMAP_DIR`` wins, then the
    cartopy-native ``CARTOPY_DATA_DIR``, then a purgeable per-user scratch dir."""
    return (
        os.environ.get("BRC_TOOLS_BASEMAP_DIR")
        or os.environ.get("CARTOPY_DATA_DIR")
        or _SCRATCH_DIR
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-dir", default=_default_dir(),
        help="cartopy data dir to stage into "
             "(default: $BRC_TOOLS_BASEMAP_DIR or $CARTOPY_DATA_DIR or scratch)",
    )
    ap.add_argument("--resolution", default="10m", help="Natural-Earth resolution")
    args = ap.parse_args()

    # cartopy reads CARTOPY_DATA_DIR into cartopy.config at import; set it before import.
    os.environ["CARTOPY_DATA_DIR"] = str(args.data_dir)
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)

    import cartopy
    import cartopy.io.shapereader as shpreader

    cartopy.config["data_dir"] = str(args.data_dir)  # belt-and-braces
    print(f"staging Natural-Earth {args.resolution} into {args.data_dir}")

    failures = 0
    for category, name in _LAYERS:
        try:
            path = shpreader.natural_earth(
                resolution=args.resolution, category=category, name=name
            )
            print(f"  [ok] {category}/{name} -> {path}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"  [FAIL] {category}/{name}: {exc}")

    if failures:
        print(f"{failures}/{len(_LAYERS)} layer(s) failed — overlays for those stay off.")
        return 1
    print("all reference layers staged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
