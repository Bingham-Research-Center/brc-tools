"""Forecast-funnel data layer: NAM analysis -> per-panel plain-array bundles.

A "forecast funnel" is the classic top-down forecasting workflow — start synoptic
(the jet, the long waves), zoom to the regional flow, then to the local scale, and
finish at the surface synoptic analysis.  This module fetches a single NAM analysis
(f00) and reduces it to the handful of cropped, plain-``numpy`` field bundles the
renderer (:mod:`brc_tools.visualize.funnel`) needs — one :class:`Panel` per funnel
step.  The renderer stays dataset-agnostic (it only ever sees ``numpy`` arrays), so
this module owns every xarray/GRIB/Herbie concern.

Two download paths, auto-picked by init date (:func:`funnel_source_for`):

* **herbie** — Herbie's operational ``nam`` model (AWS/NOMADS), for recent inits.
  Herbie-native (the repo's preferred route); ``awphys`` ships RH (not SPFH) aloft, so
  specific humidity is derived from RH + T.
* **ncei**  — the auth-free NCEI historical direct GET (:func:`~brc_tools.nwp.
  wrf_staging.stage_nam_analysis`), for pre-2017 grib1 ``namanl_218``.

The 2017-04 -> 2020-03 window is deliberately unwired (no post-2017 NCEI grib2
template yet); auto-pick raises there rather than silently 404-ing.  Everything is
UTC internally.  GRIB is cached to scratch / ``$BRC_TOOLS_HERBIE_CACHE`` — never the
repo (see CLAUDE.md).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from brc_tools.nwp._crop import crop_to_bbox
from brc_tools.nwp.derived import (
    mixing_ratio,
    saturation_vapor_pressure,
    wind_speed,
)
from brc_tools.nwp.source import _parse_init_time, load_lookups

LOG = logging.getLogger(__name__)

# ── source auto-pick windows ────────────────────────────────────────────────
# Herbie's operational NAM (AWS ``noaa-nam-pds`` back to ~2020-02, NOMADS ~last
# week) covers recent inits; the NCEI grib1 ``namanl_218`` archive ends in 2017.
_HERBIE_MIN = dt.date(2020, 3, 1)
_NCEI_MAX = dt.date(2017, 4, 1)

# Herbie operational NAM: the 12 km CONUS (grid 218) full-physics file — analysis
# at fxx=0 gives ``nam.tHHz.awphys00.tm00.grib2``.
_NAM_HERBIE_MODEL = "nam"
_NAM_HERBIE_PRODUCT = "awphys"

DEFAULT_LEVELS = (250, 500, 600)
DEFAULT_WAYPOINT_GROUP = "us40_basin"

# cfgrib short-name candidates per logical field (first match wins).
_CFGRIB_NAMES = {
    "gh": ("gh", "HGT", "z"),
    "u": ("u", "UGRD"),
    "v": ("v", "VGRD"),
    "t": ("t", "TMP"),
    "q": ("q", "SPFH"),
    "r": ("r", "RH"),
    "mslp": ("prmsl", "msl", "mslet", "PRMSL"),
}


# ── panel specification ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class PanelSpec:
    """One funnel step: what to draw, at which level, over which region."""

    key: str          # "1a".."1d"
    kind: str         # "isotach" | "moisture" | "synoptic"
    region: str       # lookups.toml region name
    level: int | None  # pressure level (hPa); None for the surface panel
    title: str
    style_key: str | None = None
    waypoint_group: str | None = None


# The default four-panel funnel (synoptic -> regional -> local -> surface).
FUNNEL_PANELS: tuple[PanelSpec, ...] = (
    PanelSpec("1a", "isotach", "conus", 250,
              "250 hPa jet: isotachs, heights, wind", "wind_speed_250"),
    PanelSpec("1b", "vorticity", "west_conus", 500,
              "500 hPa: absolute vorticity, heights, wind", "abs_vorticity_500"),
    PanelSpec("1c", "moisture", "utah", 600,
              "600 hPa: specific humidity, heights, temp advection",
              "spec_humidity_600", waypoint_group=DEFAULT_WAYPOINT_GROUP),
    PanelSpec("1d", "synoptic", "west_conus", None,
              "Surface analysis: MSLP, highs/lows, fronts"),
)


@dataclass
class Panel:
    """A single rendered-ready funnel panel of plain ``numpy`` arrays."""

    key: str
    kind: str
    title: str
    level_label: str
    extent: tuple[float, float, float, float]  # (lon0, lon1, lat0, lat1)
    lon: np.ndarray                              # 2-D
    lat: np.ndarray                              # 2-D
    fields: dict                                 # kind-specific arrays
    style_key: str | None = None
    waypoints: dict | None = None
    centers: list | None = None                  # synoptic H/L
    fronts: dict | None = None                   # synoptic frontal fields


@dataclass
class FunnelData:
    """The complete funnel: metadata plus one :class:`Panel` per step."""

    init_time: dt.datetime
    valid_time: dt.datetime
    source: str
    model_label: str
    panels: list = field(default_factory=list)


# ── source selection ────────────────────────────────────────────────────────
def funnel_source_for(init_dt: dt.datetime) -> str:
    """Return ``"herbie"`` or ``"ncei"`` for an init date, or raise on the gap.

    Recent inits (>= 2020-03) use Herbie's operational NAM; pre-2017 inits use the
    NCEI historical grib1 GET.  The 2017-04..2020-03 window has no wired template.
    """
    d = init_dt.date()
    if d >= _HERBIE_MIN:
        return "herbie"
    if d <= _NCEI_MAX:
        return "ncei"
    raise ValueError(
        f"No NAM source wired for init {d:%Y-%m-%d}: Herbie operational NAM covers "
        f">= {_HERBIE_MIN:%Y-%m}, the NCEI grib1 archive ends <= {_NCEI_MAX:%Y-%m}. "
        "Test with a recent init (Herbie) or a pre-2017 init (NCEI). See "
        "docs/FORECAST-FUNNEL.md for the post-2017 grib2 follow-up."
    )


# ── small helpers ───────────────────────────────────────────────────────────
def _region_swne(region: str) -> tuple[tuple[float, float], tuple[float, float]]:
    cfg = load_lookups().get("regions", {}).get(region)
    if not cfg:
        raise KeyError(f"region {region!r} not in lookups.toml [regions]")
    return tuple(cfg["sw"]), tuple(cfg["ne"])


def _first_ds(obj):
    """Herbie ``.xarray`` returns a list when a search spans un-mergeable cubes."""
    if isinstance(obj, list):
        if not obj:
            raise ValueError("Herbie returned an empty dataset list")
        return obj[0]
    return obj


def _pick(ds, logical: str):
    """Return the DataArray for a logical field, trying cfgrib short-name aliases."""
    for name in _CFGRIB_NAMES[logical]:
        if name in ds:
            return ds[name]
    # last resort: the sole data var (single-field search)
    dvs = list(ds.data_vars)
    if len(dvs) == 1:
        return ds[dvs[0]]
    raise KeyError(f"none of {_CFGRIB_NAMES[logical]} in dataset (have {dvs})")


def _lonlat_2d(ds) -> tuple[np.ndarray, np.ndarray]:
    lon = np.asarray(ds["longitude"].values, dtype=float)
    lat = np.asarray(ds["latitude"].values, dtype=float)
    # Normalise longitude to -180..180 for plotting over CONUS.
    lon = np.where(lon > 180.0, lon - 360.0, lon)
    return lon, lat


def _grid_spacing_m(lon2d: np.ndarray, lat2d: np.ndarray) -> tuple[float, float]:
    """Approximate (dx, dy) in metres from a 2-D lon/lat grid (for gradients)."""
    latm = float(np.nanmean(lat2d))
    dlon = float(np.nanmean(np.abs(np.diff(lon2d, axis=1)))) or 0.1
    dlat = float(np.nanmean(np.abs(np.diff(lat2d, axis=0)))) or 0.1
    dx = 111_320.0 * np.cos(np.deg2rad(latm)) * dlon
    dy = 110_540.0 * dlat
    return float(dx), float(dy)


def specific_humidity_g_per_kg(q_kg_kg=None, *, rh_pct=None, temp_k=None,
                               pressure_hpa=None) -> np.ndarray:
    """Specific humidity in g/kg: direct SPFH if given, else derived from RH/T/p.

    The Herbie path supplies SPFH directly; the NCEI grib1 analysis may carry only
    RH, so we derive q via Bolton saturation pressure (reusing ``derived``).
    """
    if q_kg_kg is not None:
        return np.asarray(q_kg_kg, dtype=float) * 1000.0
    if rh_pct is None or temp_k is None or pressure_hpa is None:
        raise ValueError("need q, or all of rh_pct/temp_k/pressure_hpa")
    es = saturation_vapor_pressure(np.asarray(temp_k, dtype=float))  # Pa
    e = np.clip(np.asarray(rh_pct, dtype=float) / 100.0, 0.0, 1.0) * es
    r = mixing_ratio(e, float(pressure_hpa) * 100.0)  # kg/kg
    return (r / (1.0 + r)) * 1000.0


# ── diagnostics ─────────────────────────────────────────────────────────────
def pressure_centers(mslp_hpa, lon2d, lat2d, *, window_pts: int = 25,
                     edge_margin: int = 4, min_sep_deg: float = 6.0) -> list[dict]:
    """Detect High/Low sea-level-pressure centres (local extrema).

    Uses a moving-window min/max filter, drops edge hits, and greedily enforces a
    minimum separation.  Returns dicts ``{lon, lat, value, kind}`` with ``kind`` in
    ``{"H", "L"}`` and ``value`` in hPa.
    """
    from scipy.ndimage import maximum_filter, minimum_filter

    p = np.asarray(mslp_hpa, dtype=float)
    lon = np.asarray(lon2d, dtype=float)
    lat = np.asarray(lat2d, dtype=float)
    size = max(3, int(window_pts))
    lows = (p == minimum_filter(p, size=size, mode="nearest"))
    highs = (p == maximum_filter(p, size=size, mode="nearest"))

    m = edge_margin
    interior = np.zeros_like(p, dtype=bool)
    interior[m:-m or None, m:-m or None] = True

    cand: list[dict] = []
    for mask, kind in ((lows, "L"), (highs, "H")):
        jj, ii = np.where(mask & interior & np.isfinite(p))
        for j, i in zip(jj, ii):
            cand.append({"lon": float(lon[j, i]), "lat": float(lat[j, i]),
                         "value": float(p[j, i]), "kind": kind})
    # Rank lows by lowest pressure, highs by highest; interleave by extremeness.
    cand.sort(key=lambda c: c["value"] if c["kind"] == "L" else -c["value"])
    kept: list[dict] = []
    for c in cand:
        if all(abs(c["lon"] - k["lon"]) > min_sep_deg
               or abs(c["lat"] - k["lat"]) > min_sep_deg for k in kept):
            kept.append(c)
    return kept


def thermal_front_parameter(temp2d, dx_m: float, dy_m: float, *,
                            smooth_sigma: float = 4.0,
                            min_grad_per_100km: float = 1.5) -> np.ndarray:
    """Thermal Front Parameter, TFP = -grad|gradT| . (gradT/|gradT|).

    Returned in K per (100 km)^2 so a physical threshold (~1-3) is meaningful.  The
    field is smoothed first (standard practice; ``smooth_sigma`` in grid cells) to tame
    the double-gradient noise, and TFP is **gated to zero where the thermal gradient is
    weaker than** ``min_grad_per_100km`` (K per 100 km) so real 12 km data does not
    sprout spurious frontlets in near-barotropic air.  TFP marks baroclinic zones; it
    does **not** type fronts.
    """
    from brc_tools.visualize.upperair import _nan_gaussian

    t = np.asarray(temp2d, dtype=float)
    if smooth_sigma and smooth_sigma > 0:
        t = _nan_gaussian(t, smooth_sigma)
    d_ty, d_tx = np.gradient(t, dy_m, dx_m)
    mag = np.sqrt(d_tx**2 + d_ty**2)                    # K / m
    with np.errstate(invalid="ignore", divide="ignore"):
        nx = np.where(mag > 0, d_tx / mag, 0.0)
        ny = np.where(mag > 0, d_ty / mag, 0.0)
    d_my, d_mx = np.gradient(mag, dy_m, dx_m)
    tfp = -(d_mx * nx + d_my * ny) * 1.0e10             # -> K / (100 km)^2
    # Gate out weakly-baroclinic air (|gradT| in K per 100 km).
    tfp = np.where(mag * 1.0e5 >= min_grad_per_100km, tfp, 0.0)
    return tfp


def temperature_advection(temp2d, u2d, v2d, dx_m: float, dy_m: float, *,
                          smooth_sigma: float = 2.0) -> np.ndarray:
    """Horizontal temperature advection -V.gradT (K/h) — warm/cold-air advection.

    Positive = warm-air advection, negative = cold-air advection.  Used both for the
    surface front colouring (850 hPa) and the 600 hPa thermal-advection contours.
    """
    from brc_tools.visualize.upperair import _nan_gaussian

    t = np.asarray(temp2d, dtype=float)
    if smooth_sigma and smooth_sigma > 0:
        t = _nan_gaussian(t, smooth_sigma)
    d_ty, d_tx = np.gradient(t, dy_m, dx_m)
    adv = -(np.asarray(u2d, dtype=float) * d_tx + np.asarray(v2d, dtype=float) * d_ty)
    return adv * 3600.0


def absolute_vorticity(u2d, v2d, lat2d, dx_m: float, dy_m: float) -> np.ndarray:
    """Absolute vorticity (relative + planetary) in 10^-5 s^-1.

    zeta = dv/dx - du/dy; f = 2 Omega sin(phi).  Approximate on a lon/lat grid (dx/dy
    from :func:`_grid_spacing_m`) — fine for a synoptic 500 hPa shortwave diagnostic.
    """
    u = np.asarray(u2d, dtype=float)
    v = np.asarray(v2d, dtype=float)
    du_dy, du_dx = np.gradient(u, dy_m, dx_m)
    dv_dy, dv_dx = np.gradient(v, dy_m, dx_m)
    zeta = dv_dx - du_dy
    f = 2.0 * 7.2921e-5 * np.sin(np.deg2rad(np.asarray(lat2d, dtype=float)))
    return (zeta + f) * 1.0e5


# ── fetch: assemble a uniform "full" dataset ────────────────────────────────
def _assemble_full(*, lat2d, lon2d, levels, gh, u, v, t600, t850, u850, v850,
                   q600_g_kg, mslp_pa):
    """Build one xarray Dataset (dims y,x; 2-D lat/lon coords) for uniform cropping."""
    import xarray as xr

    dv: dict = {}
    for lv in levels:
        dv[f"gh{lv}"] = (("y", "x"), np.asarray(gh[lv], dtype=float))
        dv[f"u{lv}"] = (("y", "x"), np.asarray(u[lv], dtype=float))
        dv[f"v{lv}"] = (("y", "x"), np.asarray(v[lv], dtype=float))
    dv["t600"] = (("y", "x"), np.asarray(t600, dtype=float))
    dv["t850"] = (("y", "x"), np.asarray(t850, dtype=float))
    dv["u850"] = (("y", "x"), np.asarray(u850, dtype=float))
    dv["v850"] = (("y", "x"), np.asarray(v850, dtype=float))
    dv["q600"] = (("y", "x"), np.asarray(q600_g_kg, dtype=float))
    dv["mslp"] = (("y", "x"), np.asarray(mslp_pa, dtype=float))
    return xr.Dataset(
        dv,
        coords={"latitude": (("y", "x"), np.asarray(lat2d, dtype=float)),
                "longitude": (("y", "x"), np.asarray(lon2d, dtype=float))},
    )


def _sel_level(da, level: int):
    """Select a single pressure level from an isobaric DataArray -> 2-D array."""
    if "isobaricInhPa" in da.dims:
        return np.asarray(da.sel(isobaricInhPa=level).values, dtype=float)
    return np.asarray(da.values, dtype=float)


def _herbie_fetch_full(init_dt: dt.datetime, levels, cache_dir):
    """Fetch the funnel fields from Herbie's operational NAM (analysis, fxx=0)."""
    from herbie import Herbie

    kwargs = dict(model=_NAM_HERBIE_MODEL, product=_NAM_HERBIE_PRODUCT, fxx=0)
    if cache_dir:
        kwargs["save_dir"] = str(cache_dir)
    H = Herbie(init_dt, **kwargs)

    lv_re = "|".join(str(int(lv)) for lv in levels)
    iso = _first_ds(H.xarray(rf":(HGT|UGRD|VGRD|TMP):({lv_re}) mb:", remove_grib=False))
    b850 = _first_ds(H.xarray(r":(TMP|UGRD|VGRD):850 mb:", remove_grib=False))
    slp = _first_ds(H.xarray(r":(PRMSL|MSLET):mean sea level:", remove_grib=False))

    lon2d, lat2d = _lonlat_2d(iso)
    gh = {lv: _sel_level(_pick(iso, "gh"), lv) for lv in levels}
    uu = {lv: _sel_level(_pick(iso, "u"), lv) for lv in levels}
    vv = {lv: _sel_level(_pick(iso, "v"), lv) for lv in levels}
    t600 = _sel_level(_pick(iso, "t"), 600)

    # NAM awphys carries RH (not SPFH) on pressure levels, so derive q from RH + T; try
    # SPFH first for any model that does ship it.  A search matching zero messages makes
    # Herbie write no subset (cfgrib then FileNotFoundError), so fall back on any failure.
    try:
        q_ds = _first_ds(H.xarray(r":SPFH:600 mb:", remove_grib=False))
        q600 = specific_humidity_g_per_kg(_sel_level(_pick(q_ds, "q"), 600))
    except Exception:  # noqa: BLE001 - no SPFH message -> RH fallback
        rh_ds = _first_ds(H.xarray(r":RH:600 mb:", remove_grib=False))
        q600 = specific_humidity_g_per_kg(
            rh_pct=_sel_level(_pick(rh_ds, "r"), 600),
            temp_k=t600, pressure_hpa=600.0)
    return _assemble_full(
        lat2d=lat2d, lon2d=lon2d, levels=levels, gh=gh, u=uu, v=vv,
        t600=t600,
        t850=_sel_level(_pick(b850, "t"), 850),
        u850=_sel_level(_pick(b850, "u"), 850),
        v850=_sel_level(_pick(b850, "v"), 850),
        q600_g_kg=q600, mslp_pa=_sel_level(_pick(slp, "mslp"), 0),
    )


