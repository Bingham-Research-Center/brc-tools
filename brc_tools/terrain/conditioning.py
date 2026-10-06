"""Terrain conditioning: what a model grid does to terrain on purpose.

Two operations, both applied to a ``(ny, nx)`` elevation raster and both meant for
*evaluating* a choice before anyone makes it on a real domain:

``limit_slope``
    relax the terrain until no cell-to-cell slope exceeds a limit -- the smoothing a
    terrain-following model needs before a steep, fine nest will integrate.  It also
    refills the canyon the nest was meant to resolve, and how much is measurable.

``breach``
    lower the cells along a channel to a prescribed thalweg profile -- "carving" a river
    through a canyon that the grid spacing averaged shut, so that the valley above it is
    no longer a closed basin.

numpy only.
"""
from __future__ import annotations

import numpy as np


def max_neighbour_slope(z: np.ndarray, res: float) -> np.ndarray:
    """Steepest slope (tangent) from each cell to any of its eight neighbours; NaN
    neighbours are ignored and a NaN cell gets 0."""
    zz = np.pad(z, 1, mode="edge")
    out = np.zeros(z.shape, dtype=np.float64)
    ny, nx = z.shape
    for dj, di in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        d = res * (np.sqrt(2.0) if dj and di else 1.0)
        out = np.fmax(out, np.abs(zz[1 + dj:1 + dj + ny, 1 + di:1 + di + nx] - z) / d)     # fmax: NaN loses
    return out


def _binomial(a: np.ndarray) -> np.ndarray:
    """3 x 3 binomial (1-2-1 by 1-2-1) mean, edges replicated."""
    k = np.array([1.0, 2.0, 1.0]) / 4.0
    zp = np.pad(a, 1, mode="edge")
    sm = k[0] * zp[:-2, 1:-1] + k[1] * zp[1:-1, 1:-1] + k[2] * zp[2:, 1:-1]
    zp2 = np.pad(sm, ((0, 0), (1, 1)), mode="edge")
    return k[0] * zp2[:, :-2] + k[1] * zp2[:, 1:-1] + k[2] * zp2[:, 2:]


def limit_slope(z: np.ndarray, res: float, max_deg: float, *, max_iter: int = 500,
                weight: float = 0.5) -> tuple[np.ndarray, int]:
    """Smooth ``z`` only where it is too steep, until the steepest neighbour slope is at most
    ``max_deg`` (or ``max_iter`` passes).  Each pass blends the offending cells and their
    neighbours toward a 1-2-1 (3 x 3 binomial) mean with ``weight``; cells on gentle terrain
    are never touched, so basin floors keep their elevation.  Returns the conditioned
    terrain and the number of passes.  NaN cells are left alone and take no part: they
    make no neighbour steep and pull no mean (filling them with a global mean would make
    real terrain beside a hole look like a cliff)."""
    lim = np.tan(np.radians(max_deg))
    out = np.array(z, dtype=np.float64, copy=True)
    nan = np.isnan(out)
    weight_valid = _binomial((~nan).astype(np.float64))        # the mean over valid cells only; 1 away from holes
    n_iter = 0
    for n_iter in range(1, max_iter + 1):
        steep = max_neighbour_slope(out, res) > lim
        if not steep.any():
            n_iter -= 1
            break
        sm = _binomial(np.where(nan, 0.0, out)) / np.maximum(weight_valid, 1e-12)
        touch = steep.copy()                       # the steep cells and their 8 neighbours
        touch[1:, :] |= steep[:-1, :]
        touch[:-1, :] |= steep[1:, :]
        touch[:, 1:] |= steep[:, :-1]
        touch[:, :-1] |= steep[:, 1:]
        out = np.where(touch & ~nan, (1.0 - weight) * out + weight * sm, out)
    return out.astype(z.dtype, copy=False), n_iter


def breach(z: np.ndarray, cells_ji, z_profile, *, half_width_cells: int = 0) -> np.ndarray:
    """Lower the terrain along a path to a thalweg profile: ``z[j, i] = min(z, profile)`` at
    each path cell, and within ``half_width_cells`` (Chebyshev) of it.  The profile is
    usually the true channel's elevation sampled at the model cells, made non-increasing
    downstream; cells already below it are untouched.  ``cells_ji`` and ``z_profile`` must
    be the same length."""
    out = np.array(z, copy=True)
    prof = np.asarray(z_profile, dtype=np.float64)
    ny, nx = out.shape
    h = int(half_width_cells)
    for (j, i), zt in zip(cells_ji, prof, strict=True):            # one profile value per path cell
        ja, jb = max(int(j) - h, 0), min(int(j) + h + 1, ny)
        ia, ib = max(int(i) - h, 0), min(int(i) + h + 1, nx)
        out[ja:jb, ia:ib] = np.minimum(out[ja:jb, ia:ib], zt)
    return out


def monotone_downstream(z_path: np.ndarray) -> np.ndarray:
    """The lowest non-increasing profile at or below ``z_path`` read upstream -> downstream
    (a running minimum): the thalweg a breach should carve so that no cell dams the one above."""
    return np.minimum.accumulate(np.asarray(z_path, dtype=np.float64))
