"""DEM tiles -> one metric grid, and the ``Grid`` geometry every other module uses.

The USGS 3DEP staged products are 1 x 1 degree GeoTIFFs in NAD83 geographic
coordinates (``USGS_13_n41w110.tif`` = 1/3 arc-second, ``USGS_1_n41w110.tif`` = 1
arc-second; the name is the tile's NW corner).  Routing wants equal-area cells, so the
tiles are merged in their native CRS and warped once to UTM zone 12N at a chosen
spacing.  The warped DEM is cached as NPZ next to a ``Grid`` (origin, spacing, shape)
that maps lat/lon to cell indices and back.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import asdict, dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

from ._optional import require

logger = logging.getLogger(__name__)

UTM12N = "EPSG:26912"           # NAD83 / UTM zone 12N -- the Uinta Basin sits in zone 12
NAD83_GEO = "EPSG:4269"         # the tiles' CRS
NODATA = -32768.0
SOURCE_CODES = {"13as": "13", "1as": "1"}   # subdirectory -> USGS product code in the filename


@dataclass(frozen=True)
class Grid:
    """A north-up metric raster: ``x0`` west edge, ``y1`` north edge, ``res`` spacing (m)."""

    x0: float
    y1: float
    res: float
    ny: int
    nx: int
    crs: str = UTM12N
    geo_crs: str = NAD83_GEO

    @cached_property
    def _to_grid(self):
        return require("pyproj").Transformer.from_crs(self.geo_crs, self.crs, always_xy=True)

    @cached_property
    def _to_geo(self):
        return require("pyproj").Transformer.from_crs(self.crs, self.geo_crs, always_xy=True)

    @property
    def to_grid(self):
        """pyproj Transformer geographic -> grid CRS (``always_xy``: lon, lat -> x, y)."""
        return self._to_grid

    @property
    def to_geo(self):
        """pyproj Transformer grid CRS -> geographic (x, y -> lon, lat)."""
        return self._to_geo

    @property
    def cell_area_m2(self) -> float:
        return float(self.res) ** 2

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    def ji(self, lat, lon) -> tuple[np.ndarray, np.ndarray]:
        """Row, column of the cell(s) containing lat/lon (may fall outside the grid)."""
        x, y = self._to_grid.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
        j = np.floor((self.y1 - np.asarray(y)) / self.res).astype(int)
        i = np.floor((np.asarray(x) - self.x0) / self.res).astype(int)
        return j, i

    def xy(self, j, i) -> tuple[np.ndarray, np.ndarray]:
        """Cell-centre coordinates in the grid CRS (m)."""
        x = self.x0 + (np.asarray(i, dtype=float) + 0.5) * self.res
        y = self.y1 - (np.asarray(j, dtype=float) + 0.5) * self.res
        return x, y

    def lonlat(self, j, i) -> tuple[np.ndarray, np.ndarray]:
        """Cell-centre longitude, latitude."""
        return self.lonlat_xy(*self.xy(j, i))

    def lonlat_xy(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        lon, lat = self._to_geo.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        return lon, lat

    def inside(self, j, i) -> np.ndarray:
        j, i = np.asarray(j), np.asarray(i)
        return (j >= 0) & (j < self.ny) & (i >= 0) & (i < self.nx)

    def flat(self, j, i) -> np.ndarray:
        return np.asarray(j) * self.nx + np.asarray(i)

    def line_cells(self, lat0, lon0, lat1, lon1, *, width_cells: int = 1) -> np.ndarray:
        """Unique flat indices of the cells under a straight line (in the grid CRS)
        between two lat/lon points, optionally thickened to ``width_cells``."""
        xa, ya = self._to_grid.transform(lon0, lat0)
        xb, yb = self._to_grid.transform(lon1, lat1)
        n = int(np.hypot(xb - xa, yb - ya) / (self.res * 0.5)) + 2
        xs, ys = np.linspace(xa, xb, n), np.linspace(ya, yb, n)
        j = np.floor((self.y1 - ys) / self.res).astype(int)
        i = np.floor((xs - self.x0) / self.res).astype(int)
        if width_cells > 1:
            w = width_cells // 2
            jj, ii = np.meshgrid(np.arange(-w, w + 1), np.arange(-w, w + 1), indexing="ij")
            j = (j[:, None] + jj.ravel()[None, :]).ravel()
            i = (i[:, None] + ii.ravel()[None, :]).ravel()
        ok = self.inside(j, i)
        return np.unique(j[ok] * self.nx + i[ok])

    def extent_lonlat(self) -> tuple[float, float, float, float]:
        """(lon_w, lon_e, lat_s, lat_n) of the grid's corners."""
        xs = np.array([self.x0, self.x0 + self.nx * self.res] * 2)
        ys = np.array([self.y1, self.y1, self.y1 - self.ny * self.res, self.y1 - self.ny * self.res])
        lon, lat = self.lonlat_xy(xs, ys)
        return float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Grid:
        return cls(x0=float(d["x0"]), y1=float(d["y1"]), res=float(d["res"]), ny=int(d["ny"]),
                   nx=int(d["nx"]), crs=str(d.get("crs", UTM12N)), geo_crs=str(d.get("geo_crs", NAD83_GEO)))


