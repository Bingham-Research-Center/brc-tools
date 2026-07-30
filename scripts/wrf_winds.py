#!/usr/bin/env python
"""Render basin-winds-style plan views and cross-sections from a WRF run.

The WRF counterpart of the ``basin-winds`` HRRR case: for each nest, a plan-view
surface map (10 m wind + barbs + terrain + towns) plus terrain-filled wind
curtains along named A->B transects, each with the geographic locator inset.
Same renderers as the HRRR path -- ``brc_tools.visualize.nwp_maps`` -- fed by the
``wrfout`` adapter in :mod:`brc_tools.nwp.wrf_section`, so sections keep the
model's native eta levels instead of being flattened onto isobaric surfaces.

Everything case-specific lives in a TOML (run directory, per-domain extents and
waypoint groups, transect endpoints, colour-scale overrides); this file is the
engine.  Schema: ``docs/WRF-WINDS.md``.

    python scripts/wrf_winds.py --config <case.toml> [--valid ...|--lead ...]

Times: ``--valid YYYY-MM-DD_HH:MM`` picks one exactly, ``--lead <minutes>`` picks
init+N, and the default renders the latest time available on *every* requested
domain -- the useful default while a run is still writing, since a coarse nest on
hourly output lags a fine nest on 5-minute output.
"""
from __future__ import annotations

import argparse
import os
import sys
import tomllib
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from brc_tools.nwp import wrf_engine as we  # noqa: E402
from brc_tools.nwp import wrf_output as wo  # noqa: E402
from brc_tools.nwp import wrf_section as ws  # noqa: E402
from brc_tools.visualize import coldpool3d as cp3  # noqa: E402
from brc_tools.visualize.nwp_maps import plot_nwp_surface_map  # noqa: E402
from brc_tools.visualize.style import VarStyle, get_style, use_publication_style  # noqa: E402
from brc_tools.visualize.wrf_curtain import plot_wrf_curtain  # noqa: E402

# Config, waypoints, colour scales and time selection are shared with the
# convective engine so the two cannot drift; see brc_tools.nwp.wrf_engine.
DEFAULT_OUTPUT_ROOT = we.DEFAULT_OUTPUT_ROOT
_MAP_LAYERS = we.MAP_LAYERS
_TIME_FMT = we.TIME_FMT


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    """Case TOML, with ``[[sections]]``/``[[views3d]]`` indexed by key."""
    return we.load_config(path, index=("sections", "views3d"))


def waypoints(group: str | None) -> dict:
    """Title-cased ``{name: {lat, lon}}`` for a ``lookups.toml`` waypoint group."""
    return we.waypoints(group)


def style_for(cfg: dict, var: str):
    """Resolve a variable's :class:`VarStyle`, applying the case's overrides."""
    return we.style_for(cfg, var)


