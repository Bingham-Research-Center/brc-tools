"""Diagnostics WRF carries the ingredients for but never writes as a field.

Three groups, and they are here rather than in :mod:`brc_tools.nwp.wrf_output`
because that module is the *reader* -- it turns a ``wrfout`` into the state
variables -- while everything below is a **derivation** on top of that state:

``moisture / obscuration``
    Visibility, fog depth, cloud base, cloud top, ceiling, layer cloud fraction,
    relative humidity, LCL.  WRF writes hydrometeor mixing ratios and a cloud
    fraction; it does not write *whether you could see across the valley*, which
    is the quantity a basin study, an aviation forecast and a satellite
    comparison all actually want.

``surface energy budget``
    Net radiation and the closure ``Rn + G = H + LE``.  A radiatively driven
    cold pool is *made* by this budget, and every term of it is already in the
    file; nothing plotted it.

``stability / turbulence``
    :math:`\\partial\\theta/\\partial z`, :math:`N^2`, and TKE.  An inversion's
    strength is a gradient, not a temperature, and a drainage layer's defining
    property is that it has decoupled -- which is a statement about TKE.

Everything takes an open ``wrfout`` :class:`xarray.Dataset` and returns plain
numpy on the model's own mass levels, ``(nz, ny, nx)`` or ``(ny, nx)``.  No
matplotlib, no case knowledge, no interpolation onto anything.

**Sign conventions are measured, not assumed.**  See
:func:`surface_energy_balance` for ``GRDFLX``, which is the one that bites.
"""
from __future__ import annotations

import numpy as np

from brc_tools.nwp import wrf_output as wo

__all__ = [
    "SURFACE_REQUIRES", "surface_diagnostic", "available_surface_diagnostics",
    "air_density", "hydrometeors_gkg", "cloud_condensate_gkg",
    "saturation_vapour_pressure_pa", "relative_humidity", "relative_humidity_2m",
    "lcl_height_agl",
    "extinction_km", "visibility_km", "surface_visibility_km",
    "obscured_depth_m", "fog_depth_m", "fog_top_asl",
    "cloud_fraction_layers", "cloud_base_agl", "cloud_top_asl", "ceiling_agl",
    "net_radiation", "surface_energy_balance",
    "turbulent_kinetic_energy", "theta_gradient_k_per_100m",
    "brunt_vaisala_squared", "column_max", "lowest_level_value",
    "VISIBILITY_MAX_KM", "FOG_VISIBILITY_KM", "MIST_VISIBILITY_KM",
]

_RD = 287.05        # J kg-1 K-1, dry air
_G = 9.80665        # m s-2
_EPS = 0.622        # Rd / Rv

#: Contrast threshold in Koschmieder's law: the visual range is the distance at
#: which contrast falls to 2%.  ``-ln(0.02) = 3.912``.
_KOSCHMIEDER = -np.log(0.02)

#: Clear-air cap on the reported visual range (km).  Beyond this the
#: hydrometeor-only extinction below is meaningless -- with no hydrometeors at
#: all it returns infinity, and real clear-air visibility is set by aerosol and
#: Rayleigh scattering that a ``wrfout`` does not carry.  RIP4 caps at 90 km; 20
#: is used here because that is where surface observations stop reporting a
#: number, so a figure on this scale can be read against a METAR.
VISIBILITY_MAX_KM = 20.0

#: The surface-observation definition of fog: visual range below 1 km.  Used as
#: the default threshold for :func:`fog_depth_m` so "fog" in a figure means what
#: it means at a station, rather than "some cloud water in the bottom cell".
FOG_VISIBILITY_KM = 1.0

#: Mist / BR: obscured but not fog.  1-5 km at a station.
MIST_VISIBILITY_KM = 5.0

