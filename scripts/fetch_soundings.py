#!/usr/bin/env python
"""Fetch radiosondes into a parquet cache for the offline figure batch.

Run on a **login / DTN node** (needs outbound network to NCEI / UWyo).  The SLURM
figure job then reads the cache offline via
``brc_tools.visualize.profile.CachedWyomingSounding``.

The mechanical fetch + provider normalisation lives in ``brc_tools.api.soundings``;
this script is just the CLI and the parquet write, so the same pull is reusable
elsewhere in the repo.

Default stations are the four operational RAOB proxies overlapping the pelican2013
WRF domains (all in d01; the basin has none): KSLC, KGJT, KRIW (Riverton WY),
KDPG (Dugway UT).  IGRA2 is the default provider (UWyo is offline as of 2026-07).

    python scripts/fetch_soundings.py --time "2013-02-02 12" \
        --stations KSLC,KGJT,KRIW,KDPG --provider auto \
        --out /scratch/general/vast/$USER/soundings_20130202_12z.parquet
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--time", default="2013-02-02 12", help="UTC 'YYYY-MM-DD HH'")
    ap.add_argument("--stations", default="KSLC,KGJT,KRIW,KDPG",
                    help="comma-separated registry names (or raw provider ids)")
    ap.add_argument("--provider", default="auto", choices=["auto", "igra2", "wyoming"],
                    help="archive; auto tries igra2 then wyoming (UWyo offline 2026-07)")
    ap.add_argument("--out", required=True, help="output parquet path (outside the repo)")
    args = ap.parse_args()

    import polars as pl

    from brc_tools.api.soundings import fetch_sounding

    # Naive UTC, matching the wrfout filename stamps the figure batch parses.
    valid = datetime.strptime(args.time, "%Y-%m-%d %H")
    names = [s.strip() for s in args.stations.split(",") if s.strip()]

    frames = []
    for name in names:
        df = fetch_sounding(name, valid, provider=args.provider)
        if df is None:
            print(f"WARN {name}: no sounding (missing launch / provider unavailable)")
            continue
        print(f"OK   {name}: {df.height} levels via {df['provider'][0]}")
        frames.append(df)

    if not frames:
        raise SystemExit("no soundings fetched")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined = pl.concat(frames)
    combined.write_parquet(out)
    print(f"wrote {out}  ({combined.height} rows, {len(frames)}/{len(names)} station(s))")


if __name__ == "__main__":
    main()
