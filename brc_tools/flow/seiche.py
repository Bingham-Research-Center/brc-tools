"""Free oscillations (seiches) of a cold pool.

A pool of depth H(x, y) under an inversion of reduced gravity g' is a shallow lake to
long internal waves of speed c = sqrt(g' H).  Its free modes solve

    omega^2 eta = -g' div( H grad eta )          (no flux through the shoreline)

the linear reduced-gravity shallow-water equations without rotation: the Rossby radius
c / f is ~80 km for c = 7 m s-1 at 40 N, several times any valley here (``rossby_radius``).
``basin_modes`` discretises this on a raster (five-point, face depth the mean of the two
wet neighbours, a face closed if either side is dry) and returns the slowest modes.
``merian_period`` is the closed-form check for a rectangle of uniform depth:
T = 2 L / (n c) between two walls, 4 L / ((2n - 1) c) with one end open.
"""
from __future__ import annotations

import numpy as np

from . import G


def wave_speed(gprime: float, H) -> np.ndarray:
    return np.sqrt(gprime * np.asarray(H, dtype=float))


def merian_period(L: float, H: float, gprime: float, mode: int = 1, ends: str = "closed") -> float:
    c = float(np.sqrt(gprime * H))
    if ends == "closed":
        return 2.0 * L / (mode * c)
    if ends == "open":
        return 4.0 * L / ((2 * mode - 1) * c)
    raise ValueError("ends must be 'closed' or 'open'")


def rossby_radius(gprime: float, H: float, lat_deg: float = 40.4) -> float:
    f = 2.0 * 7.2921e-5 * np.sin(np.radians(lat_deg))
    return float(np.sqrt(gprime * H) / f)


def basin_modes(depth: np.ndarray, dx: float, gprime: float, n_modes: int = 6, *, seed=None, open_mask=None):
    """The ``n_modes`` slowest seiche modes of the pool ``depth`` (m, NaN or <= 0 dry).

    Only the connected wet region containing ``seed`` (row, col) is solved -- the largest
    one if ``seed`` is None.  ``open_mask`` marks wet cells held at eta = 0: an open end
    where the pool spills into a much larger one (the node at Merian's open end).  Returns
    ``(periods_s, shapes)`` with ``shapes`` an ``(n_modes, ny, nx)`` array of interface
    displacement normalised to max |eta| = 1 and NaN outside the pool.
    """
    from scipy import ndimage, sparse
    from scipy.sparse.linalg import eigsh

    H = np.where(np.isfinite(depth) & (depth > 0), depth, 0.0).astype(float)
    lab, nlab = ndimage.label(H > 0)
    if nlab == 0:
        raise ValueError("no wet cells")
    if seed is None:
        keep = np.argmax(np.bincount(lab.ravel())[1:]) + 1
    else:
        keep = lab[seed]
        if keep == 0:
            raise ValueError("seed is dry")
    region = lab == keep
    held = np.zeros_like(region) if open_mask is None else (np.asarray(open_mask, dtype=bool) & region)
    wet = region & ~held
    idx = -np.ones(H.shape, dtype=np.int64)
    idx[wet] = np.arange(wet.sum())
    n = int(wet.sum())
    rows, cols, vals = [], [], []
    diag = np.zeros(n)
    c0 = gprime / dx ** 2
    for dj, di in ((0, 1), (1, 0)):
        a = wet[: H.shape[0] - dj, : H.shape[1] - di]
        b = wet[dj:, di:]
        both = a & b
        ia = idx[: H.shape[0] - dj, : H.shape[1] - di][both]
        ib = idx[dj:, di:][both]
        hf = 0.5 * (H[: H.shape[0] - dj, : H.shape[1] - di][both] + H[dj:, di:][both])
        wgt = c0 * hf
        rows += [ia, ib]
        cols += [ib, ia]
        vals += [-wgt, -wgt]
        np.add.at(diag, ia, wgt)
        np.add.at(diag, ib, wgt)
        # an unknown facing a held (eta = 0) cell drains through that face: diagonal only
        lo = (slice(0, H.shape[0] - dj), slice(0, H.shape[1] - di))
        hi = (slice(dj, None), slice(di, None))
        for side, other in ((lo, hi), (hi, lo)):
            face = wet[side] & held[other]
            np.add.at(diag, idx[side][face], c0 * 0.5 * (H[side][face] + H[other][face]))
    A = sparse.coo_matrix((np.concatenate(vals + [diag]),
                           (np.concatenate(rows + [np.arange(n)]), np.concatenate(cols + [np.arange(n)]))),
                          shape=(n, n)).tocsc()
    k = min(n_modes + 1, n - 2)
    shift = -1e-3 * float(diag.max()) / max(n, 1)
    w2, vec = eigsh(A, k=k, sigma=shift, which="LM")
    order = np.argsort(w2)
    w2, vec = w2[order], vec[:, order]
    keep_modes = w2 > 1e-10 * float(diag.max())        # drop the constant (volume) mode, if closed
    w2, vec = w2[keep_modes][:n_modes], vec[:, keep_modes][:, :n_modes]
    periods = 2.0 * np.pi / np.sqrt(w2)
    shapes = np.full((w2.size,) + H.shape, np.nan)
    for i in range(w2.size):
        v = vec[:, i] / np.max(np.abs(vec[:, i]))
        shapes[i][wet] = v
    return periods, shapes


def reduced_gravity(dtheta_k: float, theta0: float = 285.0, g: float = G) -> float:
    return g * dtheta_k / theta0
