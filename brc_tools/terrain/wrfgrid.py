"""The terrain a WRF domain actually has: ``geo_em`` on a ``Grid``, and checks on it.

``domain_calc.py`` can say a nest is self-consistent; only the terrain geogrid wrote can
say whether a canyon is open on it.  ``read_geo_em`` puts ``HGT_M`` (and the land-use
fields a lake audit needs) on a north-up ``Grid`` in the domain's own Lambert projection,
so every terrain function in this package -- fill depth, sills, throats -- runs on a model
grid exactly as it does on the DEM.  ``hgt_source_diff`` is the seam-crater detector
(``HGT_M`` against the source DEM averaged onto the same cells), and
``wps_tile_coverage`` reads a WPS binary tile set back and reports missing cells --
the check that would have caught a tile built from no source.

netCDF4 and pyproj are imported lazily; this module works in the terrain env, which
cannot import ``brc_tools.nwp``.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ._optional import require
from .dem import Grid

EARTH_RADIUS_M = 6370000.0      # WRF / WPS sphere
LAKE_CATEGORY = 21              # MODIS 20-class + lakes ("modis_lakes")


def sphere_geo_crs() -> str:
    return f"+proj=longlat +a={EARTH_RADIUS_M:.0f} +b={EARTH_RADIUS_M:.0f} +no_defs"


def read_geo_em(path: str | Path) -> tuple[np.ndarray, Grid, dict]:
    """``HGT_M`` of a ``geo_em.dNN.nc`` as a north-up float32 raster, its ``Grid`` and a dict
    of the fields beside it.

    The ``Grid`` is in the domain's Lambert conformal projection on the WRF sphere (its
    ``geo_crs`` is that sphere, so lat/lon round-trip as WRF sees them).  ``meta`` holds
    ``landmask``, ``lu_index`` and ``lake`` (bool, land-use category 21) north-up, the
    map factor, and the projection attributes.  Only Lambert (``MAP_PROJ = 1``) domains
    are supported.
    """
    nc = require("netCDF4")
    pyproj = require("pyproj")
    with nc.Dataset(path) as ds:
        if int(ds.MAP_PROJ) != 1:
            raise ValueError(f"{path}: MAP_PROJ {ds.MAP_PROJ} is not Lambert conformal")
        dx = float(ds.DX)
        if abs(float(ds.DY) - dx) > 1e-6:
            raise ValueError("DX != DY")
        hgt = np.asarray(ds["HGT_M"][0], dtype=np.float32)
        lat = np.asarray(ds["XLAT_M"][0], dtype=np.float64)
        lon = np.asarray(ds["XLONG_M"][0], dtype=np.float64)
        crs = (f"+proj=lcc +lat_1={float(ds.TRUELAT1)} +lat_2={float(ds.TRUELAT2)} +lat_0={float(ds.MOAD_CEN_LAT)} "
               f"+lon_0={float(ds.STAND_LON)} +a={EARTH_RADIUS_M:.0f} +b={EARTH_RADIUS_M:.0f} +units=m +no_defs")
        meta = {"dx": dx, "truelat1": float(ds.TRUELAT1), "truelat2": float(ds.TRUELAT2),
                "stand_lon": float(ds.STAND_LON), "cen_lat": float(ds.CEN_LAT), "cen_lon": float(ds.CEN_LON),
                "grid_id": int(ds.grid_id), "parent_grid_ratio": int(ds.parent_grid_ratio), "path": str(path)}
        for key, var in (("landmask", "LANDMASK"), ("lu_index", "LU_INDEX"), ("mapfac_m", "MAPFAC_M")):
            if var in ds.variables:
                meta[key] = np.asarray(ds[var][0])[::-1].copy()
        meta["mminlu"] = str(getattr(ds, "MMINLU", ""))
        meta["islake"] = int(getattr(ds, "ISLAKE", LAKE_CATEGORY))
    ny, nx = hgt.shape
    tr = pyproj.Transformer.from_crs(sphere_geo_crs(), crs, always_xy=True)
    x_sw, y_sw = tr.transform(lon[0, 0], lat[0, 0])            # centre of the south-west mass point
    grid = Grid(x0=float(x_sw - 0.5 * dx), y1=float(y_sw + (ny - 0.5) * dx), res=dx, ny=ny, nx=nx,
                crs=crs, geo_crs=sphere_geo_crs())
    # the projection must reproduce the file's own coordinates, or the Grid is wrong
    x_ne, y_ne = tr.transform(lon[-1, -1], lat[-1, -1])
    err = max(abs(x_ne - (x_sw + (nx - 1) * dx)), abs(y_ne - (y_sw + (ny - 1) * dx)))
    if err > 0.02 * dx:
        raise ValueError(f"{path}: projected grid is off by {err:.1f} m at the far corner")
    meta["corner_error_m"] = float(err)
    if "lu_index" in meta:
        meta["lake"] = np.rint(meta["lu_index"]).astype(int) == meta["islake"]
    return hgt[::-1].copy(), grid, meta


def hgt_source_diff(hgt: np.ndarray, src: np.ndarray, *, crater_m: float = 50.0) -> dict:
    """``HGT_M`` minus the source DEM averaged onto the same cells: statistics and the
    cells off by more than ``crater_m``.

    A geogrid seam artefact shows as an isolated large negative difference (the d02 of
    an older build carried a 600 m hole on an integer-degree line).  Returns rms, mean,
    the extremes with their (j, i), and the count and positions of the crater cells.
    Note that geogrid's own smoothing pass leaves differences of tens of metres on
    steep terrain; ``crater_m`` should sit above those.
    """
    d = np.asarray(hgt, dtype=np.float64) - np.asarray(src, dtype=np.float64)
    ok = np.isfinite(d)
    if not ok.any():
        raise ValueError("no overlap between HGT_M and the source")
    dd = np.where(ok, d, 0.0)
    jmin, imin = np.unravel_index(int(np.argmin(np.where(ok, d, np.inf))), d.shape)
    jmax, imax = np.unravel_index(int(np.argmax(np.where(ok, d, -np.inf))), d.shape)
    big = ok & (np.abs(d) > crater_m)
    jj, ii = np.nonzero(big)
    order = np.argsort(-np.abs(d[jj, ii]))[:50]
    return {"n": int(ok.sum()), "n_no_source": int((~ok).sum()), "mean_m": float(dd.sum() / ok.sum()),
            "rms_m": float(np.sqrt((dd ** 2).sum() / ok.sum())),
            "min_m": float(d[jmin, imin]), "min_ji": (int(jmin), int(imin)),
            "max_m": float(d[jmax, imax]), "max_ji": (int(jmax), int(imax)),
            "n_crater": int(big.sum()),
            "craters": [(int(jj[k]), int(ii[k]), float(d[jj[k], ii[k]])) for k in order]}


def read_wps_index(path: str | Path) -> dict[str, str]:
    """A WPS geogrid ``index`` file as a dict of strings (quotes stripped)."""
    out = {}
    for ln in Path(path).read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*(.+?)\s*$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip('"')
    return out


def wps_tile_coverage(tile_dir: str | Path, *, nodata_below: float = -1000.0) -> list[dict]:
    """Read every tile of a WPS continuous dataset back and report what is in it.

    One dict per tile: ``name``, ``lon_w``, ``lat_s`` (of the tile core), ``frac_valid``
    (core cells above ``nodata_below``), ``n_missing``, ``z_min`` / ``z_max`` of the valid
    cells, and ``has_missing_value`` (whether ``index`` declares one -- without it geogrid
    reads a hole as terrain).  A tile built where the source had no data is all missing
    values; nothing downstream reports that unless this is asked.
    """
    tile_dir = Path(tile_dir)
    idx = read_wps_index(tile_dir / "index")
    dx, dy = float(idx["dx"]), float(idx["dy"])
    bdr = int(idx.get("tile_bdr", 0))
    tx, ty = int(idx["tile_x"]), int(idx["tile_y"])
    known_lat, known_lon = float(idx["known_lat"]), float(idx["known_lon"])
    kx, ky = float(idx.get("known_x", 1)), float(idx.get("known_y", 1))
    word = int(idx.get("wordsize", 2))
    dtype = {1: "i1", 2: ">i2", 4: ">i4"}[word] if idx.get("signed", "no") == "yes" else {1: "u1", 2: ">u2", 4: ">u4"}[word]
    scale = float(idx.get("scale_factor", 1.0))
    rows = []
    for p in sorted(q for q in tile_dir.iterdir() if re.match(r"^\d{5,6}-\d{5,6}\.\d{5,6}-\d{5,6}$", q.name)):
        xs, _, ys, _ = (int(v) for v in re.split(r"[-.]", p.name))
        arr = np.fromfile(p, dtype=dtype).reshape(ty + 2 * bdr, tx + 2 * bdr).astype(np.float64) * scale
        core = arr[bdr:arr.shape[0] - bdr, bdr:arr.shape[1] - bdr]
        lon_w = known_lon + (xs - kx) * dx - 0.5 * dx
        if lon_w > 180.0:
            lon_w -= 360.0
        ok = core > nodata_below
        rows.append({"name": p.name, "lon_w": round(lon_w, 4), "lat_s": round(known_lat + (ys - ky) * dy - 0.5 * dy, 4),
                     "frac_valid": float(ok.mean()), "n_missing": int((~ok).sum()),
                     "z_min": float(core[ok].min()) if ok.any() else float("nan"),
                     "z_max": float(core[ok].max()) if ok.any() else float("nan"),
                     "has_missing_value": "missing_value" in idx})
    return rows
