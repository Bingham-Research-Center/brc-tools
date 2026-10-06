"""Slope flows and the pool they feed: closed-form scalings.

``prandtl_*``
    Prandtl's (1942) one-dimensional solution for flow on a uniformly cooled slope in a
    stratified atmosphere with constant eddy diffusivities.  Its jet sits a few metres
    above the ground on steep slopes -- which is what decides whether a model's lowest
    level is inside the jet or above it.

``equilibrium_speed``
    a bulk drainage layer in balance between along-slope buoyancy and drag (bed plus
    interfacial entrainment): the layer-averaged model of Manins & Sawford (1979).
    Its Froude number depends only on the slope and the drag, so a thalweg can be
    mapped into super- and subcritical reaches from the terrain alone.

``froude_*``, ``pool_tilt``
    the three Froude numbers that get confused (mountain, layer, densimetric), and the
    slope a pool's top takes under a geostrophic wind aloft (Margules).

numpy only.  Every function is a scaling: the diffusivities, drag coefficients and
deficits are arguments because they are the assumptions.
"""
from __future__ import annotations

import numpy as np

from . import G, OMEGA


def brunt_vaisala(dtheta_dz_k_per_m, theta0_k: float = 270.0):
    """N (s-1) from a potential-temperature gradient."""
    return np.sqrt(G / theta0_k * np.asarray(dtheta_dz_k_per_m, dtype=float))


def prandtl_length(alpha_deg, n_bv: float, k_m: float = 0.1, k_h: float | None = None):
    """Prandtl's slope-normal length scale ``l = (4 K_m K_h / (N^2 sin^2 alpha))^(1/4)`` (m)."""
    k_h = k_m if k_h is None else k_h
    s = np.sin(np.radians(np.asarray(alpha_deg, dtype=float)))
    return (4.0 * k_m * k_h / (n_bv ** 2 * s ** 2)) ** 0.25


def prandtl_jet_height(alpha_deg, n_bv: float, k_m: float = 0.1, k_h: float | None = None):
    """Height of the wind maximum above the slope: ``(pi / 4) * l``.  It thins as the slope
    steepens (``~ sin(alpha)^-1/2``): about 6 m on a 10 degree wall and 11 m on a 3 degree
    one for K = 0.1 m2 s-1 and N = 0.02 s-1."""
    return 0.25 * np.pi * prandtl_length(alpha_deg, n_bv, k_m, k_h)


def prandtl_jet_speed(surface_deficit_k: float, n_bv: float, theta0_k: float = 270.0, prandtl_number: float = 1.0) -> float:
    """Jet maximum ``0.322 * C * mu`` with ``mu = g / (theta0 N sqrt(Pr))`` for a surface
    potential-temperature deficit ``C`` (K).  It does not depend on the slope angle."""
    mu = G / (theta0_k * n_bv * np.sqrt(prandtl_number))
    return float(np.exp(-np.pi / 4.0) * np.sin(np.pi / 4.0) * abs(surface_deficit_k) * mu)


def prandtl_profile(z_n, surface_deficit_k: float, alpha_deg: float, n_bv: float, *, k_m: float = 0.1,
                    k_h: float | None = None, theta0_k: float = 270.0):
    """Down-slope wind ``u(n)`` (m s-1, positive down-slope) and potential-temperature
    perturbation ``theta'(n)`` (K, negative) at slope-normal heights ``z_n`` (m)."""
    k_h = k_m if k_h is None else k_h
    l = prandtl_length(alpha_deg, n_bv, k_m, k_h)
    mu = G / (theta0_k * n_bv) * np.sqrt(k_h / k_m)
    n = np.asarray(z_n, dtype=float) / l
    c = abs(surface_deficit_k)
    return c * mu * np.exp(-n) * np.sin(n), -c * np.exp(-n) * np.cos(n)


def entrainment_power_law(alpha_deg, coeff: float = 0.05, power: float = 2.0 / 3.0):
    """Interfacial entrainment coefficient of a drainage layer as a power law of the slope,
    ``coeff * sin(alpha)^power``.  The default is the form used in the drainage-flow
    literature following Briggs (1981); it is an ASSUMPTION here -- the entrainment into a
    stable current is uncertain by a factor of several, so bracket it."""
    return coeff * np.sin(np.radians(np.asarray(alpha_deg, dtype=float))) ** power


