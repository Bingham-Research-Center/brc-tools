"""Deterministic, tiny synthetic wrfout-like Dataset for unit tests.

Not a test module (no ``test_`` prefix): a fixture builder imported by the WRF
tests so they never need a real (large, NETCDF4) wrfout file.

Design choices that make assertions easy:
  * XLAT/XLONG are a regular grid (XLAT varies with j only, XLONG with i only),
    so ``nearest_column_index`` has a known answer.
  * potential temperature increases with level (280 + 2*level K), so cold-pool
    diagnostics are positive.
  * geopotential height on w-levels = terrain + 100 m * w-level, so the mass-level
    destagger is terrain + (k + 0.5) * 100 m.
  * U = 5, V = 2, W = 0.1 (constant) so destagger results are exact.
  * COSALPHA = 1, SINALPHA = 0, so earth-relative winds equal grid-relative.
"""

from __future__ import annotations

import numpy as np

_G = 9.80665


def make_synthetic_wrf(nz: int = 4, ny: int = 6, nx: int = 6):
    """Return a small in-memory ``xr.Dataset`` mimicking a wrfout file."""
    import xarray as xr

    nzs, nys, nxs = nz + 1, ny + 1, nx + 1
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    xlat = 40.0 + jj * 0.1
    xlon = -110.0 + ii * 0.1
    hgt = 1500.0 + 20.0 * ii + 10.0 * jj  # gentle terrain slope

    lev = np.arange(nz).reshape(nz, 1, 1)
    theta = np.broadcast_to(280.0 + 2.0 * lev, (nz, ny, nx)).astype(float)
    t_pert = theta - 300.0
    pb = np.broadcast_to(90000.0 - 1000.0 * lev, (nz, ny, nx)).astype(float)
    p = np.zeros((nz, ny, nx))

    wlev = np.arange(nzs).reshape(nzs, 1, 1)
    height_w = hgt[np.newaxis, :, :] + wlev * 100.0
    phb = height_w * _G
    ph = np.zeros((nzs, ny, nx))

    u = np.full((nz, ny, nxs), 5.0)
    v = np.full((nz, nys, nx), 2.0)
    w = np.full((nzs, ny, nx), 0.1)

    def _t(a):  # prepend a size-1 Time axis, as WRF does
        return a[np.newaxis, ...]

    xyz = ("Time", "bottom_top", "south_north", "west_east")
    sfc = ("Time", "south_north", "west_east")
    return xr.Dataset(
        data_vars={
            "T": (xyz, _t(t_pert)),
            "P": (xyz, _t(p)),
            "PB": (xyz, _t(pb)),
            "PH": (("Time", "bottom_top_stag", "south_north", "west_east"), _t(ph)),
            "PHB": (("Time", "bottom_top_stag", "south_north", "west_east"), _t(phb)),
            "U": (("Time", "bottom_top", "south_north", "west_east_stag"), _t(u)),
            "V": (("Time", "bottom_top", "south_north_stag", "west_east"), _t(v)),
            "W": (("Time", "bottom_top_stag", "south_north", "west_east"), _t(w)),
            "HGT": (sfc, _t(hgt)),
            "XLAT": (sfc, _t(xlat)),
            "XLONG": (sfc, _t(xlon)),
            "COSALPHA": (sfc, _t(np.ones((ny, nx)))),
            "SINALPHA": (sfc, _t(np.zeros((ny, nx)))),
            "PSFC": (sfc, _t(np.full((ny, nx), 90000.0))),
            "T2": (sfc, _t(np.full((ny, nx), 270.0))),
            "TH2": (sfc, _t(np.full((ny, nx), 275.0))),
            "U10": (sfc, _t(np.full((ny, nx), 3.0))),
            "V10": (sfc, _t(np.full((ny, nx), 1.0))),
            "SNOWH": (sfc, _t(np.full((ny, nx), 0.2))),
            "PBLH": (sfc, _t(np.zeros((ny, nx)))),  # f00 gotcha: PBLH == 0
            "TSK": (sfc, _t(np.full((ny, nx), 268.0))),
            "QVAPOR": (xyz, _t(np.full((nz, ny, nx), 0.002))),
        },
        attrs={
            "DX": 333.333,
            "DY": 333.333,
            "MAP_PROJ": 1,
            "TRUELAT1": 40.0,
            "TRUELAT2": 41.0,
            "STAND_LON": -110.0,
            "CEN_LAT": 40.3,
            "CEN_LON": -109.7,
        },
    )
