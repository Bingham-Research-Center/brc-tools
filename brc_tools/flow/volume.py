"""Idealised fields in every cell of a terrain-following volume.

The closures of this package return displacements, pressures and amplitudes; a renderer
wants potential temperature and wind in every cell of every column.  This module composes
them under one stated picture -- a pool of cold air at rest under a uniform stratified
wind, the flow aloft seeing only the obstacle the caller hands it -- and nothing more:

``TwoLayerProfile``    the upstream potential temperature: N_pool below an inversion at
                       z_inv, a jump dtheta, N above.  ``aloft`` continued downward is the
                       pool-free reference atmosphere, against which a pool is a heat deficit.
``ridge_capped``       the obstacle the flow aloft sees: each ridge's own relief, cut at the lid
``planes_to_columns``  constant-height planes (``LinearWave.planes``) onto column heights
``pool_extent``        where the displaced lid holds pool air: run-up, draw-down, breakthrough
``compose_theta``      theta by labels: air aloft keeps the upstream isentrope it was lifted
                       from, pool air keeps its relative place in its column
``compose_winds``      the wind aloft as given; in the pool a depth-uniform current, w linear
                       from the bed (u . grad z_g) to the lid (d eta / dt)

Labels.  A parcel at height z displaced by eta came from z - eta upstream, so
theta = theta_bar(z - eta): the steady adiabatic statement, which keeps an inversion sharp
where the first-order form theta_bar(z) - eta d(theta_bar)/dz would smear it.  Inside a pool
of undisturbed depth D0 stretched to D, the label is z0 = z_g + (z - z_g) D0 / D, exact
for a column that stretches uniformly (the long-wave limit of ``seiche``).

Closure: everything the parts assume (linear waves, a rigid lid for the flow aloft, a
pool at rest or carried by long waves), plus one-way coupling -- the flow aloft does not
feel the lid move.  numpy; ``pool_extent`` needs scipy.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import G, THETA0


@dataclass(frozen=True)
class TwoLayerProfile:
    """Upstream potential temperature: ``N_pool`` below ``z_inv`` (m), a jump ``dtheta`` (K)
    at it, ``N`` above; ``theta_inv`` is theta just above the inversion.  ``theta0`` is
    the reference for g' and the lapse rates (the package's ``THETA0``)."""

    z_inv: float
    dtheta: float
    N: float
    N_pool: float
    theta_inv: float = THETA0
    theta0: float = THETA0
    g: float = G

    @property
    def gamma_aloft(self) -> float:
        """d(theta)/dz above the inversion, K m-1: theta0 N^2 / g."""
        return self.theta0 * self.N ** 2 / self.g

    @property
    def gamma_pool(self) -> float:
        return self.theta0 * self.N_pool ** 2 / self.g

    @property
    def gprime(self) -> float:
        return self.g * self.dtheta / self.theta0

    def aloft(self, z) -> np.ndarray:
        """The air above the inversion; continued below it, the pool-free reference."""
        return self.theta_inv + self.gamma_aloft * (np.asarray(z, dtype=float) - self.z_inv)

    def pool(self, z) -> np.ndarray:
        return self.theta_inv - self.dtheta + self.gamma_pool * (np.asarray(z, dtype=float) - self.z_inv)

    def __call__(self, z) -> np.ndarray:
        z = np.asarray(z, dtype=float)
        return np.where(z < self.z_inv, self.pool(z), self.aloft(z))


def ridge_capped(z, h_ridges, z_inv: float) -> np.ndarray:
    """The obstacle above a lid at ``z_inv``: min(max(z - z_inv, 0), h_ridges).

    ``h_ridges`` is the ridges' own relief above their fitted base (0 off the ridges).
    Where a ridge's base lies below the lid this is the terrain above the lid; where the
    base itself stands above the lid only the ridge is kept, so the obstacle falls to
    zero at the footprint's edge instead of ending in a wall (the terrain above the lid
    times a footprint mask makes such a wall, and the wall's spectrum rings)."""
    above = np.clip(np.asarray(z, dtype=float) - z_inv, 0.0, None)
    return np.minimum(above, np.clip(np.asarray(h_ridges, dtype=float), 0.0, None))


def planes_to_columns(planes: np.ndarray, zetas, zeta: np.ndarray) -> np.ndarray:
    """Linear interpolation of ``planes`` ``(n_planes, ny, nx)`` given at heights ``zetas``
    (increasing) onto per-cell heights ``zeta`` ``(nz, ny, nx)``, clamped at both ends."""
    planes = np.asarray(planes)
    zetas = np.asarray(zetas, dtype=float)
    zeta = np.asarray(zeta, dtype=float)
    if planes.shape[0] != zetas.size or planes.shape[1:] != zeta.shape[1:]:
        raise ValueError("planes must be (len(zetas),) + the horizontal shape of zeta")
    if zetas.size < 2 or np.any(np.diff(zetas) <= 0):
        raise ValueError("zetas must hold at least two increasing heights")
    zc = np.clip(zeta, zetas[0], zetas[-1])
    k = np.clip(np.searchsorted(zetas, zc, side="right") - 1, 0, zetas.size - 2)
    z0 = zetas[k]
    frac = (zc - z0) / (zetas[k + 1] - z0)
    lo = np.take_along_axis(planes, k, axis=0)
    hi = np.take_along_axis(planes, k + 1, axis=0)
    return lo + frac * (hi - lo)