#: Stoelinga & Warner (1999) extinction coefficients, in the constant set RIP4
#: uses (``rip4/src/viscalc.f``): ``beta = sum(coef * C**exponent)`` with the
#: hydrometeor concentration ``C`` in g m-3 and ``beta`` in km-1.
#:
#: NB the cloud-ice coefficient appears in the literature as both 163.9 and
#: 327.8 -- the two differ by an assumed effective radius, and the NCEP/UPP
#: visibility algorithm takes the smaller one.  RIP4's set is used here because
#: it is the canonical WRF-post implementation and travels with the reference
#: everyone cites.  For a *water* fog the choice is immaterial: the cloud-water
#: term dominates by two orders of magnitude.
_EXTINCTION = {
    "qcloud": (144.7, 0.8800),
    "qrain": (2.24, 0.7500),
    "qice": (327.8, 1.0000),
    "qsnow": (10.36, 0.7776),
}

#: ISCCP pressure bands for layer cloud amount (hPa).  Pressure, not height,
#: because that is the convention every satellite product and model verification
#: uses -- but note what it means over terrain: a 1500 m basin floor sits near
#: 850 hPa, so basin fog and valley stratus both land in ``low``, which is the
#: intent.
_CLOUD_BANDS = {"low": (680.0, np.inf), "mid": (440.0, 680.0), "high": (0.0, 440.0)}

#: A cell counts as cloudy for base/top/ceiling purposes at this cloud fraction.
#: 0.5 is "broken" in the aviation sense -- the first layer that would be
#: reported as a ceiling.
_CLOUDY_FRACTION = 0.5


# --------------------------------------------------------------------------- #
# thermodynamic basics
# --------------------------------------------------------------------------- #
def air_density(ds) -> np.ndarray:
    """Moist air density (kg m-3) on mass levels, ``(nz, ny, nx)``.

    Uses the virtual temperature, because at basin humidities the dry-air value
    is off by a few tenths of a percent and the hydrometeor concentrations that
    depend on it feed a *power law* in :func:`extinction_km`.
    """
    p = wo.pressure_pa(ds)
    t = wo.temperature_k(ds)
    qv = wo.qvapor(ds)
    return p / (_RD * t * (1.0 + 0.608 * qv))


def hydrometeors_gkg(ds) -> dict[str, np.ndarray]:
    """The condensate mixing ratios present in this run, g kg-1.

    Keys are the lower-cased WRF names (``qcloud``, ``qrain``, ``qice``,
    ``qsnow``, ``qgraup``).  A species the microphysics scheme does not carry is
    simply absent from the dict rather than returned as zeros, so a caller can
    tell "no ice in this run" from "no ice at this time".
    """
    out = {}
    for name in ("QCLOUD", "QRAIN", "QICE", "QSNOW", "QGRAUP"):
        if name in ds:
            # Advection undershoots leave small negative mixing ratios; they are
            # numerical, not physical, and a power law on a negative number is
            # a NaN rather than an error you would notice.
            out[name.lower()] = np.maximum(np.asarray(wo._da(ds, name).values,
                                                      dtype=float), 0.0) * 1000.0
    return out


def cloud_condensate_gkg(ds) -> np.ndarray:
    """Suspended cloud condensate (cloud water + cloud ice), g kg-1.

    Rain, snow and graupel are excluded on purpose: they are *falling*
    hydrometeors, and what makes a cloud (or a fog) is what stays suspended.
    """
    parts = hydrometeors_gkg(ds)
    total = np.zeros_like(next(iter(parts.values()))) if parts else None
    if total is None:
        raise KeyError("this run wrote no hydrometeor mixing ratios")
    for key in ("qcloud", "qice"):
        if key in parts:
            total = total + parts[key]
    return total


def saturation_vapour_pressure_pa(temp_k) -> np.ndarray:
    """Saturation vapour pressure over liquid water (Pa), Bolton (1980) eq. 10.

    Over liquid at every temperature, including below freezing.  That is the
    right choice here because it is the convention WRF's own ``RH`` diagnostics
    and every surface observation use; switching to ice saturation below 0 C
    would make a modelled RH incomparable with a reported one.
    """
    t_c = np.asarray(temp_k, dtype=float) - 273.15
    return 611.2 * np.exp(17.67 * t_c / (t_c + 243.5))