def _ncei_fetch_full(init_time, levels, cache_dir):
    """Fetch the funnel fields from a staged NCEI grib1 NAM analysis (f00)."""
    import xarray as xr

    from brc_tools.nwp.wrf_staging import stage_nam_analysis

    import tempfile

    staged = stage_nam_analysis(
        init_time=init_time, fxx_window=(0, 0),
        output_root=cache_dir or tempfile.gettempdir(), case="forecast_funnel",
    )
    path = staged[0].local_path

    # Open ONE variable at a time. The grib1 namanl carries variables on different
    # isobaric level sets (HGT ~39 levels, RH ~5), so a single typeOfLevel filter makes
    # cfgrib raise DatasetBuildError and silently drop fields; a per-shortName filter
    # gives each variable its own consistent cube.
    def _open(short=None, level_type="isobaricInhPa"):
        keys: dict = {"typeOfLevel": level_type}
        if short:
            keys["shortName"] = short
        return xr.open_dataset(
            str(path), engine="cfgrib",
            backend_kwargs={"indexpath": "", "filter_by_keys": keys},
        )

    gh_ds, u_ds, v_ds, t_ds = _open("gh"), _open("u"), _open("v"), _open("t")
    lon2d, lat2d = _lonlat_2d(gh_ds)
    gh_da, u_da, v_da, t_da = (_pick(gh_ds, "gh"), _pick(u_ds, "u"),
                               _pick(v_ds, "v"), _pick(t_ds, "t"))
    gh = {lv: _sel_level(gh_da, lv) for lv in levels}
    uu = {lv: _sel_level(u_da, lv) for lv in levels}
    vv = {lv: _sel_level(v_da, lv) for lv in levels}

    # SPFH may be absent from the historical analysis -> derive from RH + T.
    try:
        q600 = specific_humidity_g_per_kg(_sel_level(_pick(_open("q"), "q"), 600))
    except Exception:  # noqa: BLE001 - no SPFH message -> RH fallback
        q600 = specific_humidity_g_per_kg(
            rh_pct=_sel_level(_pick(_open("r"), "r"), 600),
            temp_k=_sel_level(t_da, 600), pressure_hpa=600.0)

    slp = _open(level_type="meanSea")
    return _assemble_full(
        lat2d=lat2d, lon2d=lon2d, levels=levels, gh=gh, u=uu, v=vv,
        t600=_sel_level(t_da, 600), t850=_sel_level(t_da, 850),
        u850=_sel_level(u_da, 850), v850=_sel_level(v_da, 850),
        q600_g_kg=q600, mslp_pa=_sel_level(_pick(slp, "mslp"), 0),
    )


