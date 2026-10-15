"""A cold pool under a wind: how far the inversion moves, and whether it breaks through.

A pool that is at rest is hydrostatic: its interface sits where the pressure the flow
aloft puts on it is balanced by the weight of the cold air,

    eta = -p' / (rho0 g')                                        (``interface_displacement``)

so a 20 Pa mountain-wave pressure anomaly moves a 3 K inversion (g' = 0.1 m s-2) by
200 m.  That is why ridge-top pressure waves matter to pools when they would not matter
to the ground: g' is a hundredth of g.

The interface is also a lower boundary for the flow aloft, and it gives way.  In 2-D
hydrostatic linear theory over a stagnant pool the flow sees the terrain that protrudes
above the inversion, h_out, plus the interface's own displacement; with the boundary
pressure p-hat = rho0 Z zeta-hat (Z = i U N sgn k):

    zeta-hat = h_out-hat / (1 + Z / g'),     eta-hat = -(Z / g') zeta-hat

(``soft_boundary_2d``).  One number sets how soft the pool is:

    Gamma = U N / g'                                             (``interaction_number``)

Gamma << 1: the pool is stiff, the flow goes over the islands and the pool barely moves.
Gamma >> 1: the interface takes up the terrain, the flow aloft sees a flat boundary and
the pool sags under the lee waves.  The pool breaks (the inversion touches down, the lee
floor is swept) where -eta exceeds the local pool depth (``breakthrough``).

Pool tilt under a steady surface stress, from limnology: the Wedderburn number
W = g' H^2 / (u*^2 L); W < 1 means the interface surfaces at the upwind end (Thompson &
Imberger 1980; used for valley cold pools by Lareau & Horel 2015).

Closure: linear, hydrostatic, stagnant pool, uniform U and N aloft, the pool interface
present everywhere along the transect (so islands are approximated as terrain standing
on the interface).
"""
from __future__ import annotations

import numpy as np

from . import RHO0


def interface_displacement(p_pa, gprime: float, rho0: float = RHO0):
    return -np.asarray(p_pa, dtype=float) / (rho0 * gprime)


def interaction_number(U: float, N: float, gprime: float) -> float:
    return U * N / gprime


def wedderburn(gprime: float, H: float, ustar: float, L: float) -> float:
    return gprime * H ** 2 / (ustar ** 2 * L)


def pool_froude(U: float, gprime: float, H: float) -> float:
    return U / np.sqrt(gprime * H)


def soft_boundary_2d(h_out: np.ndarray, dx: float, U: float, N: float, gprime: float, *, pad: int = 4,
                     rho0: float = RHO0) -> dict[str, np.ndarray]:
    """Hydrostatic 2-D response of a stagnant pool and the flow aloft to the terrain that
    protrudes above the inversion.  Returns ``zeta`` (effective boundary seen aloft, m),
    ``eta`` (interface displacement, m, negative = pushed down), ``p`` (Pa at the
    boundary) and ``p_rigid`` (Pa if the interface were rigid)."""
    h = np.asarray(h_out, dtype=float)
    nx = h.size
    px = nx * pad
    hp = np.zeros(px)
    hp[:nx] = h
    k = 2.0 * np.pi * np.fft.fftfreq(px, d=dx)
    Z = 1j * U * N * np.sign(k)
    h_hat = np.fft.fft(hp)
    zeta_hat = h_hat / (1.0 + Z / gprime)
    eta_hat = -(Z / gprime) * zeta_hat           # Z(0) = 0: the mean level is not a wave
    back = lambda a: np.fft.ifft(a).real[:nx]   # noqa: E731
    return {"zeta": back(zeta_hat), "eta": back(eta_hat), "p": back(rho0 * Z * zeta_hat),
            "p_rigid": back(rho0 * Z * h_hat)}


def breakthrough(eta: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """True where the interface is pushed down by more than the pool is deep."""
    return (-np.asarray(eta)) >= np.asarray(depth)
