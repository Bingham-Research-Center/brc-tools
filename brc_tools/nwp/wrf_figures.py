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
from datetime import datetime
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
    plot_height_surface,
    temperature_advection,
)

FAMILIES = [
    "domains", "section", "upperair", "surface",
    "difference", "profile", "skewt", "heatdeficit",
]

# Vertical extent for the theta(z) profile plot (m MSL); a generic default.
_PROFILE_Y_MAX_M = 3300.0

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
            )
            for d in data.get("differences", [])
        ]
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
    time: str = "all"                   # "all" or comma-separated hours
    output_dir: str | None = None       # override output root (else routed by case)
    run_override: str | None = None      # a specific run_* dir name (else latest)
    sounding_cache: str | None = None    # parquet for skew-T obs overlay


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


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


def _focus_slug(cfg: CaseConfig) -> str:
    return _slug(cfg.focus_point.name) or "focus"


def _select_times(times: list[datetime], requested: str | None) -> list[datetime]:
    if requested in (None, "all"):
        return list(times)
    hours = {int(h) for h in str(requested).split(",")}
    return [t for t in times if t.hour in hours]


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
def task_section(cfg, run, innermost, case, label, valid, orient, out):
    ds = wo.open_wrfout(wo.wrfout_path(run, innermost, valid))
    sec = wo.build_section(ds, orient)
    plot_wrf_section(
        sec, out / f"section_{orient.lower()}_{case}_{valid:%H}z.png",
        locator_terrain=wo.surface_field(ds, "HGT"),
        title=f"{label} | d{innermost:02d} {orient} section | {valid:%Y-%m-%d %H}Z",
        annotation=cfg.annotation,
    )


def task_upperair(cfg, run, innermost, case, label, valid, out):
    ds = wo.open_wrfout(wo.wrfout_path(run, innermost, valid))
    crest = cfg.crest_m
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
        out / f"crest{int(crest)}_{case}_{valid:%H}z.png",
        temp_adv2d=temperature_advection(tk, u2, v2, dx, dy), terrain=hgt,
        target_label=f"{int(crest)} m MSL", mask=below_ground_mask(crest, hgt),
        style=resolve_style("theta_crest", overrides=cfg.style.overrides,
                            autoscale=cfg.style.autoscale),
        waypoints=cfg.waypoints,
        title=f"{label} | crest theta + wind + T-adv | {valid:%H}Z", annotation=cfg.annotation,
    )


def task_surface(cfg, run, domains, case, label, valid, sv, out):
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
        panels, out / f"{sv.key}_{case}_multidomain_{valid:%H}z.png", style=style,
        wind=sv.wind, extent=extent, waypoints=cfg.waypoints,
        suptitle=f"{label} | {sv.style} | d{innermost:02d} area | {valid:%H}Z",
    )


def task_diff_map(cfg, run_a, run_b, innermost, tag, valid, out, feedback):
    da = wo.open_wrfout(wo.wrfout_path(run_a, innermost, valid))
    db = wo.open_wrfout(wo.wrfout_path(run_b, innermost, valid))
    plot_field_difference(
        wo.surface_field(da, "XLONG"), wo.surface_field(da, "XLAT"),
        wo.theta_2m(da), wo.theta_2m(db), out / f"theta2m_{tag}_{valid:%H}z.png",
        var="theta", limit=3.0 if feedback else 5.0,
        title=f"{tag} | 2 m theta | d{innermost:02d} | {valid:%H}Z",
        terrain=wo.surface_field(da, "HGT"), annotation=cfg.annotation,
    )


def task_diff_section(cfg, run_a, run_b, innermost, tag, valid, orient, out):
    sec_a = wo.build_section(wo.open_wrfout(wo.wrfout_path(run_a, innermost, valid)), orient)
    db = wo.open_wrfout(wo.wrfout_path(run_b, innermost, valid))
    sec_b = wo.build_section(db, orient)
    plot_wrf_section_difference(
        sec_a, sec_b, out / f"section_{orient.lower()}_{tag}_{valid:%H}z.png",
        var="theta", title=f"{tag} | d{innermost:02d} {orient} theta | {valid:%H}Z",
        locator_terrain=wo.surface_field(db, "HGT"), annotation=cfg.annotation,
    )


def task_domains(cfg, run, domains, out):
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
        outlines, out / "nested_domains.png", terrain=terr, terrain_lonlat=(lon, lat),
        waypoints=cfg.waypoints, title=f"{cfg.label} WRF nested domains",
    )


def task_profiles(cfg, case_runs, valid, out):
    cols = {}
    for _case, label, run, innermost in case_runs:
        ds = wo.open_wrfout(wo.wrfout_path(run, innermost, valid))
        cols[label] = wo.extract_column(ds, cfg.focus_point.lat, cfg.focus_point.lon, label=label)
    ref_terrain = next(iter(cols.values())).terrain_m
    plot_theta_profiles(
        cols, out / f"theta_profiles_{_focus_slug(cfg)}_{valid:%H}z.png",
        terrain_m=ref_terrain, crest_m=cfg.crest_m, y_max_m=_PROFILE_Y_MAX_M,
        title=rf"$\theta(z)$ at {cfg.focus_point.name} | {valid:%Y-%m-%d %H}Z",
        annotation=cfg.annotation,
    )