def relative_humidity(ds) -> np.ndarray:
    """Relative humidity over liquid water (%), on mass levels."""
    p = wo.pressure_pa(ds)
    qv = np.maximum(wo.qvapor(ds), 0.0)
    e = qv * p / (_EPS + qv)
    return 100.0 * e / saturation_vapour_pressure_pa(wo.temperature_k(ds))


def relative_humidity_2m(ds) -> np.ndarray:
    """2 m relative humidity over liquid water (%), from ``Q2``/``T2``/``PSFC``."""
    q2 = np.maximum(wo.surface_field(ds, "Q2"), 0.0)
    psfc = wo.surface_field(ds, "PSFC")
    e = q2 * psfc / (_EPS + q2)
    return 100.0 * e / saturation_vapour_pressure_pa(wo.surface_field(ds, "T2"))


def lcl_height_agl(ds) -> np.ndarray:
    """Lifting condensation level of the 2 m air (m AGL), Espy's rule.

    ``z_LCL ~= 125 (T - T_d)``.  Approximate by design and quite good enough for
    the question it is here to answer: *how far would this air have to be lifted,
    or cooled, before it fogs?*  A basin night in which the LCL sits at 30 m is a
    fog night whatever the third decimal place says.
    """
    from brc_tools.nwp.wrf_convective import surface_dewpoint_c

    t_c = wo.surface_field(ds, "T2") - 273.15
    return np.maximum(125.0 * (t_c - surface_dewpoint_c(ds)), 0.0)


# --------------------------------------------------------------------------- #
# visibility and fog
# --------------------------------------------------------------------------- #
def extinction_km(ds, *, rho=None) -> np.ndarray:
    """Hydrometeor extinction coefficient (km-1) on mass levels.

    Stoelinga & Warner (1999): each species contributes ``coef * C**exponent``
    with ``C`` its concentration in g m-3.  Species the run did not write
    contribute nothing.
    """
    if rho is None:
        rho = air_density(ds)
    parts = hydrometeors_gkg(ds)
    beta = None
    for key, (coef, expo) in _EXTINCTION.items():
        if key not in parts:
            continue
        conc = parts[key] * rho  # g/kg * kg/m3 = g/m3
        term = coef * np.power(conc, expo)
        beta = term if beta is None else beta + term
    if beta is None:
        raise KeyError("this run wrote no hydrometeor mixing ratios")
    return beta


def visibility_km(ds, *, cap_km: float = VISIBILITY_MAX_KM, rho=None) -> np.ndarray:
    """Horizontal visual range (km) on mass levels, capped at ``cap_km``.

    Koschmieder: ``vis = -ln(0.02) / beta``.  Hydrometeors only -- see
    :data:`VISIBILITY_MAX_KM` for why the cap is not cosmetic.
    """
    beta = extinction_km(ds, rho=rho)
    with np.errstate(divide="ignore", invalid="ignore"):
        vis = _KOSCHMIEDER / beta
    return np.minimum(np.where(np.isfinite(vis), vis, cap_km), cap_km)


def surface_visibility_km(ds, **kwargs) -> np.ndarray:
    """Visual range (km) in the lowest mass level -- the station's-eye view."""
    return visibility_km(ds, **kwargs)[0]


