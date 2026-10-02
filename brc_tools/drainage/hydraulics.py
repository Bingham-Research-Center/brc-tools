"""A cold layer leaving a basin through a throat: how much can pass.

The pool is a layer of potential temperature ``dtheta`` below the air above it, so it
behaves like water under a reduced gravity ``g' = g * dtheta / theta0`` (a "1.5-layer"
model: the air above is deep and at rest).  Three capacities are computed for a throat
whose cross-section is known as area against interface level (``terrain.throat`` or
``terrain.profiles`` supply that from the DEM or from a model grid):

``critical_capacity``
    the inviscid maximum from a reservoir at rest: the flow passes through critical
    depth at the throat.  For a rectangular section this is the weir formula
    ``Q = (2/3)^1.5 * W * sqrt(g') * H^1.5``; here the section is arbitrary.

``drowned_capacity``
    the same throat when the pool downstream stands above the critical level (an orifice).

``backwater_capacity``
    a long canyon, where friction on the bed and at the interface -- not the throat --
    limits the flow: a standard-step profile from the exit upstream, reset to critical
    wherever it would fall below it, so the control section is found rather than assumed.

A real pool is continuously stratified, not a slab.  For a linearly stratified reservoir
drawn through a line opening the discharge per unit width scales as ``N * H^2`` with a
critical Froude number ``q / (N H^2)`` near ``1 / pi`` (selective withdrawal; published
values differ by tens of per cent), which is ``STRATIFIED_FACTOR`` times the layer value
for the same total buoyancy.  Carry both as a bracket; neither is a measurement.

Geometry-only measures (sill height, throat area, width in cells) need none of this and
are the firmer result; these capacities are upper bounds on what a MODEL carries, because
a model does not resolve a current through fewer than about five cells.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import G

WEIR = (2.0 / 3.0) ** 1.5                      # 0.544: rectangular critical flow, Q / (W sqrt(g') H^1.5)
STRATIFIED_FACTOR = (1.0 / np.pi) / WEIR       # 0.585: linear stratification against a slab of equal buoyancy


def reduced_gravity(dtheta_k: float, theta0_k: float = 270.0) -> float:
    """``g' = g * dtheta / theta0`` (m s-2) for a layer ``dtheta_k`` colder than the air above."""
    return G * float(dtheta_k) / float(theta0_k)


def _refine(stages, area, n: int = 400):
    stages = np.asarray(stages, dtype=np.float64)
    area = np.asarray(area, dtype=np.float64)
    if stages.ndim != 1 or stages.size != area.size or stages.size < 2 or np.any(np.diff(stages) <= 0):
        raise ValueError("stages must be increasing, with one area per stage")
    eta = np.linspace(stages[0], stages[-1], n)
    return eta, np.interp(eta, stages, area)


def critical_capacity(stages, area, energy, g_prime: float):
    """Largest discharge (m3 s-1) a throat passes from a reservoir whose surface is at
    ``energy`` (m, absolute; the pool is at rest there, so its level is the energy level).

    ``stages`` (increasing, absolute m) and ``area`` (m2) give the throat's cross-section
    below each interface level.  The discharge at interface level ``eta`` is
    ``A(eta) * sqrt(2 g' (energy - eta))``; the flow adopts the level that maximises it,
    which is the critical one.  Returns ``(Q, eta_c)``; arrays if ``energy`` is an array.
    A reservoir above the top stage is evaluated with the section held at its top value.
    """
    eta, a = _refine(stages, area)
    e = np.atleast_1d(np.asarray(energy, dtype=np.float64))
    head = np.maximum(e[:, None] - eta[None, :], 0.0)
    q = a[None, :] * np.sqrt(2.0 * g_prime * head)
    k = q.argmax(axis=1)
    qmax, eta_c = q[np.arange(e.size), k], eta[k]
    if np.ndim(energy) == 0:
        return float(qmax[0]), float(eta_c[0])
    return qmax, eta_c


def drowned_capacity(stages, area, energy, eta_down, g_prime: float) -> float:
    """Discharge through the throat when the downstream pool stands at ``eta_down``:
    free (critical) while ``eta_down`` is below the critical level, otherwise the orifice
    value ``A(eta_down) * sqrt(2 g' (energy - eta_down))``, zero once the pools are level."""
    q_free, eta_c = critical_capacity(stages, area, energy, g_prime)
    if eta_down is None or eta_down <= eta_c:
        return q_free
    if eta_down >= energy:
        return 0.0
    eta, a = _refine(stages, area)
    return float(np.interp(eta_down, eta, a) * np.sqrt(2.0 * g_prime * (energy - eta_down)))


def rating_curve(stages, area, energies, g_prime: float, *, factor: float = 1.0) -> np.ndarray:
    """``critical_capacity`` at each reservoir level, times a closure ``factor``
    (1 for a slab, ``STRATIFIED_FACTOR`` for a linearly stratified pool)."""
    q, _ = critical_capacity(stages, area, np.asarray(energies, dtype=np.float64), g_prime)
    return factor * q


@dataclass
class Reach:
    """Sections along a canyon, upstream (index 0) to downstream, each as functions of the
    interface level on a common set of stages (``terrain.profiles.SectionTable`` has exactly
    these arrays)."""

    s_m: np.ndarray            # (n,) along-channel position
    stages_m: np.ndarray       # (m,) absolute levels, increasing
    area_m2: np.ndarray        # (n, m)
    top_m: np.ndarray          # (n, m) interface width
    perimeter_m: np.ndarray    # (n, m) wetted bed perimeter

    def at(self, k: int, eta: float) -> tuple[float, float, float]:
        st = self.stages_m
        return (float(np.interp(eta, st, self.area_m2[k])), float(np.interp(eta, st, self.top_m[k])),
                float(np.interp(eta, st, self.perimeter_m[k])))

    def critical_level(self, k: int, q: float, g_prime: float) -> float:
        """Interface level at which section ``k`` carries ``q`` critically
        (``q^2 T = g' A^3``); the top stage if the section cannot carry it at all."""
        st = self.stages_m
        a, t = self.area_m2[k], np.maximum(self.top_m[k], 1e-9)
        f = g_prime * a ** 3 / t - q ** 2
        ok = np.flatnonzero(f >= 0)
        if ok.size == 0:
            return float(st[-1])
        j = int(ok[0])
        if j == 0:
            return float(st[0])
        return float(np.interp(0.0, [f[j - 1], f[j]], [st[j - 1], st[j]]))


