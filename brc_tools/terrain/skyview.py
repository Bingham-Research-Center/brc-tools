"""Sky-view factor from a DEM (Dozier & Frew 1990).

The fraction of the hemisphere a point can see: 1 on a plain, less in a canyon.  It sets
how much of a surface's downwelling longwave comes from the cold clear sky rather than
from terrain at air temperature, and so how hard the surface can cool at night.
numpy only.
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
    ny, nx = z.shape
    zz = np.where(np.isnan(z), np.nanmean(z), z).astype(np.float64)
    svf = np.zeros_like(zz)
    nsteps = int(max_km * 1000.0 / res)
    for az in np.linspace(0.0, 2.0 * np.pi, n_az, endpoint=False):
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
        svf += np.cos(hmax) ** 2
    return (svf / n_az).astype(np.float32)
