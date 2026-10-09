"""Trapped lee waves: when a ridge's lee waves stay near the ground, and how long they are.

A wave of horizontal wavenumber k is trapped in a lower layer of depth H when it
propagates there (k < l1, l = N / U the Scorer parameter) and decays above (k > l2).
Steady waves (phase speed 0) exist at the k that satisfy the vertical structure with
w = 0 at the ground, decay aloft and, at the top of the lower layer, the jump condition
for an inversion of reduced gravity g':

    U^2 (w'_below - w'_above) = g' w
    =>  m1 cot(m1 H) + mu2 = g' / U^2,      m1 = sqrt(l1^2 - k^2),  mu2 = sqrt(k^2 - l2^2)

(``dispersion``).  Two classic limits:

* Scorer (1949), no inversion: tan(m1 H) = -m1 / mu2.  A mode exists only if
  l1^2 - l2^2 > pi^2 / (4 H^2)                                 (``scorer_trapping``)
* Vosper (2004), a neutral layer under an inversion with stable air above (l1 = 0):
  k H coth(k H) + sqrt((kH)^2 - (l2 H)^2) = 1 / Fi^2,  Fi = U / sqrt(g' H).
  A mode exists only if Fi^2 < 1 / (l2 H coth(l2 H))  -- roughly Fi < 1.

The lee-wave length is 2 pi / k.  Closure: linear, uniform U, layers of constant N; the
first (longest) mode is the one a ridge excites most when its half-width is near 1/k.
"""
from __future__ import annotations

import numpy as np

from . import G, THETA0


def scorer_trapping(N1: float, N2: float, U: float, H: float) -> float:
    """(l1^2 - l2^2) / (pi^2 / 4 H^2): above 1, the two-layer atmosphere traps a mode."""
    return ((N1 / U) ** 2 - (N2 / U) ** 2) * 4.0 * H ** 2 / np.pi ** 2


def vosper_trapping(Fi: float, l2H: float) -> bool:
    """True if a neutral layer under an inversion (Froude number Fi) traps a mode."""
    x = max(l2H, 1e-9)
    return Fi ** 2 < 1.0 / (x / np.tanh(x))


def gprime(jump_k: float, theta0: float = THETA0, g: float = G) -> float:
    return g * jump_k / theta0


def _structure(k, U, N1, N2, H, gp):
    """cos(m1 H) + (mu2 - g'/U^2) sin(m1 H) / m1, real for real k > l2: zero at a mode,
    and free of the poles of cot."""
    k = np.asarray(k, dtype=float)
    l1, l2 = N1 / U, N2 / U
    mu2 = np.sqrt(np.maximum(k ** 2 - l2 ** 2, 0.0))
    s = k ** 2 - l1 ** 2
    out = np.empty_like(k)
    prop = s < 0
    m1 = np.sqrt(-s[prop])
    out[prop] = np.cos(m1 * H) + (mu2[prop] - gp / U ** 2) * np.where(m1 > 0, np.sin(m1 * H) / np.where(m1 > 0, m1, 1), H)
    ev = ~prop
    kap = np.sqrt(s[ev])
    with np.errstate(over="ignore", invalid="ignore"):
        sh = np.where(kap > 0, np.sinh(kap * H) / np.where(kap > 0, kap, 1), H)
        out[ev] = np.cosh(kap * H) + (mu2[ev] - gp / U ** 2) * sh
        out[ev] /= np.cosh(np.minimum(kap * H, 700))           # scale; zeros unchanged
    return out


def dispersion(k, U: float, N1: float, N2: float, H: float, jump_k: float = 0.0):
    """The trapped-mode function: zero at a steady trapped wave of wavenumber ``k``."""
    return _structure(k, U, N1, N2, H, gprime(jump_k))


def trapped_wavelengths(U: float, N1: float, N2: float, H: float, jump_k: float = 0.0, *,
                        k_max: float | None = None, n: int = 4000) -> np.ndarray:
    """Wavelengths (m) of every steady trapped mode, longest first; empty if none.
    ``k_max`` defaults to 40 / H (modes shorter than ~H/6 are irrelevant to a ridge)."""
    l2 = N2 / U
    k_max = 40.0 / H if k_max is None else k_max
    k = np.linspace(l2 * (1 + 1e-9) + 1e-12, k_max, n)
    f = dispersion(k, U, N1, N2, H, jump_k)
    roots = []
    for i in np.nonzero(np.sign(f[:-1]) != np.sign(f[1:]))[0]:
        a, b = k[i], k[i + 1]
        fa = f[i]
        for _ in range(80):
            c = 0.5 * (a + b)
            fc = dispersion(np.array([c]), U, N1, N2, H, jump_k)[0]
            if np.sign(fc) == np.sign(fa):
                a, fa = c, fc
            else:
                b = c
        roots.append(0.5 * (a + b))
    return np.sort(2.0 * np.pi / np.array(roots))[::-1] if roots else np.array([])
