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
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brc_tools.nwp import wrf_engine as we  # noqa: E402
from brc_tools.nwp import wrf_output as wo  # noqa: E402
from brc_tools.nwp import wrf_section as ws  # noqa: E402
from brc_tools.nwp import wrf_tracers as wt  # noqa: E402
from brc_tools.visualize import coldpool3d as cp3  # noqa: E402
from brc_tools.visualize import tracer_origin as tro  # noqa: E402
from brc_tools.visualize.nwp_maps import plot_nwp_surface_map  # noqa: E402
from brc_tools.visualize.profile import (  # noqa: E402
    plot_theta_wind_profile,
    sounding_from_column,
)
from brc_tools.visualize.style import use_publication_style  # noqa: E402
from brc_tools.visualize.wrf_curtain import (  # noqa: E402
    plot_wrf_curtain,
    shade_style_key,
)

#: Selectable with ``--figure`` (repeatable); default is all of them.
#:
#: ``topdown``  surface plan views -- wind, theta, PBLH, convergence, snow,
#:              and the derived fog / cloud / surface-energy diagnostics.
#: ``section``  terrain-filled curtains on native eta levels along A->B lines.
#: ``profile``  theta + humidity profiles with a wind panel at named points.
#: ``view3d``   3-D isentrope lid over hillshaded terrain.
#: ``tracers``  passive-tracer source attribution: origin curtains, per-source
#:              share curtains, stacked spectra at points, and origin maps.
FAMILIES = ("topdown", "section", "profile", "view3d", "tracers")

# Config, waypoints, colour scales and time selection are shared with the
# convective engine so the two cannot drift; see brc_tools.nwp.wrf_engine.
_MAP_LAYERS = we.MAP_LAYERS
_TIME_FMT = we.TIME_FMT


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    """Case TOML, with ``[[sections]]``/``[[views3d]]``/``[[profiles]]`` indexed."""
    return we.load_config(path, index=("sections", "views3d", "profiles"))


def waypoints(group: str | None) -> dict:
    """Title-cased ``{name: {lat, lon}}`` for a ``lookups.toml`` waypoint group."""
    return we.waypoints(group)


def style_for(cfg: dict, var: str):
    """Resolve a variable's :class:`VarStyle`, applying the case's overrides."""
    return we.style_for(cfg, var)


def plane_extras(cfg: dict, dom: dict, families) -> tuple[str, ...]:
    """Which optional 3-D fields this view's figures actually need.

    Each extra is another ~140 MB read per time on a 600 m nest at 99 levels, so
    they are derived from what the config *asks to draw* rather than loaded
    speculatively: a plain wind sweep still pays for nothing.  The shade names
    and the extra names coincide by construction -- see
    :data:`brc_tools.nwp.wrf_section.PLANE_EXTRAS`.
    """
    wanted: set[str] = set()
    if "section" in families:
        for key in dom.get("sections", []):
            spec = cfg["_sections"].get(key) or {}
            shade = spec.get("shade", "speed")
            if shade in ws.PLANE_EXTRAS:
                wanted.add(shade)
    if "tracers" in families and _tracer_targets(cfg, dom):
        wanted.add("tracers")
    return tuple(sorted(wanted))


def _tracer_targets(cfg: dict, dom: dict) -> dict:
    """The tracer figures this view asks for: sections, profiles, and the map."""
    sections = [k for k in dom.get("sections", [])
                if (cfg["_sections"].get(k) or {}).get("tracers")]
    profiles = [k for k in dom.get("profiles", [])
                if (cfg["_profiles"].get(k) or {}).get("tracers")]
    return {"sections": sections, "profiles": profiles,
            "map": bool(dom.get("tracer_map"))} if (
        sections or profiles or dom.get("tracer_map")) else {}


def tracer_labels(cfg: dict, n: int) -> list[str]:
    """Source names for the tracer legend, from ``[tracers].names``.

    Falls back to ``tr17_1`` ... when the case has not named them.  A tracer
    figure with unnamed sources is still readable as *layering* -- which is the
    falsifiable claim -- and only the attribution needs the names, so an unnamed
    case is degraded rather than refused.
    """
    names = list(cfg.get("tracers", {}).get("names", []))
    if len(names) < n:
        names += [f"tr17_{i + 1}" for i in range(len(names), n)]
    return names[:n]