# ── panel assembly ──────────────────────────────────────────────────────────
def _build_panel(full, spec: PanelSpec, lu) -> Panel | None:
    """Crop ``full`` to a panel's region and package its plain-array fields."""
    sw, ne = _region_swne(spec.region)
    sub = crop_to_bbox(full, sw, ne, "lonlat_after_aux")
    lon = np.asarray(sub["longitude"].values, dtype=float)
    lat = np.asarray(sub["latitude"].values, dtype=float)
    if lon.size == 0 or lat.size == 0:
        LOG.warning("panel %s: empty crop over region %s", spec.key, spec.region)
        return None
    extent = (float(np.nanmin(lon)), float(np.nanmax(lon)),
              float(np.nanmin(lat)), float(np.nanmax(lat)))

    waypoints = None
    if spec.waypoint_group:
        names = lu.get("waypoint_groups", {}).get(spec.waypoint_group, [])
        waypoints = {n: lu["waypoints"][n] for n in names if n in lu.get("waypoints", {})}

    if spec.kind in ("isotach", "vorticity", "moisture"):
        lv = spec.level
        u = np.asarray(sub[f"u{lv}"].values, dtype=float)
        v = np.asarray(sub[f"v{lv}"].values, dtype=float)
        fields = {"height": np.asarray(sub[f"gh{lv}"].values, dtype=float),
                  "u": u, "v": v}
        if spec.kind == "isotach":
            fields["scalar"] = wind_speed(u, v)
        elif spec.kind == "vorticity":
            dx, dy = _grid_spacing_m(lon, lat)
            fields["scalar"] = absolute_vorticity(u, v, lat, dx, dy)
        else:  # moisture: humidity fill + warm/cold-air (temperature) advection.
            # SPFH/TMP are staged at 600 hPa only (the moisture panel is fixed at 600).
            dx, dy = _grid_spacing_m(lon, lat)
            fields["scalar"] = np.asarray(sub["q600"].values, dtype=float)
            fields["t_adv"] = temperature_advection(
                np.asarray(sub["t600"].values, dtype=float), u, v, dx, dy)
        return Panel(spec.key, spec.kind, spec.title, f"{lv} hPa", extent, lon, lat,
                     fields, style_key=spec.style_key, waypoints=waypoints)

    # synoptic surface panel
    dx, dy = _grid_spacing_m(lon, lat)
    t850 = np.asarray(sub["t850"].values, dtype=float)
    mslp_hpa = np.asarray(sub["mslp"].values, dtype=float) / 100.0
    fronts = {
        "tfp": thermal_front_parameter(t850, dx, dy),
        "t_adv": temperature_advection(
            t850, np.asarray(sub["u850"].values, dtype=float),
            np.asarray(sub["v850"].values, dtype=float), dx, dy),
    }
    return Panel(spec.key, spec.kind, spec.title, "mean sea level", extent, lon, lat,
                 {"mslp": mslp_hpa}, style_key=None, waypoints=waypoints,
                 centers=pressure_centers(mslp_hpa, lon, lat), fronts=fronts)