# --------------------------------------------------------------------------- #
# time selection
# --------------------------------------------------------------------------- #
def select_times(run_dir: Path, domains: list[int], args) -> list[datetime]:
    """Resolve which valid time(s) to render (shared with the convective engine)."""
    return we.select_times(
        run_dir, domains,
        valid=args.valid, lead=args.lead, hourly=args.hourly,
        every=args.every, all_times=args.all_times,
    )


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_domain(cfg: dict, dom: dict, valid: datetime, init: datetime,
                  out_root: Path, args) -> int:
    run_dir = cfg["case"]["run_dir"]
    d = int(dom["domain"])
    path = ws.wrfout_path(run_dir, d, valid)
    if not path.exists():
        return 0
    ds = wo.open_wrfout(path)
    try:
        lead_min = (valid - init).total_seconds() / 60.0
        dx_km = float(ds.attrs["DX"]) / 1000.0
        # A nest may appear more than once (e.g. full extent plus a zoom), so the
        # view's own tag -- not the domain number -- names the output.
        tag = str(dom.get("tag") or f"d{d:02d}")
        stamp = f"{valid:%Y%m%d_%H%M}"
        base = (f"{cfg['case']['label']} | {tag} {dx_km:g} km | "
                f"valid {valid:%Y-%m-%d %H:%MZ} (+{lead_min:.0f} min)")
        # The section renderer parks its quiver key at the top right, so a section
        # title has to stay short; the case label and date live in the annotation
        # instead.  Plan views have no key and keep the full string.
        sec_base = f"{tag} {dx_km:g} km | {valid:%H:%MZ} +{lead_min:.0f} min"
        an = " | ".join(x for x in (cfg["case"].get("annotation", ""),
                                    f"{valid:%Y-%m-%d}", f"init {init:%H:%MZ}") if x)
        overlays = {k: bool(cfg.get("map", {}).get(k, False)) for k in _MAP_LAYERS}
        out_dir = out_root / stamp / tag
        made = 0

        # -- plan views -----------------------------------------------------
        pad = float(dom.get("pad_deg", 0.0))
        extent = tuple(dom["extent"]) if dom.get("extent") else ws.plan_extent(ds, pad_deg=pad)
        pds = ws.plan_dataset(ds)
        map_wps = waypoints(dom.get("waypoint_group"))
        for var in dom.get("surface_vars", ["wind_speed_10m"]):
            if var not in pds:
                print(f"[SKIP] {tag} {var}: not written by this run")
                continue
            st = style_for(cfg, var)
            try:
                plot_nwp_surface_map(
                    pds, var, out_dir / f"topdown_{var}_{tag}_{stamp}.png",
                    style=st, waypoints=map_wps,
                    barb_stride=int(dom.get("barb_stride", 6)),
                    extent=extent, overlays=overlays, annotation=an,
                    title=f"{base} | {st.label}", dpi=args.dpi)
                made += 1
            except Exception as exc:  # keep going: one bad panel is not a lost run
                print(f"[ERR] topdown {tag} {var}: {exc}")
                traceback.print_exc()

        # -- cross-sections + 3-D cold-pool views ----------------------------
        keys = dom.get("sections", [])
        v3d = dom.get("views3d", [])
        if keys or v3d:
            plane = ws.load_plane(ds)   # the expensive read; shared by both families
            loc = dict(lon2d=plane.lon2d, lat2d=plane.lat2d, terrain2d=plane.terrain)
            for key in keys:
                s = cfg["_sections"].get(key)
                if s is None:
                    print(f"[SKIP] {tag} section {key!r}: not in [[sections]]")
                    continue
                sec_wps = waypoints(s.get("waypoint_group"))
                try:
                    sec = ws.section_from_plane(
                        plane, tuple(s["a"]), tuple(s["b"]),
                        n_points=int(s.get("n_points", 240)),
                        termini=tuple(s.get("termini", ("A", "B"))))
                    plot_wrf_curtain(
                        sec, out_dir / f"xsection_{key}_{tag}_{stamp}.png",
                        shade=s.get("shade", "speed"),
                        style=style_for(cfg, "wind_speed_10m"),
                        title=f"{sec_base} | {s.get('label', key)}",
                        annotation=an, waypoints=sec_wps,
                        waypoint_offset_km=float(s.get("offset_km", 15.0)),
                        y_top_m=float(s.get("y_top_m", 3000.0)),
                        w_exaggeration=(args.w_exag if args.w_exag is not None
                                        else float(s.get("w_exag", 10.0))),
                        theta_interval=float(s.get("theta_interval", 1.0)),
                        quiver_stride=tuple(s.get("quiver_stride", (4, 10))),
                        locator={**loc,
                                 "extent": tuple(s["loc_extent"]) if s.get("loc_extent") else None,
                                 "rect": list(s["loc_rect"]) if s.get("loc_rect") else None,
                                 "waypoints": sec_wps},
                        dpi=args.dpi)
                    made += 1
                except Exception as exc:
                    print(f"[ERR] xsection {tag} {key}: {exc}")
                    traceback.print_exc()
            made += render_views3d(cfg, v3d, plane, tag, stamp, sec_base, an,
                                   out_dir, args)
        print(f"  {tag}: {made} figures -> {out_dir}")
        return made
    finally:
        ds.close()


