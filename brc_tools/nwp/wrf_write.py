"""Write fields in the WRF ``wrfout`` layout, so that tools which read only WRF read them.

The inverse of ``wrf_output``: given potential temperature, winds and the heights of the
w-levels on a mass grid, write one history time with WRF's names, staggering and
conventions -- T = theta - 300, heights in PHB (PH = 0), U/V/W on their staggered grids,
COSALPHA/SINALPHA for the grid's rotation from true north.  It exists to hand fields that
did not come from WRF (idealised theory, ``brc_tools.flow``) to readers that know only
WRF: ``wrf_output``'s sections and columns, and the brc-voxel-viz renderer.  Every file
says what it is in ``TITLE`` and carries the caller's provenance attributes.

Conventions that matter to the readers:
  * rows run south to north (XLAT increases with j), as in WRF: flip a north-up raster;
  * heights use g = 9.81 (WRF's own constant and brc-voxel-viz's); ``wrf_output`` reads
    with 9.80665, 0.03 % higher (about 1 m at 4 km);
  * every value is finite (a NaN would spread through any reader's smoothing), and PHB is
    the same in every file of a sequence when the terrain is (readers difference fields on
    native levels).
Filenames: ``wrf_output.wrfout_path`` (WRF's colon form).  Needs netCDF4.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import numpy as np

from .wrf_output import CP, P0, RCP, THETA0

G_WRF = 9.81                     # WRF's module_model_constants g
_TIME_FMT = "%Y-%m-%d_%H:%M:%S"


def terrain_following_levels(hgt: np.ndarray, z_top: float, *, dz_bottom: float = 15.0,
                             fine_depth: float = 400.0, stretch: float = 1.12) -> np.ndarray:
    """Heights (m ASL) of the w-levels, ``(nz + 1, ny, nx)``, for terrain ``hgt``.

    The lowest ``fine_depth`` metres above the ground are layers of ``dz_bottom`` in every
    column, so a feature at a fixed height above the ground is resolved alike everywhere;
    above them the layers grow by ``stretch`` and are rescaled per column to end exactly
    at ``z_top``, every column holding the same number of levels.  The first mass level
    is ``dz_bottom / 2`` above the ground."""
    hgt = np.asarray(hgt, dtype=float)
    n_fine = max(1, int(round(fine_depth / dz_bottom)))
    fine = np.arange(n_fine + 1) * dz_bottom
    col_up = z_top - hgt - fine[-1]
    if np.any(col_up <= dz_bottom):
        raise ValueError("z_top must clear the highest ground by more than fine_depth")
    deepest = float(col_up.max())
    n_up = max(1, int(np.ceil(np.log(1.0 + deepest * (stretch - 1.0) / dz_bottom) / np.log(stretch))))
    frac = np.cumsum(stretch ** np.arange(n_up))
    frac = frac / frac[-1]
    agl = np.concatenate([np.broadcast_to(fine[:, None, None], (fine.size,) + hgt.shape),
                          fine[-1] + frac[:, None, None] * col_up[None]], axis=0)
    return hgt[None] + agl


def stagger(a: np.ndarray, axis: int) -> np.ndarray:
    """Values on the faces between cells along ``axis``: the two-point mean inside, linear
    extrapolation at both ends.  WRF readers destagger by the two-point mean, which returns
    a linear field and the end values exactly and anything else through a 1-2-1 filter."""
    a = np.moveaxis(np.asarray(a, dtype=float), axis, -1)
    if a.shape[-1] < 2:
        raise ValueError("cannot stagger an axis shorter than two")
    mid = 0.5 * (a[..., :-1] + a[..., 1:])
    first = 1.5 * a[..., :1] - 0.5 * a[..., 1:2]
    last = 1.5 * a[..., -1:] - 0.5 * a[..., -2:-1]
    return np.moveaxis(np.concatenate([first, mid, last], axis=-1), -1, axis)


def grid_rotation(lon, lat, lon_up, lat_up) -> tuple[np.ndarray, np.ndarray]:
    """``(COSALPHA, SINALPHA)`` for cells at ``lon, lat`` whose grid-north neighbour points
    are ``lon_up, lat_up``.  alpha is minus the true bearing of grid north, which makes
    WRF's rotation ue = u cos(alpha) - v sin(alpha), ve = v cos(alpha) + u sin(alpha)
    turn grid components into east and north."""
    from pyproj import Geod

    az, _, _ = Geod(ellps="GRS80").inv(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float),
                                       np.asarray(lon_up, dtype=float), np.asarray(lat_up, dtype=float))
    alpha = -np.radians(az)
    return np.cos(alpha), np.sin(alpha)


def hydrostatic_pressure(theta: np.ndarray, z_w: np.ndarray, *, p_top: float, g: float = G_WRF) -> np.ndarray:
    """Hydrostatic pressure (Pa) on mass levels for ``theta`` ``(nz, ny, nx)`` between the
    w-levels ``z_w``: the Exner function pi = (p / p0)^(R/cp) integrated down from ``p_top``
    at the top level with d(pi)/dz = -g / (cp theta)."""
    theta = np.asarray(theta, dtype=float)
    dz = np.diff(np.asarray(z_w, dtype=float), axis=0)
    pi_w = np.empty((theta.shape[0] + 1,) + theta.shape[1:])
    pi_w[-1] = (p_top / P0) ** RCP
    for k in range(theta.shape[0] - 1, -1, -1):
        pi_w[k] = pi_w[k + 1] + g * dz[k] / (CP * theta[k])
    pi_m = 0.5 * (pi_w[:-1] + pi_w[1:])
    return P0 * pi_m ** (1.0 / RCP)


def _check_finite(name: str, a) -> None:
    if a is not None and not np.all(np.isfinite(a)):
        raise ValueError(f"{name} has non-finite values")


def write_wrfout(path: str | Path, *, valid_time: datetime, start_time: datetime, hgt: np.ndarray,
                 xlat: np.ndarray, xlong: np.ndarray, z_w: np.ndarray, theta: np.ndarray, dx: float,
                 dy: float, title: str, u: np.ndarray | None = None, v: np.ndarray | None = None,
                 w: np.ndarray | None = None, cosalpha: np.ndarray | None = None,
                 sinalpha: np.ndarray | None = None, pressure: np.ndarray | None = None,
                 attrs: dict | None = None, g: float = G_WRF, complevel: int = 4,
                 least_significant_digit: int | None = None) -> Path:
    """Write one history time.  Arrays are on the mass grid, rows south to north:
    ``hgt``/``xlat``/``xlong`` ``(ny, nx)``; ``theta``, ``u``, ``v`` ``(nz, ny, nx)`` (u and v
    are staggered here); ``z_w`` and ``w`` on the w-levels ``(nz + 1, ny, nx)``, with
    ``z_w[0]`` = ``hgt``.  Winds are grid-relative; give all three or none.  ``pressure``
    (mass levels, Pa) is written as PB with P = 0.  ``attrs`` are added to the global
    attributes (``MAP_PROJ_CHAR`` and provenance among them).  The file is written beside
    ``path`` and renamed into place."""
    from netCDF4 import Dataset

    path = Path(path)
    theta = np.asarray(theta, dtype=float)
    z_w = np.asarray(z_w, dtype=float)
    hgt = np.asarray(hgt, dtype=float)
    nz, ny, nx = theta.shape
    if z_w.shape != (nz + 1, ny, nx) or hgt.shape != (ny, nx):
        raise ValueError("z_w must be (nz + 1, ny, nx) and hgt (ny, nx) for theta (nz, ny, nx)")
    if not np.all(np.diff(z_w, axis=0) > 0):
        raise ValueError("z_w must increase upward in every column")
    if np.max(np.abs(z_w[0] - hgt)) > 0.01:
        raise ValueError("the lowest w-level must be the ground (z_w[0] = hgt)")
    winds = (u, v, w)
    if any(a is not None for a in winds) and any(a is None for a in winds):
        raise ValueError("give u, v and w together or none of them")
    for name, a in (("theta", theta), ("z_w", z_w), ("hgt", hgt), ("xlat", xlat), ("xlong", xlong),
                    ("u", u), ("v", v), ("w", w), ("cosalpha", cosalpha), ("sinalpha", sinalpha),
                    ("pressure", pressure)):
        _check_finite(name, a)
    if w is not None and np.asarray(w).shape != (nz + 1, ny, nx):
        raise ValueError("w is on the w-levels: (nz + 1, ny, nx)")

    tmp = path.with_name(path.name + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(tmp, "w", format="NETCDF4") as ds:
        for name, size in (("Time", None), ("DateStrLen", 19), ("west_east", nx), ("south_north", ny),
                           ("bottom_top", nz), ("bottom_top_stag", nz + 1), ("west_east_stag", nx + 1),
                           ("south_north_stag", ny + 1)):
            ds.createDimension(name, size)
        stamp = valid_time.strftime(_TIME_FMT)
        times = ds.createVariable("Times", "S1", ("Time", "DateStrLen"))
        times.set_auto_chartostring(False)
        times[0, :] = np.frombuffer(stamp.encode("ascii"), dtype="S1")
        xt = ds.createVariable("XTIME", "f4", ("Time",))
        xt.units = f"minutes since {start_time:%Y-%m-%d %H:%M:%S}"
        xt.description = "minutes since simulation start"
        xt[0] = (valid_time - start_time).total_seconds() / 60.0

        def put(name, dims, values, units, description, stagger_code="", lsd=None):
            values = np.asarray(values, dtype=np.float32)
            chunks = (1,) + (1,) * (len(dims) - 2) + values.shape[-2:]
            var = ds.createVariable(name, "f4", ("Time",) + dims, zlib=complevel > 0, complevel=max(complevel, 1),
                                    shuffle=True, chunksizes=chunks, least_significant_digit=lsd)
            var.units = units
            var.description = description
            var.stagger = stagger_code
            var.MemoryOrder = "XYZ" if len(dims) == 3 else "XY "
            var.FieldType = np.int32(104)
            var[0] = values

        sfc = ("south_north", "west_east")
        mass = ("bottom_top", "south_north", "west_east")
        put("XLAT", sfc, xlat, "degree_north", "LATITUDE, SOUTH IS NEGATIVE")
        put("XLONG", sfc, xlong, "degree_east", "LONGITUDE, WEST IS NEGATIVE")
        put("HGT", sfc, hgt, "m", "Terrain Height")
        put("COSALPHA", sfc, np.ones((ny, nx)) if cosalpha is None else cosalpha, "", "Local cosine of map rotation")
        put("SINALPHA", sfc, np.zeros((ny, nx)) if sinalpha is None else sinalpha, "", "Local sine of map rotation")
        put("T", mass, theta - THETA0, "K", "perturbation potential temperature (theta-t0)",
            lsd=least_significant_digit)
        put("PH", ("bottom_top_stag", "south_north", "west_east"), np.zeros_like(z_w), "m2 s-2",
            "perturbation geopotential", "Z")
        put("PHB", ("bottom_top_stag", "south_north", "west_east"), g * z_w, "m2 s-2", "base-state geopotential", "Z")
        if u is not None:
            put("U", ("bottom_top", "south_north", "west_east_stag"), stagger(u, 2), "m s-1",
                "x-wind component", "X", lsd=least_significant_digit)
            put("V", ("bottom_top", "south_north_stag", "west_east"), stagger(v, 1), "m s-1",
                "y-wind component", "Y", lsd=least_significant_digit)
            put("W", ("bottom_top_stag", "south_north", "west_east"), w, "m s-1", "z-wind component", "Z",
                lsd=least_significant_digit)
        if pressure is not None:
            put("P", mass, np.zeros_like(theta), "Pa", "perturbation pressure")
            put("PB", mass, pressure, "Pa", "BASE STATE PRESSURE")

        jc, ic = ny // 2, nx // 2
        ds.setncatts({
            "TITLE": title,
            "START_DATE": f"{start_time:{_TIME_FMT}}",
            "SIMULATION_START_DATE": f"{start_time:{_TIME_FMT}}",
            "DX": np.float32(dx), "DY": np.float32(dy),
            "CEN_LAT": np.float32(np.asarray(xlat)[jc, ic]), "CEN_LON": np.float32(np.asarray(xlong)[jc, ic]),
            "MAP_PROJ": np.int32(0), "MAP_PROJ_CHAR": "Cartesian (idealised)", "MP_PHYSICS": np.int32(0),
            "WEST-EAST_GRID_DIMENSION": np.int32(nx + 1), "SOUTH-NORTH_GRID_DIMENSION": np.int32(ny + 1),
            "BOTTOM-TOP_GRID_DIMENSION": np.int32(nz + 1),
        })
        if attrs:
            ds.setncatts(dict(attrs))
    os.replace(tmp, path)
    return path
