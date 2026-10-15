"""An observed or analysed profile as the layers the closures take.

A sounding or an analysis column gives theta(z) and (u, v)(z); the wave and hydraulic
closures want a few numbers: the wind along the cross-barrier line, a lower layer of
buoyancy frequency N1 under an inversion of jump dtheta at z_inv, N2 above.  This module
does that reduction and nothing else -- it is a fit, and ``two_layer_fit`` returns the
residual so the caller can say how good a two-layer picture of that profile is.

Conventions: heights in m, theta in K, winds in m s-1; ``from_deg`` is the direction the
wind blows FROM (meteorological), so the along-wind component of a wind that blows
exactly from ``from_deg`` is its speed.
"""
from __future__ import annotations

import numpy as np

from .mountainwave import Layer
from . import G, THETA0


def along_wind(u, v, from_deg: float) -> np.ndarray:
    """Component of (u, v) along the wind that blows from ``from_deg``: positive with it."""
    r = np.radians(from_deg)
    return -(np.asarray(u, dtype=float) * np.sin(r) + np.asarray(v, dtype=float) * np.cos(r))


def brunt_vaisala(z, theta, z0: float, z1: float, *, g: float = G) -> float:
    """N (s-1) from the least-squares slope of theta over z0 <= z <= z1; NaN if the slope
    is negative or fewer than two levels fall in the band."""
    z = np.asarray(z, dtype=float)
    th = np.asarray(theta, dtype=float)
    sel = (z >= z0) & (z <= z1) & np.isfinite(th)
    if sel.sum() < 2:
        return float("nan")
    slope = np.polyfit(z[sel], th[sel], 1)[0]
    return float(np.sqrt(g * slope / th[sel].mean())) if slope > 0 else float("nan")


def two_layer_fit(z, theta, *, z_top: float, z_bottom: float = 0.0, min_layer: float = 200.0,
                  g: float = G) -> dict[str, float]:
    """Fit theta(z) between ``z_bottom`` and ``z_top`` by two straight lines with a jump
    between them, the jump placed at each sample level in turn and the best (least
    squares) kept.  Returns ``z_inv`` (m), ``dtheta`` (K, >= 0), ``N_below``, ``N_above``
    (s-1), ``theta_inv`` (K, just above the jump), ``rms_K`` (the fit's residual) and
    ``rms_one_K`` (one line through the whole band, for comparison).  Each layer must
    hold at least ``min_layer`` m and two samples."""
    z = np.asarray(z, dtype=float)
    th = np.asarray(theta, dtype=float)
    sel = (z >= z_bottom) & (z <= z_top) & np.isfinite(th) & np.isfinite(z)
    z, th = z[sel], th[sel]
    order = np.argsort(z)
    z, th = z[order], th[order]
    if z.size < 4:
        raise ValueError("need at least four levels in the band")
    one = np.polyfit(z, th, 1)
    rms_one = float(np.sqrt(np.mean((np.polyval(one, z) - th) ** 2)))
    best = None
    for i in range(1, z.size - 1):
        zi = 0.5 * (z[i - 1] + z[i])                     # the jump between samples i-1 and i
        lo, hi = z < zi, z >= zi
        if lo.sum() < 2 or hi.sum() < 2 or zi - z[0] < min_layer or z[-1] - zi < min_layer:
            continue
        pl, ph = np.polyfit(z[lo], th[lo], 1), np.polyfit(z[hi], th[hi], 1)
        if pl[0] < 0 or ph[0] < 0:
            continue
        resid = np.concatenate([np.polyval(pl, z[lo]) - th[lo], np.polyval(ph, z[hi]) - th[hi]])
        rms = float(np.sqrt(np.mean(resid ** 2)))
        jump = float(np.polyval(ph, zi) - np.polyval(pl, zi))
        if jump < 0:
            continue
        if best is None or rms < best["rms_K"]:
            best = {"z_inv": float(zi), "dtheta": jump,
                    "N_below": float(np.sqrt(g * pl[0] / th[lo].mean())),
                    "N_above": float(np.sqrt(g * ph[0] / th[hi].mean())),
                    "theta_inv": float(np.polyval(ph, zi)), "rms_K": rms, "rms_one_K": rms_one}
    if best is None:
        raise ValueError("no two-layer fit with non-negative slopes and a non-negative jump")
    return best


def layer_stack(fit: dict[str, float], z_base: float) -> list[Layer]:
    """The ``layers`` argument of ``layered_2d`` / ``layered_3d`` from a ``two_layer_fit``,
    heights measured from the model's flat base ``z_base`` (m ASL)."""
    return [Layer(top=float(fit["z_inv"]) - z_base, N=float(fit["N_below"])),
            Layer(top=np.inf, N=float(fit["N_above"]), jump=float(fit["dtheta"]))]
