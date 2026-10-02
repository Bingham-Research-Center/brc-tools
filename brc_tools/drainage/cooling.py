"""Clear-night surface energy balance: how fast a surface draws heat out of the air.

Every patch of ground on a clear night loses longwave to the sky, takes some back from
the air touching it (the sensible flux -- the term a drainage flow runs on) and some
from the ground beneath.  ``solve_surface`` solves that balance for the surface
temperature and returns the fluxes, per cell, for arrays of air temperature, humidity,
sky-view factor and snow cover:

    eps * sigma * Ts^4 = L_down + H + G
    L_down = SVF * eps_clear(Ta, ea) * sigma * Ta^4 + (1 - SVF) * sigma * Ta^4
    H      = rho * cp * C_HN * f(Ri_b) * U * (Ta - Ts),   f = 1 / (1 + coef * Ri_b)
    G      = k * (T_base - Ts) / d

with the Prata (1996) clear-sky emissivity and the Louis (1979) stable damping.  The
constants are the assumptions: ``CoolingParams`` holds a central value for each, and the
two that dominate -- the slope-layer wind ``U`` and the neutral transfer coefficient
``C_HN`` -- have no default that can be defended to better than a factor of two, because
they stand for how strongly a stable surface layer stays coupled to the ground.

``open_water_flux`` is the companion for a lake that has not frozen: a bulk estimate of
the heat an open-water surface puts INTO the air on the same night.

numpy only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np

from . import CP, G, SIGMA


@dataclass(frozen=True)
class CoolingParams:
    """Constants of the surface balance (central values; bracket them, do not trust them)."""

    eps_snow: float = 0.98                  # snow emissivity
    eps_soil: float = 0.95                  # bare soil / short vegetation
    k_snow_W_m_K: float = 0.20              # seasonal-snow conductivity
    k_soil_W_m_K: float = 1.0
    d_soil_m: float = 0.20                  # damping depth of the nocturnal ground heat flux
    snow_min_depth_m: float = 0.10          # a thinner pack conducts like its base
    c_hn: float = 2.0e-3                    # neutral bulk transfer coefficient
    u_ms: float = 3.0                       # wind in the layer the surface exchanges with
    ri_coef: float = 10.0                   # stable damping 1 / (1 + coef * Ri_b)
    z_ref_m: float = 2.0                    # height of the bulk Richardson number
    rho: float = 1.0                        # air density (kg m-3) at Basin elevations

    def with_(self, **kw) -> CoolingParams:
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return asdict(self)


def vapour_pressure_hpa(td_k):
    """Saturation vapour pressure at the dew point (hPa; Bolton 1980)."""
    tc = np.asarray(td_k, dtype=float) - 273.15
    return 6.112 * np.exp(17.67 * tc / (tc + 243.5))


def prata_emissivity(t_a, e_hpa):
    """Clear-sky atmospheric emissivity from screen temperature (K) and vapour pressure
    (hPa): Prata (1996)."""
    w = 46.5 * np.asarray(e_hpa, dtype=float) / np.asarray(t_a, dtype=float)
    return 1.0 - (1.0 + w) * np.exp(-np.sqrt(1.2 + 3.0 * w))


def longwave_down(t_a, e_hpa, svf):
    """Downwelling longwave at a surface that sees a fraction ``svf`` of clear sky and
    terrain at air temperature in the rest (W m-2)."""
    t_a = np.asarray(t_a, dtype=float)
    return (svf * prata_emissivity(t_a, e_hpa) + (1.0 - svf)) * SIGMA * t_a ** 4


def solve_surface(t_a, e_hpa, svf, snow, snow_depth_m, t_base, params: CoolingParams = CoolingParams(), *,
                  wind_ms=None, ts0=None, n_iter: int = 12):
    """Newton solve of the surface energy balance for the surface temperature.

    Arrays (broadcastable): air temperature ``t_a`` (K), vapour pressure ``e_hpa``,
    sky-view factor ``svf``, bool ``snow`` cover, ``snow_depth_m``, and ``t_base`` (K),
    the temperature at the base of the pack or of the soil layer.  ``wind_ms`` (an array,
    e.g. an analysed 10 m wind) replaces the single ``params.u_ms``.  Returns
    ``(Ts, H, G, L_down, L_up)`` in K and W m-2, with ``H`` positive where the AIR loses
    heat to the surface.
    """
    p = params
    t_a = np.asarray(t_a, dtype=float)
    u = p.u_ms if wind_ms is None else np.asarray(wind_ms, dtype=float)
    eps_s = np.where(snow, p.eps_snow, p.eps_soil)
    k_over_d = np.where(snow, p.k_snow_W_m_K / np.maximum(snow_depth_m, p.snow_min_depth_m), p.k_soil_W_m_K / p.d_soil_m)
    l_down = longwave_down(t_a, e_hpa, svf)
    ts = (t_a - 5.0) if ts0 is None else np.array(ts0, dtype=float, copy=True)
    ch0 = p.rho * CP * p.c_hn * u
    for _ in range(n_iter):
        d_t = t_a - ts
        ri = np.clip(G / t_a * d_t * p.z_ref_m / u ** 2, 0.0, None)
        f = 1.0 / (1.0 + p.ri_coef * ri)
        h = ch0 * f * d_t
        g = k_over_d * (t_base - ts)
        resid = eps_s * SIGMA * ts ** 4 - l_down - h - g
        d_resid = 4.0 * eps_s * SIGMA * ts ** 3 + ch0 * f + k_over_d
        ts = ts - resid / d_resid
    d_t = t_a - ts
    ri = np.clip(G / t_a * d_t * p.z_ref_m / u ** 2, 0.0, None)
    h = ch0 * d_t / (1.0 + p.ri_coef * ri)
    g = k_over_d * (t_base - ts)
    return ts, h, g, l_down, eps_s * SIGMA * ts ** 4


def open_water_flux(t_water_k, t_air_k, e_air_hpa, wind_ms, *, pressure_hpa: float = 800.0, c_h: float = 1.5e-3,
                    c_e: float = 1.5e-3, rho: float = 1.0):
    """Bulk sensible and latent heat flux from open water into colder air (W m-2, positive
    upward): ``H = rho cp C_H U (Tw - Ta)``, ``LE = rho L_v C_E U (q_sat(Tw) - q_a)``.
    Neutral coefficients are used; over water much warmer than the air the layer is
    unstable and the true flux is larger, so this is a floor.  Returns ``(H, LE)``."""
    t_w, t_a = np.asarray(t_water_k, dtype=float), np.asarray(t_air_k, dtype=float)
    u = np.asarray(wind_ms, dtype=float)
    es_w = vapour_pressure_hpa(t_w)
    q_w = 0.622 * es_w / (pressure_hpa - 0.378 * es_w)
    q_a = 0.622 * np.asarray(e_air_hpa, dtype=float) / (pressure_hpa - 0.378 * np.asarray(e_air_hpa, dtype=float))
    h = rho * CP * c_h * u * (t_w - t_a)
    le = rho * 2.5e6 * c_e * u * np.maximum(q_w - q_a, 0.0)
    return h, le
