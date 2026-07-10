"""Dataset-agnostic engine for WRF publication figures.

This is the reusable core behind the ``scripts/wrf_figures.py`` CLI: it turns a
declarative :class:`CaseConfig` (loaded from a per-study TOML) plus a runtime
:class:`Selection` into a list of ``(name, callable, args)`` figure tasks for
:func:`brc_tools.nwp.case_study.run_figure_pipeline`.

Design goals (see ``docs/WRF-FIGURE-ENGINE.md``):

* **Case config is data, not code.** Which runs, the focus point, crest height,
  waypoints, surface variables, difference pairs and RAOB stations all live in the
  TOML; this module holds no study-specific constants.
* **Domain-aware from the data.** Nests are discovered by globbing ``wrfout_d0N``
  (:func:`brc_tools.nwp.wrf_output.discover_domains`) and labelled from the ``DX``
  global attr, so a 2-, 3- or 4-nest run works with no code change.
* **Fail loudly with a named reason.** :func:`preflight` probes each case up front
  (domains present, focus point in-domain, surface variables present, times present)
  and returns a structured report; :func:`build_tasks` only emits tasks that will
  succeed and prints an explicit skip/warn report — a missing ``SNOWH`` or an
  off-grid focus point becomes a named skip, not a silent per-figure ``[ERROR]``.

The renderers (``brc_tools.visualize.*``) and the reader (``wrf_output``) are already
dataset-agnostic and are reused unchanged; nothing here touches the brc-wrf-facing
``brc_tools.visualize.grid`` seam.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.crosssection import (
    plot_wrf_section,
    plot_wrf_section_difference,
)
from brc_tools.visualize.domains import plot_domain_boxes
from brc_tools.visualize.profile import (
    CachedSounding,
    plot_skewt,
    plot_theta_profiles,
    sounding_from_column,
)
from brc_tools.visualize.style import VarStyle, resolve_style
from brc_tools.visualize.surface import plot_domain_panels, plot_field_difference
from brc_tools.visualize.timeseries import plot_scalar_timeseries
from brc_tools.visualize.upperair import (
    below_ground_mask,
    interp_to_height_surface,
    interp_to_pressure_surface,
    plot_height_surface,
    temperature_advection,
)

FAMILIES = [
    "domains", "section", "upperair", "surface",
    "difference", "profile", "skewt", "heatdeficit",
]

# Vertical extent for the theta(z) profile plot (m MSL); a generic default.
_PROFILE_Y_MAX_M = 3300.0

# Upper-air smoothing (grid cells).  The crest map is on the fine inner nest, so its
# advection needs a firm pre-gradient smooth; the pressure map is on the coarse outer
# nest already, so it needs only a light touch.
_CREST_ADV_SMOOTH = 2.0
_PRESSURE_ADV_SMOOTH = 1.5
# View crop (deg lon, deg lat) around the focus point for the synoptic pressure map — the
# advection is computed on the full outer nest, but shown over the basin + flanking ranges.
_PRESSURE_VIEW_DEG = (1.5, 1.05)
# Natural-Earth reference layers a case may switch on via its ``[map]`` table.
_MAP_LAYERS = ("states", "roads", "rivers", "lakes")

# Which raw wrfout variables each surface key needs.  A key is "available" if *any*
# alternative group is fully present (theta_2m can come from TH2 or T2+PSFC).
_SURFACE_REQUIRES: dict[str, tuple[tuple[str, ...], ...]] = {
    "theta2m": (("TH2",), ("T2", "PSFC")),
    "t2": (("T2",),),
    "wspd10": (("U10", "V10"),),
    "snow": (("SNOWH",),),
    "pblh": (("PBLH",),),
}


# --------------------------------------------------------------------------- #
# config dataclasses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FocusPoint:
    """A named lat/lon of interest (profiles / skew-T / heat-deficit)."""

    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class SurfaceVar:
    """A multi-domain surface panel: engine key, style key, and wind-vector flag."""

    key: str
    style: str
    wind: bool = False


@dataclass(frozen=True)
class DiffPair:
    """A difference family: case ``a`` minus case ``b`` (2 m theta map, opt. sections)."""

    a: str
    b: str
    tag: str
    feedback: bool = False
    sections: bool = False
    dir: str | None = None  # output subdir; default derived from the tag slug
    limit: float | None = None  # fixed symmetric diverging limit (K); else feedback default


@dataclass(frozen=True)
class RunSpec:
    """One archived run: directory name under the archive and a display label."""

    dir: str
    label: str


@dataclass(frozen=True)
class StyleConfig:
    """Per-case colour-scale policy.  Fixed shared scales stay the default."""

    autoscale: bool = False
    overrides: dict[str, VarStyle] = field(default_factory=dict)


@dataclass
class CaseConfig:
    """Everything study-specific about a WRF figure case (loaded from TOML)."""

    slug: str
    label: str
    archive_dir: Path
    run_subdir: str
    annotation: str
    crest_m: float
    focus_point: FocusPoint
    waypoints: dict[str, dict]
    surface_vars: list[SurfaceVar]
    sounding_stations: tuple[str, ...]
    ic_cases: tuple[str, ...]
    runs: dict[str, RunSpec]
    differences: list[DiffPair]
    style: StyleConfig
    profile_hours: tuple[int, ...]
    sounding_hour: int
    upper_pressure_hpa: float = 600.0     # pressure surface for the synoptic T-adv map
    upper_adv_domain: str = "outer"       # "outer" (clean synoptic) | "inner" (fine)
    map_overlays: dict = field(default_factory=dict)  # {layer: bool} Natural-Earth refs

    # -- run-directory resolution (was the module-global run_dir/RUN_OVERRIDE) --
    def run_base(self, case: str) -> Path:
        return self.archive_dir / self.runs[case].dir / self.run_subdir

    def resolve_run_dir(self, case: str, run_override: str | None = None) -> Path:
        base = self.run_base(case)
        return (base / run_override) if run_override else wo.latest_run_dir(base)

    @classmethod
    def from_toml(cls, path: str | Path, *, archive_override: str | None = None) -> CaseConfig:
        """Build a :class:`CaseConfig` from a case TOML (see docs for the schema)."""
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
        case = data["case"]
        fp = case["focus_point"]
        # env BRC_WRF_ARCHIVE still wins over the TOML default, preserving prior behaviour.
        archive = archive_override or os.environ.get("BRC_WRF_ARCHIVE") or case["archive_dir"]
        waypoints = {
            name: {"lat": float(v["lat"]), "lon": float(v["lon"])}
            for name, v in data.get("waypoints", {}).items()
        }
        surface_vars = [
            SurfaceVar(sv["key"], sv["style"], bool(sv.get("wind", False)))
            for sv in case.get("surface_vars", [])
        ]
        soundings = data.get("soundings", {})
        runs = {k: RunSpec(v["dir"], v["label"]) for k, v in data.get("runs", {}).items()}
        differences = [
            DiffPair(
                d["a"], d["b"], d["tag"],
                feedback=bool(d.get("feedback", False)),
                sections=bool(d.get("sections", False)),
                dir=d.get("dir"),
                limit=(float(d["limit"]) if d.get("limit") is not None else None),
            )
            for d in data.get("differences", [])
        ]
        map_data = data.get("map", {})
        map_overlays = {layer: bool(map_data.get(layer, False)) for layer in _MAP_LAYERS}
        style_data = data.get("style", {})
        overrides = {
            k: _varstyle_from_dict(v)
            for k, v in style_data.get("overrides", {}).items()
        }
        return cls(
            slug=case["slug"],
            label=case["label"],
            archive_dir=Path(archive),
            run_subdir=case.get("run_subdir", ""),
            annotation=case.get("annotation", ""),
            crest_m=float(case["crest_m"]),
            focus_point=FocusPoint(fp.get("name", "focus"), float(fp["lat"]), float(fp["lon"])),
            waypoints=waypoints,
            surface_vars=surface_vars,
            sounding_stations=tuple(soundings.get("stations", [])),
            ic_cases=tuple(soundings.get("ic_cases", [])),
            runs=runs,
            differences=differences,
            style=StyleConfig(
                autoscale=bool(style_data.get("autoscale", False)),
                overrides=overrides,
            ),
            profile_hours=tuple(int(h) for h in case.get("profile_hours", [])),
            sounding_hour=int(case.get("sounding_hour", 12)),
            upper_pressure_hpa=float(case.get("upper_pressure_hpa", 600.0)),
            upper_adv_domain=str(case.get("upper_adv_domain", "outer")),
            map_overlays=map_overlays,
        )


def _varstyle_from_dict(d: dict) -> VarStyle:
    return VarStyle(
        cmap=d["cmap"],
        label=d.get("label", ""),
        vmin=d.get("vmin"),
        vmax=d.get("vmax"),
        levels=tuple(d["levels"]) if d.get("levels") else None,
        extend=d.get("extend", "both"),
        diverging=bool(d.get("diverging", False)),
    )


@dataclass
class Selection:
    """Runtime figure selection (the CLI flags), independent of the case config."""

    cases: list[str] | None = None      # None -> every run in the config
    families: list[str] | None = None   # None -> every family
    time: str = "all"                   # "all" or comma-separated hours (hour-of-day)
    output_dir: str | None = None       # override output root (else routed by case)
    run_override: str | None = None      # a specific run_* dir name (else latest)
    sounding_cache: str | None = None    # parquet for skew-T obs overlay
    lead: str | None = None              # forecast lead hour(s) from init; overrides `time`
    skip_existing: bool = False          # skip figures already newer than their wrfout
    section_domain: str | None = None    # section family nest override (e.g. "d03"); None -> innermost


@dataclass
class PreflightReport:
    """Structured result of probing one case's data before building tasks."""

    case: str
    domains: list[int]
    innermost: int | None
    outermost: int | None
    point_ok: bool
    usable_surface_vars: list[SurfaceVar]
    times: list[datetime]
    skips: list[str]
    warnings: list[str]
    init: datetime | None = None  # model init/cycle time (for forecast-lead selection)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


