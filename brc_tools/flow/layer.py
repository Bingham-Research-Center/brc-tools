"""One-layer reduced-gravity hydraulics over an obstacle.

A layer of depth D0 moving at U0 under a deep, passive layer that is lighter by g' -- the
air below a capping inversion, or a cold pool under the free atmosphere -- meets an
obstacle of height h.  Two numbers decide everything (Long 1954; Houghton & Kasahara
1968; Baines 1995, ch. 2):

    F0 = U0 / sqrt(g' D0)        upstream Froude number
    M  = h / D0                  obstacle height in layer depths

Nondimensionalise lengths by D0 and speeds by sqrt(g' D0).  Mass q = u d and Bernoulli
u^2/2 + d + b = const give, at a crest where the flow is critical (local Froude number 1,
d_c = q^(2/3)),

    M_c(F0) = 1 + F0^2/2 - (3/2) F0^(2/3)          (``critical_height``)

Below M_c the flow passes without a control: it thins over the crest if F0 < 1 and
thickens if F0 > 1, and the lee is a mirror of the windward side -- no windstorm.  At or
above M_c the crest becomes a hydraulic control: a bore runs upstream and deepens the
approach flow, the lee goes supercritical (a thin, fast jet down the lee slope: the
hydraulic analogue of a downslope windstorm), and the jet ends in a hydraulic jump.  For
F0 > 1 an upstream jump can stand still once M exceeds

    M_s(F0) = d1 [1 + F1^2/2 - (3/2) F1^(2/3)],  d1 = (sqrt(1 + 8 F0^2) - 1)/2,  F1 = F0 / d1^(3/2)

and between M_s and M_c both states are possible (hysteresis).

Closure: hydrostatic, inviscid, steady, uniform across the flow, a passive upper layer
(no interfacial stress).  Where it is wrong first: when the air above the inversion is
itself stratified (it then carries waves that feed back on the interface; Vosper 2004
found the hydraulic boundaries still hold to within ~20 % for strong inversions), and in
the jump, which dissipates energy the model cannot place.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def critical_height(F0):
    """M_c(F0): the smallest obstacle (in layer depths) that controls the flow."""
    F0 = np.asarray(F0, dtype=float)
    return 1.0 + 0.5 * F0 ** 2 - 1.5 * F0 ** (2.0 / 3.0)


def jump_ratio(F):
    """Depth ratio across a stationary hydraulic jump (Belanger): d_after / d_before."""
    F = np.asarray(F, dtype=float)
    return 0.5 * (np.sqrt(1.0 + 8.0 * F ** 2) - 1.0)


def stationary_jump_height(F0):
    """M_s(F0) for F0 > 1: an upstream jump can stand still with critical flow at the
    crest.  NaN for F0 <= 1."""
    F0 = np.asarray(F0, dtype=float)
    d1 = jump_ratio(F0)
    F1 = F0 / d1 ** 1.5
    out = d1 * critical_height(F1)
    return np.where(F0 > 1.0, out, np.nan)


def regime(F0: float, M: float) -> str:
    """'subcritical' | 'supercritical' | 'two states' | 'controlled'."""
    if M >= critical_height(F0):
        return "controlled"
    if F0 < 1.0:
        return "subcritical"
    if M < stationary_jump_height(F0):
        return "supercritical"
    return "two states"


def _bisect(f, a: float, b: float, n: int = 200) -> float:
    fa = f(a)
    for _ in range(n):
        c = 0.5 * (a + b)
        fc = f(c)
        if np.sign(fc) == np.sign(fa):
            a, fa = c, fc
        else:
            b = c
    return 0.5 * (a + b)


def lee_depth(q: float, E: float) -> float:
    """The supercritical depth with flux ``q`` and specific energy ``E`` (both
    nondimensional) at the foot of the obstacle: the root of q^2/(2 d^2) + d = E below
    the critical depth q^(2/3)."""
    dc = q ** (2.0 / 3.0)
    return _bisect(lambda d: q * q / (2 * d * d) + d - E, 1e-6 * dc, dc)


@dataclass(frozen=True)
class ControlledFlow:
    """A controlled (M >= M_c) state, nondimensional (lengths / D0, speeds / sqrt(g' D0))."""

    F0: float
    M: float
    d_up: float        # approach depth behind the upstream bore
    u_up: float        # approach speed behind the bore
    bore_speed: float  # speed of the bore against the ground, positive upstream
    q: float           # flux over the crest
    d_lee: float       # depth of the lee jet at the foot (before the jump)
    u_lee: float       # speed of the lee jet
    F_lee: float       # Froude number of the lee jet
    d_jump: float      # depth after the hydraulic jump that ends the jet

    @property
    def speedup(self) -> float:
        """Lee-jet speed over the undisturbed upstream speed."""
        return self.u_lee / self.F0 if self.F0 > 0 else np.inf


def controlled_flow(F0: float, M: float) -> ControlledFlow:
    """The steady state with critical flow at the crest when ``M >= critical_height(F0)``
    and F0 < 1 (or above M_c for F0 > 1): a bore of depth ratio r runs upstream, satisfying
    mass and momentum across it,

        (F0 + c) = sqrt(r (r + 1) / 2),   u_up = (F0 + c) / r - c,

    and r is chosen so that the deepened approach flow is exactly critical at the crest,
    M = r + u_up^2/2 - (3/2)(u_up r)^(2/3).  The lee depth is the supercritical conjugate
    of the same energy and flux at the foot."""
    if M < critical_height(F0):
        raise ValueError(f"M={M:.3f} is below M_c={critical_height(F0):.3f}: the flow is not controlled")

    def state(r):
        c = np.sqrt(r * (r + 1.0) / 2.0) - F0
        u = (F0 + c) / r - c
        return c, u

    def resid(r):
        c, u = state(r)
        q = max(u * r, 1e-12)
        return r + 0.5 * u * u - 1.5 * q ** (2.0 / 3.0) - M

    lo, hi = 1.0 + 1e-9, 2.0
    while resid(hi) < 0 and hi < 1e4:
        hi *= 2.0
    r = _bisect(resid, lo, hi) if resid(lo) < 0 else 1.0
    c, u = state(r)
    q = u * r
    E = 0.5 * u * u + r
    d_lee = lee_depth(q, E)
    u_lee = q / d_lee
    F_lee = u_lee / np.sqrt(d_lee)
    return ControlledFlow(F0=F0, M=M, d_up=r, u_up=u, bore_speed=c, q=q, d_lee=d_lee, u_lee=u_lee,
                          F_lee=F_lee, d_jump=d_lee * float(jump_ratio(F_lee)))


def crest_depth(F0: float, M: float) -> float:
    """Depth over the crest for an UNcontrolled flow (M < M_c): the root of
    F0^2/(2 d^2) + d + M = 1 + F0^2/2 on the same side of criticality as the approach."""
    dc = F0 ** (2.0 / 3.0)
    E = 1.0 + 0.5 * F0 ** 2 - M
    f = lambda d: F0 * F0 / (2 * d * d) + d - E   # noqa: E731
    return _bisect(f, dc, max(E, dc) + 1.0) if F0 < 1.0 else _bisect(f, 1e-6, dc)
