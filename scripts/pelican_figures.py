#!/usr/bin/env python
"""Generate publication figures for the pelican2013 WRF cold-pool cases.

Three archived runs (GFS 2-way, NAM 2-way, NAM 1-way) share the same d01/d02/d03
nest (3 km / 1 km / 333 m) over the Uinta Basin for 2013-02-02 12->18 UTC.  This
driver builds terrain-following cross-sections, multi-domain surface panels,
GFS-vs-NAM and feedback difference maps, basin-core profiles / skew-T, crest-level
upper-air maps, a nested-domain map, and a cold-pool heat-deficit time series.

Outputs route OUTSIDE the repo:
  * per-case figures  -> <run>/full-figures/<family>/
  * cross-case figures -> $BRC_WRF_ARCHIVE/pelican2013_pub_figures/compare/
Override with --output-dir (e.g. a scratch dir for a smoke test).

Run heavy batches via scripts/pelican_figures.slurm.  Soundings need a network
node: run scripts/fetch_soundings.py first and pass --sounding-cache.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import numpy as np

from brc_tools.nwp import wrf_output as wo
from brc_tools.nwp.case_study import run_figure_pipeline
from brc_tools.visualize.crosssection import (
    plot_wrf_section,
    plot_wrf_section_difference,
)
from brc_tools.visualize.domains import plot_domain_boxes
from brc_tools.visualize.profile import (
    CachedWyomingSounding,
    plot_skewt,
    plot_theta_profiles,
    sounding_from_column,
)
from brc_tools.visualize.style import get_style, use_publication_style
from brc_tools.visualize.surface import plot_domain_panels, plot_field_difference
from brc_tools.visualize.timeseries import plot_scalar_timeseries
from brc_tools.visualize.upperair import (
    below_ground_mask,
    interp_to_height_surface,
    plot_height_surface,
    temperature_advection,
)

ARCHIVE = Path(os.environ.get(
    "BRC_WRF_ARCHIVE",
    "/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/wrf_archive",
))
CASES = {
    "gfs": ("pelican2013_gfs_3_1_333m_75lev", "GFS 2-way"),
    "nam": ("pelican2013_nam_3_1_333m_75lev", "NAM 2-way"),
    "nam_oneway": ("pelican2013_nam_3_1_333m_75lev_oneway", "NAM 1-way"),
}
HORSEPOOL = (40.144, -109.467)
CREST_M = 2200.0
ANNOT = "pelican2013 | brc-tools"
WAYPOINTS = {
    "Horsepool": {"lat": 40.144, "lon": -109.467},
    "Vernal": {"lat": 40.455, "lon": -109.530},
    "Roosevelt": {"lat": 40.300, "lon": -109.989},
}
# Multi-domain surface fields: key -> (style key, needs wind vectors)
SURFACE_VARS = {
    "theta2m": ("theta_2m", True),
    "t2": ("temp_2m", True),
    "wspd10": ("wind_speed_10m", True),
    "snow": ("snow_depth", False),
    "pblh": ("pblh", False),
}
FAMILIES = ["domains", "section", "upperair", "surface", "difference", "profile", "skewt", "heatdeficit"]


def run_dir(case: str) -> Path:
    return wo.latest_run_dir(ARCHIVE / CASES[case][0] / "full6h")


def _validate_output_dir(path: Path) -> None:
    repo = Path(__file__).resolve().parent.parent
    resolved = path.resolve()
    if resolved == repo or repo in resolved.parents:
        raise SystemExit(f"refusing to write figures into the repo checkout: {resolved}")


def out_dir(args, family: str, case: str | None) -> Path:
    if args.output_dir:
        base = Path(args.output_dir)
        if case is not None:
            base = base / case
        base = base / family
    elif case is not None:
        base = run_dir(case) / "full-figures" / family
    else:
        base = ARCHIVE / "pelican2013_pub_figures" / "compare" / family
    _validate_output_dir(base)
    base.mkdir(parents=True, exist_ok=True)
    return base


def times_for(case: str, requested: str) -> list[datetime]:
    available = wo.list_valid_times(run_dir(case), 3)
    if requested == "all":
        return available
    hours = {int(h) for h in requested.split(",")}
    return [t for t in available if t.hour in hours]


# --------------------------------------------------------------------------- #
# per-figure tasks (each self-contained for run_figure_pipeline try/except)
# --------------------------------------------------------------------------- #
def _wind_speed(ds):
    u = wo.surface_field(ds, "U10")
    v = wo.surface_field(ds, "V10")
    return np.hypot(u, v)


def _surface_field_for(ds, key: str):
    if key == "theta2m":
        return wo.theta_2m(ds)
    if key == "t2":
        return wo.surface_field(ds, "T2")
    if key == "wspd10":
        return _wind_speed(ds)
    if key == "snow":
        return wo.surface_field(ds, "SNOWH")
    if key == "pblh":
        return wo.surface_field(ds, "PBLH")
    raise KeyError(key)


def task_section(run, case, label, valid, orient, out):
    ds = wo.open_wrfout(wo.wrfout_path(run, 3, valid))
    sec = wo.build_section(ds, orient)
    plot_wrf_section(
        sec, out / f"section_{orient.lower()}_{case}_{valid:%H}z.png",
        locator_terrain=wo.surface_field(ds, "HGT"),
        title=f"{label} | d03 {orient} section | {valid:%Y-%m-%d %H}Z", annotation=ANNOT,
    )


def task_upperair(run, case, label, valid, out):
    ds = wo.open_wrfout(wo.wrfout_path(run, 3, valid))
    z = wo.geopotential_height_mass(ds)
    ue, ve = wo.earth_relative_winds(ds)
    dx, dy = wo.dx_dy(ds)
    th = interp_to_height_surface(wo.potential_temperature(ds), z, CREST_M)
    u2 = interp_to_height_surface(ue, z, CREST_M)
    v2 = interp_to_height_surface(ve, z, CREST_M)
    tk = interp_to_height_surface(wo.temperature_k(ds), z, CREST_M)
    hgt = wo.surface_field(ds, "HGT")
    plot_height_surface(
        wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT"), th, u2, v2,
        out / f"crest{int(CREST_M)}_{case}_{valid:%H}z.png",
        temp_adv2d=temperature_advection(tk, u2, v2, dx, dy), terrain=hgt,
        target_label=f"{int(CREST_M)} m MSL", mask=below_ground_mask(CREST_M, hgt),
        style=get_style("theta_crest"), waypoints=WAYPOINTS,
        title=f"{label} | crest theta + wind + T-adv | {valid:%H}Z", annotation=ANNOT,
    )


def task_surface(run, case, label, valid, var_key, out):
    style_key, with_wind = SURFACE_VARS[var_key]
    d03 = wo.open_wrfout(wo.wrfout_path(run, 3, valid))
    lon3, lat3 = wo.surface_field(d03, "XLONG"), wo.surface_field(d03, "XLAT")
    extent = (float(lon3.min()), float(lon3.max()), float(lat3.min()), float(lat3.max()))
    panels = []
    for dom, dlabel in [(1, "d01 (3 km)"), (2, "d02 (1 km)"), (3, "d03 (333 m)")]:
        ds = wo.open_wrfout(wo.wrfout_path(run, dom, valid))
        panel = {
            "label": dlabel, "lon": wo.surface_field(ds, "XLONG"),
            "lat": wo.surface_field(ds, "XLAT"), "field": _surface_field_for(ds, var_key),
            "terrain": wo.surface_field(ds, "HGT"),
        }
        if with_wind:
            panel["u"] = wo.surface_field(ds, "U10")
            panel["v"] = wo.surface_field(ds, "V10")
        panels.append(panel)
    plot_domain_panels(
        panels, out / f"{var_key}_{case}_multidomain_{valid:%H}z.png", style=get_style(style_key),
        wind=with_wind, extent=extent, waypoints=WAYPOINTS,
        suptitle=f"{label} | {style_key} | d03 area | {valid:%H}Z",
    )


def task_diff_map(run_a, run_b, tag, valid, out, feedback):
    da = wo.open_wrfout(wo.wrfout_path(run_a, 3, valid))
    db = wo.open_wrfout(wo.wrfout_path(run_b, 3, valid))
    plot_field_difference(
        wo.surface_field(da, "XLONG"), wo.surface_field(da, "XLAT"),
        wo.theta_2m(da), wo.theta_2m(db), out / f"theta2m_{tag}_{valid:%H}z.png",
        var="theta", limit=3.0 if feedback else 5.0,
        title=f"{tag} | 2 m theta | d03 | {valid:%H}Z", terrain=wo.surface_field(da, "HGT"),
        annotation=ANNOT,
    )


def task_diff_section(run_a, run_b, tag, valid, orient, out):
    sec_a = wo.build_section(wo.open_wrfout(wo.wrfout_path(run_a, 3, valid)), orient)
    db = wo.open_wrfout(wo.wrfout_path(run_b, 3, valid))
    sec_b = wo.build_section(db, orient)
    plot_wrf_section_difference(
        sec_a, sec_b, out / f"section_{orient.lower()}_{tag}_{valid:%H}z.png",
        var="theta", title=f"{tag} | d03 {orient} theta | {valid:%H}Z",
        locator_terrain=wo.surface_field(db, "HGT"), annotation=ANNOT,
    )


def task_domains(out):
    outlines = []
    d01_terr = d01_lon = d01_lat = None
    for dom, dlabel in [(1, "d01 (3 km)"), (2, "d02 (1 km)"), (3, "d03 (333 m)")]:
        ds = wo.open_wrfout(wo.wrfout_path(run_dir("nam"), dom, wo.list_valid_times(run_dir("nam"), dom)[0]))
        outlines.append(wo.domain_outline(ds, label=dlabel))
        if dom == 1:
            d01_terr = wo.surface_field(ds, "HGT")
            d01_lon, d01_lat = wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT")
    plot_domain_boxes(
        outlines, out / "nested_domains.png", terrain=d01_terr, terrain_lonlat=(d01_lon, d01_lat),
        waypoints=WAYPOINTS, title="Pelican-2013 WRF nested domains",
    )


def task_profiles(valid, out):
    cols = {}
    for case, (_, label) in CASES.items():
        ds = wo.open_wrfout(wo.wrfout_path(run_dir(case), 3, valid))
        cols[label] = wo.extract_column(ds, *HORSEPOOL, label=label)
    plot_theta_profiles(
        cols, out / f"theta_profiles_horsepool_{valid:%H}z.png",
        terrain_m=cols["NAM 2-way"].terrain_m, crest_m=CREST_M, y_max_m=3300.0,
        title=rf"$\theta(z)$ at Horsepool | {valid:%Y-%m-%d %H}Z", annotation=ANNOT,
    )


def task_skewt(case, valid, out, sounding_cache):
    _, label = CASES[case]
    ds = wo.open_wrfout(wo.wrfout_path(run_dir(case), 3, valid))
    model = sounding_from_column(wo.extract_column(ds, *HORSEPOOL), source=label,
                                 station="Horsepool", valid_time=valid)
    obs = None
    if sounding_cache:
        obs = CachedWyomingSounding(sounding_cache).get("KSLC", valid)
    plot_skewt(
        model, out / f"skewt_horsepool_{case}_{valid:%H}z.png", obs=obs,
        title=f"{label} skew-T | Horsepool | {valid:%H}Z", annotation=ANNOT,
    )


def task_heatdeficit(out):
    series = {}
    for case, (_, label) in CASES.items():
        times = wo.list_valid_times(run_dir(case), 3)
        deficits = []
        for t in times:
            ds = wo.open_wrfout(wo.wrfout_path(run_dir(case), 3, t))
            deficits.append(wo.cold_pool_heat_deficit(wo.extract_column(ds, *HORSEPOOL), CREST_M) / 1e6)
        series[label] = (times, np.array(deficits))
    plot_scalar_timeseries(
        series, out / "heat_deficit_timeseries.png",
        ylabel=r"cold-pool heat deficit (MJ m$^{-2}$)",
        title=f"Cold-pool heat deficit at Horsepool (crest {int(CREST_M)} m)",
    )


# --------------------------------------------------------------------------- #
def build_tasks(args) -> list[tuple]:
    fams = FAMILIES if args.figure == "all" else args.figure.split(",")
    cases = list(CASES) if args.case == "all" else args.case.split(",")
    tasks: list[tuple] = []

    if "domains" in fams:
        tasks.append(("domains map", task_domains, (out_dir(args, "domains", None),)))
    if "profile" in fams:
        for t in times_for(cases[0], "12"):
            tasks.append((f"profiles {t:%H}Z", task_profiles, (t, out_dir(args, "profiles", None))))
    if "heatdeficit" in fams:
        tasks.append(("heat deficit series", task_heatdeficit, (out_dir(args, "heatdeficit", None),)))

    for case in cases:
        run, label = run_dir(case), CASES[case][1]
        for t in times_for(case, args.time):
            if "section" in fams:
                for orient in ("EW", "NS"):
                    tasks.append((f"{label} {orient} {t:%H}Z", task_section,
                                  (run, case, label, t, orient, out_dir(args, "sections", case))))
            if "upperair" in fams:
                tasks.append((f"{label} upperair {t:%H}Z", task_upperair,
                              (run, case, label, t, out_dir(args, "upperair", case))))
            if "surface" in fams:
                for var_key in SURFACE_VARS:
                    tasks.append((f"{label} {var_key} {t:%H}Z", task_surface,
                                  (run, case, label, t, var_key, out_dir(args, "surface", case))))
            if "skewt" in fams:
                tasks.append((f"{label} skewt {t:%H}Z", task_skewt,
                              (case, t, out_dir(args, "skewt", None), args.sounding_cache)))

    if "difference" in fams and {"gfs", "nam"} <= set(cases):
        for t in times_for("nam", args.time):
            odir = out_dir(args, "diff_gfs_nam", None)
            tasks.append((f"GFS-NAM map {t:%H}Z", task_diff_map,
                          (run_dir("gfs"), run_dir("nam"), "GFS-NAM", t, odir, False)))
            for orient in ("EW", "NS"):
                tasks.append((f"GFS-NAM {orient} {t:%H}Z", task_diff_section,
                              (run_dir("gfs"), run_dir("nam"), "GFS-NAM", t, orient, odir)))
    if "difference" in fams and {"nam", "nam_oneway"} <= set(cases):
        for t in times_for("nam", args.time):
            odir = out_dir(args, "diff_feedback", None)
            tasks.append((f"2way-1way map {t:%H}Z", task_diff_map,
                          (run_dir("nam"), run_dir("nam_oneway"), "2way-1way", t, odir, True)))
    return tasks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="all", help="gfs|nam|nam_oneway|all (comma-separated ok)")
    ap.add_argument("--figure", default="all", help="|".join(FAMILIES) + "|all (comma-separated ok)")
    ap.add_argument("--time", default="all", help="hour(s) 12..18 or 'all' (comma-separated ok)")
    ap.add_argument("--output-dir", default=None, help="override output root (else routed by case)")
    ap.add_argument("--sounding-cache", default=None, help="parquet from fetch_soundings.py (offline obs)")
    args = ap.parse_args()

    use_publication_style()
    tasks = build_tasks(args)
    print(f"pelican_figures: {len(tasks)} figure task(s)")
    run_figure_pipeline(tasks)
    print("done")


if __name__ == "__main__":
    main()
