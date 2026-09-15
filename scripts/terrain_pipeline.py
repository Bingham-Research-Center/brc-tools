#!/usr/bin/env python
"""D8 catchments and perpendicular gates for a basin, from USGS 3DEP tiles to NPZ + CSV.

    python -B scripts/terrain_pipeline.py --tiles-dir $WRF_ARCHIVE/terrain/usgs_3dep \
        --res 30 --extent -111.8 -107.4 39.05 41.9 --sink ouray \
        --outlet 39.80 -110.05 39.80 -109.80 \
        --cut green_island_park 40.40 -109.16 40.72 -109.16 \
        --cut white_river_east 39.85 -108.60 40.45 -108.60 \
        --rims 1800 2000 2200 --channel-km2 20 --out-dir /scratch/.../terrain --tag basin30

Method: mosaic -> priority-flood fill -> D8 -> accumulation -> for each rim height the
basin floor (below-rim component holding the sink, upstream of the outlet, upstream of no
cut), the channels crossing into it, the catchment behind each crossing, and a gate cut
perpendicular to the channel at the crossing.  No theory, no figures: those belong to the
case (ub-wx).  Writes ``<out>/terrain_<tag>.npz`` (dem, accumulation, per-rim labels and
floors), ``gates_<tag>.csv`` (one row per channel crossing with its gate line and widths)
and ``basin_<tag>.json`` (totals).  Run on a compute node: ``scripts/terrain_pipeline.slurm``.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

import brc_tools
from brc_tools.terrain import catchments as ct
from brc_tools.terrain import d8, dem, gates

log = logging.getLogger("terrain_pipeline")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiles-dir", required=True)
    ap.add_argument("--source", choices=["auto", "13as", "1as"], default="auto")
    ap.add_argument("--res", type=float, required=True, help="grid spacing (m)")
    ap.add_argument("--extent", type=float, nargs=4, required=True, metavar=("LON_W", "LON_E", "LAT_S", "LAT_N"))
    ap.add_argument("--sink", required=True, help="lookups.toml waypoint name of the basin sink (e.g. ouray)")
    ap.add_argument("--outlet", type=float, nargs=4, required=True, metavar=("LAT0", "LON0", "LAT1", "LON1"),
                    help="line the basin's river leaves through; its largest-accumulation cell is the outlet")
    ap.add_argument("--cut", nargs=5, action="append", default=[], metavar=("NAME", "LAT0", "LON0", "LAT1", "LON1"),
                    help="a line where the floor is open to a river corridor the grid cannot hold (repeatable)")
    ap.add_argument("--rims", type=float, nargs="+", default=[2000.0])
    ap.add_argument("--channel-km2", type=float, default=20.0)
    ap.add_argument("--floor-leak", type=float, default=0.01, help="drop crossings with more floor upstream than this")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--cache-dir", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    t0 = time.time()

    source = args.source if args.source != "auto" else ("13as" if args.res < 30 else "1as")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    z, grid = dem.mosaic_tiles(args.tiles_dir, source, tuple(args.extent), args.res,
                               cache_dir=args.cache_dir or out / "cache")
    ny, nx = z.shape
    zf = d8.fill_depressions(z, grid)
    rcv = d8.d8_receivers(zf, grid.res)
    fo = d8.flow_accumulation(rcv)
    acc, order, starts = fo.acc, fo.order, fo.starts
    step = d8.step_length(rcv, nx, grid.res)
    slope = d8.slope_deg(z, grid.res)
    zbins = ct.elevation_bins(zf, 50.0)

    # read lookups.toml directly: importing brc_tools.nwp would pull in Herbie, which the
    # terrain-2026 env deliberately lacks
    import tomllib
    with open(Path(brc_tools.__file__).parent / "nwp" / "lookups.toml", "rb") as fh:
        wp = tomllib.load(fh)["waypoints"][args.sink]
    sink = tuple(int(v) for v in grid.ji(float(wp["lat"]), float(wp["lon"])))
    outlet = ct.line_max_acc_cell(grid, acc, tuple(args.outlet))
    cuts = {c[0]: ct.line_max_acc_cell(grid, acc, tuple(float(v) for v in c[1:])) for c in args.cut}
    hydro = ct.hydro_mask(rcv, order, starts, outlet, cuts)
    log.info("outlet cell drains %.0f km2; cuts: %s", acc[outlet] * grid.cell_area_m2 / 1e6,
             {k: round(acc[v] * grid.cell_area_m2 / 1e6) for k, v in cuts.items()})

    basin = {"res_m": grid.res, "source": source, "extent": args.extent, "n_cells": int(z.size),
             "grid": grid.to_dict(), "sink": args.sink, "channel_min_km2": args.channel_km2, "rims": {}}
    rows, labels = [], {}
    for rim in args.rims:
        floor = ct.basin_floor(zf, rim, sink, hydro)
        xc = ct.rim_crossings(floor, rcv)
        lab, dist = d8.label_upstream(rcv, order, starts, xc, np.arange(xc.size, dtype=np.int32), step=step)
        h = ct.aggregate(lab, xc.size, grid.cell_area_m2, zf, slope, zbins)
        leak = ct.floor_leak_fraction(lab, floor, xc.size, grid.cell_area_m2, h.area_m2)
        trunc = ct.touches_edge_or_nodata(lab, xc.size, z)
        flen = ct.flow_length(lab, dist, xc.size)
        is_chan = (acc[xc] * grid.cell_area_m2 >= args.channel_km2 * 1e6) & (leak <= args.floor_leak)
        log.info("rim %.0f: floor %.0f km2, %d crossings, %d channel gates (%d truncated)", rim,
                 floor.sum() * grid.cell_area_m2 / 1e6, xc.size, is_chan.sum(), (is_chan & trunc).sum())
        for k in np.flatnonzero(is_chan):
            c = int(xc[k])
            g = gates.perpendicular_gate(zf, grid, c, rcv=rcv, acc=acc, name=f"r{rim:.0f}_{k}")
            rows.append({
                "rim_m": rim, "id": g.name, "cell": c, "lat": round(g.mouth[0], 5), "lon": round(g.mouth[1], 5),
                "lat_up": round(g.upstream[0], 5), "lon_up": round(g.upstream[1], 5),
                "a_lat": round(g.a[0], 5), "a_lon": round(g.a[1], 5), "b_lat": round(g.b[0], 5), "b_lon": round(g.b[1], 5),
                "azimuth_deg": round(g.azimuth_deg, 1), "line_length_m": round(g.line_length_m),
                "z_mouth_m": round(float(zf.ravel()[c])), "thalweg_m": round(g.thalweg_m),
                "acc_km2": round(float(acc[c]) * grid.cell_area_m2 / 1e6, 1),
                "catch_km2": round(h.area_m2[k] / 1e6, 1), "z_mean_m": round(float(h.z_mean_m[k])),
                "z_max_m": round(float(h.z_max_m[k])), "slope_mean_deg": round(float(h.slope_mean_deg[k]), 2),
                "flow_len_km": round(float(flen[k]) / 1e3, 1),
                **{f"width{int(hh)}_m": round(w) for hh, w in g.widths_m.items()},
                "truncated_at_edge": bool(trunc[k]), "floor_leak": round(float(leak[k]), 4),
            })
        labels[f"lab_rim{rim:.0f}"] = np.where(is_chan[np.maximum(lab, 0)] & (lab >= 0), lab, -1).astype(np.int32).reshape(ny, nx)
        labels[f"floor_rim{rim:.0f}"] = floor
        basin["rims"][f"{rim:.0f}"] = {
            "floor_km2": round(floor.sum() * grid.cell_area_m2 / 1e6),
            "channel_gates": int((is_chan & ~trunc).sum()), "truncated_gates": int((is_chan & trunc).sum()),
            "channel_km2": round(h.area_m2[is_chan & ~trunc].sum() / 1e6),
            "truncated_km2": round(h.area_m2[is_chan & trunc].sum() / 1e6),
            "inward_draining_km2": round(h.area_m2[leak <= args.floor_leak].sum() / 1e6),
        }
    dem.save_labels_npz(out / f"terrain_{args.tag}.npz", grid, dem=z, acc_cells=acc.reshape(ny, nx), **labels)
    with open(out / f"gates_{args.tag}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    basin["elapsed_s"] = round(time.time() - t0)
    with open(out / f"basin_{args.tag}.json", "w") as fh:
        json.dump(basin, fh, indent=1)
    log.info("wrote %s/{terrain,gates,basin}_%s.* in %.1f min", out, args.tag, (time.time() - t0) / 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