# --------------------------------------------------------------------------- #
# time selection
# --------------------------------------------------------------------------- #
def select_times(run_dir: Path, domains: list[int], args) -> list[datetime]:
    """Resolve which valid time(s) to render (shared with the convective engine)."""
    return we.select_times(
        run_dir, domains,
        valid=args.valid, lead=args.lead, hourly=args.hourly,
        every=args.every, all_times=args.all_times,
        start=args.start, end=args.end,
    )


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_domain(cfg: dict, dom: dict, valid: datetime, init: datetime,
                  out_root: Path, args, ledger, families=FAMILIES) -> int:
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
        src = [path]  # every figure for this view derives from this one file

        # -- plan views -----------------------------------------------------
        pad = float(dom.get("pad_deg", 0.0))
        extent = tuple(dom["extent"]) if dom.get("extent") else ws.plan_extent(ds, pad_deg=pad)
        surface_vars = (dom.get("surface_vars", ["wind_speed_10m"])
                        if "topdown" in families else [])
        # Derived plan-view fields (fog, cloud, the surface energy budget, ...)
        # ride the same `extra=` hook the convective engine uses, and only the
        # ones this view actually names are computed -- visibility alone is a
        # full-depth read of every hydrometeor species.
        pds = ws.plan_dataset(ds, extra=ws.plan_diagnostics(
            ds, surface_vars, params=cfg.get("diagnostics", {})))
        map_wps = waypoints(dom.get("waypoint_group"))
        for var in surface_vars:
            if var not in pds:
                print(f"[SKIP] {tag} {var}: not written by this run")
                ledger.note(we.ABSENT, "not written by this run",
                            family="topdown", domain=d, var=var)
                continue
            st = style_for(cfg, var)
            made += ledger.emit(
                out_dir / f"topdown_{var}_{tag}_{stamp}.png",
                lambda path, var=var, st=st: plot_nwp_surface_map(
                    pds, var, path,
                    style=st, waypoints=map_wps,
                    barb_stride=int(dom.get("barb_stride", 6)),
                    extent=extent, overlays=overlays, annotation=an,
                    title=we.compose_title(we.SOURCE_WRF, base, st.label),
                    dpi=args.dpi),
                sources=src, family="topdown", domain=d, var=var,
            )

        # -- cross-sections + 3-D cold-pool views ----------------------------
        keys = dom.get("sections", []) if "section" in families else []
        v3d = dom.get("views3d", []) if "view3d" in families else []
        tracer_jobs = _tracer_targets(cfg, dom) if "tracers" in families else {}
        want_profiles = "profile" in families and dom.get("profiles")
        if keys or v3d or tracer_jobs:
            extras = plane_extras(cfg, dom, families)
            # The expensive read; shared by every family that needs 3-D state.
            plane = ws.load_plane(ds, extras=extras)
            loc = dict(lon2d=plane.lon2d, lat2d=plane.lat2d, terrain2d=plane.terrain)
            for key in keys:
                s = cfg["_sections"].get(key)
                if s is None:
                    print(f"[SKIP] {tag} section {key!r}: not in [[sections]]")
                    ledger.note(we.ABSENT, "not in [[sections]]",
                                family="section", domain=d, var=key)
                    continue
                if not we.check_section_on_grid(plane, key, s, tag=tag):
                    ledger.note(we.ABSENT, "transect does not intersect this nest",
                                family="section", domain=d, var=key)
                    continue
                sec_wps = waypoints(s.get("waypoint_group"))
                shade = s.get("shade", "speed")

                def _draw(path, s=s, key=key, sec_wps=sec_wps, shade=shade):
                    sec = cut_section(plane, s)
                    plot_wrf_curtain(
                        sec, path,
                        shade=shade,
                        # Per SHADE, not a fixed wind scale: this used to pass
                        # wind_speed_10m for every shade, so a theta curtain came
                        # out on a 0-15 m/s ramp labelled "10 m wind".
                        style=style_for(cfg, s.get("style", shade_style_key(shade))),
                        title=we.compose_title(we.SOURCE_WRF, sec_base,
                                               s.get("label", key)),
                        annotation=an, waypoints=sec_wps,
                        waypoint_offset_km=float(s.get("offset_km", 15.0)),
                        **curtain_axes(s),
                        w_exaggeration=(args.w_exag if args.w_exag is not None
                                        else float(s.get("w_exag", 10.0))),
                        theta_interval=float(s.get("theta_interval", 1.0)),
                        quiver_stride=tuple(s.get("quiver_stride", (4, 10))),
                        locator=section_locator(loc, s, sec_wps),
                        dpi=args.dpi)

                made += ledger.emit(
                    out_dir / f"xsection_{shade}_{key}_{tag}_{stamp}.png",
                    _draw, sources=src, family="section", domain=d, var=key,
                )
            made += render_views3d(cfg, v3d, plane, tag, stamp, sec_base, an,
                                   out_dir, args, ledger, domain=d, sources=src)
            if tracer_jobs:
                made += render_tracers(cfg, dom, plane, tracer_jobs, tag, stamp,
                                       sec_base, an, out_dir, args, ledger,
                                       domain=d, sources=src, loc=loc,
                                       extent=extent, overlays=overlays)

        if want_profiles:
            made += render_profiles(cfg, dom, ds, tag, stamp, sec_base, an, out_dir,
                                    args, ledger, domain=d, sources=src)
        print(f"  {tag}: {made} figures -> {out_dir}")
        return made
    finally:
        ds.close()


