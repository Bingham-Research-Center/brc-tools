#!/usr/bin/env python
"""Render convective diagnostics from a WRF run: reflectivity, beams, soundings.

The convective counterpart of ``wrf_winds.py``.  Seven figure families, each
switched on per nest in the case TOML:

``surface``   plan views from the history stream -- composite reflectivity,
              gust swath, updraft helicity, echo top, vertical vorticity.
``aux``       the same kind of plan view from a high-cadence auxiliary stream,
              which is the only way to see a feature the history stream aliases.
``section``   reflectivity / vertical-velocity / theta curtains along A->B lines.
``beam``      **simulated reflectivity sampled on a real radar's beam surface** --
              the only apples-to-apples comparison against a distant WSR-88D.
``sounding``  skew-T with a parcel path and LCL/LFC/EL, plus a hodograph.
``verify``    model surface traces against observations at named stations.
``track``     the reflectivity-centroid track over the window.

Everything case-specific lives in the TOML; this file is the engine.
Schema and a worked example: ``docs/WRF-CONVECTIVE.md``.

    python scripts/wrf_convective.py --config <case.toml> [--valid ...|--every 1]

For a publication figure set use ``wrf_figures.py``; for drainage winds use
``wrf_winds.py``.  Different engines, different jobs.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from brc_tools.nwp import convective_env as ce  # noqa: E402
from brc_tools.nwp import wrf_convective as wc  # noqa: E402
from brc_tools.nwp import wrf_engine as we  # noqa: E402
from brc_tools.nwp import wrf_output as wo  # noqa: E402
from brc_tools.nwp import wrf_section as ws  # noqa: E402
from brc_tools.nwp import wrf_tslist as wt  # noqa: E402
from brc_tools.radar import beam as rb  # noqa: E402
from brc_tools.radar.sites import get_site  # noqa: E402
from brc_tools.visualize.hodograph import plot_hodograph  # noqa: E402
from brc_tools.visualize.nwp_maps import plot_nwp_surface_map  # noqa: E402
from brc_tools.visualize.profile import plot_skewt, sounding_from_column  # noqa: E402
from brc_tools.visualize.style import use_publication_style  # noqa: E402
from brc_tools.visualize.wrf_curtain import plot_wrf_curtain  # noqa: E402

FAMILIES = ("surface", "aux", "section", "beam", "sounding", "verify", "track")

#: History-stream 2-D fields this engine can plot, mapped to their style key.
#: Anything here is read from ``wrfout``; the auxiliary stream is handled
#: separately because its maximum fields reset on the history write.
_SURFACE_FIELDS = {
    "REFD_COM": "refl_comp",
    "REFD_MAX": "refl_comp",
    "ECHOTOP": "echo_top",
    "WSPD10MAX": "wspd10max",
    "UP_HELI_MAX": "uphel_2to5km",
    "HAIL_MAX2D": "hail_max",
    "AFWA_LLWS": "llws",
    "AFWA_CAPE": "cape_ml",
    "AFWA_CIN": "cin_ml",
    "TORNADO_MASK": "tornado_mask",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _titles(cfg: dict, dom: dict, ds, valid: datetime, init: datetime):
    """``(tag, stamp, title_base, short_base, annotation)`` for one view."""
    number = int(dom["domain"])
    tag = str(dom.get("tag") or f"d{number:02d}")
    dx_km = float(ds.attrs["DX"]) / 1000.0
    lead = (valid - init).total_seconds() / 60.0
    stamp = f"{valid:%Y%m%d_%H%M}"
    base = (f"{cfg['case']['label']} | {tag} {dx_km:g} km | "
            f"valid {valid:%Y-%m-%d %H:%MZ} (+{lead:.0f} min)")
    short = f"{tag} {dx_km:g} km | {valid:%H:%MZ} +{lead:.0f} min"
    annotation = " | ".join(
        x for x in (cfg["case"].get("annotation", ""), f"{valid:%Y-%m-%d}",
                    f"init {init:%H:%MZ}") if x
    )
    return tag, stamp, base, short, annotation


def _echo_top_km(field):
    """Echo top in km for plotting; the style is in km MSL, the field in m."""
    return np.asarray(field, dtype=float) / 1000.0


#: Values at or below these floors are masked to NaN before plotting.
#:
#: Without this, a reflectivity panel paints the whole domain in the low end of the
#: colour map and clear air reads as data -- on a 213 x 171 km footprint holding one
#: storm, that is most of the figure. Operational radar products mask below ~5 dBZ
#: for the same reason. Echo top is 0 where there is no echo at all, not 0 km.
_MASK_AT_OR_BELOW = {
    "refl_comp": 5.0,
    "refl_beam": 5.0,
    "refl": 5.0,
    "echo_top": 0.0,
    "hail_max": 0.0,
    "tornado_mask": 0.0,
}


def _masked(key: str, field):
    """Apply the presentation floor for ``key``, if it has one."""
    floor = _MASK_AT_OR_BELOW.get(key)
    array = np.asarray(field, dtype=float)
    if floor is None:
        return array
    return np.where(array <= floor, np.nan, array)


def _plan_extra(ds, dom: dict) -> dict:
    """Extra 2-D fields for ``plan_dataset``, keyed by style name."""
    extra: dict[str, np.ndarray] = {}
    for name, style_key in _SURFACE_FIELDS.items():
        if name not in ds:
            continue
        field = wo.surface_field(ds, name)
        key = style_key if style_key not in extra else name.lower()
        extra[key] = _masked(key, _echo_top_km(field) if name == "ECHOTOP" else field)
    level = dom.get("vorticity_level_agl_m")
    if level is not None and "U" in ds and "V" in ds:
        from brc_tools.visualize.upperair import interp_to_height_surface

        zeta = wc.vertical_vorticity(ds)
        z = wo.geopotential_height_mass(ds)
        target = wo.surface_field(ds, "HGT") + float(level)
        # Plotted in 10^-3 s^-1, matching the style's label.
        extra["vert_vorticity"] = interp_to_height_surface(zeta, z, target) * 1000.0
    return extra


# --------------------------------------------------------------------------- #
# families
# --------------------------------------------------------------------------- #
def render_surface(cfg, dom, ds, out_dir, ctx, args, *, extra=None) -> int:
    """Plan views of whatever 2-D convective fields the run wrote."""
    tag, stamp, base, _short, annotation = ctx
    pds = ws.plan_dataset(ds, extra=extra if extra is not None else _plan_extra(ds, dom))
    extent = tuple(dom["extent"]) if dom.get("extent") else ws.plan_extent(
        ds, pad_deg=float(dom.get("pad_deg", 0.0))
    )
    wps = we.waypoints(dom.get("waypoint_group"))
    overlays = we.overlays_from(cfg)
    made = 0
    for var in dom.get("surface_vars", ["refl_comp"]):
        if var not in pds:
            print(f"[SKIP] {tag} {var}: not written by this run")
            continue
        style = we.style_for(cfg, var)
        try:
            plot_nwp_surface_map(
                pds, var, out_dir / f"plan_{var}_{tag}_{stamp}.png",
                style=style, waypoints=wps,
                barb_stride=int(dom.get("barb_stride", 8)),
                extent=extent, overlays=overlays, annotation=annotation,
                title=f"{base} | {style.label}", dpi=args.dpi,
            )
            made += 1
        except Exception as exc:  # one bad panel is not a lost run
            print(f"[ERR] plan {tag} {var}: {exc}")
            traceback.print_exc()
    return made


def render_aux(cfg, dom, valid, init, out_dir, args) -> int:
    """Plan views from the high-cadence auxiliary stream.

    The point of this family is cadence: a ~3 km swath crossing a point in ~4
    minutes is invisible at 10-minute history output.  The stream carries no
    grid coordinates, so they are borrowed from the nearest history file.
    """
    run_dir = cfg["case"]["run_dir"]
    number = int(dom["domain"])
    stream = int(dom.get("aux_stream", 2))
    try:
        aux, index = wc.open_auxhist(run_dir, number, valid, stream)
    except FileNotFoundError as exc:
        print(f"[SKIP] aux d{number:02d}: {exc}")
        return 0
    try:
        history = _nearest_history(run_dir, number, valid)
        if history is None:
            print(f"[SKIP] aux d{number:02d}: no history file to borrow coordinates from")
            return 0
        # attach_grid_coords is called for its GRID-SHAPE CHECK, not for its
        # coordinates: plan_dataset builds latitude/longitude itself from the
        # history file below, and passing them in `extra` as well makes xarray
        # reject the dataset ("found in both data_vars and coords").
        wc.attach_grid_coords(aux, history)
        extra: dict[str, np.ndarray] = {}
        for name in dom.get("aux_fields", ["REFD_COM"]):
            if name not in aux:
                print(f"[SKIP] aux d{number:02d} {name}: not in the stream")
                continue
            try:
                field = wc.aux_field(aux, name, index)
            except ValueError as exc:  # a *_MAX field: refused on purpose
                print(f"[SKIP] aux d{number:02d} {name}: {exc}")
                continue
            key = _SURFACE_FIELDS.get(name, name.lower())
            extra[key] = _masked(key, _echo_top_km(field) if name == "ECHOTOP" else field)

        ds_hist = wo.open_wrfout(history)
        try:
            ctx = _titles(cfg, dom, ds_hist, valid, init)
            aux_dom = dict(dom)
            aux_dom["tag"] = f"{ctx[0]}_aux"
            aux_dom["surface_vars"] = list(extra)
            ctx = (aux_dom["tag"], ctx[1], ctx[2], ctx[3], ctx[4])
            return render_surface(cfg, aux_dom, ds_hist, out_dir, ctx, args, extra=extra)
        finally:
            ds_hist.close()
    finally:
        aux.close()


def _nearest_history(run_dir, domain: int, valid: datetime):
    """A history file for this domain, preferring the exact time.

    Only its static coordinates are wanted, so any time will do -- but taking the
    nearest keeps the reported grid unambiguous if a run ever moved a nest.
    """
    times = ws.list_valid_times(run_dir, domain)
    if not times:
        return None
    best = min(times, key=lambda t: abs((t - valid).total_seconds()))
    path = ws.wrfout_path(run_dir, domain, best)
    return path if path.exists() else None


def render_sections(cfg, dom, plane, out_dir, ctx, args) -> int:
    """Curtains along the named A->B transects."""
    tag, stamp, _base, short, annotation = ctx
    locator = dict(lon2d=plane.lon2d, lat2d=plane.lat2d, terrain2d=plane.terrain)
    made = 0
    for key in dom.get("sections", []):
        spec = cfg["_sections"].get(key)
        if spec is None:
            print(f"[SKIP] {tag} section {key!r}: not in [[sections]]")
            continue
        shade = spec.get("shade", "refl")
        wps = we.waypoints(spec.get("waypoint_group"))
        try:
            section = ws.section_from_plane(
                plane, tuple(spec["a"]), tuple(spec["b"]),
                n_points=int(spec.get("n_points", 240)),
                termini=tuple(spec.get("termini", ("A", "B"))),
            )
            plot_wrf_curtain(
                section, out_dir / f"xsection_{shade}_{key}_{tag}_{stamp}.png",
                shade=shade,
                style=we.style_for(cfg, spec.get("style", _shade_style(shade))),
                title=f"{short} | {spec.get('label', key)}",
                annotation=annotation, waypoints=wps,
                waypoint_offset_km=float(spec.get("offset_km", 10.0)),
                y_top_m=float(spec.get("y_top_m", 12000.0)),
                w_exaggeration=(args.w_exag if args.w_exag is not None
                                else float(spec.get("w_exag", 5.0))),
                theta_interval=float(spec.get("theta_interval", 2.0)),
                quiver_stride=tuple(spec.get("quiver_stride", (4, 10))),
                locator={
                    **locator,
                    "extent": tuple(spec["loc_extent"]) if spec.get("loc_extent") else None,
                    "rect": list(spec["loc_rect"]) if spec.get("loc_rect") else None,
                    "waypoints": wps,
                },
                dpi=args.dpi,
            )
            made += 1
        except Exception as exc:
            print(f"[ERR] xsection {tag} {key}: {exc}")
            traceback.print_exc()
    return made


def _shade_style(shade: str) -> str:
    return {"refl": "refl", "w": "w", "theta": "theta", "speed": "wind_speed_10m"}.get(
        shade, "refl"
    )


def render_beams(cfg, dom, ds, plane, out_dir, ctx, args) -> int:
    """Simulated reflectivity sampled on a radar's beam surfaces.

    This is the family that exists so a comparison against a distant WSR-88D is
    honest.  A fixed height AGL is *not* the same measurement: over this domain a
    single beam surface climbs by kilometres, and the sampled height is printed in
    the annotation so a reader can see which layer they are looking at.
    """
    tag, stamp, _base, _short, annotation = ctx
    if plane.refl is None:
        print(f"[SKIP] {tag} beams: run has no REFL_10CM (needs do_radar_ref = 1)")
        return 0

    extent = tuple(dom["extent"]) if dom.get("extent") else ws.plan_extent(
        ds, pad_deg=float(dom.get("pad_deg", 0.0))
    )
    wps = we.waypoints(dom.get("waypoint_group"))
    overlays = we.overlays_from(cfg)
    made = 0
    for key in dom.get("beams", []):
        spec = cfg["_beams"].get(key)
        if spec is None:
            print(f"[SKIP] {tag} beam {key!r}: not in [[beams]]")
            continue
        site = get_site(spec["site"])
        for elev in spec.get("elevations_deg", [0.5]):
            try:
                surface = rb.beam_surface_asl(plane.lat2d, plane.lon2d, site, float(elev))
                sampled = _masked("refl_beam", rb.sample_on_beam(plane.refl, plane.height, surface))
                agl = surface - plane.terrain
                pds = ws.plan_dataset(ds, extra={"refl_beam": sampled})
                note = (
                    f"{annotation} | {site.id} {float(elev):g} deg beam: "
                    f"{np.nanmin(agl) / 1000:.1f}-{np.nanmax(agl) / 1000:.1f} km AGL "
                    f"across this domain"
                )
                plot_nwp_surface_map(
                    pds, "refl_beam",
                    out_dir / f"beam_{site.id}_{float(elev):g}deg_{tag}_{stamp}.png",
                    style=we.style_for(cfg, "refl_beam"), waypoints=wps,
                    barb_stride=int(dom.get("barb_stride", 8)),
                    extent=extent, overlays=overlays, annotation=note,
                    # Short title: the full case label clips at this width, and it
                    # is already in the annotation.
                    title=f"{_short} | {site.id} {float(elev):g} deg beam surface",
                    dpi=args.dpi,
                )
                made += 1
            except Exception as exc:
                print(f"[ERR] beam {tag} {site.id} {elev}: {exc}")
                traceback.print_exc()

        if spec.get("compare_observed"):
            made += _render_observed(cfg, spec, site, extent, wps, overlays, ctx, out_dir, args)
    return made


def _render_observed(cfg, spec, site, extent, wps, overlays, ctx, out_dir, args) -> int:
    """Observed Level-III reflectivity at the same tilt, on the same colour scale.

    Uses the Iowa State IEM RIDGE archive, which carries elevation 1 (0.5 deg) for
    historical dates.  That is one of the tilts a beam-matched comparison needs and
    is the only observed source available for a 2025 case -- see the transport table
    in ``docs/nwp/NWP-SOURCE-MATRIX.md``.

    A missing scan is reported, not raised: an archive gap is a fact about the data.
    """
    from brc_tools.radar import iem

    tag, stamp, _base, short, annotation = ctx
    valid = datetime.strptime(stamp, "%Y%m%d_%H%M")
    product = spec.get("observed_product", "N0B")
    try:
        field = iem.observed_sweep(
            site.id, valid, product=product,
            window_minutes=float(spec.get("observed_window_minutes", 10.0)),
            extent=extent,
        )
    except Exception as exc:  # noqa: BLE001 - obs are a bonus, never a precondition
        print(f"[SKIP] observed {site.id} {product}: {type(exc).__name__}: {exc}")
        return 0
    if field is None:
        print(f"[SKIP] observed {site.id} {product}: no scan within the window of {stamp}")
        return 0

    lag = (field.valid_time - valid).total_seconds() / 60.0
    try:
        plot_nwp_surface_map(
            iem.to_plan_dataset(field), "refl_beam",
            out_dir / f"observed_{site.id}_{product}_{stamp}.png",
            style=we.style_for(cfg, "refl_beam"), waypoints=wps,
            extent=extent, overlays=overlays, terrain_contours=False,
            annotation=(
                f"{annotation} | IEM RIDGE {product} | observed {field.valid_time:%H:%MZ} "
                f"({lag:+.0f} min vs model) | elevation 1 = {field.elevation_deg:g} deg"
            ),
            title=f"OBSERVED {site.id} {product} {field.elevation_deg:g} deg | {short}",
            dpi=args.dpi,
        )
        return 1
    except Exception as exc:
        print(f"[ERR] observed {site.id} {product}: {exc}")
        traceback.print_exc()
        return 0


def render_soundings(cfg, dom, ds, out_dir, ctx, args) -> int:
    """Skew-T with a parcel path, plus a hodograph, at named points."""
    tag, stamp, _base, short, annotation = ctx
    made = 0
    for key in dom.get("soundings", []):
        spec = cfg["_soundings"].get(key)
        if spec is None:
            print(f"[SKIP] {tag} sounding {key!r}: not in [[soundings]]")
            continue
        point = we.waypoint(spec["waypoint"])
        parcel = spec.get("parcel", "ml")
        try:
            column = wo.extract_column(ds, point["lat"], point["lon"], label=key)
            summary = ce.environment_summary(column, parcel)
            note = (
                f"{annotation} | CAPE {summary[f'cape_{parcel}']:.0f} "
                f"CIN {summary[f'cin_{parcel}']:.0f} J/kg | "
                f"LCL {summary['lcl_agl_m']:.0f} m | "
                f"0-6 km shear {summary['shear_mag_0to6km']:.1f} m/s"
            )
            sounding = sounding_from_column(
                column, source=f"WRF {tag}", station=key,
                valid_time=datetime.strptime(stamp, "%Y%m%d_%H%M"),
            )
            plot_skewt(
                sounding, out_dir / f"skewt_{key}_{tag}_{stamp}.png",
                title=f"{short} | {spec.get('label', key)} | {parcel} parcel",
                annotation=note, parcel=parcel, mark_levels=True, shade_cape=True,
                p_top_hpa=float(spec.get("p_top_hpa", 150.0)),
                t_range=tuple(spec.get("t_range", (-50.0, 30.0))),
                dpi=args.dpi,
            )
            made += 1

            motion = ce.bunkers_storm_motion(column)
            observed = spec.get("observed_motion_ms")
            plot_hodograph(
                column.u_kt / 1.94384, column.v_kt / 1.94384,
                column.height_asl - column.terrain_m,
                out_dir / f"hodograph_{key}_{tag}_{stamp}.png",
                title=f"{short} | {spec.get('label', key)}",
                max_height_m=float(spec.get("hodograph_top_m", 9000.0)),
                storm_motion=(motion.right_u, motion.right_v),
                observed_motion=tuple(observed) if observed else None,
                observed_motion_label=spec.get("observed_motion_label", "observed"),
                annotation=(
                    f"0-6 km shear {summary['shear_mag_0to6km']:.1f} m/s | "
                    f"SRH 0-3 km {summary['srh_0to3km']:.0f} m2/s2"
                ),
                dpi=args.dpi,
            )
            made += 1
        except Exception as exc:
            print(f"[ERR] sounding {tag} {key}: {exc}")
            traceback.print_exc()
    return made


#: Colour per station pair, so a model trace and its observed counterpart match.
_PAIR_COLOURS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
                 "#8c564b", "#17becf", "#e377c2")


def render_verify(cfg, out_dir, args) -> int:
    """Model surface traces against observations at the named stations.

    Model values come from the ``tslist`` traces, written every model time step --
    the only stream fine enough to time a boundary passage.  Observations come from
    Synoptic, drawn dashed in the same colour as their station's model trace.

    Without a token, or for a station Synoptic does not carry, the model trace is
    still plotted: the model's internal timing and propagation speed can be read
    off it alone.  Which stations got observations is printed, so a model-only
    panel is never mistaken for agreement.
    """
    from brc_tools.visualize.timeseries import plot_scalar_timeseries

    run_dir = cfg["case"]["run_dir"]
    made = 0
    for entry in cfg.get("verify", []):
        key = entry["key"]
        domain = int(entry.get("domain", 2))
        variable = entry.get("variable", "wind_speed_10m")
        window = entry.get("window")
        try:
            series: dict[str, tuple] = {}
            styles: dict[str, dict] = {}
            obs = _observations(entry, variable, window) if entry.get("observations", True) else {}

            for index, station in enumerate(entry["stations"]):
                prefix = station["ts_prefix"]
                colour = _PAIR_COLOURS[index % len(_PAIR_COLOURS)]
                path = wt.ts_path(run_dir, prefix, domain)
                if not path.exists():
                    print(f"[SKIP] verify {key}: no {path.name}")
                    continue
                frame = wt.read_ts(path)
                if window:
                    lo = datetime.strptime(window[0], we.TIME_FMT)
                    hi = datetime.strptime(window[1], we.TIME_FMT)
                    stamps = frame["valid_time"].to_numpy()
                    keep = (stamps >= np.datetime64(lo)) & (stamps <= np.datetime64(hi))
                    frame = frame.filter(keep)
                if frame.height == 0:
                    print(f"[SKIP] verify {key} {prefix}: no rows in the window")
                    continue

                label = station.get("label", prefix)
                values = frame[_ts_column(variable)].to_numpy()
                if variable == "temp_2m":
                    values = values - 273.15  # obs are degC; compare like with like
                elif variable == "pressure_surface":
                    values = values / 100.0  # hPa
                model_label = f"{label} (model)"
                series[model_label] = (frame["valid_time"].to_list(), values)
                styles[model_label] = dict(color=colour, ls="-", marker=None, lw=1.6)

                stid = station.get("stid")
                if stid and stid in obs:
                    times, obs_values = obs[stid]
                    obs_label = f"{label} (obs {stid})"
                    series[obs_label] = (times, obs_values)
                    styles[obs_label] = dict(color=colour, ls="--", lw=1.1, marker="o", ms=3.0)

            if not series:
                continue
            drawn = sorted({s for s in obs if any(
                st.get("stid") == s for st in entry["stations"])})
            print(f"  verify {key}: observations for {drawn or 'NONE (model only)'}")
            plot_scalar_timeseries(
                series, out_dir / f"verify_{key}_{variable}.png",
                ylabel=_ts_label(cfg, variable),
                title=f"{cfg['case']['label']} | {entry.get('label', key)}",
                run_styles=styles, figsize=(10.0, 5.0), dpi=args.dpi,
            )
            made += 1
        except Exception as exc:
            print(f"[ERR] verify {key}: {exc}")
            traceback.print_exc()
    return made


def _observations(entry: dict, variable: str, window) -> dict[str, tuple]:
    """``{stid: (times, values)}`` from Synoptic, or ``{}`` if unavailable.

    Never fatal: a missing token or an unreachable API must not cost the model
    traces, which carry the internal timing on their own.
    """
    stids = [s["stid"] for s in entry["stations"] if s.get("stid")]
    if not stids or not window:
        return {}
    alias = {"pressure_surface": "pressure_surface"}.get(variable, variable)
    try:
        from brc_tools.obs import ObsSource

        frame = ObsSource().timeseries(
            stids=stids,
            start=window[0].replace("_", " ") + "Z",
            end=window[1].replace("_", " ") + "Z",
            variables=[alias],
        )
    except Exception as exc:  # noqa: BLE001 - obs are a bonus, not a precondition
        print(f"  [obs ] unavailable ({type(exc).__name__}: {exc}); plotting model only")
        return {}
    if alias not in frame.columns:
        print(f"  [obs ] Synoptic returned no {alias}; plotting model only")
        return {}

    out: dict[str, tuple] = {}
    for stid in stids:
        rows = frame.filter(frame["stid"] == stid).drop_nulls(alias).sort("valid_time")
        if rows.height:
            values = rows[alias].to_numpy()
            if alias == "pressure_surface":
                values = values / 100.0
            out[stid] = (rows["valid_time"].to_list(), values)
    return out


def _ts_label(cfg: dict, variable: str) -> str:
    return {
        "wind_speed_10m": r"10 m wind (m s$^{-1}$)",
        "wind_dir_10m": r"10 m wind direction ($^{\circ}$)",
        "temp_2m": r"$T_{2\,\mathrm{m}}$ ($^{\circ}$C)",
        "pressure_surface": "surface pressure (hPa)",
    }.get(variable, we.style_for(cfg, _ts_style(variable)).label)


def _ts_column(variable: str) -> str:
    return {
        "wind_speed_10m": "wind_speed_10m",
        "wind_dir_10m": "wind_dir_10m",
        "temp_2m": "t_2m_k",
        "pressure_surface": "psfc_pa",
    }.get(variable, variable)


def _ts_style(variable: str) -> str:
    return {"temp_2m": "temp_2m", "wind_dir_10m": "wind_speed_10m"}.get(
        variable, "wind_speed_10m"
    )


def render_track(cfg, dom, times, out_dir, args) -> int:
    """Reflectivity-centroid track over the window, written as a CSV.

    Deliberately a table rather than a figure: this is what sizes a nested domain,
    and a nest must be sized from where the *model* puts the storm.  A nest placed
    on an observed track is a nest with no storm in it if the two disagree.
    """
    run_dir = cfg["case"]["run_dir"]
    number = int(dom["domain"])
    spec = cfg.get("track", {})
    near = spec.get("near_waypoint")
    centre = we.waypoint(near) if near else None
    rows = []
    for valid in times:
        path = ws.wrfout_path(run_dir, number, valid)
        if not path.exists():
            continue
        ds = wo.open_wrfout(path)
        try:
            if "REFD_COM" in ds:
                field = wo.surface_field(ds, "REFD_COM")
            elif "REFL_10CM" in ds:
                field = np.nanmax(wo.reflectivity(ds), axis=0)
            else:
                print(f"[SKIP] track d{number:02d}: no reflectivity field")
                return 0
            found = wc.reflectivity_centroid(
                wo.surface_field(ds, "XLAT"),
                ws._lon180(wo.surface_field(ds, "XLONG")),
                field,
                threshold_dbz=float(spec.get("threshold_dbz", 35.0)),
                near=(centre["lat"], centre["lon"]) if centre else None,
                radius_km=float(spec.get("radius_km", 40.0)),
                largest_cluster=bool(spec.get("largest_cluster", True)),
            )
        finally:
            ds.close()
        if found is None:
            rows.append((valid, None, None, 0, np.nan))
        else:
            lat, lon, cells = found
            rows.append((valid, lat, lon, int(cells), float(np.nanmax(field))))

    if not rows:
        return 0
    out = out_dir / f"track_d{number:02d}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        handle.write("valid_utc,centroid_lat,centroid_lon,cells_above_threshold,max_dbz\n")
        for valid, lat, lon, cells, peak in rows:
            lat_s = "" if lat is None else f"{lat:.5f}"
            lon_s = "" if lon is None else f"{lon:.5f}"
            handle.write(f"{valid:%Y-%m-%dT%H:%MZ},{lat_s},{lon_s},{cells},{peak:.1f}\n")
    print(f"  track: {len(rows)} times -> {out}")
    return 1


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def render_domain(cfg, dom, valid, init, out_root, families, args) -> int:
    run_dir = cfg["case"]["run_dir"]
    number = int(dom["domain"])
    path = ws.wrfout_path(run_dir, number, valid)

    if "aux" in families and not path.exists():
        # The auxiliary stream can hold times the history stream does not.
        return render_aux(cfg, dom, valid, init, out_root / f"{valid:%Y%m%d_%H%M}", args)
    if not path.exists():
        return 0

    ds = wo.open_wrfout(path)
    try:
        ctx = _titles(cfg, dom, ds, valid, init)
        out_dir = out_root / ctx[1] / ctx[0]
        made = 0
        if "surface" in families:
            made += render_surface(cfg, dom, ds, out_dir, ctx, args)
        if "aux" in families:
            made += render_aux(cfg, dom, valid, init, out_root / ctx[1], args)
        if "sounding" in families:
            made += render_soundings(cfg, dom, ds, out_dir, ctx, args)

        wants_plane = ("section" in families and dom.get("sections")) or (
            "beam" in families and dom.get("beams")
        )
        if wants_plane:
            plane = ws.load_plane(ds)  # the expensive read, shared by both families
            if "section" in families:
                made += render_sections(cfg, dom, plane, out_dir, ctx, args)
            if "beam" in families:
                made += render_beams(cfg, dom, ds, plane, out_dir, ctx, args)
        print(f"  {ctx[0]}: {made} figures -> {out_dir}")
        return made
    finally:
        ds.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, type=Path, help="case TOML")
    parser.add_argument("--run-dir", type=Path, help="override the TOML run directory")
    we.add_time_arguments(parser)
    parser.add_argument(
        "--figure", action="append", metavar="FAMILY",
        help=f"restrict to a family ({'|'.join(FAMILIES)}); repeatable",
    )
    parser.add_argument("--domain", type=int, action="append",
                        help="restrict to this nest (repeatable)")
    parser.add_argument("--output-dir", type=Path, help="override the output root")
    parser.add_argument("--w-exag", type=float,
                        help="override every section's vertical exaggeration; a "
                             "convective updraft wants ~5, a drainage night ~100")
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    cfg = we.load_config(args.config, index=("sections", "beams", "soundings"))
    if args.run_dir:
        cfg["case"]["run_dir"] = args.run_dir
    run_dir = cfg["case"]["run_dir"]
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")

    bad = [f for f in (args.figure or []) if f not in FAMILIES]
    if bad:
        raise SystemExit(f"unknown figure family {bad}; known: {list(FAMILIES)}")
    families = set(args.figure or FAMILIES)

    domains = [d for d in cfg.get("domains", [])
               if not args.domain or int(d["domain"]) in args.domain]
    if not domains:
        raise SystemExit("no domains selected")
    numbers = [int(d["domain"]) for d in domains]

    use_publication_style(dpi=args.dpi)
    out_root = we.output_root(cfg, args.output_dir, config_path=args.config)

    # Sweeping the auxiliary stream alone needs its times, not the history's.
    aux_only = families == {"aux"}
    times = we.select_times(
        run_dir, numbers,
        valid=args.valid, lead=args.lead, hourly=args.hourly,
        every=args.every, all_times=args.all_times,
        start=args.start, end=args.end,
        times_for=(lambda d: wc.list_aux_times(run_dir, d)) if aux_only else None,
        label="auxhist" if aux_only else "wrfout",
    )
    init = ws.init_time(run_dir, min(numbers))

    print(f"[run ] {run_dir}")
    print(f"[init] {init:{we.TIME_FMT}}")
    print(f"[out ] {out_root}")
    print(f"[fams] {sorted(families)}")

    total = 0
    for valid in times:
        for dom in domains:
            total += render_domain(cfg, dom, valid, init, out_root, families, args)

    if "verify" in families:
        total += render_verify(cfg, out_root, args)
    if "track" in families:
        # One CSV per NEST, not per view: a nest may appear as several [[domains]]
        # entries (full extent plus a zoom) and they would otherwise overwrite each
        # other's output while double-counting the total.
        seen_domains: set[int] = set()
        for dom in domains:
            number = int(dom["domain"])
            if number in seen_domains:
                continue
            seen_domains.add(number)
            total += render_track(cfg, dom, times, out_root, args)

    print(f"[done] {total} output(s) -> {out_root}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
