"""Single-flow-direction hydrology on a metric grid.

D8 (O'Callaghan & Mark 1984): every cell sends all of its flow to the steepest of its
eight neighbours.  Pits are removed first by priority-flood filling (Barnes, Lehman &
Mulla 2014, ``richdem``) with an epsilon gradient so every filled cell still drains.
Flow accumulation and upstream labelling use one topological (Kahn) ordering of the
receiver graph, so both are O(N) vectorised gathers rather than recursion -- which is
what makes 6e8-cell grids tractable in numpy.

Arrays are ``(ny, nx)`` float32/bool rasters or flat ``int32`` index vectors; a cell's
flat index is ``j * nx + i``.  A cell with no lower neighbour (a sink, or nodata) is
its own receiver.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ._optional import require

logger = logging.getLogger(__name__)

NODATA = -32768.0
NEIGHBORS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def fill_depressions(dem: np.ndarray, grid, *, epsilon: bool = True, nodata: float = NODATA) -> np.ndarray:
    """Priority-flood pit filling (richdem).  NaN cells stay NaN and act as outlets."""
    rd = require("richdem")
    z = np.where(np.isnan(dem), nodata, dem).astype(np.float32)
    rda = rd.rdarray(z, no_data=nodata)
    rda.geotransform = (grid.x0, grid.res, 0.0, grid.y1, 0.0, -grid.res)
    rd.FillDepressions(rda, epsilon=epsilon, in_place=True, topology="D8")
    out = np.asarray(rda, dtype=np.float32).copy()
    out[np.isnan(dem)] = np.nan
    return out


def d8_receivers(zf: np.ndarray, res: float, *, band: int = 1024) -> np.ndarray:
    """Steepest-descent receiver (flat int32 index) per cell; a cell with no lower
    neighbour receives itself.  Nodata (NaN) cells are treated as -inf so that flow
    leaves the data through them, and are themselves sinks."""
    ny, nx = zf.shape
    z = np.where(np.isnan(zf), -np.inf, zf)
    zp = np.pad(z, 1, constant_values=np.inf)
    rcv = np.arange(ny * nx, dtype=np.int32).reshape(ny, nx)
    for j0 in range(0, ny, band):
        j1 = min(ny, j0 + band)
        zc = z[j0:j1]
        best = np.zeros_like(zc)
        best_k = np.full(zc.shape, -1, np.int8)
        for k, (dj, di) in enumerate(NEIGHBORS):
            zn = zp[j0 + 1 + dj:j1 + 1 + dj, 1 + di:nx + 1 + di]
            with np.errstate(invalid="ignore"):
                drop = (zc - zn) / (res * np.sqrt(2.0) if dj and di else res)
                better = drop > best
            best = np.where(better, drop, best)
            best_k[better] = k
        jj, ii = np.indices(zc.shape)
        jj += j0
        for k, (dj, di) in enumerate(NEIGHBORS):
            m = best_k == k
            rcv[j0:j1][m] = ((jj[m] + dj) * nx + (ii[m] + di)).astype(np.int32)
    rcv = rcv.ravel()
    nod = np.isnan(zf).ravel()
    rcv[nod] = np.flatnonzero(nod).astype(np.int32)
    return rcv


def step_length(rcv: np.ndarray, nx: int, res: float) -> np.ndarray:
    """Distance from each cell to its receiver: ``res`` or ``res * sqrt(2)`` (float32)."""
    dd = np.abs(rcv - np.arange(rcv.size, dtype=np.int32))
    return np.where((dd == nx + 1) | (dd == nx - 1), res * np.sqrt(2.0), res).astype(np.float32)


@dataclass
class FlowOrder:
    """Flow accumulation plus the topological order it was built in.

    ``order[starts[k]:starts[k+1]]`` is level ``k``; every receiver sits in a later level
    than all of its donors, so a reverse sweep over levels propagates labels or
    distances downstream -> upstream in O(N).
    """

    acc: np.ndarray          # uint32 cell count draining through each cell, including itself
    order: np.ndarray        # int32, every cell once, ridges first
    starts: np.ndarray       # int64 level boundaries into ``order``
    n_levels: int


def flow_accumulation(rcv: np.ndarray) -> FlowOrder:
    """Cell-count accumulation by Kahn's algorithm on the receiver graph."""
    n = rcv.size
    self_idx = np.arange(n, dtype=np.int32)
    not_self = rcv != self_idx
    del self_idx
    indeg = np.bincount(rcv[not_self], minlength=n).astype(np.uint8)
    acc = np.ones(n, dtype=np.uint32)
    frontier = np.flatnonzero(indeg == 0).astype(np.int32)
    levels, starts, pos = [], [0], 0
    while frontier.size:
        levels.append(frontier)
        pos += frontier.size
        starts.append(pos)
        r = rcv[frontier]
        keep = r != frontier
        r, src = r[keep], frontier[keep]
        np.add.at(acc, r, acc[src])
        np.subtract.at(indeg, r, 1)
        cand = r[indeg[r] == 0]
        frontier = np.unique(cand).astype(np.int32)
    order = np.concatenate(levels) if levels else np.zeros(0, dtype=np.int32)
    if order.size != n:
        raise RuntimeError(f"Kahn order covers {order.size} of {n} cells: the receiver graph has a cycle")
    logger.info("accumulation: %d levels, max %d cells", len(levels), int(acc.max()))
    return FlowOrder(acc=acc, order=order, starts=np.asarray(starts, dtype=np.int64), n_levels=len(levels))


