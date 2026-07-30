"""Plan views and arbitrary-line cross-sections straight from ``wrfout`` files.

This is the WRF-side adapter onto the renderers written for gridded NWP --
:func:`brc_tools.visualize.nwp_maps.plot_nwp_surface_map` and
:func:`~brc_tools.visualize.nwp_maps.plot_nwp_section` -- so a WRF nest can be
drawn in exactly the layout the ``basin-winds`` HRRR case uses (10 m wind plan
view plus terrain-filled wind curtains along named A->B transects, with the
geographic locator inset and along-section town labels).

Two adapters, and a deliberate difference from the HRRR path:

``plan_dataset``
    ``wrfout`` -> a minimal :class:`xarray.Dataset` in the surface schema those
    renderers expect (2-D ``latitude``/``longitude``, ``terrain_height``, and
    style-keyed fields such as ``wind_speed_10m``).

``extract_wrf_section``
    ``wrfout`` -> :class:`brc_tools.nwp.section.NWPSection` sampled along an
    arbitrary geographic line **on the model's native eta levels**.  The HRRR
    analogue in :mod:`brc_tools.nwp.section` has to stack isobaric levels because
    that is all GRIB carries; here the native column is available, so a 600 m
    nest keeps the stretched near-surface levels intact.  That matters when the
    feature of interest -- a drainage layer tens of metres deep -- lives entirely
    below the first isobaric level a pressure interpolation would offer.

Winds are earth-relative throughout (rotated via ``COSALPHA``/``SINALPHA``), so
the along-transect component of a section means the same thing whatever the map
projection is doing.  Nothing here is case-specific: transect endpoints, extents,
waypoints, and colour scales are the caller's business.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from brc_tools.nwp import wrf_output as wo
from brc_tools.nwp.section import NWPSection

__all__ = ["WRFPlane", "load_plane", "plan_dataset", "plan_extent",
           "section_from_plane", "extract_wrf_section",
           "list_valid_times", "wrfout_path", "init_time"]

_KM_PER_DEG_LAT = 110.574
_KM_PER_DEG_LON = 111.320

# WRF writes history filenames as `%Y-%m-%d_%H:%M:%S`, unless the run set
# `nocolons = .true.` (common on filesystems and tooling that dislike colons), in
# which case the time separators become underscores.  wrf_output assumes the first;
# everything here accepts either, so one run directory convention is not a
# precondition for getting figures out.
_TIME_FMTS = ("%Y-%m-%d_%H:%M:%S", "%Y-%m-%d_%H_%M_%S")


def _parse_stamp(stamp: str) -> datetime | None:
    for fmt in _TIME_FMTS:
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def list_valid_times(run_dir: str | Path, domain: int) -> list[datetime]:
    """Valid times present for a domain, parsed from either filename convention."""
    prefix = f"wrfout_d{domain:02d}_"
    times = [t for p in sorted(Path(run_dir).glob(f"{prefix}*"))
             if (t := _parse_stamp(p.name[len(prefix):])) is not None]
    return sorted(times)


def wrfout_path(run_dir: str | Path, domain: int, valid_time: datetime) -> Path:
    """Path to one wrfout, trying both time conventions; returns the one on disk.

    Falls back to the colon form (WRF's default) when neither exists, so the
    caller's ``FileNotFoundError`` names something recognisable.
    """
    run_dir = Path(run_dir)
    candidates = [run_dir / f"wrfout_d{domain:02d}_{valid_time:{fmt}}" for fmt in _TIME_FMTS]
    return next((p for p in candidates if p.exists()), candidates[0])


def init_time(run_dir: str | Path, domain: int) -> datetime:
    """Model initialization time: ``SIMULATION_START_DATE``, else earliest wrfout."""
    times = list_valid_times(run_dir, domain)
    if not times:
        raise FileNotFoundError(f"no wrfout_d{domain:02d}_* files under {run_dir}")
    ds = wo.open_wrfout(wrfout_path(run_dir, domain, times[0]))
    try:
        stamp = ds.attrs.get("SIMULATION_START_DATE")
    finally:
        ds.close()
    return (_parse_stamp(str(stamp).strip()) or times[0]) if stamp else times[0]


def _lon180(lon) -> np.ndarray:
    lon = np.asarray(lon, dtype=float)
    return np.where(lon > 180.0, lon - 360.0, lon)


def _rotate_to_earth(ds, u, v):
    """Rotate grid-relative ``(u, v)`` onto earth axes; identity if unrotated."""
    cosa = wo.surface_field(ds, "COSALPHA") if "COSALPHA" in ds else np.ones(u.shape)
    sina = wo.surface_field(ds, "SINALPHA") if "SINALPHA" in ds else np.zeros(u.shape)
    return u * cosa - v * sina, v * cosa + u * sina


# --------------------------------------------------------------------------- #
# plan view
# --------------------------------------------------------------------------- #
def plan_dataset(ds, *, extra: dict | None = None):
    """Build the surface :class:`xarray.Dataset` the plan-view renderer expects.

    Field names are :mod:`brc_tools.visualize.style` keys, because
    :func:`~brc_tools.visualize.nwp_maps.plot_nwp_surface_map` looks the colour
    scale up by variable name: ``wind_speed_10m``, ``wind_u_10m``,
    ``wind_v_10m``, ``theta_2m``, ``temp_2m``, ``pblh``, plus ``terrain_height``
    and 2-D ``latitude``/``longitude``.  ``pblh`` is omitted when the run did not
    write ``PBLH``.  ``extra`` adds ``{name: 2-D array}`` pairs verbatim.
    """
    import xarray as xr

    u10, v10 = _rotate_to_earth(ds, wo.surface_field(ds, "U10"), wo.surface_field(ds, "V10"))
    fields = {
        "terrain_height": wo.surface_field(ds, "HGT"),
        "wind_u_10m": u10,
        "wind_v_10m": v10,
        "wind_speed_10m": np.hypot(u10, v10),
        "theta_2m": wo.theta_2m(ds),
        "temp_2m": wo.surface_field(ds, "T2"),
    }
    if "PBLH" in ds:
        fields["pblh"] = wo.surface_field(ds, "PBLH")
    fields.update(extra or {})
    return xr.Dataset(
        {k: (("y", "x"), np.asarray(a, dtype=float)) for k, a in fields.items()},
        coords={
            "latitude": (("y", "x"), wo.surface_field(ds, "XLAT")),
            "longitude": (("y", "x"), _lon180(wo.surface_field(ds, "XLONG"))),
        },
    )


def plan_extent(ds, *, pad_deg: float = 0.0) -> tuple[float, float, float, float]:
    """``(lon0, lon1, lat0, lat1)`` covering the domain, inset by ``pad_deg``.

    A positive ``pad_deg`` trims the view inward -- useful for hiding the nest's
    relaxation zone, where the solution is blended toward the parent.
    """
    lat = wo.surface_field(ds, "XLAT")
    lon = _lon180(wo.surface_field(ds, "XLONG"))
    return (float(lon.min()) + pad_deg, float(lon.max()) - pad_deg,
            float(lat.min()) + pad_deg, float(lat.max()) - pad_deg)


# --------------------------------------------------------------------------- #
# cross-section
# --------------------------------------------------------------------------- #
@dataclass
class WRFPlane:
    """The 3-D state one ``wrfout`` time needs for arbitrary-line sections.

    Read once per file and reused across transects: the 3-D arrays are the
    expensive part, and a case typically cuts several lines through the same
    time.  All winds are earth-relative; heights are geometric m ASL on mass
    levels.
    """

    lat2d: np.ndarray  # (ny, nx)
    lon2d: np.ndarray  # (ny, nx) -180..180
    terrain: np.ndarray  # (ny, nx) m ASL
    height: np.ndarray  # (nz, ny, nx) m ASL, mass levels
    height_w: np.ndarray  # (nz+1, ny, nx) m ASL, w levels = the true cell edges
    theta: np.ndarray  # (nz, ny, nx) K
    temp: np.ndarray  # (nz, ny, nx) K
    ue: np.ndarray  # (nz, ny, nx) m/s, earth-relative east
    ve: np.ndarray  # (nz, ny, nx) m/s, earth-relative north
    w: np.ndarray  # (nz, ny, nx) m/s
    pressure_hpa: np.ndarray  # (nz,) domain-mean level pressure, for reference only


def load_plane(ds) -> WRFPlane:
    """Read the 3-D fields for :func:`section_from_plane` from an open ``wrfout``."""
    ue, ve = wo.earth_relative_winds(ds)
    return WRFPlane(
        lat2d=wo.surface_field(ds, "XLAT"),
        lon2d=_lon180(wo.surface_field(ds, "XLONG")),
        terrain=wo.surface_field(ds, "HGT"),
        height=wo.geopotential_height_mass(ds),
        height_w=wo.geopotential_height_w(ds),
        theta=wo.potential_temperature(ds),
        temp=wo.temperature_k(ds),
        ue=ue,
        ve=ve,
        w=wo.vertical_velocity(ds),
        pressure_hpa=wo.pressure_pa(ds).mean(axis=(1, 2)) / 100.0,
    )


def _sample_line(start, end, n):
    """``n`` points on the straight A->B line: lon, lat, distance-from-A (km)."""
    lat0, lon0 = float(start[0]), float(start[1])
    lat1, lon1 = float(end[0]), float(end[1])
    frac = np.linspace(0.0, 1.0, n)
    lon_line = lon0 + frac * (lon1 - lon0)
    lat_line = lat0 + frac * (lat1 - lat0)
    coslat = np.cos(np.deg2rad(0.5 * (lat0 + lat1)))
    dx = (lon_line - lon0) * _KM_PER_DEG_LON * coslat
    dy = (lat_line - lat0) * _KM_PER_DEG_LAT
    return lon_line, lat_line, np.hypot(dx, dy)


def _unit_ab(start, end) -> tuple[float, float]:
    """Unit (east, north) components of the A->B direction."""
    coslat = np.cos(np.deg2rad(0.5 * (float(start[0]) + float(end[0]))))
    e = (float(end[1]) - float(start[1])) * _KM_PER_DEG_LON * coslat
    n = (float(end[0]) - float(start[0])) * _KM_PER_DEG_LAT
    mag = float(np.hypot(e, n))
    if mag == 0.0:
        raise ValueError("section start and end are the same point")
    return e / mag, n / mag


def section_from_plane(
    plane: WRFPlane,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    n_points: int = 240,
    termini: tuple[str, str] = ("A", "B"),
    orientation: str = "EW",
) -> NWPSection:
    """Cut an :class:`NWPSection` from ``plane`` along ``start`` -> ``end``.

    Each sample takes the *nearest model column* -- no horizontal interpolation,
    matching the HRRR path in :func:`brc_tools.nwp.section.extract_nwp_section`.
    Nearest is measured in kilometres (longitudes scaled by cos(lat)), so the
    pick does not drift east-west the way a raw-degree distance would.

    ``start``/``end`` are ``(lat, lon)``.  The along-section component is
    positive toward B.  ``pressure_hpa`` carries the domain-mean level pressures
    for reference; the curtain itself is drawn on geometric height.
    """
    from scipy.spatial import cKDTree

    lon_line, lat_line, dist = _sample_line(start, end, n_points)
    coslat = float(np.cos(np.deg2rad(np.mean(plane.lat2d))))
    tree = cKDTree(np.column_stack([
        plane.lat2d.ravel() * _KM_PER_DEG_LAT,
        plane.lon2d.ravel() * _KM_PER_DEG_LON * coslat,
    ]))
    _, flat = tree.query(np.column_stack([
        lat_line * _KM_PER_DEG_LAT, lon_line * _KM_PER_DEG_LON * coslat]))
    jj, ii = np.unravel_index(flat, plane.lat2d.shape)

    e_hat, n_hat = _unit_ab(start, end)
    ue = plane.ue[:, jj, ii]
    ve = plane.ve[:, jj, ii]
    return NWPSection(
        distance_km=dist,
        lon_line=lon_line,
        lat_line=lat_line,
        height2d=plane.height[:, jj, ii],
        speed2d=np.hypot(ue, ve),
        theta2d=plane.theta[:, jj, ii],
        temp2d=plane.temp[:, jj, ii],
        along2d=ue * e_hat + ve * n_hat,
        w2d=plane.w[:, jj, ii],
        terrain1d=plane.terrain[jj, ii],
        pressure_hpa=plane.pressure_hpa,
        termini=termini,
        orientation=orientation,
        height_w2d=plane.height_w[:, jj, ii],
    )


def extract_wrf_section(ds, start, end, **kwargs) -> NWPSection:
    """One-shot :func:`load_plane` + :func:`section_from_plane`.

    Convenient for a single transect; for several lines through the same time,
    call :func:`load_plane` once and reuse the plane.
    """
    return section_from_plane(load_plane(ds), start, end, **kwargs)