def obscured_depth_m(ds, *, threshold_km: float = FOG_VISIBILITY_KM,
                     vis=None) -> np.ndarray:
    """Depth (m AGL) of the ground-based layer with visibility below a threshold.

    Deliberately **ground-based and contiguous**: the top of the layer is the
    first level that clears, so a stratus deck a kilometre up cannot be counted
    as fog just because something else is obscured somewhere in the column.
    Zero where the surface itself is clear.

    Reported as the height of the highest *obscured* cell, so a single obscured
    bottom cell gives that cell's height (~5 m on this vertical grid) rather than
    zero -- the layer exists and has a depth, it is just shallow.
    """
    if vis is None:
        vis = visibility_km(ds)
    z = wo.height_agl(ds)
    obscured = np.asarray(vis, dtype=float) < float(threshold_km)

    depth = np.zeros(obscured.shape[1:], dtype=float)
    contiguous = obscured[0].copy()
    for k in range(obscured.shape[0]):
        if k:
            contiguous &= obscured[k]
        if not contiguous.any():
            break
        depth = np.where(contiguous, z[k], depth)
    return depth


def fog_depth_m(ds, **kwargs) -> np.ndarray:
    """Depth (m AGL) of ground-based fog -- visibility below 1 km. NaN where none.

    NaN rather than 0 for "no fog": zero-depth fog and no fog are the same thing
    physically, and a figure that paints the whole basin the bottom colour of a
    depth scale says "shallow fog everywhere" when it means "clear".
    """
    depth = obscured_depth_m(ds, **kwargs)
    return np.where(depth > 0.0, depth, np.nan)


def fog_top_asl(ds, **kwargs) -> np.ndarray:
    """Height (m ASL) of the top of ground-based fog. NaN where there is none."""
    return fog_depth_m(ds, **kwargs) + wo.surface_field(ds, "HGT")


# --------------------------------------------------------------------------- #
# cloud
# --------------------------------------------------------------------------- #
def cloud_fraction_layers(ds) -> dict[str, np.ndarray]:
    """Maximum ``CLDFRA`` within each ISCCP pressure band, ``{low, mid, high}``.

    Maximum rather than random or maximum-random overlap: the question these
    panels answer is *is there a deck in this layer and how solid is it*, and an
    overlap assumption would mix the layers back together, which is the one
    thing separating them was for.
    """
    cf = np.asarray(wo._da(ds, "CLDFRA").values, dtype=float)
    p_hpa = wo.pressure_pa(ds) / 100.0
    out = {}
    for name, (lo, hi) in _CLOUD_BANDS.items():
        band = (p_hpa > lo) & (p_hpa <= hi)
        out[name] = np.where(band, cf, 0.0).max(axis=0)
    return out


def _first_cloudy_from_ground(cf, fraction: float):
    """``(k_index, found)`` of the lowest level with ``cf >= fraction``."""
    cloudy = np.asarray(cf, dtype=float) >= float(fraction)
    return np.argmax(cloudy, axis=0), cloudy.any(axis=0)


def cloud_base_agl(ds, *, fraction: float = _CLOUDY_FRACTION) -> np.ndarray:
    """Height (m AGL) of the lowest cloudy level. NaN in a cloud-free column."""
    cf = np.asarray(wo._da(ds, "CLDFRA").values, dtype=float)
    k, found = _first_cloudy_from_ground(cf, fraction)
    z = wo.height_agl(ds)
    return np.where(found, np.take_along_axis(z, k[None], axis=0)[0], np.nan)


def cloud_top_asl(ds, *, fraction: float = _CLOUDY_FRACTION) -> np.ndarray:
    """Height (m ASL) of the highest cloudy level. NaN in a cloud-free column."""
    cf = np.asarray(wo._da(ds, "CLDFRA").values, dtype=float)
    cloudy = cf >= float(fraction)
    found = cloudy.any(axis=0)
    k = cf.shape[0] - 1 - np.argmax(cloudy[::-1], axis=0)
    z = wo.geopotential_height_mass(ds)
    return np.where(found, np.take_along_axis(z, k[None], axis=0)[0], np.nan)


