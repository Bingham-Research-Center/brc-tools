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

from pathlib import Path

import numpy as np

_G = 9.80665

_WRFOUT_TIME_FMT = "%Y-%m-%d_%H:%M:%S"


def make_synthetic_wrf(
    nz: int = 4,
    ny: int = 6,
    nx: int = 6,
    *,
    lat0: float = 40.0,
    lon0: float = -110.0,
    drop_vars: tuple[str, ...] = (),
):
    """Return a small in-memory ``xr.Dataset`` mimicking a wrfout file.

    ``lat0``/``lon0`` place the grid at a different region (the grid stays regular);
    ``drop_vars`` omits fields to exercise missing-variable handling.
    """
    import xarray as xr

    nzs, nys, nxs = nz + 1, ny + 1, nx + 1
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    xlat = lat0 + jj * 0.1
    xlon = lon0 + ii * 0.1
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
    ds = xr.Dataset(
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
            "TRUELAT1": lat0,
            "TRUELAT2": lat0 + 1.0,
            "STAND_LON": lon0,
            "CEN_LAT": lat0 + 0.3,
            "CEN_LON": lon0 + 0.3,
        },
    )
    if drop_vars:
        ds = ds.drop_vars([v for v in drop_vars if v in ds])
    return ds


def write_synthetic_run(
    run_dir,
    domains: dict[int, dict],
    times,
    *,
    nz: int = 4,
    lat0: float = 40.0,
    lon0: float = -110.0,
):
    """Write ``wrfout_d0N_<stamp>`` NetCDF files for a synthetic multi-domain run.

    ``domains`` maps a domain number to a spec dict, e.g.
    ``{1: {"ny": 8, "nx": 8, "dx": 3000.0},
       2: {"ny": 10, "nx": 10, "dx": 1000.0, "drop_vars": ("SNOWH",)}}``.
    Each spec may set ``ny``/``nx``/``dx``/``dy``/``lat0``/``lon0``/``drop_vars``.
    Used by the figure-engine acceptance test to exercise a non-pelican shape off
    disk (domain discovery, ``DX`` labels, missing-variable skips).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for dom, spec in domains.items():
        ds = make_synthetic_wrf(
            nz=nz, ny=spec["ny"], nx=spec["nx"],
            lat0=spec.get("lat0", lat0), lon0=spec.get("lon0", lon0),
            drop_vars=tuple(spec.get("drop_vars", ())),
        )
        if "dx" in spec:
            ds.attrs["DX"] = float(spec["dx"])
            ds.attrs["DY"] = float(spec.get("dy", spec["dx"]))
        for t in times:
            fname = f"wrfout_d{dom:02d}_{t.strftime(_WRFOUT_TIME_FMT)}"
            ds.to_netcdf(run_dir / fname, engine="netcdf4")
    return run_dir
