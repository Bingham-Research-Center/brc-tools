"""Vertical cross-section along an arbitrary lat/lon line from gridded NWP data.

The NWP analogue of :func:`brc_tools.nwp.wrf_output.build_section`. Where the WRF
path cuts a grid-aligned row/column of native eta levels, this samples the nearest
model column along an arbitrary A->B geographic line and stacks per-level pressure
fields into a height-distance curtain.

It consumes an :class:`xarray.Dataset` whose pressure-level fields are *flat
per-level variables* named ``{prefix}_{level}`` -- exactly what
:meth:`brc_tools.nwp.NWPSource.fetch` returns for HRRR/RRFS when ``levels=[...]``
is passed (e.g. ``wind_u_850``, ``height_700``) -- plus a 2-D terrain field, and
hands plain numpy arrays to the ``visualize`` renderers. Like the rest of the
package it keeps the physics here and the Matplotlib rendering in ``visualize``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

_RD = 287.05  # J kg-1 K-1 (dry air gas constant)
_G = 9.80665  # m s-2
_P0 = 100000.0  # Pa (reference pressure)
_RCP = 0.2854  # R_d / c_p


@dataclass
class NWPSection:
    """A vertical cross-section sampled along a geographic line.

    Distances are km from terminus A; heights are geometric (m ASL) from the
    model's per-level geopotential height, so the curtain is drawn at true
    altitude. Fields are NaN below the terrain surface.
    """

    distance_km: np.ndarray  # (n,)
    lon_line: np.ndarray  # (n,) -180..180
    lat_line: np.ndarray  # (n,)
    height2d: np.ndarray  # (nz, n) m ASL
    speed2d: np.ndarray  # (nz, n) horizontal wind speed, m/s
    theta2d: np.ndarray  # (nz, n) potential temperature, K
    temp2d: np.ndarray  # (nz, n) temperature, K
    along2d: np.ndarray  # (nz, n) along-transect horizontal wind (+ toward B), m/s
    w2d: np.ndarray  # (nz, n) vertical velocity, m/s
    terrain1d: np.ndarray  # (n,) m ASL
    pressure_hpa: np.ndarray  # (nz,)
    thetae2d: np.ndarray | None = None  # (nz, n) equiv. potential temp, K (needs dewpoint)
    termini: tuple[str, str] = ("A", "B")
    orientation: str = "EW"  # accent-colour key for the crosssection helpers


def _lon180(lon) -> np.ndarray:
    """Wrap longitudes from 0..360 to -180..180 (HRRR grids are 0..360)."""
    lon = np.asarray(lon, dtype=float)
    return np.where(lon > 180.0, lon - 360.0, lon)


def _sample_line(start, end, n):
    """Sample ``n`` points on the straight A->B line; return lon, lat, distance(km).

    ``start``/``end`` are ``(lat, lon)``. Distance uses a local equirectangular
    metric -- accurate to well under a percent over a single basin-scale transect.
    """
    lat0, lon0 = float(start[0]), float(start[1])
    lat1, lon1 = float(end[0]), float(end[1])
    frac = np.linspace(0.0, 1.0, n)
    lon_line = lon0 + frac * (lon1 - lon0)
    lat_line = lat0 + frac * (lat1 - lat0)
    coslat = np.cos(np.deg2rad(0.5 * (lat0 + lat1)))
    dx = (lon_line - lon0) * 111.320 * coslat
    dy = (lat_line - lat0) * 110.574
    return lon_line, lat_line, np.hypot(dx, dy)


def extract_nwp_section(
    ds,
    start: tuple[float, float],
    end: tuple[float, float],
    levels,
    *,
    n_points: int = 220,
    prefixes: tuple[str, str, str, str, str] = ("wind_u", "wind_v", "temp", "height", "omega"),
    dewpoint_prefix: str | None = "dewpoint",
    terrain_var: str = "terrain_height",
    time_index: int = 0,
    termini: tuple[str, str] = ("A", "B"),
) -> NWPSection:
    """Extract a cross-section from ``start`` to ``end`` (each ``(lat, lon)``).

    Parameters
    ----------
    ds : xarray.Dataset
        Must hold 2-D ``latitude``/``longitude`` coords and flat per-level vars
        ``{u}_{lev}``, ``{v}_{lev}``, ``{temp}_{lev}``, ``{height}_{lev}`` (and
        optionally ``{omega}_{lev}``) for each level in *levels*, plus *terrain_var*.
    levels : sequence of int
        Pressure levels (hPa) present as per-level variables, ordered as desired
        (bottom-up recommended, e.g. ``[1000, 975, ..., 700]``).
    n_points : int
        Samples along the line (nearest model column per sample).
    prefixes : (u, v, temp, height, omega)
        Variable-name prefixes; ``{prefix}_{level}`` is looked up per level.
    dewpoint_prefix : str or None
        Prefix for per-level dewpoint (K).  When every level is present,
        ``thetae2d`` (equivalent potential temperature) is computed via Bolton
        (1980); otherwise it stays ``None``.  Pass ``None`` to skip.
    terrain_var : str
        2-D terrain-height variable name (m ASL) for the terrain floor + masking.

    Returns
    -------
    NWPSection
    """
    from scipy.spatial import cKDTree

    lat2d = np.asarray(ds["latitude"].values, dtype=float)
    lon2d = _lon180(ds["longitude"].values)
    tree = cKDTree(np.column_stack([lat2d.ravel(), lon2d.ravel()]))

    lon_line, lat_line, dist = _sample_line(start, end, n_points)
    _, flat = tree.query(np.column_stack([lat_line, lon_line]))
    flat = np.asarray(flat, dtype=int)

    def gather(varname: str) -> np.ndarray:
        da = ds[varname]
        if "time" in da.dims:
            da = da.isel(time=time_index)
        return np.asarray(da.values, dtype=float).ravel()[flat]

    levels = [int(x) for x in levels]
    nz, n = len(levels), n_points
    up, vp, tp, hp, op = prefixes
    u = np.full((nz, n), np.nan)
    v = np.full((nz, n), np.nan)
    temp = np.full((nz, n), np.nan)
    hgt = np.full((nz, n), np.nan)
    omega = np.full((nz, n), np.nan)
    has_td = dewpoint_prefix is not None and all(
        f"{dewpoint_prefix}_{lev}" in ds for lev in levels)
    dewpoint = np.full((nz, n), np.nan) if has_td else None
    for k, lev in enumerate(levels):
        u[k] = gather(f"{up}_{lev}")
        v[k] = gather(f"{vp}_{lev}")
        temp[k] = gather(f"{tp}_{lev}")
        hgt[k] = gather(f"{hp}_{lev}")
        if f"{op}_{lev}" in ds:
            omega[k] = gather(f"{op}_{lev}")
        if has_td:
            dewpoint[k] = gather(f"{dewpoint_prefix}_{lev}")
    terrain1d = gather(terrain_var)

    pres_pa = (np.array(levels, dtype=float) * 100.0)[:, None]  # (nz, 1)
    speed = np.hypot(u, v)
    theta = temp * (_P0 / pres_pa) ** _RCP
    thetae = None
    if has_td:
        from brc_tools.nwp.derived import theta_e
        thetae = np.asarray(theta_e(temp, dewpoint, pres_pa / 100.0), dtype=float)
    # omega (Pa/s) -> geometric w (m/s):  w = -omega * R_d * T / (p * g)
    w = -omega * _RD * temp / (pres_pa * _G)

    # along-transect horizontal component (+ toward B), east/north basis
    lat0, lon0 = float(start[0]), float(start[1])
    lat1, lon1 = float(end[0]), float(end[1])
    coslat = np.cos(np.deg2rad(0.5 * (lat0 + lat1)))
    tx, ty = (lon1 - lon0) * coslat, (lat1 - lat0)
    tnorm = np.hypot(tx, ty) or 1.0
    tx, ty = tx / tnorm, ty / tnorm
    along = u * tx + v * ty

    # Mask fields below the terrain surface (isobaric levels under ground are
    # extrapolated); keep height2d valid so pcolormesh can still place the cells,
    # and let the terrain fill cover them.
    below = hgt < terrain1d[None, :]
    for a in (speed, theta, temp, along, w) + ((thetae,) if thetae is not None else ()):
        a[below] = np.nan

    return NWPSection(
        distance_km=dist,
        lon_line=lon_line,
        lat_line=lat_line,
        height2d=hgt,
        speed2d=speed,
        theta2d=theta,
        temp2d=temp,
        along2d=along,
        w2d=w,
        terrain1d=terrain1d,
        pressure_hpa=np.array(levels, dtype=float),
        thetae2d=thetae,
        termini=termini,
    )