def ceiling_agl(ds, *, fraction: float = _CLOUDY_FRACTION) -> np.ndarray:
    """Ceiling (m AGL): the lowest broken-or-worse layer. NaN where there is none.

    Same computation as :func:`cloud_base_agl` and a different name on purpose,
    because the two answer different questions once the layer is on the ground:
    a base at 5 m is a *surface obscuration*, not a ceiling, and an aviation
    reader must not read one as the other.  Columns whose lowest cloudy level is
    the first mass level are therefore returned as NaN here and left to
    :func:`fog_depth_m`.
    """
    cf = np.asarray(wo._da(ds, "CLDFRA").values, dtype=float)
    k, found = _first_cloudy_from_ground(cf, fraction)
    z = wo.height_agl(ds)
    base = np.where(found, np.take_along_axis(z, k[None], axis=0)[0], np.nan)
    return np.where(found & (k > 0), base, np.nan)


# --------------------------------------------------------------------------- #
# surface energy budget
# --------------------------------------------------------------------------- #
def net_radiation(ds) -> np.ndarray:
    """Net all-wave radiation at the surface (W m-2), positive **downward**.

    ``(SWDNB - SWUPB) + (LWDNB - LWUPB)``.  Falls back to
    ``SWDOWN*(1-ALBEDO) + GLW - sigma*EMISS*TSK**4`` when the boundary flux
    diagnostics were not written, which is the common case for a run that did
    not switch them on.
    """
    have = ("SWDNB", "SWUPB", "LWDNB", "LWUPB")
    if all(v in ds for v in have):
        sw_dn, sw_up, lw_dn, lw_up = (wo.surface_field(ds, v) for v in have)
        return (sw_dn - sw_up) + (lw_dn - lw_up)
    sigma = 5.670374419e-8
    sw_net = wo.surface_field(ds, "SWDOWN") * (1.0 - wo.surface_field(ds, "ALBEDO"))
    emiss = wo.surface_field(ds, "EMISS") if "EMISS" in ds else 1.0
    lw_up = emiss * sigma * wo.surface_field(ds, "TSK") ** 4
    return sw_net + wo.surface_field(ds, "GLW") - lw_up


def surface_energy_balance(ds) -> dict[str, np.ndarray]:
    """The surface energy budget terms and its closure residual (W m-2).

    Returns ``rnet``, ``hfx``, ``lh``, ``grdflx`` and ``residual``, where

    .. code::

        residual = Rn + G - H - LE

    **The ground-flux sign is measured, not assumed.**  WRF's ``GRDFLX`` sign
    convention varies with the land-surface scheme, and getting it backwards
    turns a closed budget into a 120 W m-2 error that still looks plausible.
    Against the Noah (``sf_surface_physics = 2``) run this was written for, the
    form above closes to a median -0.4 W m-2 and a mean absolute residual of
    1.4 W m-2, while the opposite sign leaves ~120 W m-2 -- so in that
    configuration ``GRDFLX`` is positive **upward**, from the soil toward the
    surface.  A large ``residual`` from this function is therefore a signal that
    the run's scheme uses the other convention, not that the budget is open.

    That upward ground flux is the physics of a radiative cold pool: on the
    night this was built for the surface loses ~77 W m-2 to space, the soil
    returns ~62 of it, and the remaining ~15 is taken out of the air -- which is
    the cold pool being manufactured, in the units it is manufactured in.
    """
    rnet = net_radiation(ds)
    hfx = wo.surface_field(ds, "HFX")
    lh = wo.surface_field(ds, "LH")
    grdflx = wo.surface_field(ds, "GRDFLX") if "GRDFLX" in ds else np.zeros_like(hfx)
    return {"rnet": rnet, "hfx": hfx, "lh": lh, "grdflx": grdflx,
            "residual": rnet + grdflx - hfx - lh}