def task_skewt(cfg, run, innermost, case, label, valid, out):
    """Focus-point (innermost) model skew-T -- the cold-pool structure (model-only)."""
    ds = wo.open_wrfout(wo.wrfout_path(run, innermost, valid))
    model = sounding_from_column(
        wo.extract_column(ds, cfg.focus_point.lat, cfg.focus_point.lon),
        source=label, station=cfg.focus_point.name, valid_time=valid,
    )
    plot_skewt(
        model, out / f"skewt_{_focus_slug(cfg)}_{case}_{valid:%H}z.png",
        title=f"{label} skew-T | {cfg.focus_point.name} (d{innermost:02d}) | {valid:%Y-%m-%d %H}Z",
        annotation=cfg.annotation,
    )


def task_skewt_station(cfg, run, outermost, case, label, station_name, valid, out, sounding_cache):
    """Model outermost-domain column at a RAOB proxy site, overlaid on that sounding."""
    from brc_tools.api.soundings import STATIONS

    st = STATIONS[station_name]
    ds = wo.open_wrfout(wo.wrfout_path(run, outermost, valid))
    model = sounding_from_column(
        wo.extract_column(ds, st.lat, st.lon),
        source=label, station=station_name, valid_time=valid,
    )
    obs = CachedSounding(sounding_cache).get(station_name, valid) if sounding_cache else None
    plot_skewt(
        model, out / f"skewt_{station_name}_{case}_{valid:%H}z.png", obs=obs,
        title=f"{label} vs RAOB | {station_name} ({st.location}) d{outermost:02d} | {valid:%H}Z",
        annotation=cfg.annotation,
    )


def task_heatdeficit(cfg, case_runs, out):
    series = {}
    for _case, label, run, innermost in case_runs:
        times = wo.list_valid_times(run, innermost)
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
        series, out / "heat_deficit_timeseries.png",
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

    return PreflightReport(case, domains, innermost, outermost, point_ok, usable, times, skips, warnings)


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

    reports = {c: preflight(cfg, c, run_override=selection.run_override) for c in cases}
    _print_report(cfg, reports)

    usable_cases = [c for c in cases if reports[c].domains]
    point_cases = [c for c in usable_cases if reports[c].point_ok]
    case_runs = [
        (c, cfg.runs[c].label, cfg.resolve_run_dir(c, selection.run_override), reports[c].innermost)
        for c in point_cases
    ]
    tasks: list[tuple] = []

    # --- cross-case families ---
    if "domains" in fams and usable_cases:
        c0 = usable_cases[0]
        run0 = cfg.resolve_run_dir(c0, selection.run_override)
        tasks.append(("domains map", task_domains,
                      (cfg, run0, reports[c0].domains, out_dir(cfg, selection, "domains", None))))
    if "profile" in fams and case_runs:
        for t in [t for t in reports[point_cases[0]].times if t.hour in cfg.profile_hours]:
            tasks.append((f"profiles {t:%H}Z", task_profiles,
                          (cfg, case_runs, t, out_dir(cfg, selection, "profiles", None))))
    if "heatdeficit" in fams and case_runs:
        tasks.append(("heat deficit series", task_heatdeficit,
                      (cfg, case_runs, out_dir(cfg, selection, "heatdeficit", None))))

    # --- per-case families ---
    for case in usable_cases:
        rep = reports[case]
        run = cfg.resolve_run_dir(case, selection.run_override)
        label = cfg.runs[case].label
        innermost, outermost = rep.innermost, rep.outermost
        for t in _select_times(rep.times, selection.time):
            if "section" in fams:
                for orient in ("EW", "NS"):
                    tasks.append((f"{label} {orient} {t:%H}Z", task_section,
                                  (cfg, run, innermost, case, label, t, orient,
                                   out_dir(cfg, selection, "sections", case))))
            if "upperair" in fams:
                tasks.append((f"{label} upperair {t:%H}Z", task_upperair,
                              (cfg, run, innermost, case, label, t,
                               out_dir(cfg, selection, "upperair", case))))
            if "surface" in fams:
                for sv in rep.usable_surface_vars:
                    tasks.append((f"{label} {sv.key} {t:%H}Z", task_surface,
                                  (cfg, run, rep.domains, case, label, t, sv,
                                   out_dir(cfg, selection, "surface", case))))
            if "skewt" in fams and rep.point_ok:
                tasks.append((f"{label} skewt {cfg.focus_point.name} {t:%H}Z", task_skewt,
                              (cfg, run, innermost, case, label, t,
                               out_dir(cfg, selection, "skewt", None))))
        # Station-collocated skew-Ts at the sounding hour (the analysis-time RAOBs),
        # only for the distinct driving analyses (ic_cases).
        if "skewt" in fams and case in cfg.ic_cases:
            for t in [t for t in rep.times if t.hour == cfg.sounding_hour]:
                for stn in cfg.sounding_stations:
                    tasks.append((f"{label} skewt {stn} {t:%H}Z", task_skewt_station,
                                  (cfg, run, outermost, case, label, stn, t,
                                   out_dir(cfg, selection, "skewt", None), selection.sounding_cache)))

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
            for t in _select_times(reports[dp.a].times, selection.time):
                tasks.append((f"{dp.tag} map {t:%H}Z", task_diff_map,
                              (cfg, run_a, run_b, innermost, dp.tag, t, odir, dp.feedback)))
                if dp.sections:
                    for orient in ("EW", "NS"):
                        tasks.append((f"{dp.tag} {orient} {t:%H}Z", task_diff_section,
                                      (cfg, run_a, run_b, innermost, dp.tag, t, orient, odir)))
    return tasks