def cut_section(plane, spec: dict):
    """Cut one ``[[sections]]`` transect from an already-loaded plane."""
    return ws.section_from_plane(
        plane, tuple(spec["a"]), tuple(spec["b"]),
        n_points=int(spec.get("n_points", 240)),
        termini=tuple(spec.get("termini", ("A", "B"))))


def curtain_axes(spec: dict) -> dict:
    """The vertical-axis kwargs a ``[[sections]]`` entry sets.

    ``y_bottom_m`` and ``vertical`` are together the tight-z knob: a section
    whose whole subject is a 250 m inversion under a 1100 m terrain drop is
    unreadable on the 3400 m axis that makes the *regional* sections comparable,
    and the fix is a second entry over the same line rather than a compromise
    that serves neither.
    """
    axes = {"y_top_m": float(spec.get("y_top_m", 3000.0)),
            "vertical": str(spec.get("vertical", "asl"))}
    if spec.get("y_bottom_m") is not None:
        axes["y_bottom_m"] = float(spec["y_bottom_m"])
    return axes


def section_locator(loc: dict, spec: dict, waypoints_: dict) -> dict:
    """The locator-inset kwargs for one section."""
    return {**loc,
            "extent": tuple(spec["loc_extent"]) if spec.get("loc_extent") else None,
            "rect": list(spec["loc_rect"]) if spec.get("loc_rect") else None,
            "waypoints": waypoints_}