def render_views3d(cfg, keys, plane, tag, stamp, sec_base, an, out_dir, args) -> int:
    """Render the ``[[views3d]]`` cold-pool panels for one domain and time."""
    made = 0
    for key in keys:
        v = cfg["_views3d"].get(key)
        if v is None:
            print(f"[SKIP] {tag} view3d {key!r}: not in [[views3d]]")
            continue
        try:
            rows, cols = cp3.extent_window(plane.lon2d, plane.lat2d, tuple(v["extent"]))
        except Exception as exc:
            print(f"[ERR] view3d {tag} {key}: {exc}")
            continue
        lon, lat = plane.lon2d[rows, cols], plane.lat2d[rows, cols]
        terr = plane.terrain[rows, cols]
        theta, height = plane.theta[:, rows, cols], plane.height[:, rows, cols]
        for iso in (args.theta_iso or v.get("theta_iso", [310.0])):
            try:
                lid = cp3.isentrope_lid(theta, height, terr, float(iso),
                                        max_depth_m=float(v.get("max_depth_m", 1500.0)))
                cp3.plot_coldpool_3d(
                    lon, lat, terr, lid,
                    out_dir / f"coldpool3d_{key}_th{float(iso):g}_{tag}_{stamp}.png",
                    theta_iso=float(iso),
                    title=(f"{sec_base} | {v.get('label', key)} | "
                           rf"cold air below $\theta$ = {float(iso):g} K"),
                    annotation=an,
                    stride=int(v.get("stride", 2)),
                    elev=float(v.get("elev", 22.0)),
                    azim=float(v.get("azim", -90.0)),
                    z_frac=float(v.get("z_frac", 0.45)),
                    depth_min_m=float(v.get("depth_min_m", 25.0)),
                    depth_max_m=float(v.get("depth_max_m", 600.0)),
                    dpi=args.dpi)
                made += 1
            except Exception as exc:
                print(f"[ERR] view3d {tag} {key} theta={iso}: {exc}")
                traceback.print_exc()
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, type=Path, help="case TOML")
    ap.add_argument("--run-dir", type=Path, help="override the TOML run directory")
    ap.add_argument("--valid", help=f"exact valid time, {_TIME_FMT.replace('%', '%%')}")
    ap.add_argument("--lead", type=int, help="minutes after init")
    ap.add_argument("--hourly", action="store_true",
                    help="sweep every whole-hour valid time written so far "
                         "(shorthand for --every 60)")
    ap.add_argument("--every", type=int, metavar="MIN",
                    help="sweep every valid time on a MIN-minute cadence (e.g. 15). "
                         "A domain that lacks a given time is skipped for it")
    ap.add_argument("--all", dest="all_times", action="store_true",
                    help="sweep every valid time at the run's native output "
                         "interval (a 5-minute nest makes this a lot of figures)")
    ap.add_argument("--theta-iso", type=float, action="append", metavar="K",
                    help="override the [[views3d]] isentrope(s) for the 3-D "
                         "cold-pool panels (repeatable)")
    ap.add_argument("--domain", type=int, action="append",
                    help="restrict to this nest (repeatable); default = all in the TOML")
    ap.add_argument("--output-dir", type=Path, help="override the output root")
    ap.add_argument("--w-exag", type=float,
                    help="override every section's vertical exaggeration. The right "
                         "value is regime-dependent: a convective afternoon resolves "
                         "w ~ 1 m/s and wants ~10, a quiescent drainage night ~100.")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.run_dir:
        cfg["case"]["run_dir"] = args.run_dir
    run_dir = cfg["case"]["run_dir"]
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")

    doms = [d for d in cfg.get("domains", [])
            if not args.domain or int(d["domain"]) in args.domain]
    if not doms:
        raise SystemExit("no domains selected")
    numbers = [int(d["domain"]) for d in doms]

    use_publication_style(dpi=args.dpi)
    times = select_times(run_dir, numbers, args)
    init = ws.init_time(run_dir, min(numbers))
    out_root = (args.output_dir or Path(os.path.expandvars(cfg["case"]["output_dir"]))
                if (args.output_dir or cfg["case"].get("output_dir"))
                else DEFAULT_OUTPUT_ROOT / cfg["case"]["slug"])

    print(f"[run ] {run_dir}")
    print(f"[init] {init:{_TIME_FMT}}")
    total, absent = 0, 0
    for valid in times:
        print(f"[valid] {valid:{_TIME_FMT}} "
              f"(+{(valid - init).total_seconds() / 60:.0f} min)")
        for dom in doms:
            # On a sweep, a coarse nest simply has no file at a sub-hourly time.
            # That is expected, not an error, and printing it per view would bury
            # the log -- so count it and report the total once at the end.
            if not ws.wrfout_path(run_dir, int(dom["domain"]), valid).exists():
                absent += 1
                continue
            # One bad time (a wrfout caught half-written by the running job, say)
            # must not take the rest of the sweep down with it.
            try:
                total += render_domain(cfg, dom, valid, init, out_root, args)
            except Exception as exc:
                print(f"[ERR] {dom.get('tag', dom['domain'])} {valid:{_TIME_FMT}}: {exc}")
                traceback.print_exc()
    print(f"\nDone. {total} figures over {len(times)} time(s) -> {out_root}")
    if absent:
        print(f"({absent} view-times skipped: no wrfout at that domain/time)")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