def equilibrium_speed(g_prime: float, depth_m, alpha_deg, cd: float = 0.005, entrainment=None):
    """Layer-mean speed of a drainage current in balance on a slope:
    ``U = sqrt(g' h sin(alpha) / (cd + E))`` -- along-slope buoyancy against bed drag and
    entrainment, the steady layer-averaged balance (after Manins & Sawford 1979 with the
    storage and advection terms dropped).  ``entrainment`` defaults to
    ``entrainment_power_law``; pass 0 for bed drag alone."""
    e = entrainment_power_law(alpha_deg) if entrainment is None else entrainment
    s = np.sin(np.radians(np.asarray(alpha_deg, dtype=float)))
    return np.sqrt(g_prime * np.asarray(depth_m, dtype=float) * s / (cd + e))


def equilibrium_froude(alpha_deg, cd: float = 0.005, entrainment=None):
    """Froude number of that balance, ``sqrt(tan(alpha) / (cd + E))`` -- independent of depth
    and deficit, so criticality along a thalweg follows from its slope and the drag."""
    e = entrainment_power_law(alpha_deg) if entrainment is None else entrainment
    return np.sqrt(np.tan(np.radians(np.asarray(alpha_deg, dtype=float))) / (cd + e))


def critical_slope_deg(cd: float = 0.005, entrainment=None, n_iter: int = 60) -> float:
    """The slope at which the equilibrium current is exactly critical (``tan(alpha) = cd + E``):
    steeper reaches run supercritical, gentler ones subcritical.  ``entrainment`` as in
    ``equilibrium_froude`` (a constant, or None for the power law)."""
    lo, hi = 1e-4, 30.0
    for _ in range(n_iter):
        mid = 0.5 * (lo + hi)
        if equilibrium_froude(mid, cd, entrainment) > 1.0:
            hi = mid
        else:
            lo = mid
    return float(0.5 * (lo + hi))


def travel_time_s(dist_m, speed_ms) -> float:
    """Time to traverse a path given the speed at each of its points (trapezoid on 1/U)."""
    d = np.asarray(dist_m, dtype=float)
    u = np.maximum(np.asarray(speed_ms, dtype=float), 1e-6)
    return float(np.sum(0.5 * (1.0 / u[1:] + 1.0 / u[:-1]) * np.abs(np.diff(d))))


def froude_mountain(speed_ms, n_bv, height_m):
    """``U / (N H)``: below about 1 the flow goes round an obstacle of height H, not over it."""
    return np.asarray(speed_ms, dtype=float) / (np.asarray(n_bv, dtype=float) * np.asarray(height_m, dtype=float))


def froude_layer(speed_ms, g_prime, depth_m):
    """``U / sqrt(g' h)``: 1 at a hydraulic control; a jump takes a current from above to below."""
    return np.asarray(speed_ms, dtype=float) / np.sqrt(g_prime * np.asarray(depth_m, dtype=float))


def coriolis(lat_deg: float) -> float:
    return float(2.0 * OMEGA * np.sin(np.radians(lat_deg)))


def geostrophic_pressure_gradient(speed_ms, lat_deg: float, rho: float = 1.0):
    """Pressure gradient (Pa m-1) that balances a geostrophic wind: ``rho f U``."""
    return rho * coriolis(lat_deg) * np.asarray(speed_ms, dtype=float)


def pool_tilt(speed_ms, lat_deg: float, g_prime: float):
    """Slope (m per m) of a pool's top under a geostrophic wind aloft, ``f U / g'``
    (Margules).  With the pool at rest, ``grad(h) = (f / g') k x U``: the top rises to the
    LEFT of the wind looking downwind (northern hemisphere), towards the lower pressure
    aloft -- under an easterly, towards the south.  7 m s-1 over a 5 K pool at 40 N tilts
    it about 3.6 m per km."""
    return coriolis(lat_deg) * np.asarray(speed_ms, dtype=float) / g_prime


def pool_head_pa(depth_m, g_prime: float, rho: float = 1.0):
    """Hydrostatic head of a cold layer, ``rho g' h`` (Pa): what a synoptic pressure
    difference across the basin is to be compared with."""
    return rho * g_prime * np.asarray(depth_m, dtype=float)
