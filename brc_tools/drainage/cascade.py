"""Basins joined by throats, filling and spilling through a night.

A "basin-wide cold pool" is, on real terrain, a chain of basins: each collects the cold
air its own slopes produce, fills, and leaks through whatever throat leads to the next.
This module integrates that picture as a small system of reservoirs.

Each ``Node`` is a basin with its hypsometry (the elevations of the cells of its local
catchment), an exit throat given as area against stage on some terrain, and the node its
outflow enters.  The state of a node is its pool VOLUME and its HEAT DEFICIT, so the
pool's temperature deficit ``dtheta = D / (rho cp V)`` is an outcome, not a constant:

    dV/dt = eff * P_slope / (rho cp dtheta_in) + sum(Q_in) - Q_out
    dD/dt = eff * P_slope + P_pool + sum(rho cp dtheta_up Q_in) - rho cp dtheta Q_out

``P_slope`` is the cooling over the part of the catchment above the pool top (terrain
the pool has drowned no longer feeds it), ``P_pool`` the cooling of the surface under the
pool (it chills the pool without adding volume), ``eff`` the fraction of the slope
cooling that reaches the pool as a drainage current rather than staying as an inversion
in place, and ``Q_out`` the throat's capacity for the pool's own reduced gravity
(``hydraulics.drowned_capacity``), so a pool backing up from below throttles the one
above it.

Everything is a stated assumption -- most of all ``eff`` and ``dtheta_in``, which the
terrain cannot supply.  Run it over their brackets, and run it twice with the throat
curves of the true terrain and of a model grid: the difference is what grid spacing
does to the answer.  numpy only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import CP, G
from .hydraulics import drowned_capacity


@dataclass
class Node:
    """One basin."""

    name: str
    z_cells: np.ndarray                 # elevations (m) of the cells of the local catchment
    cell_area_m2: float
    throat_stage_m: np.ndarray          # absolute stages at which the exit throat's area is given
    throat_area_m2: np.ndarray
    downstream: str | None = None       # the node the outflow enters; None = leaves the system
    closure_factor: float = 1.0         # hydraulics.STRATIFIED_FACTOR for a stratified pool
    v0_m3: float = 0.0
    d0_j: float = 0.0
    _z: np.ndarray = field(init=False, repr=False)
    _csum: np.ndarray = field(init=False, repr=False)
    _v_at: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        z = np.sort(np.asarray(self.z_cells, dtype=np.float64).ravel())
        z = z[np.isfinite(z)]
        if z.size == 0:
            raise ValueError(f"node {self.name}: no cells")
        self._z = z
        self._csum = np.concatenate([[0.0], np.cumsum(z)])
        k = np.arange(1, z.size + 1)
        self._v_at = (z * (k - 1) - self._csum[:-1]) * self.cell_area_m2

    @property
    def floor_m(self) -> float:
        return float(self._z[0])

    @property
    def area_m2(self) -> float:
        return float(self._z.size * self.cell_area_m2)

    def stage(self, volume_m3: float) -> float:
        """Level top (m) of a pool of this volume."""
        if volume_m3 <= 0.0:
            return self.floor_m
        n = int(np.clip(np.searchsorted(self._v_at, volume_m3, side="right"), 1, self._z.size))
        return float((volume_m3 / self.cell_area_m2 + self._csum[n]) / n)

    def flooded_area(self, stage_m: float) -> float:
        return float(np.searchsorted(self._z, stage_m, side="left") * self.cell_area_m2)

    def volume(self, stage_m: float) -> float:
        k = int(np.searchsorted(self._z, stage_m, side="left"))
        return float((stage_m * k - self._csum[k]) * self.cell_area_m2)


@dataclass(frozen=True)
class CascadeParams:
    efficiency: float = 0.5             # share of slope cooling delivered to the pool as a current
    dtheta_in_k: float = 5.0            # deficit of the arriving drainage air
    theta0_k: float = 270.0
    rho: float = 1.0
    day_loss: float = 0.5               # share of a pool's deficit the day removes (1 = gone by sunset)
    min_dtheta_k: float = 0.2           # floor on the pool deficit used for g' (a pool cannot drain itself warm)


@dataclass
class CascadeResult:
    t_s: np.ndarray                     # (nt,)
    names: list[str]
    stage_m: np.ndarray                 # (nt, n_node)
    volume_m3: np.ndarray
    deficit_j: np.ndarray
    dtheta_k: np.ndarray
    q_out_m3s: np.ndarray
    phi_out_w: np.ndarray               # heat-deficit flux leaving through the exit throat
    supply_w: np.ndarray                # eff * P_slope + P_pool

    def column(self, name: str) -> int:
        return self.names.index(name)

    def first_outflow_s(self, name: str, q_min: float = 1.0) -> float:
        """Time of the first outflow above ``q_min`` m3 s-1 (NaN if never)."""
        k = self.column(name)
        hit = np.flatnonzero(self.q_out_m3s[:, k] > q_min)
        return float(self.t_s[hit[0]]) if hit.size else float("nan")

    def delivered_j(self, name: str) -> float:
        """Heat deficit that left ``name`` through its exit over the run."""
        k = self.column(name)
        return float(np.trapezoid(self.phi_out_w[:, k], self.t_s))


def _order(nodes: list[Node]) -> list[int]:
    """Indices upstream-first (a node after everything that drains into it)."""
    idx = {n.name: i for i, n in enumerate(nodes)}
    depth = {}

    def d(i, seen=()):
        if i in depth:
            return depth[i]
        down = nodes[i].downstream
        if down is None or down not in idx:
            depth[i] = 0
        else:
            if idx[down] in seen:
                raise ValueError("the cascade has a cycle")
            depth[i] = 1 + d(idx[down], seen + (i,))
        return depth[i]

    return sorted(range(len(nodes)), key=lambda i: -d(i))


def integrate(nodes: list[Node], s_slope_w_m2: dict[str, np.ndarray], s_pool_w_m2: dict[str, np.ndarray],
              t_forcing_s: np.ndarray, params: CascadeParams = CascadeParams(), *, dt: float = 60.0,
              is_day=None, record_every: int = 5) -> CascadeResult:
    """Integrate the cascade over ``t_forcing_s`` (seconds, increasing).

    ``s_slope_w_m2[name]`` and ``s_pool_w_m2[name]`` are the cooling rates (W m-2, the air's
    loss to the surface) over each node's slopes and under its pool at the forcing times;
    they are interpolated linearly.  ``is_day(t)`` (optional, t in seconds) marks the hours
    in which a pool decays: at the rate that leaves ``1 - day_loss`` of it after a day
    of ``is_day`` hours (10 h assumed).  Explicit Euler with step ``dt``; the outflow of a
    step is capped at the volume present.
    """
    p = params
    idx = {n.name: i for i, n in enumerate(nodes)}
    order = _order(nodes)
    nn = len(nodes)
    t0, t1 = float(t_forcing_s[0]), float(t_forcing_s[-1])
    nstep = int(round((t1 - t0) / dt))
    v = np.array([n.v0_m3 for n in nodes], dtype=np.float64)
    d = np.array([n.d0_j for n in nodes], dtype=np.float64)
    rcp = p.rho * CP
    decay = 0.0 if p.day_loss <= 0.0 else (-np.log(max(1.0 - p.day_loss, 1e-6)) / (10.0 * 3600.0))
    rec_t, rec = [], {k: [] for k in ("stage", "vol", "def", "dth", "q", "phi", "sup")}
    for step in range(nstep + 1):
        t = t0 + step * dt
        stage = np.array([nodes[i].stage(v[i]) for i in range(nn)])
        dth = np.where(v > 0.0, d / np.maximum(rcp * v, 1e-9), p.dtheta_in_k)
        q = np.zeros(nn)
        phi = np.zeros(nn)
        sup = np.zeros(nn)
        dv = np.zeros(nn)
        dd = np.zeros(nn)
        for i in order:
            n = nodes[i]
            ss = float(np.interp(t, t_forcing_s, s_slope_w_m2[n.name]))
            sp = float(np.interp(t, t_forcing_s, s_pool_w_m2[n.name]))
            wet = n.flooded_area(stage[i])
            p_slope = p.efficiency * max(ss, 0.0) * (n.area_m2 - wet)
            p_pool = max(sp, 0.0) * wet
            sup[i] = p_slope + p_pool
            dv[i] += p_slope / (rcp * p.dtheta_in_k)
            dd[i] += p_slope + p_pool
            if v[i] > 0.0:
                gp = G * max(dth[i], p.min_dtheta_k) / p.theta0_k
                eta_down = stage[idx[n.downstream]] if (n.downstream in idx and v[idx[n.downstream]] > 0.0) else None
                qi = n.closure_factor * drowned_capacity(n.throat_stage_m, n.throat_area_m2, stage[i], eta_down, gp)
                qi = min(qi, v[i] / dt)
                q[i] = qi
                phi[i] = rcp * dth[i] * qi
                dv[i] -= qi
                dd[i] -= phi[i]
                if n.downstream in idx:
                    j = idx[n.downstream]
                    dv[j] += qi
                    dd[j] += phi[i]
        if step % record_every == 0:
            rec_t.append(t)
            for key, arr in (("stage", stage), ("vol", v), ("def", d), ("dth", np.where(v > 0, dth, 0.0)),
                             ("q", q), ("phi", phi), ("sup", sup)):
                rec[key].append(arr.copy())
        v = np.maximum(v + dv * dt, 0.0)
        d = np.maximum(d + dd * dt, 0.0)
        if decay and is_day is not None and is_day(t):
            f = np.exp(-decay * dt)
            v *= f
            d *= f
        d = np.where(v > 0.0, d, 0.0)
    out = {k: np.asarray(a) for k, a in rec.items()}
    return CascadeResult(t_s=np.asarray(rec_t), names=[n.name for n in nodes], stage_m=out["stage"], volume_m3=out["vol"],
                         deficit_j=out["def"], dtheta_k=out["dth"], q_out_m3s=out["q"], phi_out_w=out["phi"],
                         supply_w=out["sup"])
