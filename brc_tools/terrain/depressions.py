"""Closed depressions, the sills between basins, and volume-against-stage curves.

Water fills a depression to its spill level and then leaves; a nocturnal cold pool does
the same.  On the true terrain the closed depressions are ponds, lake basins and
glacial hollows.  On a model grid there is a second population: canyons too narrow for
the grid spacing are averaged shut, and the valley above each becomes a basin that must
fill to a *spurious sill* before any air can leave it.  The functions here measure
both -- the inventory of closed storage on any terrain, the lowest pass connecting two
places (which on a model grid is the sill a pool has to reach), and the volume a
basin holds below a given stage.

Everything works on ``(ny, nx)`` float arrays with NaN for nodata and needs only numpy
and ``scipy.ndimage``; the priority-flood fill itself is ``d8.fill_depth`` (richdem).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

EIGHT = np.ones((3, 3), dtype=int)


@dataclass
class Depression:
    """One closed depression: where it is, how much it holds, and the level it spills at."""

    id: int
    n_cells: int
    area_m2: float
    volume_m3: float
    max_depth_m: float
    mean_depth_m: float
    spill_m: float              # elevation of the filled surface
    floor_m: float              # lowest terrain cell
    deepest_ji: tuple[int, int]

    def to_dict(self) -> dict:
        return asdict(self)


def inventory(dem: np.ndarray, depth: np.ndarray, cell_area_m2: float, *, min_depth_m: float = 2.0,
              min_cells: int = 4) -> tuple[np.ndarray, list[Depression]]:
    """Label the closed depressions of ``dem`` and summarise each.

    ``depth`` is ``d8.fill_depth(dem, grid)``.  A depression is a connected region
    (8-neighbour) deeper than ``min_depth_m`` with at least ``min_cells`` cells -- the
    thresholds drop the centimetre-scale pits every DEM has.  Returns the label raster
    (0 = none, else the 1-based index into the list) and the list, largest volume first.
    """
    from scipy import ndimage

    deep = np.nan_to_num(depth, nan=0.0) > min_depth_m
    lab, n = ndimage.label(deep, structure=EIGHT)
    if n == 0:
        return lab.astype(np.int32), []
    idx = np.arange(1, n + 1)
    counts = ndimage.sum_labels(deep, lab, idx).astype(np.int64)
    vol = ndimage.sum_labels(np.where(deep, depth, 0.0), lab, idx) * cell_area_m2
    dmax = ndimage.maximum(depth, lab, idx)
    zmin = ndimage.minimum(dem, lab, idx)
    pos = ndimage.maximum_position(depth, lab, idx)
    keep = np.flatnonzero(counts >= min_cells)
    order = keep[np.argsort(-vol[keep])]
    relabel = np.zeros(n + 1, dtype=np.int32)
    out = []
    for new_id, k in enumerate(order, start=1):
        relabel[k + 1] = new_id
        j, i = (int(v) for v in pos[k])
        out.append(Depression(
            id=new_id, n_cells=int(counts[k]), area_m2=float(counts[k] * cell_area_m2), volume_m3=float(vol[k]),
            max_depth_m=float(dmax[k]), mean_depth_m=float(vol[k] / (counts[k] * cell_area_m2)),
            spill_m=float(dem[j, i] + depth[j, i]), floor_m=float(zmin[k]), deepest_ji=(j, i)))
    return relabel[lab], out


def volume_stage(z_cells: np.ndarray, cell_area_m2: float, stages) -> tuple[np.ndarray, np.ndarray]:
    """Volume (m3) and flooded area (m2) below each stage for a set of cell elevations.

    ``V(Z) = sum(max(Z - z, 0)) * cell_area`` -- the air a pool with a level top at ``Z``
    holds over those cells.  ``stages`` are absolute elevations (m)."""
    z = np.sort(np.asarray(z_cells, dtype=np.float64).ravel())
    z = z[np.isfinite(z)]
    stages = np.atleast_1d(np.asarray(stages, dtype=np.float64))
    csum = np.concatenate([[0.0], np.cumsum(z)])
    k = np.searchsorted(z, stages, side="left")
    vol = (stages * k - csum[k]) * cell_area_m2
    return vol, k * cell_area_m2


def stage_for_volume(z_cells: np.ndarray, cell_area_m2: float, volume_m3) -> np.ndarray:
    """Inverse of ``volume_stage``: the stage (m) at which the cells hold ``volume_m3``."""
    z = np.sort(np.asarray(z_cells, dtype=np.float64).ravel())
    z = z[np.isfinite(z)]
    csum = np.concatenate([[0.0], np.cumsum(z)])
    k = np.arange(1, z.size + 1)
    v_at_cell = (z * (k - 1) - csum[:-1]) * cell_area_m2      # volume when the stage reaches each cell's elevation
    vol = np.atleast_1d(np.asarray(volume_m3, dtype=np.float64))
    n = np.clip(np.searchsorted(v_at_cell, vol, side="right"), 1, z.size)   # cells flooded at that volume
    return (vol / cell_area_m2 + csum[n]) / n


def connected(mask: np.ndarray, seed_a, seed_b) -> bool:
    """Are two (j, i) cells -- or two bool masks -- in one 8-connected component of ``mask``?"""
    from scipy import ndimage

    lab, _ = ndimage.label(mask, structure=EIGHT)
    la, lb = _labels_at(lab, seed_a), _labels_at(lab, seed_b)
    return bool(np.intersect1d(la, lb).size)


def _labels_at(lab: np.ndarray, seed) -> np.ndarray:
    if isinstance(seed, np.ndarray) and seed.dtype == bool:
        v = np.unique(lab[seed])
    else:
        v = np.atleast_1d(lab[int(seed[0]), int(seed[1])])
    return v[v > 0]


def sill_between(z: np.ndarray, seed_a, seed_b, *, tol: float = 1.0, z_max: float | None = None) -> float:
    """The lowest stage at which a pool floods a continuous path between two places: the
    highest point of the lowest connecting route (the "minimax" pass), to within ``tol``
    metres.  ``seed_a`` / ``seed_b`` are (j, i) cells or bool masks; NaN cells are walls.

    Found by bisection on the stage with a connected-component test, so it costs about
    ``log2(relief / tol)`` labelings of the window and needs no path search.  Returns
    ``inf`` when the two are not connected even at ``z_max`` (default: the highest cell).
    """
    zz = np.where(np.isnan(z), np.inf, z)
    lo = max(_seed_floor(zz, seed_a), _seed_floor(zz, seed_b))
    hi = float(np.nanmax(z)) if z_max is None else float(z_max)
    if not connected(zz <= hi, seed_a, seed_b):
        return float("inf")
    if connected(zz <= lo, seed_a, seed_b):
        return float(lo)
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if connected(zz <= mid, seed_a, seed_b):
            hi = mid
        else:
            lo = mid
    return float(hi)


def _seed_floor(zz: np.ndarray, seed) -> float:
    if isinstance(seed, np.ndarray) and seed.dtype == bool:
        return float(zz[seed].min())
    return float(zz[int(seed[0]), int(seed[1])])


def lowest_cell(z: np.ndarray, grid, lat: float, lon: float, *, radius_m: float = 1500.0) -> tuple[int, int]:
    """The lowest cell within ``radius_m`` of a point: a robust seed for "the floor of the
    basin at this place" on any grid spacing (a named point can sit on a bench or a wall)."""
    j0, i0 = (int(v) for v in grid.ji(lat, lon))
    r = max(int(round(radius_m / grid.res)), 0)
    ja, jb = max(j0 - r, 0), min(j0 + r + 1, z.shape[0])
    ia, ib = max(i0 - r, 0), min(i0 + r + 1, z.shape[1])
    if ja >= jb or ia >= ib:
        raise ValueError(f"({lat}, {lon}) is outside the grid")
    sub = z[ja:jb, ia:ib]
    jj, ii = np.unravel_index(int(np.nanargmin(sub)), sub.shape)
    return ja + int(jj), ia + int(ii)