# --------------------------------------------------------------------------- #
# cache locations
# --------------------------------------------------------------------------- #
def terrain_cache_dir(explicit: str | Path | None = None) -> Path:
    """``explicit`` > ``$BRC_TOOLS_TERRAIN_CACHE`` > ``~/.cache/brc-tools/terrain`` (never the repo)."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("BRC_TOOLS_TERRAIN_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "brc-tools" / "terrain"


def dem_cache_path(source: str, res_m: float, extent, *, cache_dir: str | Path | None = None) -> Path:
    key = hashlib.sha1(f"{source}|{res_m:g}|{','.join(f'{v:.3f}' for v in extent)}".encode()).hexdigest()[:8]
    return terrain_cache_dir(cache_dir) / f"dem_{source}_{res_m:g}m_{key}.npz"


# --------------------------------------------------------------------------- #
# tiles -> grid
# --------------------------------------------------------------------------- #
def tile_paths(tiles_dir: str | Path, source: str, extent) -> list[Path]:
    """The GeoTIFFs under ``tiles_dir/source`` that intersect ``extent``
    (lon_w, lon_e, lat_s, lat_n)."""
    rasterio = require("rasterio")
    code = SOURCE_CODES[source]
    lon0, lon1, lat0, lat1 = extent
    out = []
    for p in sorted((Path(tiles_dir) / source).glob(f"USGS_{code}_*.tif")):
        with rasterio.open(p) as ds:
            b = ds.bounds
            if b.right > lon0 and b.left < lon1 and b.top > lat0 and b.bottom < lat1:
                out.append(p)
    return out


def mosaic_tiles(
    tiles_dir: str | Path,
    source: str,
    extent,
    res_m: float,
    *,
    cache_dir: str | Path | None = None,
    refresh: bool = False,
    num_threads: int = 8,
    pad_deg: float = 0.02,
) -> tuple[np.ndarray, Grid]:
    """Merge the intersecting tiles in their native CRS and warp once to UTM 12N at
    ``res_m``: average resampling when coarsening, bilinear otherwise.  Nodata and the
    ocean sentinel become NaN.  Cached as ``dem_<source>_<res>m_<key>.npz``.

    ``extent`` is (lon_w, lon_e, lat_s, lat_n).  Returns ``(dem, grid)`` with ``dem``
    float32 ``(ny, nx)`` metres.
    """
    cache = dem_cache_path(source, res_m, extent, cache_dir=cache_dir)
    if cache.exists() and not refresh:
        logger.info("DEM cache hit %s", cache)
        return load_cached_dem(cache)
    rasterio = require("rasterio")
    from rasterio.enums import Resampling
    from rasterio.merge import merge
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    tifs = tile_paths(tiles_dir, source, extent)
    if not tifs:
        raise FileNotFoundError(f"no {source} tiles under {tiles_dir} intersect {extent}")
    logger.info("%d tiles intersect %s: %s", len(tifs), extent, [t.stem[-7:] for t in tifs])
    lon0, lon1, lat0, lat1 = extent
    tr = require("pyproj").Transformer.from_crs(NAD83_GEO, UTM12N, always_xy=True)
    corners = np.array([[lon0, lat0], [lon0, lat1], [lon1, lat0], [lon1, lat1],
                        [(lon0 + lon1) / 2, lat0], [(lon0 + lon1) / 2, lat1]])
    xs, ys = tr.transform(corners[:, 0], corners[:, 1])
    x0, x1 = np.floor(xs.min() / res_m) * res_m, np.ceil(xs.max() / res_m) * res_m
    y0, y1 = np.floor(ys.min() / res_m) * res_m, np.ceil(ys.max() / res_m) * res_m
    nx, ny = int(round((x1 - x0) / res_m)), int(round((y1 - y0) / res_m))
    dst_transform = from_origin(x0, y1, res_m, res_m)
    logger.info("target grid %d x %d at %g m (%.1f M cells)", ny, nx, res_m, ny * nx / 1e6)

    srcs = [rasterio.open(p) for p in tifs]
    try:
        native = abs(srcs[0].transform.a)
        merged, src_transform = merge(srcs, bounds=(lon0 - pad_deg, lat0 - pad_deg, lon1 + pad_deg, lat1 + pad_deg),
                                      nodata=NODATA, dtype="float32")
        src_crs = srcs[0].crs
    finally:
        for s in srcs:
            s.close()
    merged = merged[0]
    dst = np.full((ny, nx), NODATA, dtype=np.float32)
    coarsening = res_m > native * 111e3 * 1.5
    reproject(merged, dst, src_transform=src_transform, src_crs=src_crs, src_nodata=NODATA,
              dst_transform=dst_transform, dst_crs=UTM12N, dst_nodata=NODATA,
              resampling=Resampling.average if coarsening else Resampling.bilinear,
              num_threads=num_threads)
    del merged
    dst[dst <= -1000] = np.nan
    grid = Grid(float(x0), float(y1), float(res_m), ny, nx)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, dem=dst, x0=x0, y1=y1, res=res_m, ny=ny, nx=nx)
    logger.info("warped: %.2f%% nodata, z %.0f..%.0f m -> %s", np.isnan(dst).mean() * 100,
                np.nanmin(dst), np.nanmax(dst), cache)
    return dst, grid


def load_cached_dem(path: str | Path) -> tuple[np.ndarray, Grid]:
    z = np.load(path)
    dem = z["dem"]
    return dem, Grid(float(z["x0"]), float(z["y1"]), float(z["res"]), *dem.shape)


# --------------------------------------------------------------------------- #
# label rasters on the same grid
# --------------------------------------------------------------------------- #
def save_labels_npz(path: str | Path, grid: Grid, **arrays) -> Path:
    """Write label/accumulation rasters with the grid geometry beside them (compressed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, x0=grid.x0, y1=grid.y1, res=grid.res, ny=grid.ny, nx=grid.nx,
                        crs=grid.crs, geo_crs=grid.geo_crs, **arrays)
    return path


def load_labels_npz(path: str | Path) -> tuple[Grid, dict[str, np.ndarray]]:
    z = np.load(path)
    meta = {"x0", "y1", "res", "ny", "nx", "crs", "geo_crs"}
    grid = Grid(float(z["x0"]), float(z["y1"]), float(z["res"]), int(z["ny"]), int(z["nx"]),
                str(z["crs"]) if "crs" in z.files else UTM12N,
                str(z["geo_crs"]) if "geo_crs" in z.files else NAD83_GEO)
    return grid, {k: z[k] for k in z.files if k not in meta}


def sample_labels(lab: np.ndarray, grid: Grid, lat, lon, *, fill: int = -1) -> np.ndarray:
    """Nearest-cell label at lat/lon points (any shape); ``fill`` outside the grid."""
    j, i = grid.ji(lat, lon)
    ok = grid.inside(j, i)
    out = np.full(np.shape(j), fill, dtype=lab.dtype)
    out[ok] = lab[j[ok], i[ok]]
    return out