def fetch_funnel_fields(
    init_time,
    *,
    source: str = "auto",
    cache_dir: str | Path | None = None,
    levels=DEFAULT_LEVELS,
    panels: tuple[PanelSpec, ...] = FUNNEL_PANELS,
) -> FunnelData:
    """Download a NAM analysis and reduce it to per-panel plain-array bundles.

    ``source`` is ``"auto"`` (pick by init date), ``"herbie"``, or ``"ncei"``.  For
    an analysis the valid time equals the init time.  GRIB caches under
    ``cache_dir`` (or ``$BRC_TOOLS_HERBIE_CACHE`` for the Herbie path) — never the
    repo checkout.
    """
    init_dt = _parse_init_time(init_time)
    # Always fetch every level a panel needs, so a trimmed --levels can't starve one.
    needed = {int(lv) for lv in levels} | {int(s.level) for s in panels if s.level}
    levels = tuple(sorted(needed))
    chosen = funnel_source_for(init_dt) if source == "auto" else source
    LOG.info("forecast funnel: init %s, source=%s, levels=%s",
             init_dt.isoformat(), chosen, levels)

    if chosen == "herbie":
        full = _herbie_fetch_full(init_dt, levels, cache_dir)
        model_label = "NAM 12 km analysis (Herbie/operational)"
    elif chosen == "ncei":
        full = _ncei_fetch_full(init_time, levels, cache_dir)
        model_label = "NAM 12 km analysis (NCEI namanl_218)"
    else:
        raise ValueError(f"unknown source {source!r} (want auto|herbie|ncei)")

    lu = load_lookups()
    built = [_build_panel(full, spec, lu) for spec in panels]
    return FunnelData(
        init_time=init_dt, valid_time=init_dt, source=chosen,
        model_label=model_label, panels=[p for p in built if p is not None],
    )