def pool_extent(z_ground: np.ndarray, z_inv: float, eta: np.ndarray, pool0: np.ndarray, *,
                reach_cells: float, min_depth: float = 1.0):
    """Where a lid displaced by ``eta`` (m, finite on the undisturbed pool ``pool0``) holds
    pool air.

    The lid is carried up to ``reach_cells`` onto dry ground by the nearest pool value
    (run-up as it rises; the shoreline retreats as it falls).  A cell holds pool air where
    the lid stands more than ``min_depth`` above the ground and the cell is connected to
    the undisturbed pool.  Returns ``(z_lid, wet, broken)``: the lid height (NaN where
    dry), the wet mask, and the undisturbed pool cells now dry -- where the lid has reached
    the ground and linear theory has broken down."""
    from scipy import ndimage

    zg = np.asarray(z_ground, dtype=float)
    eta = np.asarray(eta, dtype=float)
    pool0 = np.asarray(pool0, dtype=bool)
    have = pool0 & np.isfinite(eta)
    if not have.any():
        raise ValueError("eta has no finite value on the pool")
    dist, (jj, ii) = ndimage.distance_transform_edt(~have, return_indices=True)
    z_lid = np.where(dist <= reach_cells, z_inv + eta[jj, ii], np.nan)
    candidate = np.isfinite(z_lid) & (z_lid > zg + min_depth)
    lab, _ = ndimage.label(candidate)
    keep = np.unique(lab[candidate & pool0])
    wet = np.isin(lab, keep[keep > 0])
    return np.where(wet, z_lid, np.nan), wet, pool0 & ~wet


def compose_theta(z: np.ndarray, z_ground: np.ndarray, z_lid: np.ndarray, wet: np.ndarray,
                  profile: TwoLayerProfile, eta_aloft: np.ndarray | None = None) -> np.ndarray:
    """Potential temperature (K) at heights ``z`` ``(nz, ny, nx)``.

    Pool air (a ``wet`` column, below ``z_lid``): theta = profile.pool(z0) with the label
    z0 = z_g + (z - z_g) D0 / D, D0 = max(z_inv - z_g, 0), D = z_lid - z_g; ground the lid
    has run up onto (D0 = 0) holds air from the top of the pool.  Everything else is air
    from aloft: theta = profile.aloft(max(z - eta_aloft, z_inv)), with ``eta_aloft``
    ``(nz, ny, nx)`` the displacement of the flow aloft at each cell (None: undisturbed).
    The floor at z_inv keeps air above the lid from taking a pool label where the lid has
    sunk below its undisturbed level."""
    z = np.asarray(z, dtype=float)
    zg = np.asarray(z_ground, dtype=float)[None]
    zl = np.asarray(z_lid, dtype=float)[None]
    label = z if eta_aloft is None else z - np.asarray(eta_aloft, dtype=float)
    theta = profile.aloft(np.maximum(label, profile.z_inv))
    with np.errstate(invalid="ignore"):
        in_pool = np.asarray(wet, dtype=bool)[None] & (z < zl)
    d0 = np.maximum(profile.z_inv - zg, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z0 = np.where(d0 > 0, zg + (z - zg) * d0 / (zl - zg), profile.z_inv)
    return np.where(in_pool, profile.pool(z0), theta)


def compose_winds(z: np.ndarray, z_ground: np.ndarray, z_lid: np.ndarray, wet: np.ndarray, *,
                  aloft=None, pool_uv=None, eta_rate=None, ground_grad=None):
    """(u, v, w) in m s-1 at heights ``z`` ``(nz, ny, nx)``.

    ``aloft`` is the full wind above the pool, a ``(u, v, w)`` triple of ``(nz, ny, nx)``
    arrays (None: calm).  In the pool (a ``wet`` column below ``z_lid``) the current
    ``pool_uv`` = ``(u, v)`` (each ``(ny, nx)``; None: at rest) is uniform in depth and w is
    linear in height from the kinematic value at the bed, u . grad z_g (``ground_grad`` =
    ``(dz_g/dx, dz_g/dy)``), to ``eta_rate`` = d(eta)/dt at the lid -- which is what
    continuity asks of a depth-uniform current."""
    z = np.asarray(z, dtype=float)
    shape2 = np.asarray(z_ground).shape
    if aloft is None:
        u = np.zeros(z.shape)
        v = np.zeros(z.shape)
        w = np.zeros(z.shape)
    else:
        u, v, w = (np.array(a, dtype=float) for a in aloft)
    zero = np.zeros(shape2)
    pu, pv = (zero, zero) if pool_uv is None else (np.nan_to_num(np.asarray(a, dtype=float)) for a in pool_uv)
    gx, gy = (zero, zero) if ground_grad is None else (np.asarray(a, dtype=float) for a in ground_grad)
    rate = zero if eta_rate is None else np.nan_to_num(np.asarray(eta_rate, dtype=float))
    zg = np.asarray(z_ground, dtype=float)[None]
    zl = np.asarray(z_lid, dtype=float)[None]
    with np.errstate(invalid="ignore"):
        in_pool = np.asarray(wet, dtype=bool)[None] & (z < zl)
    w_bed = pu * gx + pv * gy
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.clip(np.nan_to_num((z - zg) / (zl - zg)), 0.0, 1.0)
    w_pool = w_bed[None] + frac * (rate - w_bed)[None]
    return (np.where(in_pool, pu[None], u), np.where(in_pool, pv[None], v), np.where(in_pool, w_pool, w))
