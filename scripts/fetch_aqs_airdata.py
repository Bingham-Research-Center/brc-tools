#!/usr/bin/env python
"""Fetch EPA AQS AirData bulk observations into a parquet cache.

Anonymous download (no key).  One AirData file covers one parameter x one year
x one cadence for the whole US; this script downloads what it needs into
``BRC_TOOLS_AQS_CACHE`` (default ``~/.cache/brc-tools/aqs``), filters to the
requested sites/bbox/dates, and writes one tidy parquet.

The Uinta Basin winter-ozone monitor registry (Ute Tribe, UDAQ, NPS, USFS
sites verified for winter 2012-13) ships in ``brc_tools.api.aqs`` -- pass
``--basin`` to use it.  Use ``--kind daily`` for EPA's own regulatory MDA8
("1st Max Value" per pollutant-standard row); do not recompute MDA8 from
hourly data.

Examples (pelican2013 episode context):
    python scripts/fetch_aqs_airdata.py --param ozone --kind daily \
        --years 2013 --basin --start 2013-01-01 --end 2013-02-28 \
        --out /scratch/general/vast/$USER/aqs_ozone_daily_janfeb2013.parquet

    python scripts/fetch_aqs_airdata.py --param ozone --kind hourly \
        --years 2012 2013 --basin --start 2012-12-01 --end 2013-02-28 \
        --out /scratch/general/vast/$USER/aqs_ozone_hourly_win1213.parquet

    python scripts/fetch_aqs_airdata.py --param pm25_nonfrm --kind hourly \
        --years 2013 --sites 49-047-2003 49-047-2002 49-013-0002 \
        --start 2013-01-01 --end 2013-02-28 \
        --out /scratch/general/vast/$USER/aqs_pm25_hourly_janfeb2013.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--param", default="ozone",
                    help="PARAMS key (ozone, pm25_nonfrm, wind, ...) or raw AirData code")
    ap.add_argument("--kind", default="daily", choices=["hourly", "daily"])
    ap.add_argument("--years", nargs="+", type=int, required=True)
    ap.add_argument("--sites", nargs="*", default=None,
                    help="AQS ids like 49-047-2003 (zero-padding optional)")
    ap.add_argument("--basin", action="store_true",
                    help="use the verified Uinta Basin winter-ozone site registry")
    ap.add_argument("--include-flagged", action="store_true",
                    help="with --basin, keep sites flagged incomplete (Enefit)")
    ap.add_argument("--bbox", nargs=4, type=float, default=None,
                    metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    ap.add_argument("--start", default=None, help="inclusive ISO date")
    ap.add_argument("--end", default=None, help="inclusive ISO date")
    ap.add_argument("--out", required=True, help="output parquet path (outside the repo)")
    args = ap.parse_args()

    import polars as pl

    from brc_tools.api.aqs import basin_site_ids, download_airdata, load_airdata

    sites = list(args.sites or [])
    if args.basin:
        sites += basin_site_ids(include_flagged=args.include_flagged)
    sites = sites or None

    frames = []
    for year in args.years:
        zp = download_airdata(args.kind, args.param, year)
        print(f"cached {zp.name} ({zp.stat().st_size/1e6:.1f} MB)")
        df = load_airdata(zp, sites=sites, bbox=args.bbox,
                          start=args.start, end=args.end)
        print(f"  {year}: {df.height} rows after filters")
        frames.append(df)

    df = pl.concat(frames, how="vertical_relaxed")
    if not df.height:
        raise SystemExit("no rows matched the filters")

    keys = ["State Code", "County Code", "Site Num"]
    time_col = "valid_time" if "valid_time" in df.columns else "date_local"
    cov = (df.group_by(keys)
             .agg(pl.len().alias("n"),
                  pl.col(time_col).min().alias("first"),
                  pl.col(time_col).max().alias("last"))
             .sort(keys))
    with pl.Config(tbl_rows=40):
        print(cov)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    print(f"wrote {df.height} rows -> {out}")


if __name__ == "__main__":
    main()