def render_tracers(cfg, dom, plane, jobs, tag, stamp, sec_base, an, out_dir, args,
                   ledger, *, domain=None, sources=(), loc=None, extent=None,
                   overlays=None) -> int:
    """Origin curtains, per-source share curtains, spectra and the origin map.

    Attached to the existing ``[[sections]]`` / ``[[profiles]]`` / ``[[domains]]``
    entries by a ``tracers = true`` switch rather than given their own config
    block: a tracer figure wants exactly the transect, extent, waypoint group and
    locator the case has already chosen, and a parallel set of definitions would
    drift from them.
    """
    if plane.tracers is None:
        print(f"[SKIP] {tag}: this run wrote no tr17_* tracers")
        ledger.note(we.ABSENT, "no tr17_* tracers in this run",
                    family="tracers", domain=domain)
        return 0
    tcfg = cfg.get("tracers", {})
    floor = float(tcfg.get("floor", wt.DEFAULT_TOTAL_FLOOR))
    labels = tracer_labels(cfg, plane.tracers.shape[0])
    # 1-based in the config because the tracers are named tr17_1..tr17_8, and a
    # config that says `shares = [7, 8]` should mean those two.
    shares = [int(i) - 1 for i in tcfg.get("shares", [])]
    made = 0

    for key in jobs.get("sections", []):
        s = cfg["_sections"][key]
        sec_wps = waypoints(s.get("waypoint_group"))
        common = dict(annotation=an, waypoints=sec_wps,
                      waypoint_offset_km=float(s.get("offset_km", 15.0)),
                      locator=section_locator(loc or {}, s, sec_wps),
                      theta_interval=float(s.get("theta_interval", 1.0)),
                      dpi=args.dpi, **curtain_axes(s))

        # The cut happens inside each closure, so a --dry-run or a --skip-existing
        # pass costs nothing beyond the plane that was loaded anyway.
        def _origin(path, s=s, key=key, common=common):
            tro.plot_origin_curtain(
                cut_section(plane, s), path, labels=labels, floor=floor,
                title=we.compose_title(we.SOURCE_WRF, sec_base,
                                       s.get("label", key), "air-mass origin"),
                **common)

        made += ledger.emit(out_dir / f"origin_{key}_{tag}_{stamp}.png",
                            _origin, sources=sources, family="tracers",
                            domain=domain, var=f"origin_{key}")

        for i in shares:
            if i < 0 or i >= plane.tracers.shape[0]:
                continue

            def _share(path, i=i, s=s, key=key, common=common):
                sec = cut_section(plane, s)
                share_i, _total = wt.tracer_shares(sec.tracers2d, floor=floor)
                plot_wrf_curtain(
                    sec, path, values=share_i[i],
                    style=style_for(cfg, "tracer_share"),
                    cbar_label=f"share of the tagged air from {labels[i]}",
                    title=we.compose_title(we.SOURCE_WRF, sec_base,
                                           s.get("label", key),
                                           f"from {labels[i]}"),
                    w_exaggeration=(args.w_exag if args.w_exag is not None
                                    else float(s.get("w_exag", 10.0))),
                    quiver_stride=tuple(s.get("quiver_stride", (4, 10))),
                    **common)

            made += ledger.emit(
                out_dir / f"share_tr{i + 1}_{key}_{tag}_{stamp}.png",
                _share, sources=sources, family="tracers", domain=domain,
                var=f"share{i + 1}_{key}")

    for key in jobs.get("profiles", []):
        spec = cfg["_profiles"][key]
        wp = we.waypoint(spec["waypoint"])
        j, i = ws.nearest_column(plane, float(wp["lat"]), float(wp["lon"]))

        def _spectrum(path, spec=spec, key=key, j=j, i=i):
            tro.plot_tracer_spectrum(
                plane.tracers[:, :, j, i],
                plane.height[:, j, i] - plane.terrain[j, i],
                path, labels=labels, floor=floor,
                theta_col=plane.theta[:, j, i],
                top_m=float(spec.get("tracer_top_m", spec.get("y_top_m", 2000.0))),
                title=we.compose_title(we.SOURCE_WRF, sec_base,
                                       spec.get("label", key),
                                       "where the air came from"),
                annotation=an, dpi=args.dpi)

        made += ledger.emit(out_dir / f"spectrum_{key}_{tag}_{stamp}.png",
                            _spectrum, sources=sources, family="tracers",
                            domain=domain, var=f"spectrum_{key}")

    if jobs.get("map"):
        level = int(tcfg.get("level", 0))
        map_wps = waypoints(dom.get("waypoint_group"))

        def _map(path):
            tro.plot_origin_map(
                plane.lon2d, plane.lat2d, plane.terrain,
                plane.tracers[:, level], path, labels=labels, floor=floor,
                extent=extent, overlays=overlays, waypoints=map_wps,
                wind=(plane.ue[level], plane.ve[level]),
                barb_stride=int(dom.get("barb_stride", 6)),
                title=we.compose_title(
                    we.SOURCE_WRF, sec_base,
                    f"air-mass origin, model level {level}"),
                annotation=an, dpi=args.dpi)

        made += ledger.emit(out_dir / f"origin_map_{tag}_{stamp}.png",
                            _map, sources=sources, family="tracers",
                            domain=domain, var="origin_map")
    return made