def label_upstream(rcv: np.ndarray, order: np.ndarray, starts: np.ndarray, roots, ids, *, step=None):
    """Label every cell with the id of the root its flow path reaches (-1 if none).

    A root is a sink for labelling: cells downstream of it are not part of it.  With
    ``step`` (the per-cell step length) the along-flow distance to the root is returned
    as well.
    """
    n = rcv.size
    lab = np.full(n, -1, dtype=np.int32)
    lab[np.asarray(roots)] = np.asarray(ids, dtype=np.int32)
    is_root = np.zeros(n, dtype=bool)
    is_root[np.asarray(roots)] = True
    dist = np.zeros(n, dtype=np.float32) if step is not None else None
    for lv in range(len(starts) - 2, -1, -1):
        f = order[starts[lv]:starts[lv + 1]]
        r = rcv[f]
        m = ~is_root[f] & (r != f)
        fm, rm = f[m], r[m]
        lab[fm] = lab[rm]
        if dist is not None:
            dist[fm] = dist[rm] + step[fm]
    if dist is not None:
        dist[lab < 0] = 0.0
        return lab, dist
    return lab


def walk_downstream(rcv: np.ndarray, cell: int, nsteps: int) -> int:
    for _ in range(nsteps):
        cell = int(rcv[cell])
    return cell


def walk_upstream_main(rcv: np.ndarray, acc: np.ndarray, cell: int, nsteps: int, nx: int) -> int:
    """Follow the largest-accumulation donor upstream for ``nsteps`` cells (the main stem)."""
    n = rcv.size
    for _ in range(nsteps):
        j, i = divmod(int(cell), nx)
        best, best_acc = None, 0
        for dj, di in NEIGHBORS:
            cc = (j + dj) * nx + (i + di)
            if 0 <= cc < n and rcv[cc] == cell and acc[cc] > best_acc:
                best, best_acc = cc, acc[cc]
        if best is None:
            break
        cell = best
    return int(cell)


def trace_downstream(rcv: np.ndarray, start: int, *, stop=None, max_steps: int | None = None) -> np.ndarray:
    """The flow path from ``start`` as flat indices, ending at a sink, at the first cell for
    which ``stop`` is true (a flat bool mask; that cell is included) or after ``max_steps``."""
    path = [int(start)]
    limit = rcv.size if max_steps is None else int(max_steps)
    cell = int(start)
    for _ in range(limit):
        if stop is not None and stop[cell]:
            break
        nxt = int(rcv[cell])
        if nxt == cell:
            break
        path.append(nxt)
        cell = nxt
    return np.asarray(path, dtype=np.int64)


def trace_upstream_main(rcv: np.ndarray, acc: np.ndarray, start: int, nx: int, *, min_acc: float = 0.0,
                        max_steps: int | None = None) -> np.ndarray:
    """The main stem above ``start`` as flat indices (``start`` first): at each cell follow
    the donor with the largest accumulation, until none has at least ``min_acc`` cells."""
    n = rcv.size
    path = [int(start)]
    cell = int(start)
    limit = n if max_steps is None else int(max_steps)
    for _ in range(limit):
        j, i = divmod(cell, nx)
        best, best_acc = -1, 0
        for dj, di in NEIGHBORS:
            jj, ii = j + dj, i + di
            if 0 <= ii < nx:
                cc = jj * nx + ii
                if 0 <= cc < n and rcv[cc] == cell and cc != cell and acc[cc] > best_acc:
                    best, best_acc = cc, acc[cc]
        if best < 0 or best_acc < min_acc:
            break
        path.append(int(best))
        cell = int(best)
    return np.asarray(path, dtype=np.int64)


def fill_depth(dem: np.ndarray, grid) -> np.ndarray:
    """Depth of every cell below its depression's spill level (m, >= 0; NaN where nodata):
    a priority-flood fill WITHOUT the epsilon gradient, minus the terrain.  On a real
    DEM this is ponds and lake basins; on a model grid it is also the storage that
    coarsening put behind canyons it could no longer resolve."""
    flat = fill_depressions(dem, grid, epsilon=False)
    # subtract on the fill's own float32 values: a float64 DEM would leave ~1e-4 m of
    # rounding as depth in every cell the fill never touched
    return np.maximum(flat - np.asarray(dem, dtype=np.float32), np.float32(0.0))


def slope_deg(dem: np.ndarray, res: float) -> np.ndarray:
    """Terrain slope (degrees) from central differences; NaN filled with the mean first."""
    gy, gx = np.gradient(np.where(np.isnan(dem), np.nanmean(dem), dem), res, res)
    return np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)


def channel_mask(acc: np.ndarray, cell_area_m2: float, min_km2: float) -> np.ndarray:
    """Cells with at least ``min_km2`` upstream (a channel by the accumulation threshold)."""
    return acc.astype(np.float64) * cell_area_m2 >= min_km2 * 1e6