def _focus_slug(cfg: CaseConfig) -> str:
    return _slug(cfg.focus_point.name) or "focus"


def _section_domain(
    selection: Selection, rep: PreflightReport
) -> tuple[int | None, str, str | None]:
    """Resolve the nest the ``section`` family renders on, plus a filename tag.

    Defaults to the innermost nest with an empty tag (legacy filenames, so existing
    output and ``--skip-existing`` are unaffected).  With ``--section-domain`` set to
    a nest that exists (e.g. ``d03`` on a 4-nest run whose innermost is ``d04``), use
    that nest and tag its filenames ``_dNN`` so the override coexists with the default
    set.  Returns ``(None, "", reason)`` when the requested nest isn't present, so the
    caller name-skips it rather than crashing (consistent with the fail-soft preflight).
    """
    if not selection.section_domain:
        return rep.innermost, "", None
    want = int(str(selection.section_domain).lower().lstrip("d"))
    if want not in rep.domains:
        have = ",".join(f"d{d:02d}" for d in rep.domains)
        return None, "", f"d{want:02d} not among [{have}]"
    tag = "" if want == rep.innermost else f"_d{want:02d}"
    return want, tag, None


def _select_times(
    times: list[datetime], selection: Selection, init: datetime | None
) -> tuple[list[datetime], list[tuple[int, datetime]]]:
    """Resolve a case's valid times to render, plus any requested-but-absent leads.

    With ``selection.lead`` set, select the valid times at ``init + lead`` hours
    (this *overrides* ``--time``); leads whose wrfout file is not present come back
    as ``(lead_hours, target_valid_time)`` so the caller can name-skip them instead
    of crashing.  Otherwise fall back to ``--time`` (``all`` or hour-of-day).
    """
    if selection.lead:
        base = init if init is not None else (times[0] if times else None)
        available = set(times)
        selected: list[datetime] = []
        missing: list[tuple[int, datetime]] = []
        for lead in (int(x) for x in str(selection.lead).split(",")):
            if base is None:
                continue
            target = base + timedelta(hours=lead)
            if target in available:
                selected.append(target)
            else:
                missing.append((lead, target))
        return sorted(selected), missing
    requested = selection.time
    if requested in (None, "all"):
        return list(times), []
    hours = {int(h) for h in str(requested).split(",")}
    return [t for t in times if t.hour in hours], []