def friction_slope(q: float, a: float, t: float, p: float, g_prime: float, cd: float, ci: float) -> float:
    """``S_f = u^2 (cd * P + ci * T) / (g' A)``: drag on the wetted bed (``cd``) and at the
    interface (``ci``, entrainment acting as drag) per unit weight of the layer."""
    if a <= 0.0:
        return np.inf
    u = q / a
    return u * u * (cd * p + ci * t) / (g_prime * a)


def backwater_energy(reach: Reach, q: float, g_prime: float, *, cd: float = 0.01, ci: float = 0.002,
                     eta_exit: float | None = None) -> tuple[float, np.ndarray, int]:
    """Reservoir level needed to push ``q`` through ``reach``: a standard-step profile from
    the exit upstream.

    At the exit the layer is critical (or at ``eta_exit`` if a downstream pool stands
    higher).  Moving upstream, each section's level solves
    ``eta + q^2/(2 g' A^2) = [same at the section below] + mean friction slope * ds`` on
    the subcritical branch; where the available energy is less than the section's own
    critical energy the section is a control and the level is reset to critical there.
    Returns ``(energy at the upstream end, level at every section, index of the controlling
    section -- the most upstream one that was critical)``.
    """
    n = reach.s_m.size
    st = reach.stages_m
    levels = np.zeros(n)
    k = n - 1
    eta = reach.critical_level(k, q, g_prime)
    if eta_exit is not None:
        eta = max(eta, float(eta_exit))
    a, t, p = reach.at(k, eta)
    h_dn = eta + q * q / (2.0 * g_prime * max(a, 1e-9) ** 2)
    sf_dn = friction_slope(q, a, t, p, g_prime, cd, ci)
    levels[k] = eta
    control = k
    for k in range(n - 2, -1, -1):
        ds = abs(float(reach.s_m[k + 1] - reach.s_m[k]))
        eta_c = reach.critical_level(k, q, g_prime)

        def resid(e, _k=k, _ds=ds, _h=h_dn, _sf=sf_dn):
            aa, tt, pp = reach.at(_k, e)
            if aa <= 0.0:
                return -np.inf
            return e + q * q / (2.0 * g_prime * aa * aa) - (_h + 0.5 * (friction_slope(q, aa, tt, pp, g_prime, cd, ci) + _sf) * _ds)

        if resid(eta_c) >= 0.0:                     # more energy at critical than is available: a control
            eta = eta_c
            control = k
        else:
            lo, hi = eta_c, float(st[-1])
            if resid(hi) < 0.0:                     # the section table is not tall enough: saturate
                eta = hi
            else:
                for _ in range(48):
                    mid = 0.5 * (lo + hi)
                    if resid(mid) >= 0.0:
                        hi = mid
                    else:
                        lo = mid
                eta = hi
        a, t, p = reach.at(k, eta)
        h_dn = eta + q * q / (2.0 * g_prime * max(a, 1e-9) ** 2)
        sf_dn = friction_slope(q, a, t, p, g_prime, cd, ci)
        levels[k] = eta
    return float(h_dn), levels, control


def backwater_capacity(reach: Reach, energy: float, g_prime: float, *, cd: float = 0.01, ci: float = 0.002,
                       eta_exit: float | None = None, q_max: float | None = None, tol: float = 1e-3) -> tuple[float, int]:
    """Discharge (m3 s-1) a reservoir at ``energy`` drives through a canyon with friction:
    the ``q`` whose ``backwater_energy`` equals ``energy`` (bisection).  Returns
    ``(q, control section index)``.  With ``cd = ci = 0`` it reduces to the smallest
    ``critical_capacity`` along the reach."""
    if q_max is None:
        q_max = min(critical_capacity(reach.stages_m, reach.area_m2[k], energy, g_prime)[0] for k in range(reach.s_m.size))
    if q_max <= 0.0:
        return 0.0, reach.s_m.size - 1
    e_top, _, ctl = backwater_energy(reach, q_max, g_prime, cd=cd, ci=ci, eta_exit=eta_exit)
    if e_top <= energy:
        return float(q_max), ctl
    lo, hi = 0.0, float(q_max)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        e_mid, _, ctl = backwater_energy(reach, mid, g_prime, cd=cd, ci=ci, eta_exit=eta_exit)
        if e_mid <= energy:
            lo = mid
        else:
            hi = mid
        if hi - lo <= tol * max(hi, 1.0):
            break
    _, _, ctl = backwater_energy(reach, lo, g_prime, cd=cd, ci=ci, eta_exit=eta_exit)
    return float(lo), ctl


def normal_depth_discharge(a: float, p: float, t: float, slope: float, g_prime: float, cd: float, ci: float = 0.0) -> float:
    """Uniform ("normal") flow in a section: ``Q = A * sqrt(g' A S / (cd P + ci T))`` --
    gravity along the bed against drag, the reduced-gravity Chezy formula."""
    if a <= 0.0 or slope <= 0.0:
        return 0.0
    return float(a * np.sqrt(g_prime * a * slope / (cd * p + ci * t)))
