#!/usr/bin/env python
"""Render a NAM "forecast funnel" montage for a given analysis init time.

Downloads a single NAM analysis (f00) and renders the four-panel forecast funnel
(250 hPa jet -> 500 hPa flow -> 600 hPa moisture/LLJ -> surface synoptic analysis)
as one publication montage.  The NAM source is auto-picked by init date: Herbie's
operational NAM for recent inits, the NCEI historical grib1 archive for pre-2017
(the 2017-2020 window is unwired — see ``docs/FORECAST-FUNNEL.md``).

Examples
--------
    # recent init (Herbie path)
    python scripts/forecast_funnel.py --init-time "2026-07-20 00Z"

    # historical init (NCEI path), custom output dir
    python scripts/forecast_funnel.py --init-time 2013013100 \
        --output-dir /scratch/general/vast/$USER/forecast_funnel

Downloads/figures route OUTSIDE the repo (scratch by default).  GRIB is heavy and
needs a network node — run on a DTN via ``scripts/forecast_funnel.dtn.slurm``.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from brc_tools.nwp.forecast_funnel import DEFAULT_LEVELS, fetch_funnel_fields
from brc_tools.nwp.source import _parse_init_time
from brc_tools.visualize.funnel import plot_forecast_funnel
from brc_tools.visualize.style import use_publication_style


def _default_output_dir() -> str:
    user = os.environ.get("USER", "user")
    return f"/scratch/general/vast/{user}/forecast_funnel"


def _levels_arg(value: str) -> tuple[int, ...]:
    return tuple(int(v) for v in value.split(",")) if value else DEFAULT_LEVELS


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--init-time", required=True,
                    help="analysis init, 'YYYY-MM-DD HHZ' or YYYYMMDDHH (UTC).")
    ap.add_argument("--output-dir", default=_default_output_dir(),
                    help="figure output root (default: scratch; never the repo).")
    ap.add_argument("--source", default="auto", choices=("auto", "herbie", "ncei"),
                    help="NAM source (default: auto-pick by init date).")
    ap.add_argument("--levels", default=",".join(str(x) for x in DEFAULT_LEVELS),
                    help="pressure levels hPa, comma-separated (default: 250,500,600).")
    ap.add_argument("--cache-dir", default=None,
                    help="GRIB cache dir (default: $BRC_TOOLS_HERBIE_CACHE / scratch).")
    ap.add_argument("--dpi", type=int, default=300, help="figure DPI (default: 300).")
    args = ap.parse_args()

    init_dt = _parse_init_time(args.init_time)
    use_publication_style(dpi=args.dpi)

    data = fetch_funnel_fields(
        args.init_time, source=args.source, cache_dir=args.cache_dir,
        levels=_levels_arg(args.levels),
    )

    stamp = init_dt.strftime("%Y%m%d_%H%M")
    out_path = Path(args.output_dir) / f"forecast_funnel_{stamp}Z.png"
    written = plot_forecast_funnel(data, out_path, dpi=args.dpi)
    print(f"wrote {written}  (source={data.source}, panels={len(data.panels)})")


if __name__ == "__main__":
    main()