# --------------------------------------------------------------------------- #
# stability and turbulence
# --------------------------------------------------------------------------- #
def turbulent_kinetic_energy(ds) -> np.ndarray:
    """TKE (m2 s-2) on mass levels.

    MYNN writes ``QKE``, which is **twice** the TKE, and writes ``TKE_PBL`` as
    identically zero -- so a plot of ``TKE_PBL`` from an MYNN run is a blank
    panel that looks like a result.  ``QKE`` is preferred here and halved;
    ``TKE_PBL`` is used only when ``QKE`` is absent (the YSU/Shin-Hong path).
    """
    if "QKE" in ds:
        qke = np.asarray(wo._da(ds, "QKE").values, dtype=float)
        if qke.ndim == 3 and qke.shape[0] > 1:
            return 0.5 * qke
    if "TKE_PBL" in ds:
        tke = np.asarray(wo._da(ds, "TKE_PBL").values, dtype=float)
        # TKE_PBL sits on w levels; destagger to mass points if it is one longer.
        if tke.shape[0] == wo.potential_temperature(ds).shape[0] + 1:
            return 0.5 * (tke[1:] + tke[:-1])
        return tke
    raise KeyError("this run wrote neither QKE nor TKE_PBL")


def theta_gradient_k_per_100m(theta, height) -> np.ndarray:
    """``d(theta)/dz`` in K per 100 m -- inversion strength, in readable units.

    K per 100 m rather than K per m because that is the number a forecaster
    already has intuition for: a dry adiabatic layer is 0, a strong nocturnal
    basin inversion runs 2-10, and the deepest cells here reach ~30.
    """
    theta = np.asarray(theta, dtype=float)
    height = np.asarray(height, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        grad = np.gradient(theta, axis=0) / np.gradient(height, axis=0)
    return grad * 100.0


def brunt_vaisala_squared(theta, height) -> np.ndarray:
    """``N^2 = (g / theta) d(theta)/dz`` (s-2) on the levels given."""
    theta = np.asarray(theta, dtype=float)
    return _G / theta * theta_gradient_k_per_100m(theta, height) / 100.0


# --------------------------------------------------------------------------- #
# small shared reductions
# --------------------------------------------------------------------------- #
def surface_theta_gradient(ds, *, depth_m: float = 100.0) -> np.ndarray:
    """Bulk ``d(theta)/dz`` (K per 100 m) over the lowest ``depth_m`` of the column.

    The **inversion-strength map**: one number per column saying how stably
    stratified the air immediately above the ground is.  A plan view of
    ``theta_2m`` shows where the cold air *is*; this shows where it is *trapped*,
    and the two are not the same field -- a cold, well-mixed slope is not a pool.

    Computed as a finite difference between the lowest mass level and the first
    level at or above ``depth_m``, rather than a fitted gradient: the quantity
    wanted is the bulk stability of that layer, and a fit would let a sharp
    surface inversion under a neutral layer average away to nothing.
    """
    theta = wo.potential_temperature(ds)
    z = wo.height_agl(ds)
    above = z >= float(depth_m)
    k = np.where(above.any(axis=0), np.argmax(above, axis=0), theta.shape[0] - 1)
    th_top = np.take_along_axis(theta, k[None], axis=0)[0]
    z_top = np.take_along_axis(z, k[None], axis=0)[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        return (th_top - theta[0]) / (z_top - z[0]) * 100.0


#: Style key -> the ``wrfout`` variables it needs, mirroring
#: :data:`brc_tools.nwp.wrf_convective.MESO_REQUIRES`.  A key whose requirements
#: this run did not write is named-skipped by the engines rather than crashing
#: them, so one config can serve runs with different output variable sets.
SURFACE_REQUIRES: dict[str, tuple[str, ...]] = {
    # obscuration
    "visibility_sfc": ("QCLOUD",),
    "fog_depth": ("QCLOUD",),
    "condensate_max": ("QCLOUD",),
    # cloud
    "cloud_low": ("CLDFRA",),
    "cloud_mid": ("CLDFRA",),
    "cloud_high": ("CLDFRA",),
    "cloud_base": ("CLDFRA",),
    "ceiling": ("CLDFRA",),
    # near-surface moisture
    "rh_2m": ("Q2", "T2", "PSFC"),
    "lcl_agl": ("Q2", "T2", "PSFC"),
    # the surface energy budget that builds a radiative pool
    "rnet_sfc": ("SWDOWN", "GLW", "ALBEDO", "TSK"),
    "hfx": ("HFX",),
    "lh": ("LH",),
    "grdflx": ("GRDFLX",),
    "energy_residual": ("HFX", "LH", "GRDFLX", "SWDOWN", "GLW", "ALBEDO", "TSK"),
    "lw_down": ("GLW",),
    "sw_down": ("SWDOWN",),
    # stability and turbulence
    "theta_grad_sfc": ("T",),
    "tke_max": ("QKE",),
    "ust": ("UST",),
    "tsk": ("TSK",),
    "heat_deficit": ("T",),
}


def available_surface_diagnostics(ds) -> list[str]:
    """The :data:`SURFACE_REQUIRES` keys this run wrote the ingredients for."""
    return sorted(k for k, need in SURFACE_REQUIRES.items()
                  if all(v in ds for v in need))


def surface_diagnostic(ds, key: str, **params) -> np.ndarray:
    """One derived 2-D field by style key.

    ``params`` carries the few knobs that are a *case* decision rather than a
    physical constant: ``crest_m`` for ``heat_deficit``, ``depth_m`` for
    ``theta_grad_sfc``, ``below_m`` for ``tke_max``.
    """
    if key not in SURFACE_REQUIRES:
        raise KeyError(f"unknown surface diagnostic {key!r}; "
                       f"known: {sorted(SURFACE_REQUIRES)}")
    missing = [v for v in SURFACE_REQUIRES[key] if v not in ds]
    if missing:
        raise KeyError(f"{key} needs {', '.join(missing)}, absent from this run")

    if key == "visibility_sfc":
        return surface_visibility_km(ds)
    if key == "fog_depth":
        return fog_depth_m(ds)
    if key == "condensate_max":
        return column_max(cloud_condensate_gkg(ds))
    if key in ("cloud_low", "cloud_mid", "cloud_high"):
        return cloud_fraction_layers(ds)[key.split("_", 1)[1]]
    if key == "cloud_base":
        return cloud_base_agl(ds)
    if key == "ceiling":
        return ceiling_agl(ds)
    if key == "rh_2m":
        return relative_humidity_2m(ds)
    if key == "lcl_agl":
        return lcl_height_agl(ds)
    if key == "rnet_sfc":
        return net_radiation(ds)
    if key in ("hfx", "lh", "grdflx"):
        return wo.surface_field(ds, key.upper())
    if key == "energy_residual":
        return surface_energy_balance(ds)["residual"]
    if key == "lw_down":
        return wo.surface_field(ds, "GLW")
    if key == "sw_down":
        return wo.surface_field(ds, "SWDOWN")
    if key == "ust":
        return wo.surface_field(ds, "UST")
    if key == "tsk":
        return wo.surface_field(ds, "TSK")
    if key == "theta_grad_sfc":
        return surface_theta_gradient(ds, depth_m=float(params.get("depth_m", 100.0)))
    if key == "tke_max":
        return column_max(turbulent_kinetic_energy(ds), height=wo.height_agl(ds),
                          below_m=float(params.get("below_m", 1000.0)))
    # heat_deficit
    return wo.heat_deficit_field(ds, float(params.get("crest_m", 2000.0))) / 1e6


def column_max(field3d, *, height=None, below_m: float | None = None) -> np.ndarray:
    """Column maximum of a 3-D field, optionally only below ``below_m`` (m AGL)."""
    field = np.asarray(field3d, dtype=float)
    if below_m is None:
        return np.nanmax(field, axis=0)
    if height is None:
        raise TypeError("below_m needs the matching height field")
    return np.nanmax(np.where(np.asarray(height) <= float(below_m), field, np.nan),
                     axis=0)


def lowest_level_value(field3d) -> np.ndarray:
    """The bottom mass level of a 3-D field -- the model's own near-surface value."""
    return np.asarray(field3d, dtype=float)[0]