def _skip_existing(out_png: Path, srcs: list[Path], enabled: bool) -> bool:
    """Whether an idempotent re-run may skip ``out_png``.

    True only when ``enabled`` and the figure already exists and is at least as new
    as every source wrfout it derives from (mtime).  A source rewritten by a later
    WRF run is thus newer than the figure, so the figure regenerates ("move to newer
    output").  Keyed on the hour-only filename, so it is safe for hourly (or coarser)
    output; sub-hourly cadence would collide (see docs/WRF-FIGURE-ENGINE.md).
    """
    if not enabled or not out_png.exists():
        return False
    out_mtime = out_png.stat().st_mtime
    for s in srcs:
        s = Path(s)
        if not s.exists() or s.stat().st_mtime > out_mtime:
            return False
    return True


def _surface_var_available(present: set[str], key: str) -> tuple[bool, tuple[str, ...]]:
    """Whether a surface key is computable from the variables ``present`` in a file."""
    groups = _SURFACE_REQUIRES.get(key)
    if groups is None:
        return True, ()  # unknown key: don't block; the compute fn will raise if wrong
    for group in groups:
        if all(v in present for v in group):
            return True, ()
    return False, groups[0]  # report the preferred group's names as "missing"


def _wind_speed(ds) -> np.ndarray:
    return np.hypot(wo.surface_field(ds, "U10"), wo.surface_field(ds, "V10"))


def _surface_field_for(ds, key: str) -> np.ndarray:
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