def render_profiles(cfg, dom, ds, tag, stamp, sec_base, an, out_dir, args, ledger,
                    *, domain=None, sources=()) -> int:
    """theta + humidity profiles with a wind panel, at named waypoints.

    Deliberately not a skew-T.  A skew-T is built to read a deep convective
    parcel path; a basin study is asking how deep the stable layer is and whether
    the air above it is dry enough to mix down, and theta-versus-height answers
    that directly -- inversion depth is a slope you can see, not a curve you
    interpret against a background of adiabats.  The convective engine keeps the
    skew-T, because there the parcel path *is* the question.
    """
    made = 0
    for key in dom.get("profiles", []):
        spec = cfg["_profiles"].get(key)
        if spec is None:
            print(f"[SKIP] {tag} profile {key!r}: not in [[profiles]]")
            ledger.note(we.ABSENT, "not in [[profiles]]", family="profile",
                        domain=domain, var=key)
            continue
        wp = we.waypoint(spec["waypoint"])

        def _draw(path, spec=spec, key=key, wp=wp):
            col = wo.extract_column(ds, float(wp["lat"]), float(wp["lon"]))
            snd = sounding_from_column(
                col, source=f"WRF {tag}", station=spec.get("label", key))
            plot_theta_wind_profile(
                {f"{sec_base.split('|')[-1].strip()}": snd}, path,
                title=we.compose_title(we.SOURCE_WRF, sec_base,
                                       spec.get("label", key)),
                annotation=an,
                crest_m=spec.get("crest_m"),
                y_top_m=float(spec.get("y_top_m", 5500.0)),
                humidity=spec.get("humidity", "rh"),
                wind_bars=bool(spec.get("wind_bars", True)),
                barb_interval_m=float(spec.get("barb_interval_m", 250.0)),
                dpi=args.dpi,
            )

        made += ledger.emit(
            out_dir / f"profile_{key}_{tag}_{stamp}.png",
            _draw, sources=sources, family="profile", domain=domain, var=key,
        )
    return made


