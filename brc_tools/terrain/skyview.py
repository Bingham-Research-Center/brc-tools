"""Sky-view factor and horizon angles from a DEM (Dozier & Frew 1990).

The fraction of the hemisphere a point can see: 1 on a plain, less in a canyon.  It sets
how much of a surface's downwelling longwave comes from the cold clear sky rather than
from terrain at air temperature, and so how hard the surface can cool at night.  The
same horizon scan, kept per azimuth, says when the sun drops behind a ridge
(``horizon_angles``, ``in_shadow``).  numpy only; arrays are north-up (row 0 north).
"""
from __future__ import annotations

import numpy as np


def sky_view(z: np.ndarray, res: float, *, n_az: int = 16, max_km: float = 10.0) -> np.ndarray:
    """Sky-view factor per cell: the mean over ``n_az`` azimuths of cos^2 of the horizon
    angle found within ``max_km``.  NaN cells are filled with the mean elevation first.

    The horizon search is a shift per step per azimuth, so the cost is
    ``n_az * max_km / res`` array passes: run it on a coarsened grid (a few hundred
    metres) for a whole airshed.
    """
    zz = np.where(np.isnan(z), np.nanmean(z), z).astype(np.float64)
    svf = np.zeros_like(zz)
    nsteps = int(max_km * 1000.0 / res)
    for az in np.linspace(0.0, 2.0 * np.pi, n_az, endpoint=False):
        svf += np.cos(_horizon(zz, res, az, nsteps)) ** 2
    return (svf / n_az).astype(np.float32)


def _horizon(zz: np.ndarray, res: float, az: float, nsteps: int) -> np.ndarray:
    """Horizon elevation angle (rad, >= 0) towards azimuth ``az`` (rad clockwise from north)."""
    ny, nx = zz.shape
    dx, dy = np.sin(az), np.cos(az)
    hmax = np.zeros_like(zz)
    for k in range(1, nsteps + 1):
        di, dj = int(round(k * dx)), int(round(-k * dy))
        if di == 0 and dj == 0:
            continue
        if abs(dj) >= ny or abs(di) >= nx:
            break
        sh = np.full_like(zz, np.nan)
        js = slice(max(dj, 0), ny + min(dj, 0))
        jd = slice(max(-dj, 0), ny + min(-dj, 0))
        is_ = slice(max(di, 0), nx + min(di, 0))
        id_ = slice(max(-di, 0), nx + min(-di, 0))
        sh[jd, id_] = zz[js, is_]
        ang = np.arctan((sh - zz) / (k * res))
        hmax = np.fmax(hmax, np.nan_to_num(ang, nan=0.0))
    return hmax


def horizon_angles(z: np.ndarray, res: float, *, n_az: int = 72, max_km: float = 20.0) -> tuple[np.ndarray, np.ndarray]:
    """Horizon elevation angle (degrees, >= 0) per cell for ``n_az`` azimuths.

    Returns ``(azimuths_deg, angles)`` with ``angles`` shaped ``(n_az, ny, nx)`` float32.
    Terrain beyond the array edge counts as flat, so pad the DEM by ``max_km`` on the
    side the sun sets behind.  Cost and memory scale with ``n_az``: coarsen first.
    """
    zz = np.where(np.isnan(z), np.nanmean(z), z).astype(np.float64)
    nsteps = int(max_km * 1000.0 / res)
    az = np.linspace(0.0, 360.0, n_az, endpoint=False)
    out = np.empty((n_az,) + zz.shape, dtype=np.float32)
    for i, a in enumerate(az):
        out[i] = np.degrees(_horizon(zz, res, np.radians(a), nsteps))
    return az, out


def in_shadow(azimuths_deg: np.ndarray, angles: np.ndarray, sun_az_deg: float, sun_el_deg: float) -> np.ndarray:
    """True where the terrain horizon towards the sun (linearly interpolated between the
    azimuth bins, circularly) stands above the sun's elevation."""
    az = np.asarray(azimuths_deg, dtype=float)
    step = 360.0 / az.size
    f = (sun_az_deg % 360.0 - az[0]) / step
    i0 = int(np.floor(f)) % az.size
    i1 = (i0 + 1) % az.size
    w = f - np.floor(f)
    hor = (1.0 - w) * angles[i0] + w * angles[i1]
    return hor > sun_el_deg
