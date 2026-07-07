#!/usr/bin/env python
"""Fetch radiosondes from the University of Wyoming archive into a parquet cache.

Run this on a **login / DTN node** (it needs outbound network).  The batch figure
job then reads the cache offline via
``brc_tools.visualize.profile.CachedWyomingSounding``.

Usage:
    python scripts/fetch_soundings.py --time "2013-02-02 12" \
        --stations KSLC,KGJT --out /scratch/general/vast/$USER/soundings_20130202_12z.parquet
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

# Wyoming numeric station ids for the nearest operational sondes to the basin.
STATIONS = {"KSLC": "72572", "KGJT": "72476"}


def _fetch(station_id: str, valid: datetime):
    from siphon.simplewebservice.wyoming import WyomingUpperAir

    return WyomingUpperAir.request_data(valid, station_id)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--time", default="2013-02-02 12", help="UTC 'YYYY-MM-DD HH'")
    ap.add_argument("--stations", default="KSLC,KGJT", help="comma-separated names")
    ap.add_argument("--out", required=True, help="output parquet path (outside the repo)")
    args = ap.parse_args()

    import polars as pl

    valid = datetime.strptime(args.time, "%Y-%m-%d %H")
    frames = []
    for name in [s.strip() for s in args.stations.split(",") if s.strip()]:
        station_id = STATIONS.get(name, name)
        try:
            df = _fetch(station_id, valid)
        except Exception as exc:  # network / missing sounding
            print(f"WARN {name} ({station_id}): {exc}")
            continue
        frames.append(
            pl.DataFrame(
                {
                    "station": name,
                    "valid_time": valid,
                    "pressure_hpa": df["pressure"].values,
                    "temperature_c": df["temperature"].values,
                    "dewpoint_c": df["dewpoint"].values,
                    "u_kt": df["u_wind"].values,
                    "v_kt": df["v_wind"].values,
                }
            )
        )
        print(f"OK {name}: {len(df)} levels")

    if not frames:
        raise SystemExit("no soundings fetched")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.concat(frames).write_parquet(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
