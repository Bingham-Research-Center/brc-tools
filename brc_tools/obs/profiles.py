"""Surface stations read as profiles: potential temperature against elevation, and the
drainage signal at a canyon mouth.

A basin ringed by stations at different heights is a poor man's sounding: plot each
station's potential temperature against its elevation and the cold pool, its top and the
free-air stratification above it appear without a balloon. This module holds the pieces
that turn Synoptic time series into that picture and into per-night drainage numbers.
Everything takes numpy arrays (or anything ``numpy.asarray`` reads) and returns arrays or
small frozen dataclasses, and nothing here touches the network, so it is unit-testable and
runs in any environment with numpy.

Conventions: UTC times (naive ones are read as UTC, aware ones converted once); temperature
in degrees C in, potential temperature in K out; heights in metres. **Pressure is in hPa,
but Synoptic reports Pa** -- divide by 100 first; the functions that take a pressure refuse
values that can only be Pa, because Pa passed as hPa does not fail loudly on its own (the
pressure fit rejects every report and the heat deficit comes out 27 times too large).
**Synoptic station elevations are in feet** -- convert with :func:`feet_to_m` before
anything else.

Pressure for theta. Few mesonet stations report pressure, and a 1 % pressure error is a
0.3 % (0.8 K) theta error, which is as large as the signal. So theta is not computed from a
standard atmosphere here. :func:`fit_pressure_height` fits ``ln p = a + b z`` to the
stations that *do* report pressure at that hour (the hydrostatic relation for the layer's
own mean temperature), and :func:`pressure_at` evaluates it at every station's height;
reported pressures are used for the fit only, so that every theta in one profile shares one
pressure-height relation and differences between neighbours are not sensor offsets. An
hour with no usable report at all can only be given the standard atmosphere, and the fit
warns when that happens rather than doing it quietly.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

__all__ = [
    "FT_TO_M", "feet_to_m", "standard_pressure_hpa", "altimeter_to_station_pressure_hpa",
    "PressureFit", "fit_pressure_height", "pressure_at", "potential_temperature", "wind_components",
    "in_sector", "sector_from_azimuth", "pseudo_profile", "TwoLayerFit", "two_layer_fit",
    "DrainageNight", "drainage_metrics", "count_surges", "nightly_cooling",
    "HeatDeficit", "heat_deficit", "ThetaPlane", "theta_plane_fit", "wind_constancy",
]

FT_TO_M = 0.3048
_KAPPA = 287.05 / 1004.0
_G, _RD, _CP = 9.80665, 287.05, 1004.0
# No surface pressure on Earth reaches 1100 hPa, and no station pressure in Pa falls below
# 30000; any value above this can only be Pa.
_MAX_PLAUSIBLE_HPA = 2000.0


def _hpa(pressure, name: str = "pressure_hpa") -> np.ndarray:
    """``pressure`` as a float array, refused if it is in Pa rather than hPa.

    Synoptic (and WRF) give pressure in Pa; this module works in hPa. Passed through
    unconverted, a Pa pressure fails every 3 % check in :func:`fit_pressure_height` -- so
    the fit falls back to the standard atmosphere without a word -- and multiplies the
    density in :func:`heat_deficit` by about 27. Neither looks like an error downstream.
    """
    p = np.asarray(pressure, dtype=float)
    finite = p[np.isfinite(p)]
    # any one value, not the median: a single Pa report among hPa ones gives theta ~75 K
    if finite.size and float(finite.max()) > _MAX_PLAUSIBLE_HPA:
        raise ValueError(f"{name} looks like Pa, not hPa (max {float(finite.max()):.0f}); "
                         "Synoptic and WRF report Pa -- divide by 100 before passing it here")
    return p


def _utc64(t) -> np.ndarray:
    """UTC ``datetime64[s]`` from a datetime, a sequence of them, or datetime64 values.

    Aware datetimes are converted to naive UTC here, once, before numpy sees them: numpy
    converts them correctly too, but with a UserWarning for every element.
    """
    def naive(x):
        if isinstance(x, datetime) and x.tzinfo is not None and x.utcoffset() is not None:
            return x.astimezone(timezone.utc).replace(tzinfo=None)
        return x

    if isinstance(t, datetime):
        return np.datetime64(naive(t), "s")
    a = np.asarray(t)
    if a.dtype == object:
        a = np.array([naive(x) for x in a.ravel()], dtype=object).reshape(a.shape)
    return a.astype("datetime64[s]")


def feet_to_m(feet):
    """Synoptic ``elevation`` (feet) to metres."""
    return np.asarray(feet, dtype=float) * FT_TO_M


def standard_pressure_hpa(z_m):
    """ICAO standard-atmosphere pressure (hPa) at height ``z_m``; a fallback and a QC bound only."""
    z = np.asarray(z_m, dtype=float)
    return 1013.25 * (1.0 - 2.25577e-5 * z) ** 5.25588


def altimeter_to_station_pressure_hpa(altimeter_hpa, z_m):
    """Station pressure from an altimeter setting (the inverse of the standard reduction)."""
    a = np.asarray(altimeter_hpa, dtype=float)
    z = np.asarray(z_m, dtype=float)
    return a * (1.0 - 2.25577e-5 * z) ** 5.25588


@dataclass(frozen=True)
class PressureFit:
    """``ln p = a + b z`` fitted to reporting stations; ``scale_height_m = -1/b``."""
    a: float
    b: float
    n: int
    rms_hpa: float

    @property
    def scale_height_m(self) -> float:
        return -1.0 / self.b if self.b else float("nan")


def fit_pressure_height(z_m, pressure_hpa, *, tolerance: float = 0.03, min_stations: int = 4) -> PressureFit:
    """Least-squares fit of ``ln p`` on height over stations whose pressure is within
    ``tolerance`` (fractional) of the standard atmosphere -- the test that throws out
    altimeter settings and sea-level pressures filed as station pressure.

    With fewer than ``min_stations`` usable reports the fit falls back to the standard
    atmosphere's own slope shifted to the median of what is there (``n`` says how many).
    With none at all it is the standard atmosphere itself, and a ``UserWarning`` says so.
    ``pressure_hpa`` in Pa raises ``ValueError`` (see the module notes).
    """
    z = np.asarray(z_m, dtype=float)
    p = _hpa(pressure_hpa)
    ok = np.isfinite(z) & np.isfinite(p) & (p > 0)
    std = standard_pressure_hpa(z)
    ok &= np.abs(p / std - 1.0) <= tolerance
    n = int(ok.sum())
    if n >= min_stations and np.ptp(z[ok]) > 200.0:
        b, a = np.polyfit(z[ok], np.log(p[ok]), 1)
        rms = float(np.sqrt(np.mean((np.exp(a + b * z[ok]) - p[ok]) ** 2)))
        return PressureFit(float(a), float(b), n, rms)
    if n == 0:
        warnings.warn(f"no usable station pressure among {p.size} report(s) (none finite and within "
                      f"{tolerance:.0%} of the standard atmosphere): the fit IS the standard atmosphere, "
                      "so theta from it carries that atmosphere's error", UserWarning, stacklevel=2)
    # fallback: the standard atmosphere's slope near 2 km, level set by the median ratio
    z0, z1 = 1500.0, 2500.0
    b = float(np.log(standard_pressure_hpa(z1) / standard_pressure_hpa(z0)) / (z1 - z0))
    ratio = float(np.median(p[ok] / std[ok])) if n else 1.0
    a = float(np.log(standard_pressure_hpa(z0) * ratio) - b * z0)
    return PressureFit(a, b, n, float("nan"))


def pressure_at(z_m, fit: PressureFit):
    """Pressure (hPa) at height ``z_m`` from a :class:`PressureFit`."""
    return np.exp(fit.a + fit.b * np.asarray(z_m, dtype=float))


def potential_temperature(temp_c, pressure_hpa):
    """Potential temperature (K) from temperature (degrees C) and pressure (hPa; Pa raises)."""
    t = np.asarray(temp_c, dtype=float) + 273.15
    return t * (1000.0 / _hpa(pressure_hpa)) ** _KAPPA


def wind_components(speed, direction_deg):
    """``(u, v)`` from speed and meteorological direction (degrees FROM)."""
    s = np.asarray(speed, dtype=float)
    d = np.radians(np.asarray(direction_deg, dtype=float))
    return -s * np.sin(d), -s * np.cos(d)


def in_sector(direction_deg, lo: float, hi: float):
    """True where a direction lies in the sector ``lo..hi`` (degrees FROM), through north when ``lo > hi``."""
    d = np.mod(np.asarray(direction_deg, dtype=float), 360.0)
    lo, hi = lo % 360.0, hi % 360.0
    return ((d >= lo) & (d <= hi)) if lo <= hi else ((d >= lo) | (d <= hi))


def sector_from_azimuth(downstream_azimuth_deg: float, half_width: float = 40.0) -> tuple[float, float]:
    """The down-valley wind sector for a channel that runs *toward* ``downstream_azimuth_deg``.

    Down-valley air blows toward the azimuth, so it comes FROM the reciprocal; the sector is
    the reciprocal +/- ``half_width``.
    """
    centre = (downstream_azimuth_deg + 180.0) % 360.0
    return (centre - half_width) % 360.0, (centre + half_width) % 360.0


def pseudo_profile(z_m, value, *, bin_m: float = 100.0, z_min: float | None = None, z_max: float | None = None,
                   min_count: int = 1) -> dict[str, np.ndarray]:
    """Bin stations by elevation: median, quartiles and count of ``value`` per ``bin_m`` layer.

    Returns arrays ``z`` (bin centre), ``median``, ``q25``, ``q75``, ``n`` for the bins that hold at
    least ``min_count`` stations. Bins are half-open, ``[lower, upper)``, so a station exactly on
    an edge belongs to the bin above it; ``z_min``/``z_max``, when given, are the bottom and the
    (excluded) top of the range. A pseudo-profile, not a sounding: the stations sit on the
    ground, so it is the near-surface air at each height.
    """
    z = np.asarray(z_m, dtype=float)
    v = np.asarray(value, dtype=float)
    ok = np.isfinite(z) & np.isfinite(v)
    z, v = z[ok], v[ok]
    if z.size == 0:
        return {k: np.array([]) for k in ("z", "median", "q25", "q75", "n")}
    lo = np.floor((z.min() if z_min is None else z_min) / bin_m) * bin_m
    # Without z_max the top edge must lie strictly above the highest station: rounding it up
    # with ceil leaves a station at an exact multiple of bin_m ON the top edge, past the last
    # half-open bin, and the highest station -- often the rim, the reference level -- is lost.
    hi = np.ceil(z_max / bin_m) * bin_m if z_max is not None else (np.floor(z.max() / bin_m) + 1.0) * bin_m
    edges = np.arange(lo, hi + bin_m, bin_m)
    idx = np.digitize(z, edges) - 1
    rows = []
    for k in range(edges.size - 1):
        m = idx == k
        if m.sum() >= min_count:
            rows.append((edges[k] + bin_m / 2, np.median(v[m]), np.percentile(v[m], 25), np.percentile(v[m], 75), m.sum()))
    arr = np.array(rows, dtype=float).reshape(-1, 5)
    return {"z": arr[:, 0], "median": arr[:, 1], "q25": arr[:, 2], "q75": arr[:, 3], "n": arr[:, 4].astype(int)}


@dataclass(frozen=True)
class TwoLayerFit:
    """A pool below a kink and the free air above it, fitted to theta against height."""
    z_top_m: float            # height of the kink: the pool top
    lower_k_per_km: float     # d(theta)/dz below it
    upper_k_per_km: float     # d(theta)/dz above it
    theta_top_k: float        # theta at the kink
    deficit_k: float          # theta at the kink minus theta at the lowest station height
    rms_k: float
    n: int


def two_layer_fit(z_m, theta_k, *, min_side: int = 3, step_m: float = 25.0) -> TwoLayerFit | None:
    """Continuous two-segment least-squares fit of theta on height; the break is the pool top.

    Every candidate break between the ``min_side``-th lowest and ``min_side``-th highest
    station is tried at ``step_m`` spacing and the one with the smallest residual is kept.
    Returns ``None`` with fewer than ``2 * min_side`` stations. The fit says where the
    stratification changes; it is the caller's job to decide whether the lower layer is a
    pool (lower gradient well above the upper one) or just a uniform atmosphere.
    """
    z = np.asarray(z_m, dtype=float)
    th = np.asarray(theta_k, dtype=float)
    ok = np.isfinite(z) & np.isfinite(th)
    z, th = z[ok], th[ok]
    if z.size < 2 * min_side:
        return None
    order = np.argsort(z)
    z, th = z[order], th[order]
    lo, hi = z[min_side - 1], z[-min_side]
    if hi <= lo:
        return None
    best = None
    for zb in np.arange(lo, hi + step_m, step_m):
        # theta = c0 + c1 * min(z - zb, 0) + c2 * max(z - zb, 0): continuous at zb
        design = np.column_stack([np.ones_like(z), np.minimum(z - zb, 0.0), np.maximum(z - zb, 0.0)])
        coef, *_ = np.linalg.lstsq(design, th, rcond=None)
        res = th - design @ coef
        sse = float(res @ res)
        if best is None or sse < best[0]:
            best = (sse, zb, coef)
    sse, zb, (c0, c1, c2) = best
    return TwoLayerFit(z_top_m=float(zb), lower_k_per_km=float(c1 * 1000.0), upper_k_per_km=float(c2 * 1000.0),
                       theta_top_k=float(c0), deficit_k=float(c1 * (zb - z[0])), rms_k=float(np.sqrt(sse / z.size)),
                       n=int(z.size))


def count_surges(along_speed, *, rise: float = 1.0, window: int = 3) -> int:
    """Number of separate surges in a down-valley speed series.

    A surge is a rise of at least ``rise`` (m/s) above the minimum of the preceding ``window``
    samples, counted once until the speed has fallen back by ``rise`` from its peak. Gaps
    (NaN) end a surge.
    """
    s = np.asarray(along_speed, dtype=float)
    n = 0
    armed = True
    peak = -np.inf
    for i in range(s.size):
        if not np.isfinite(s[i]):
            armed, peak = True, -np.inf
            continue
        prev = s[max(0, i - window):i]
        prev = prev[np.isfinite(prev)]
        if armed and prev.size and s[i] - prev.min() >= rise:
            n += 1
            armed, peak = False, s[i]
        elif not armed:
            peak = max(peak, s[i])
            if peak - s[i] >= rise:
                armed = True
    return n


@dataclass(frozen=True)
class DrainageNight:
    """What a mouth station saw between one sunset and the next sunrise."""
    n_obs: int
    fraction_down: float          # share of observations in the down-valley sector
    onset_min_after_sunset: float  # first sustained down-valley run, minutes after sunset (NaN if none; negative = before sunset)
    duration_h: float             # hours in the sector (observation count x median spacing)
    mean_speed: float             # mean speed while in the sector
    mean_along: float             # night-mean down-valley component (negative = up-valley)
    max_speed: float
    n_surges: int
    calm_fraction: float          # share of observations below the calm threshold


def drainage_metrics(times, speed, direction_deg, sector: tuple[float, float], *, sunset, sunrise,
                     calm: float = 0.3, run: int = 3, lead_h: float = 3.0, surge_rise: float = 1.0) -> DrainageNight | None:
    """Per-night drainage numbers for one station.

    ``times`` are UTC ``datetime64`` or datetimes (naive = UTC, aware converted), or anything
    ``numpy.asarray(..., 'datetime64[s]')`` accepts; likewise ``sunset``/``sunrise``. The
    fraction, duration and speeds use sunset..sunrise. The onset is the start of the first
    run of ``run`` consecutive in-sector, non-calm observations at or after
    ``sunset - lead_h`` (drainage in a shaded canyon starts before astronomical sunset).
    Calm observations (below ``calm`` m/s) carry no direction and count as not down-valley;
    one reported without a direction adds zero to ``mean_along``.
    """
    t = _utc64(times)
    s = np.asarray(speed, dtype=float)
    d = np.asarray(direction_deg, dtype=float)
    ss, sr = _utc64(sunset), _utc64(sunrise)
    order = np.argsort(t)
    t, s, d = t[order], s[order], d[order]
    ok = np.isfinite(s) & (np.isfinite(d) | (s < calm))
    t, s, d = t[ok], s[ok], d[ok]
    night = (t >= ss) & (t <= sr)
    if night.sum() < 6:
        return None
    centre = np.radians(_sector_centre(*sector))
    u, v = wind_components(s, np.where(np.isfinite(d), d, 0.0))
    along = -(u * np.sin(centre) + v * np.cos(centre))       # component blowing FROM the sector centre
    # a calm with no direction is no wind, not a northerly: projected through the 0.0
    # stand-in above, every calm report pulled mean_along toward wind from the north
    along = np.where(np.isfinite(d), along, 0.0)
    down = in_sector(d, *sector) & (s >= calm)
    tn, sn, dn, an = t[night], s[night], down[night], along[night]
    spacing_h = float(np.median(np.diff(tn).astype(float))) / 3600.0 if tn.size > 1 else float("nan")
    # onset
    early = t >= (ss - np.timedelta64(int(lead_h * 3600), "s"))
    te, de = t[early & (t <= sr)], down[early & (t <= sr)]
    onset = float("nan")
    for i in range(0, te.size - run + 1):
        if de[i:i + run].all():
            onset = float((te[i] - ss).astype(float)) / 60.0
            break
    return DrainageNight(
        n_obs=int(night.sum()), fraction_down=float(dn.mean()), onset_min_after_sunset=onset,
        duration_h=float(dn.sum() * spacing_h), mean_speed=float(sn[dn].mean()) if dn.any() else float("nan"),
        mean_along=float(np.nanmean(an)), max_speed=float(np.nanmax(sn)),
        n_surges=count_surges(np.where(dn, an, 0.0), rise=surge_rise), calm_fraction=float((sn < calm).mean()))


def _sector_centre(lo: float, hi: float) -> float:
    lo, hi = lo % 360.0, hi % 360.0
    width = (hi - lo) % 360.0
    return (lo + width / 2.0) % 360.0


def nightly_cooling(times, temp_c, *, sunset, sunrise, window_min: float = 30.0) -> dict[str, float] | None:
    """How much a station cooled over a night: sunset temperature, minimum and sunrise temperature.

    The sunset and sunrise values are means within ``window_min`` of each; ``cooling_k`` is
    sunset minus minimum (positive = it cooled); ``t_min_h`` is the hour of the minimum after sunset.
    Times as in :func:`drainage_metrics`.
    """
    t = _utc64(times)
    x = np.asarray(temp_c, dtype=float)
    ok = np.isfinite(x)
    t, x = t[ok], x[ok]
    ss, sr = _utc64(sunset), _utc64(sunrise)
    w = np.timedelta64(int(window_min * 60), "s")
    at_ss = x[(t >= ss - w) & (t <= ss + w)]
    at_sr = x[(t >= sr - w) & (t <= sr + w)]
    night = (t >= ss) & (t <= sr)
    if at_ss.size == 0 or night.sum() < 4:
        return None
    k = int(np.argmin(x[night]))
    return {"t_sunset_c": float(at_ss.mean()), "t_min_c": float(x[night][k]),
            "t_sunrise_c": float(at_sr.mean()) if at_sr.size else float("nan"),
            "cooling_k": float(at_ss.mean() - x[night][k]),
            "t_min_h": float((t[night][k] - ss).astype(float)) / 3600.0}


@dataclass(frozen=True)
class HeatDeficit:
    """How much heat a column lacks below ``z_ref_m`` against air at the reference theta."""
    j_per_m2: float           # c_p * integral of rho * (theta_ref - theta) dz
    head_pa: float            # the hydrostatic pressure excess that deficit puts on the bottom
    z_bottom_m: float
    z_ref_m: float
    theta_ref_k: float
    max_deficit_k: float      # theta_ref minus the coldest theta in the layer


def heat_deficit(z_m, theta_k, *, z_ref_m: float, pressure_hpa=None) -> HeatDeficit | None:
    """Valley heat deficit of a theta profile below ``z_ref_m`` (Whiteman et al. 1999).

    ``H = c_p * integral(rho * (theta(z_ref) - theta(z)) dz)`` from the lowest level to
    ``z_ref_m``: the heat (J m-2) that must be added to bring the column to the potential
    temperature at the reference height, which is the strength of a cold pool without choosing
    a pool top. ``head_pa = g * integral(rho * (theta_ref - theta) / theta dz)`` is the same
    deficit as a hydrostatic pressure excess at the bottom of the column -- the number to set
    against a synoptic pressure difference across the basin. Layers warmer than the reference
    count as zero. ``pressure_hpa`` (same shape) gives the density; the standard atmosphere is
    used without it (a 1-2 % effect); Pa raises ``ValueError``. Returns ``None`` if the
    profile does not reach ``z_ref_m`` or has fewer than two levels below it.
    """
    z = np.asarray(z_m, dtype=float)
    th = np.asarray(theta_k, dtype=float)
    p = standard_pressure_hpa(z) if pressure_hpa is None else _hpa(pressure_hpa)
    ok = np.isfinite(z) & np.isfinite(th) & np.isfinite(p)
    z, th, p = z[ok], th[ok], p[ok]
    order = np.argsort(z)
    z, th, p = z[order], th[order], p[order]
    if z.size < 2 or z[-1] < z_ref_m or z[0] >= z_ref_m:
        return None
    th_ref = float(np.interp(z_ref_m, z, th))
    p_ref = float(np.exp(np.interp(z_ref_m, z, np.log(p))))
    below = z < z_ref_m
    zz = np.append(z[below], z_ref_m)
    tt = np.append(th[below], th_ref)
    pp = np.append(p[below], p_ref)
    rho = pp * 100.0 / (_RD * tt * (pp / 1000.0) ** _KAPPA)
    deficit = np.maximum(th_ref - tt, 0.0)
    f_heat = rho * deficit
    f_head = rho * deficit / tt
    dz = np.diff(zz)
    heat = float(_CP * np.sum(0.5 * (f_heat[1:] + f_heat[:-1]) * dz))
    head = float(_G * np.sum(0.5 * (f_head[1:] + f_head[:-1]) * dz))
    return HeatDeficit(heat, head, float(zz[0]), float(z_ref_m), th_ref, float(deficit.max()))


@dataclass(frozen=True)
class ThetaPlane:
    """theta = a + b z + c x + d y fitted to stations: the stratification and its horizontal tilt."""
    k_per_km: float               # d(theta)/dz
    grad_k_per_100km: float       # magnitude of the horizontal gradient at fixed height
    cold_toward_deg: float        # azimuth toward which theta falls at fixed height (the pool deepens that way)
    slope_m_per_100km: float      # isentrope slope = horizontal gradient / vertical gradient
    dtheta_dx_k_per_100km: float
    dtheta_dy_k_per_100km: float
    rms_k: float
    n: int


def theta_plane_fit(z_m, x_km, y_km, theta_k) -> ThetaPlane | None:
    """Least-squares plane of theta in height and horizontal position.

    Stations at different heights on different sides of a basin mix the stratification with
    any horizontal tilt of the isentropes; fitting both at once separates them. An isentrope
    rises toward the cold side at ``|grad_h theta| / (d theta / dz)``: that slope, and the
    azimuth it rises toward, are what a pressure gradient aloft should set (pool deeper toward
    low heights). ``x_km`` is east and ``y_km`` north of any origin. Returns ``None`` with
    fewer than six stations or a non-positive stratification.
    """
    z = np.asarray(z_m, dtype=float)
    x = np.asarray(x_km, dtype=float)
    y = np.asarray(y_km, dtype=float)
    th = np.asarray(theta_k, dtype=float)
    ok = np.isfinite(z) & np.isfinite(x) & np.isfinite(y) & np.isfinite(th)
    z, x, y, th = z[ok], x[ok], y[ok], th[ok]
    if z.size < 6:
        return None
    design = np.column_stack([np.ones_like(z), z - z.mean(), x - x.mean(), y - y.mean()])
    coef, *_ = np.linalg.lstsq(design, th, rcond=None)
    res = th - design @ coef
    b, c, d = float(coef[1]), float(coef[2]), float(coef[3])
    if b <= 0:
        return None
    grad = float(np.hypot(c, d))
    return ThetaPlane(k_per_km=b * 1000.0, grad_k_per_100km=grad * 100.0,
                      cold_toward_deg=float(np.degrees(np.arctan2(-c, -d)) % 360.0),
                      slope_m_per_100km=grad / b * 100.0, dtheta_dx_k_per_100km=c * 100.0, dtheta_dy_k_per_100km=d * 100.0,
                      rms_k=float(np.sqrt(np.mean(res ** 2))), n=int(z.size))


def wind_constancy(speed, direction_deg, *, calm: float = 0.3) -> dict[str, float] | None:
    """Vector-mean wind of a series and how steady it was.

    Returns ``vector_speed``, ``vector_dir`` (degrees FROM), ``scalar_speed`` (mean of all
    observations, calms included), ``constancy`` (vector speed over the mean speed of the
    non-calm observations: 1 is a wind that never turns) and ``calm_fraction``. A drainage
    current shows as a constancy near 1 from a direction that needs no sector to be chosen in
    advance. ``None`` with no finite speed.
    """
    s = np.asarray(speed, dtype=float)
    d = np.asarray(direction_deg, dtype=float)
    ok = np.isfinite(s)
    if not ok.any():
        return None
    s, d = s[ok], d[ok]
    moving = (s >= calm) & np.isfinite(d)
    out = {"scalar_speed": float(s.mean()), "calm_fraction": float((s < calm).mean()), "n": int(s.size),
           "vector_speed": float("nan"), "vector_dir": float("nan"), "constancy": float("nan")}
    if moving.any():
        u, v = wind_components(s[moving], d[moving])
        vm = float(np.hypot(u.mean(), v.mean()))
        out.update(vector_speed=vm, vector_dir=float(np.degrees(np.arctan2(-u.mean(), -v.mean())) % 360.0),
                   constancy=vm / float(s[moving].mean()))
    return out