# --------------------------------------------------------------------------- #
# per-figure tasks (each self-contained for run_figure_pipeline try/except)
# --------------------------------------------------------------------------- #
def task_section(cfg, run, dom, case, label, valid, orient, out, skip_existing=False, domain_tag=""):
    # ``domain_tag`` is "" for the default innermost nest (legacy filename) and "_dNN"
    # when --section-domain targets a coarser nest, so the override coexists with the
    # default set instead of clobbering it.
    out_png = out / f"section_{orient.lower()}_{case}{domain_tag}_{valid:%H}z.png"
    src = wo.wrfout_path(run, dom, valid)
    if _skip_existing(out_png, [src], skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    ds = wo.open_wrfout(src)
    sec = wo.build_section(ds, orient)
    plot_wrf_section(
        sec, out_png,
        locator_terrain=wo.surface_field(ds, "HGT"),
        title=f"{label} | d{dom:02d} {orient} section | {valid:%Y-%m-%d %H}Z",
        annotation=cfg.annotation, waypoints=cfg.waypoints,
    )


def task_upperair(cfg, run, innermost, case, label, valid, out, skip_existing=False):
    crest = cfg.crest_m
    out_png = out / f"crest{int(crest)}_{case}_{valid:%H}z.png"
    src = wo.wrfout_path(run, innermost, valid)
    if _skip_existing(out_png, [src], skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    ds = wo.open_wrfout(src)
    z = wo.geopotential_height_mass(ds)
    ue, ve = wo.earth_relative_winds(ds)
    dx, dy = wo.dx_dy(ds)
    th = interp_to_height_surface(wo.potential_temperature(ds), z, crest)
    u2 = interp_to_height_surface(ue, z, crest)
    v2 = interp_to_height_surface(ve, z, crest)
    tk = interp_to_height_surface(wo.temperature_k(ds), z, crest)
    hgt = wo.surface_field(ds, "HGT")
    plot_height_surface(
        wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT"), th, u2, v2,
        out_png,
        temp_adv2d=temperature_advection(tk, u2, v2, dx, dy, smooth_sigma=_CREST_ADV_SMOOTH),
        terrain=hgt,
        target_label=f"{int(crest)} m MSL", mask=below_ground_mask(crest, hgt),
        adv_smooth_sigma=_CREST_ADV_SMOOTH,
        style=resolve_style("theta_crest", overrides=cfg.style.overrides,
                            autoscale=cfg.style.autoscale),
        waypoints=cfg.waypoints, overlays=cfg.map_overlays,
        title=f"{label} | crest theta + wind + T-adv | {valid:%H}Z", annotation=cfg.annotation,
    )


def task_upperair_pressure(cfg, run, domain, case, label, valid, out, skip_existing=False):
    """Synoptic temperature-advection map on a pressure surface (default 600 hPa).

    Computed on the *outer* nest by default: 600 hPa sits well above the shallow inner
    nest, where a raw ``grad(T)`` on the 333 m mesh is dominated by noise.  The coarse
    nest plus a pre-gradient smooth gives the clean warm/cold-advection pattern that caps
    the cold pool.
    """
    p_hpa = float(cfg.upper_pressure_hpa)
    out_png = out / f"p{int(p_hpa)}_advection_{case}_{valid:%H}z.png"
    src = wo.wrfout_path(run, domain, valid)
    if _skip_existing(out_png, [src], skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    ds = wo.open_wrfout(src)
    lon2d, lat2d = wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT")
    p = wo.pressure_pa(ds)
    ue, ve = wo.earth_relative_winds(ds)
    dx, dy = wo.dx_dy(ds)
    target_pa = p_hpa * 100.0
    tk = interp_to_pressure_surface(wo.temperature_k(ds), p, target_pa)
    tc = tk - 273.15
    u = interp_to_pressure_surface(ue, p, target_pa)
    v = interp_to_pressure_surface(ve, p, target_pa)
    dlon, dlat = _PRESSURE_VIEW_DEG
    fx, fy = cfg.focus_point.lon, cfg.focus_point.lat
    extent = (max(float(lon2d.min()), fx - dlon), min(float(lon2d.max()), fx + dlon),
              max(float(lat2d.min()), fy - dlat), min(float(lat2d.max()), fy + dlat))
    plot_height_surface(
        lon2d, lat2d, tc, u, v, out_png,
        temp_adv2d=temperature_advection(tk, u, v, dx, dy, smooth_sigma=_PRESSURE_ADV_SMOOTH),
        terrain=None,  # d01 terrain contours are too busy here; overlays give the geography
        target_label=f"{int(p_hpa)} hPa", mask=None,
        adv_smooth_sigma=_PRESSURE_ADV_SMOOTH, extent=extent,
        style=resolve_style("temp_upper", overrides=cfg.style.overrides,
                            autoscale=cfg.style.autoscale),
        waypoints=cfg.waypoints, overlays=cfg.map_overlays,
        title=f"{label} | d{domain:02d} {int(p_hpa)} hPa T + wind + T-adv | {valid:%H}Z",
        annotation=cfg.annotation,
    )


def task_surface(cfg, run, domains, case, label, valid, sv, out, skip_existing=False):
    out_png = out / f"{sv.key}_{case}_multidomain_{valid:%H}z.png"
    srcs = [wo.wrfout_path(run, dom, valid) for dom in domains]
    if _skip_existing(out_png, srcs, skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    innermost = domains[-1]
    d_in = wo.open_wrfout(wo.wrfout_path(run, innermost, valid))
    lon_in, lat_in = wo.surface_field(d_in, "XLONG"), wo.surface_field(d_in, "XLAT")
    extent = (float(lon_in.min()), float(lon_in.max()), float(lat_in.min()), float(lat_in.max()))
    panels = []
    for dom in domains:
        ds = wo.open_wrfout(wo.wrfout_path(run, dom, valid))
        panel = {
            "label": f"d{dom:02d} ({wo.grid_spacing_label(ds)})",
            "lon": wo.surface_field(ds, "XLONG"), "lat": wo.surface_field(ds, "XLAT"),
            "field": _surface_field_for(ds, sv.key), "terrain": wo.surface_field(ds, "HGT"),
        }
        if sv.wind:
            panel["u"] = wo.surface_field(ds, "U10")
            panel["v"] = wo.surface_field(ds, "V10")
        panels.append(panel)
    style = resolve_style(sv.style, overrides=cfg.style.overrides, autoscale=cfg.style.autoscale)
    plot_domain_panels(
        panels, out_png, style=style,
        wind=sv.wind, extent=extent, waypoints=cfg.waypoints, overlays=cfg.map_overlays,
        suptitle=f"{label} | {sv.style} | d{innermost:02d} area | {valid:%H}Z",
    )


def task_diff_map(cfg, run_a, run_b, innermost, tag, valid, out, feedback, limit=None,
                  skip_existing=False):
    out_png = out / f"theta2m_{tag}_{valid:%H}z.png"
    srcs = [wo.wrfout_path(run_a, innermost, valid), wo.wrfout_path(run_b, innermost, valid)]
    if _skip_existing(out_png, srcs, skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    da = wo.open_wrfout(srcs[0])
    db = wo.open_wrfout(srcs[1])
    lim = limit if limit is not None else (3.0 if feedback else 5.0)
    plot_field_difference(
        wo.surface_field(da, "XLONG"), wo.surface_field(da, "XLAT"),
        wo.theta_2m(da), wo.theta_2m(db), out_png,
        var="theta", limit=lim,
        title=f"{tag} | 2 m theta | d{innermost:02d} | {valid:%H}Z",
        terrain=wo.surface_field(da, "HGT"), annotation=cfg.annotation,
    )


def task_diff_section(cfg, run_a, run_b, innermost, tag, valid, orient, out, limit=None,
                      skip_existing=False):
    out_png = out / f"section_{orient.lower()}_{tag}_{valid:%H}z.png"
    src_a = wo.wrfout_path(run_a, innermost, valid)
    src_b = wo.wrfout_path(run_b, innermost, valid)
    if _skip_existing(out_png, [src_a, src_b], skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    sec_a = wo.build_section(wo.open_wrfout(src_a), orient)
    db = wo.open_wrfout(src_b)
    sec_b = wo.build_section(db, orient)
    plot_wrf_section_difference(
        sec_a, sec_b, out_png,
        var="theta", limit=limit,
        title=f"{tag} | d{innermost:02d} {orient} theta | {valid:%H}Z",
        locator_terrain=wo.surface_field(db, "HGT"), annotation=cfg.annotation,
        waypoints=cfg.waypoints,
    )


def task_domains(cfg, run, domains, out, skip_existing=False):
    out_png = out / "nested_domains.png"
    srcs = [wo.wrfout_path(run, dom, wo.list_valid_times(run, dom)[0]) for dom in domains]
    if _skip_existing(out_png, srcs, skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    outlines = []
    outermost = domains[0]
    terr = lon = lat = None
    for dom in domains:
        times = wo.list_valid_times(run, dom)
        ds = wo.open_wrfout(wo.wrfout_path(run, dom, times[0]))
        outlines.append(wo.domain_outline(ds, label=f"d{dom:02d} ({wo.grid_spacing_label(ds)})"))
        if dom == outermost:
            terr = wo.surface_field(ds, "HGT")
            lon, lat = wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT")
    plot_domain_boxes(
        outlines, out_png, terrain=terr, terrain_lonlat=(lon, lat),
        waypoints=cfg.waypoints, overlays=cfg.map_overlays,
        title=f"{cfg.label} WRF nested domains",
    )


def task_profiles(cfg, case_runs, valid, out, skip_existing=False):
    out_png = out / f"theta_profiles_{_focus_slug(cfg)}_{valid:%H}z.png"
    srcs = [wo.wrfout_path(run, innermost, valid) for _case, _label, run, innermost in case_runs]
    if _skip_existing(out_png, srcs, skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    cols = {}
    for _case, label, run, innermost in case_runs:
        ds = wo.open_wrfout(wo.wrfout_path(run, innermost, valid))
        cols[label] = wo.extract_column(ds, cfg.focus_point.lat, cfg.focus_point.lon, label=label)
    ref_terrain = next(iter(cols.values())).terrain_m
    plot_theta_profiles(
        cols, out_png,
        terrain_m=ref_terrain, crest_m=cfg.crest_m, y_max_m=_PROFILE_Y_MAX_M,
        title=rf"$\theta(z)$ at {cfg.focus_point.name} | {valid:%Y-%m-%d %H}Z",
        annotation=cfg.annotation,
    )


def task_skewt(cfg, run, innermost, case, label, valid, out, skip_existing=False):
    """Focus-point (innermost) model skew-T -- the cold-pool structure (model-only)."""
    out_png = out / f"skewt_{_focus_slug(cfg)}_{case}_{valid:%H}z.png"
    src = wo.wrfout_path(run, innermost, valid)
    if _skip_existing(out_png, [src], skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    ds = wo.open_wrfout(src)
    model = sounding_from_column(
        wo.extract_column(ds, cfg.focus_point.lat, cfg.focus_point.lon),
        source=label, station=cfg.focus_point.name, valid_time=valid,
    )
    plot_skewt(
        model, out_png,
        title=f"{label} skew-T | {cfg.focus_point.name} (d{innermost:02d}) | {valid:%Y-%m-%d %H}Z",
        annotation=cfg.annotation,
    )


def task_skewt_station(
    cfg, run, outermost, case, label, station_name, valid, out, sounding_cache, skip_existing=False
):
    """Model outermost-domain column at a RAOB proxy site, overlaid on that sounding."""
    from brc_tools.api.soundings import STATIONS

    out_png = out / f"skewt_{station_name}_{case}_{valid:%H}z.png"
    src = wo.wrfout_path(run, outermost, valid)
    if _skip_existing(out_png, [src], skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    st = STATIONS[station_name]
    ds = wo.open_wrfout(src)
    model = sounding_from_column(
        wo.extract_column(ds, st.lat, st.lon),
        source=label, station=station_name, valid_time=valid,
    )
    obs = CachedSounding(sounding_cache).get(station_name, valid) if sounding_cache else None
    plot_skewt(
        model, out_png, obs=obs,
        title=f"{label} vs RAOB | {station_name} ({st.location}) d{outermost:02d} | {valid:%H}Z",
        annotation=cfg.annotation,
    )


def task_heatdeficit(cfg, case_runs, out, skip_existing=False):
    out_png = out / "heat_deficit_timeseries.png"
    times_by_case = {
        label: wo.list_valid_times(run, innermost)
        for _case, label, run, innermost in case_runs
    }
    srcs = [
        wo.wrfout_path(run, innermost, t)
        for _case, label, run, innermost in case_runs
        for t in times_by_case[label]
    ]
    if _skip_existing(out_png, srcs, skip_existing):
        print(f"  [skip] {out_png.name} up to date")
        return
    series = {}
    for _case, label, run, innermost in case_runs:
        times = times_by_case[label]
        deficits = []
        for t in times:
            ds = wo.open_wrfout(wo.wrfout_path(run, innermost, t))
            deficits.append(
                wo.cold_pool_heat_deficit(
                    wo.extract_column(ds, cfg.focus_point.lat, cfg.focus_point.lon), cfg.crest_m
                ) / 1e6
            )
        series[label] = (times, np.array(deficits))
    plot_scalar_timeseries(
        series, out_png,
        ylabel=r"cold-pool heat deficit (MJ m$^{-2}$)",
        title=f"Cold-pool heat deficit at {cfg.focus_point.name} (crest {int(cfg.crest_m)} m)",
    )


# --------------------------------------------------------------------------- #
# preflight validation
# --------------------------------------------------------------------------- #
def preflight(cfg: CaseConfig, case: str, *, run_override: str | None = None) -> PreflightReport:
    """Probe one case's data and report what can/can't be rendered (never raises)."""
    skips: list[str] = []
    warnings: list[str] = []
    try:
        run = cfg.resolve_run_dir(case, run_override)
    except (FileNotFoundError, KeyError) as exc:
        return PreflightReport(case, [], None, None, False, [], [], [f"case {case}: {exc}"], [])

    domains = wo.discover_domains(run)
    if not domains:
        skips.append(f"case {case}: no wrfout_d0* files under {run}")
        return PreflightReport(case, [], None, None, False, [], [], skips, warnings)

    innermost, outermost = domains[-1], domains[0]
    times = wo.list_valid_times(run, innermost)
    if not times:
        skips.append(f"case {case}: no valid times for d{innermost:02d} under {run}")
        return PreflightReport(case, domains, innermost, outermost, False, [], [], skips, warnings)
    init = wo.init_time(run, innermost)  # for forecast-lead (--lead) selection

    # probe each domain (at the first time) for the focus point and variable presence.
    point_ok = True
    present_by_dom: dict[int, set[str]] = {}
    for dom in domains:
        try:
            ds = wo.open_wrfout(wo.wrfout_path(run, dom, times[0]))
        except (FileNotFoundError, OSError) as exc:
            skips.append(f"case {case}: cannot open d{dom:02d} at {times[0]:%H}Z ({exc})")
            continue
        present_by_dom[dom] = set(ds.data_vars)
        if dom == innermost:
            point_ok = wo.point_in_domain(ds, cfg.focus_point.lat, cfg.focus_point.lon)
        ds.close()

    if not point_ok:
        warnings.append(
            f"case {case}: focus point {cfg.focus_point.name} "
            f"({cfg.focus_point.lat}, {cfg.focus_point.lon}) is outside d{innermost:02d} bounds"
        )
        skips.append(
            f"case {case}: profile / skew-T / heat-deficit skipped (focus point off-grid)"
        )

    usable: list[SurfaceVar] = []
    for sv in cfg.surface_vars:
        missing_dom = None
        missing_vars: tuple[str, ...] = ()
        for dom in domains:
            present = present_by_dom.get(dom)
            if present is None:
                continue
            avail, req = _surface_var_available(present, sv.key)
            if not avail:
                missing_dom, missing_vars = dom, req
                break
        if missing_dom is None:
            usable.append(sv)
        else:
            skips.append(
                f"case {case}: surface:{sv.key} — {'/'.join(missing_vars)} "
                f"absent in d{missing_dom:02d}"
            )

    return PreflightReport(
        case, domains, innermost, outermost, point_ok, usable, times, skips, warnings, init=init
    )


def _print_report(cfg: CaseConfig, reports: dict[str, PreflightReport]) -> None:
    header = f"preflight: {cfg.label}"
    print(f"\n=== {header} ===")
    for case, rep in reports.items():
        if not rep.domains:
            print(f"  [SKIP] {case}: {'; '.join(rep.skips) or 'no data'}")
            continue
        doms = ",".join(f"d{d:02d}" for d in rep.domains)
        print(f"  {case}: {doms} (innermost d{rep.innermost:02d}); {len(rep.times)} time(s)")
        for w in rep.warnings:
            print(f"    [WARN] {w}")
        for s in rep.skips:
            print(f"    [SKIP] {s}")
    print("=" * (len(header) + 8))


def _report_missing_leads(reports: dict[str, PreflightReport], selection: Selection) -> None:
    """Name-skip requested forecast leads whose wrfout file isn't present yet.

    A lead WRF hasn't reached is reported (not crashed on): re-running once that
    output lands picks it up.  No-op unless ``--lead`` is set.
    """
    if not selection.lead:
        return
    for case, rep in reports.items():
        if not rep.domains or rep.init is None:
            continue
        _, missing = _select_times(rep.times, selection, rep.init)
        for lead, target in missing:
            print(f"  [SKIP] {case}: lead {lead}h → {target:%Y-%m-%d %H}Z not available yet")


# --------------------------------------------------------------------------- #
# output routing (generated figures must stay OUT of the repo checkout)
# --------------------------------------------------------------------------- #
def _validate_output_dir(path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]  # brc_tools/nwp/wrf_figures.py -> repo root
    resolved = Path(path).resolve()
    if resolved == repo or repo in resolved.parents:
        raise SystemExit(f"refusing to write figures into the repo checkout: {resolved}")


def out_dir(cfg: CaseConfig, selection: Selection, family: str, case: str | None) -> Path:
    if selection.output_dir:
        base = Path(selection.output_dir)
        if case is not None:
            base = base / case
        base = base / family
    elif case is not None:
        base = cfg.resolve_run_dir(case, selection.run_override) / "full-figures" / family
    else:
        base = cfg.archive_dir / f"{cfg.slug}_pub_figures" / "compare" / family
    _validate_output_dir(base)
    base.mkdir(parents=True, exist_ok=True)
    return base


# --------------------------------------------------------------------------- #
# task assembly
# --------------------------------------------------------------------------- #
def build_tasks(cfg: CaseConfig, selection: Selection) -> list[tuple]:
    """Preflight every selected case, print a report, and emit only runnable tasks."""
    fams = selection.families or FAMILIES
    cases = selection.cases or list(cfg.runs)
    unknown = [c for c in cases if c not in cfg.runs]
    if unknown:
        raise SystemExit(f"unknown case(s) {unknown}; known cases: {list(cfg.runs)}")

    if selection.lead and selection.time not in (None, "all"):
        print(f"note: --lead {selection.lead} governs time selection; --time {selection.time} ignored")

    reports = {c: preflight(cfg, c, run_override=selection.run_override) for c in cases}
    _print_report(cfg, reports)
    _report_missing_leads(reports, selection)

    usable_cases = [c for c in cases if reports[c].domains]
    point_cases = [c for c in usable_cases if reports[c].point_ok]
    case_runs = [
        (c, cfg.runs[c].label, cfg.resolve_run_dir(c, selection.run_override), reports[c].innermost)
        for c in point_cases
    ]
    tasks: list[tuple] = []

    skip = selection.skip_existing

    # --- cross-case families ---
    if "domains" in fams and usable_cases:
        c0 = usable_cases[0]
        run0 = cfg.resolve_run_dir(c0, selection.run_override)
        tasks.append(("domains map", task_domains,
                      (cfg, run0, reports[c0].domains, out_dir(cfg, selection, "domains", None), skip)))
    if "profile" in fams and case_runs:
        prep = reports[point_cases[0]]
        if selection.lead:
            profile_times, _ = _select_times(prep.times, selection, prep.init)
        else:
            profile_times = [t for t in prep.times if t.hour in cfg.profile_hours]
        for t in profile_times:
            tasks.append((f"profiles {t:%H}Z", task_profiles,
                          (cfg, case_runs, t, out_dir(cfg, selection, "profiles", None), skip)))
    if "heatdeficit" in fams and case_runs:
        tasks.append(("heat deficit series", task_heatdeficit,
                      (cfg, case_runs, out_dir(cfg, selection, "heatdeficit", None), skip)))

    # --- per-case families ---
    for case in usable_cases:
        rep = reports[case]
        run = cfg.resolve_run_dir(case, selection.run_override)
        label = cfg.runs[case].label
        innermost, outermost = rep.innermost, rep.outermost
        sel_times, _ = _select_times(rep.times, selection, rep.init)
        # section-family nest: innermost by default, overridable via --section-domain.
        sec_dom, sec_tag, sec_reason = _section_domain(selection, rep)
        if "section" in fams and sec_dom is None:
            print(f"  [SKIP] {case}: section-domain {selection.section_domain} — {sec_reason}")
        for t in sel_times:
            if "section" in fams and sec_dom is not None:
                for orient in ("EW", "NS"):
                    tasks.append((f"{label} {orient} d{sec_dom:02d} {t:%H}Z", task_section,
                                  (cfg, run, sec_dom, case, label, t, orient,
                                   out_dir(cfg, selection, "sections", case), skip, sec_tag)))
            if "upperair" in fams:
                tasks.append((f"{label} upperair {t:%H}Z", task_upperair,
                              (cfg, run, innermost, case, label, t,
                               out_dir(cfg, selection, "upperair", case), skip)))
                adv_dom = outermost if cfg.upper_adv_domain == "outer" else innermost
                tasks.append((f"{label} {int(cfg.upper_pressure_hpa)}hPa T-adv {t:%H}Z",
                              task_upperair_pressure,
                              (cfg, run, adv_dom, case, label, t,
                               out_dir(cfg, selection, "upperair", case), skip)))
            if "surface" in fams:
                for sv in rep.usable_surface_vars:
                    tasks.append((f"{label} {sv.key} {t:%H}Z", task_surface,
                                  (cfg, run, rep.domains, case, label, t, sv,
                                   out_dir(cfg, selection, "surface", case), skip)))
            if "skewt" in fams and rep.point_ok:
                tasks.append((f"{label} skewt {cfg.focus_point.name} {t:%H}Z", task_skewt,
                              (cfg, run, innermost, case, label, t,
                               out_dir(cfg, selection, "skewt", None), skip)))
        # Station-collocated skew-Ts at the sounding hour (the analysis-time RAOBs),
        # only for the distinct driving analyses (ic_cases).  Keyed to the RAOB launch
        # time, so unaffected by --lead.
        if "skewt" in fams and case in cfg.ic_cases:
            for t in [t for t in rep.times if t.hour == cfg.sounding_hour]:
                for stn in cfg.sounding_stations:
                    tasks.append((f"{label} skewt {stn} {t:%H}Z", task_skewt_station,
                                  (cfg, run, outermost, case, label, stn, t,
                                   out_dir(cfg, selection, "skewt", None),
                                   selection.sounding_cache, skip)))

    # --- difference families ---
    if "difference" in fams:
        usable_set = set(usable_cases)
        for dp in cfg.differences:
            if not ({dp.a, dp.b} <= usable_set):
                continue
            run_a = cfg.resolve_run_dir(dp.a, selection.run_override)
            run_b = cfg.resolve_run_dir(dp.b, selection.run_override)
            innermost = reports[dp.a].innermost
            odir = out_dir(cfg, selection, dp.dir or f"diff_{_slug(dp.tag)}", None)
            diff_times, _ = _select_times(reports[dp.a].times, selection, reports[dp.a].init)
            for t in diff_times:
                tasks.append((f"{dp.tag} map {t:%H}Z", task_diff_map,
                              (cfg, run_a, run_b, innermost, dp.tag, t, odir,
                               dp.feedback, dp.limit, skip)))
                if dp.sections:
                    for orient in ("EW", "NS"):
                        tasks.append((f"{dp.tag} {orient} {t:%H}Z", task_diff_section,
                                      (cfg, run_a, run_b, innermost, dp.tag, t, orient, odir,
                                       dp.limit, skip)))
    return tasks
