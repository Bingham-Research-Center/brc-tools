"""The throat between two basins: how wide and how large the narrowest passage is.

A pool behind a canyon leaves through the canyon's narrowest cross-section.  Two
measures of that section are computed here for a pool whose level top stands at
``stage`` (m), from the terrain alone:

``clearance_width``
    the width of the widest path through the flooded region between the two basins -- how
    many grid cells across the passage is, which is what decides whether a model can carry
    a current through it at all.

``min_cut_area``
    the smallest cross-sectional area (m2) separating the two basins inside the flooded
    region: a depth-weighted minimum cut.  It needs no thalweg and no transect, so it is
    indifferent to meanders, it ignores dead-end side canyons, and it sums parallel routes
    (a braided reach, a bypass over a low saddle).

Both take the upstream and downstream basins as bool MASKS -- never single cells: the
cheapest cut round one cell is that cell's own perimeter, usually smaller than the
throat, and a path can be no wider than the cell it starts from.  A mask must reach
well past the throat's width on both sides (a disc of a few kilometres round
``depressions.lowest_cell`` will do).  They work on any grid: the true terrain, a
block-averaged model grid, or ``HGT_M`` of a real WRF domain.  numpy and scipy only.
"""
from __future__ import annotations

import numpy as np

EIGHT = np.ones((3, 3), dtype=int)
# Cauchy-Crofton edge weights for an 8-neighbour grid graph: with them the weight of a cut
# approximates its Euclidean length (to ~8 %) whatever its orientation.
W_AXIS = np.pi / 8.0
W_DIAG = np.pi / (8.0 * np.sqrt(2.0))


def _as_mask(shape, seed, which: str) -> np.ndarray:
    # a point seed measures the seed, not the throat: the ring round one cell is a cheaper cut
    # than most canyons (13 400 m2 against 39 900 m2 for the 9-cell test channel), so refuse it
    if not (isinstance(seed, np.ndarray) and seed.dtype == bool and seed.shape == tuple(shape)):
        raise ValueError(f"{which} must be a bool mask of the basin, shape {tuple(shape)}, not a (j, i) cell: "
                         "the cut round a single cell is smaller than the throat.  Pass the basin, e.g. a disc of "
                         "cells round depressions.lowest_cell reaching well past the throat's width")
    if np.count_nonzero(seed) < 2:
        what = "empty" if not seed.any() else "a single cell"
        raise ValueError(f"{which} is {what}: pass the basin as a mask reaching well past the throat's width")
    return seed


def flooded(z: np.ndarray, stage: float) -> np.ndarray:
    """Cells a pool with a level top at ``stage`` would cover, a cell AT the stage included
    -- as ``depressions.sill_between`` counts it, so at the sill the throat is open (one
    cell wide, no depth).  NaN is dry."""
    return np.nan_to_num(z, nan=np.inf) <= stage


def clearance_width(z: np.ndarray, res: float, stage: float, src, dst, *, tol_cells: float = 0.25) -> float:
    """Width (m) of the widest path from ``src`` to ``dst`` (bool masks of the two basins)
    through the cells at or below ``stage``.

    The clearance of a cell is its Euclidean distance to the nearest dry cell; a path's
    clearance is its smallest; the widest path maximises it (a bisection on the clearance
    threshold with a connected-component test -- no path search).  A one-cell-wide channel
    has clearance 1, so the width is ``(2 d - 1) * res``.  Returns 0 where the basins are
    not connected at this stage.
    """
    from scipy import ndimage

    wet = flooded(z, stage)
    a, b = _as_mask(z.shape, src, "src") & wet, _as_mask(z.shape, dst, "dst") & wet
    if not a.any() or not b.any():
        return 0.0

    def linked(mask) -> bool:
        lab, _ = ndimage.label(mask, structure=EIGHT)
        la, lb = np.unique(lab[a & mask]), np.unique(lab[b & mask])
        return bool(np.intersect1d(la[la > 0], lb[lb > 0]).size)

    if not linked(wet):
        return 0.0
    d = ndimage.distance_transform_edt(wet)
    lo, hi = 1.0, float(min(d[a].max(), d[b].max()))          # the path cannot be wider than its ends
    if hi <= lo:
        return float(res)
    if linked(d >= hi):
        return float((2.0 * hi - 1.0) * res)
    while hi - lo > tol_cells:
        mid = 0.5 * (lo + hi)
        if linked(d >= mid):
            lo = mid
        else:
            hi = mid
    return float((2.0 * lo - 1.0) * res)