def render_views3d(cfg, keys, plane, tag, stamp, sec_base, an, out_dir, args,
                   ledger, *, domain=None, sources=()) -> int:
    """Render the ``[[views3d]]`` cold-pool panels for one domain and time."""
    made = 0
    for key in keys:
        v = cfg["_views3d"].get(key)
        if v is None:
            print(f"[SKIP] {tag} view3d {key!r}: not in [[views3d]]")
            ledger.note(we.ABSENT, "not in [[views3d]]", family="view3d",
                        domain=domain, var=key)
            continue
        try:
            rows, cols = cp3.extent_window(plane.lon2d, plane.lat2d, tuple(v["extent"]))
        except Exception as exc:
            print(f"[ERR] view3d {tag} {key}: {exc}")
            ledger.note(we.ERROR, f"{type(exc).__name__}: {exc}", family="view3d",
                        domain=domain, var=key)
            continue
        lon, lat = plane.lon2d[rows, cols], plane.lat2d[rows, cols]
        terr = plane.terrain[rows, cols]
        theta, height = plane.theta[:, rows, cols], plane.height[:, rows, cols]
        for iso in (args.theta_iso or v.get("theta_iso", [310.0])):

            def _draw(path, iso=iso, v=v, key=key, lon=lon, lat=lat, terr=terr,
                      theta=theta, height=height):
                lid = cp3.isentrope_lid(theta, height, terr, float(iso),
                                        max_depth_m=float(v.get("max_depth_m", 1500.0)))
                cp3.plot_coldpool_3d(
                    lon, lat, terr, lid, path,
                    theta_iso=float(iso),
                    title=we.compose_title(
                        we.SOURCE_WRF, sec_base, v.get("label", key),
                        rf"cold air below $\theta$ = {float(iso):g} K"),
                    annotation=an,
                    stride=int(v.get("stride", 2)),
                    elev=float(v.get("elev", 22.0)),
                    azim=float(v.get("azim", -90.0)),
                    z_frac=float(v.get("z_frac", 0.45)),
                    depth_min_m=float(v.get("depth_min_m", 25.0)),
                    depth_max_m=float(v.get("depth_max_m", 600.0)),
                    dpi=args.dpi)

            made += ledger.emit(
                out_dir / f"coldpool3d_{key}_th{float(iso):g}_{tag}_{stamp}.png",
                _draw, sources=sources, family="view3d", domain=domain,
                var=f"{key}_th{float(iso):g}",
            )
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, type=Path, help="case TOML")
    ap.add_argument("--run-dir", type=Path, help="override the TOML run directory")
    # The shared set, so --start/--end exist here too.  They did not, which made
    # docs/VISUAL-SUITE-SOP.md's "bound the window" step an argparse error on one
    # of the two engines it is written for.
    we.add_time_arguments(ap)
    ap.add_argument(
        "--figure", action="append", metavar="FAMILY",
        help=f"restrict to a family ({'|'.join(FAMILIES)}); repeatable",
    )
    ap.add_argument("--theta-iso", type=float, action="append", metavar="K",
                    help="override the [[views3d]] isentrope(s) for the 3-D "
                         "cold-pool panels (repeatable)")
    ap.add_argument("--domain", type=int, action="append",
                    help="restrict to this nest (repeatable); default = all in the TOML")
    ap.add_argument("--output-dir", type=Path, help="override the output root")
    ap.add_argument("--w-exag", type=float,
                    help="override every section's vertical exaggeration. One rule: "
                             "typical |u| / typical |w|, which puts the typical "
                             "vector at 45 deg -- a deep convective core wants ~5, "
                             "a drainage night ~100. NOT the plot aspect; see "
                             "docs/WRF-WINDS.md")
    ap.add_argument("--dpi", type=int, default=200)
    we.add_output_arguments(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.run_dir:
        cfg["case"]["run_dir"] = args.run_dir
    run_dir = cfg["case"]["run_dir"]
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")

    families = tuple(args.figure) if args.figure else FAMILIES
    unknown = [f for f in families if f not in FAMILIES]
    if unknown:
        raise SystemExit(f"unknown --figure {unknown}; choose from {list(FAMILIES)}")

    doms = [d for d in cfg.get("domains", [])
            if not args.domain or int(d["domain"]) in args.domain]
    if not doms:
        raise SystemExit("no domains selected")
    numbers = [int(d["domain"]) for d in doms]

    use_publication_style(dpi=args.dpi)
    times = select_times(run_dir, numbers, args)
    init = ws.init_time(run_dir, min(numbers))
    # we.output_root, not an inlined copy: the shared resolver carries the guard
    # that refuses an output path inside the brc-tools or case checkout.
    out_root = we.output_root(cfg, args.output_dir, config_path=args.config)

    # --report reads what previous jobs recorded; it renders nothing.
    if args.report:
        return we.report_coverage(out_root)

    ledger = we.FigureLedger(skip_existing=args.skip_existing, dry_run=args.dry_run)

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
                ledger.note(we.ABSENT, "no wrfout at this domain/time",
                            family="domain", domain=int(dom["domain"]), valid=valid)
                continue
            # One bad time (a wrfout caught half-written by the running job, say)
            # must not take the rest of the sweep down with it.
            try:
                total += render_domain(cfg, dom, valid, init, out_root, args,
                                       ledger, families=families)
            except Exception as exc:
                print(f"[ERR] {dom.get('tag', dom['domain'])} {valid:{_TIME_FMT}}: {exc}")
                traceback.print_exc()
                ledger.note(we.ERROR, f"{type(exc).__name__}: {exc}",
                            family="domain", domain=int(dom["domain"]), valid=valid)

    if args.dry_run:
        print(f"\n[dry ] {ledger.count(we.PLANNED)} figure(s) would be rendered:")
        for line in ledger.planned_lines():
            print(line)
    else:
        manifest = ledger.write_manifest(
            out_root, config_path=args.config, run_dir=run_dir, argv=sys.argv[1:],
        )
        print(f"[man ] {manifest}")
    print(f"\nDone. {total} figures over {len(times)} time(s) -> {out_root}")
    if absent:
        print(f"({absent} view-times skipped: no wrfout at that domain/time)")
    print(ledger.summarise())
    return ledger.exit_code(allow_errors=args.allow_errors)


if __name__ == "__main__":
    raise SystemExit(main())