def min_cut_area(z: np.ndarray, res: float, stage: float, src, dst, *, scale: float = 10.0,
                 return_cut: bool = False):
    """Smallest cross-sectional area (m2) between ``src`` and ``dst`` under a pool at ``stage``.

    The flooded cells are the nodes of a graph; neighbouring cells are joined by an edge
    whose capacity is the area of the water column on the face between them --
    ``weight * res * (stage - max(z_a, z_b))`` with the Cauchy-Crofton weights that make a
    cut's total weight its length.  The maximum flow from the upstream basin to the
    downstream one equals the minimum cut, i.e. the throat's area.

    ``src`` / ``dst`` are bool masks of the two basins (a single cell is refused: the cut
    round it would be the answer); their cells are tied to a super-source and a super-sink.  ``scale`` sets the integer resolution of the
    capacities (10 -> 0.1 m2).  With ``return_cut`` the bool mask of the cells on the
    upstream side of the cut is returned too, so the throat can be drawn on a map.
    Returns 0 where the basins are not connected at this stage.
    """
    from scipy import ndimage
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import breadth_first_order, maximum_flow

    wet = flooded(z, stage)
    a, b = _as_mask(z.shape, src, "src") & wet, _as_mask(z.shape, dst, "dst") & wet
    none = (0.0, np.zeros(z.shape, dtype=bool)) if return_cut else 0.0
    if not a.any() or not b.any():
        return none
    lab, _ = ndimage.label(wet, structure=EIGHT)
    la, lb = np.unique(lab[a]), np.unique(lab[b])
    common = np.intersect1d(la[la > 0], lb[lb > 0])
    if common.size == 0:
        return none
    comp = np.isin(lab, common)
    a, b = a & comp, b & comp
    if (a & b).any():
        raise ValueError("the upstream and downstream masks overlap")

    jj, ii = np.nonzero(comp)
    j0, j1, i0, i1 = jj.min(), jj.max() + 1, ii.min(), ii.max() + 1
    comp_w = comp[j0:j1, i0:i1]
    depth = np.where(comp_w, stage - z[j0:j1, i0:i1], 0.0)
    n = int(comp_w.sum())
    node = np.full(comp_w.shape, -1, dtype=np.int64)
    node[comp_w] = np.arange(n)
    rows, cols, caps = [], [], []
    for dj, di, w in ((0, 1, W_AXIS), (1, 0, W_AXIS), (1, 1, W_DIAG), (1, -1, W_DIAG)):
        ny, nx = comp_w.shape
        ja, jb = slice(0, ny - dj), slice(dj, ny)
        if di >= 0:
            ia, ib = slice(0, nx - di), slice(di, nx)
        else:
            ia, ib = slice(-di, nx), slice(0, nx + di)
        both = comp_w[ja, ia] & comp_w[jb, ib]
        c = np.rint(w * res * np.minimum(depth[ja, ia], depth[jb, ib])[both] * scale).astype(np.int64)
        u, v = node[ja, ia][both], node[jb, ib][both]
        ok = c > 0
        rows += [u[ok], v[ok]]
        cols += [v[ok], u[ok]]
        caps += [c[ok], c[ok]]
    rows, cols, caps = np.concatenate(rows), np.concatenate(cols), np.concatenate(caps)
    # super-source / super-sink: each basin cell is tied with the capacity of all its own faces
    # (as much as could ever pass through it), which keeps every number inside int32
    through = np.bincount(rows, weights=caps, minlength=n).astype(np.int64)
    s, t = n, n + 1
    sa, sb = node[a[j0:j1, i0:i1]], node[b[j0:j1, i0:i1]]
    rows = np.concatenate([rows, np.full(sa.size, s), sb])
    cols = np.concatenate([cols, sa, np.full(sb.size, t)])
    caps = np.concatenate([caps, through[sa], through[sb]])
    if caps.max(initial=0) >= 2 ** 31 or through[sa].sum() >= 2 ** 62:
        raise OverflowError("capacities exceed int32: lower `scale`")
    g = csr_matrix((caps.astype(np.int32), (rows.astype(np.int32), cols.astype(np.int32))), shape=(n + 2, n + 2))
    res_flow = maximum_flow(g, s, t)
    area = float(res_flow.flow_value) / scale
    if not return_cut:
        return area
    residual = (g - res_flow.flow).tocsr()
    residual.data = np.where(residual.data > 0, 1, 0).astype(np.int8)
    residual.eliminate_zeros()
    reach = breadth_first_order(residual, s, directed=True, return_predecessors=False)
    side = np.zeros(n + 2, dtype=bool)
    side[reach] = True
    up = np.zeros(z.shape, dtype=bool)
    up[j0:j1, i0:i1][comp_w] = side[:n]
    return area, up


def cut_cells(upstream_side: np.ndarray, wet: np.ndarray) -> np.ndarray:
    """The flooded cells on the upstream side of a cut that touch its downstream side: the
    line the throat is drawn along."""
    from scipy import ndimage

    down = wet & ~upstream_side
    return upstream_side & ndimage.binary_dilation(down, structure=EIGHT)


def throat_curve(z: np.ndarray, res: float, stages, src, dst) -> dict[str, np.ndarray]:
    """Throat area and clearance width at each stage (absolute elevations, m); ``src`` and
    ``dst`` are bool masks of the two basins."""
    stages = np.atleast_1d(np.asarray(stages, dtype=float))
    area = np.array([min_cut_area(z, res, s, src, dst) for s in stages])
    width = np.array([clearance_width(z, res, s, src, dst) for s in stages])
    return {"stage_m": stages, "area_m2": area, "width_m": width}
