"""Convective environment diagnostics: parcel thermodynamics and shear kinematics.

MetPy does the physics; this module's job is to feed it correctly and to return
plain floats and arrays rather than pint quantities, so callers and figure code
never have to care about units.  That boundary matters: a silent unit slip in a
parcel calculation produces a plausible number, not an error.

Input is a :class:`brc_tools.nwp.wrf_output.WRFColumn` or a
:class:`brc_tools.visualize.profile.Sounding`, both of which already carry
pressure in hPa, temperature and dewpoint in degC, winds in knots and height ASL
in metres.  Nothing here reads a file.

A note on what these numbers can support.  For a high-shear / low-CAPE nocturnal
event the *ordering* of LCL, LFC and EL and the depth of the stable layer carry
the argument; the absolute CAPE does not, because it is sensitive to the parcel
choice.  So every parcel routine here names its parcel explicitly and there is no
default "the" CAPE.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Parcel choices accepted by :func:`cape_cin` and :func:`parcel_levels`.
#:
#: ``sb``
#:     surface-based: the lowest level of the profile.
#: ``ml``
#:     mixed-layer: the mean of the lowest :data:`MIXED_LAYER_DEPTH_HPA`.
#: ``mu``
#:     most-unstable: the level of maximum equivalent potential temperature
#:     within :data:`MOST_UNSTABLE_DEPTH_HPA` of the surface.
PARCELS = ("sb", "ml", "mu")

#: Depth of the mixed layer used for the ``ml`` parcel (hPa).  Matches HRRR's
#: own 180 hPa mixed-layer CAPE product, so a model-vs-HRRR comparison is like
#: for like.
MIXED_LAYER_DEPTH_HPA = 180.0

#: Search depth for the ``mu`` parcel (hPa).  Matches HRRR's 255 hPa MUCAPE.
MOST_UNSTABLE_DEPTH_HPA = 255.0

#: Knots per m/s, for converting the column's wind units.
_KT_PER_MS = 1.94384


@dataclass(frozen=True)
class ParcelLevels:
    """Heights and pressures of the parcel levels, all plain floats.

    Heights are metres **above ground**, which is the form the funnel-precondition
    argument needs; NaN where the level does not exist (no LFC for a parcel that
    never becomes positively buoyant, no EL below the profile top).
    """

    parcel: str
    lcl_hpa: float
    lcl_agl_m: float
    lfc_hpa: float
    lfc_agl_m: float
    el_hpa: float
    el_agl_m: float


@dataclass(frozen=True)
class BulkShear:
    """Bulk wind difference over a layer, in m/s."""

    depth_m: float
    u: float
    v: float
    magnitude: float


@dataclass(frozen=True)
class StormMotion:
    """Bunkers storm motion and the mean wind it is built on, all m/s."""

    right_u: float
    right_v: float
    left_u: float
    left_v: float
    mean_u: float
    mean_v: float


def _profile(column):
    """Pull ``(p_hPa, T_degC, Td_degC, u_ms, v_ms, z_agl_m)`` off a column/sounding.

    Both :class:`WRFColumn` and :class:`Sounding` expose the same names; heights
    are converted to AGL using ``terrain_m`` when present, else the lowest level.
    """
    p = np.asarray(column.pressure_hpa, dtype=float)
    t = np.asarray(column.temperature_c, dtype=float)
    td = np.asarray(column.dewpoint_c, dtype=float)
    u = np.asarray(column.u_kt, dtype=float) / _KT_PER_MS
    v = np.asarray(column.v_kt, dtype=float) / _KT_PER_MS

    # Height is optional: an observed sounding may carry none, and the parcel
    # thermodynamics do not need it. The height-dependent routines (shear, SRH)
    # then return NaN rather than a number derived from a guess.
    z = getattr(column, "height_asl", None)
    if z is None:
        z = getattr(column, "height_m", None)
    if z is None:
        z = np.full(p.shape, np.nan)
        ground = 0.0
    else:
        z = np.asarray(z, dtype=float)
        ground = float(getattr(column, "terrain_m", None) or z[0])

    order = np.argsort(-p)  # surface first, ascending height
    return p[order], t[order], td[order], u[order], v[order], z[order] - ground


def _units():
    from metpy.units import units

    return units


def cape_cin(column, parcel: str = "ml") -> tuple[float, float]:
    """CAPE and CIN (J/kg) for one named parcel.

    Returns ``(cape, cin)`` as plain floats, CIN negative.  ``(nan, nan)`` if the
    profile is too short or the parcel cannot be lifted.

    There is deliberately no default-parcel convenience wrapper: for a
    low-CAPE environment the parcel choice moves the answer by more than the
    signal, so it must be stated at every call site.
    """
    if parcel not in PARCELS:
        raise ValueError(f"parcel must be one of {PARCELS}, got {parcel!r}")

    import metpy.calc as mpcalc

    u = _units()
    p, t, td, *_ = _profile(column)
    if p.size < 3:
        return float("nan"), float("nan")

    pq, tq, tdq = p * u.hPa, t * u.degC, td * u.degC
    try:
        if parcel == "sb":
            cape, cin = mpcalc.surface_based_cape_cin(pq, tq, tdq)
        elif parcel == "ml":
            cape, cin = mpcalc.mixed_layer_cape_cin(
                pq, tq, tdq, depth=MIXED_LAYER_DEPTH_HPA * u.hPa
            )
        else:
            cape, cin = mpcalc.most_unstable_cape_cin(
                pq, tq, tdq, depth=MOST_UNSTABLE_DEPTH_HPA * u.hPa
            )
    except (ValueError, IndexError):
        return float("nan"), float("nan")
    return float(cape.m), float(cin.m)


def _parcel_start(column, parcel: str):
    """``(p, T, Td)`` pint quantities for the chosen parcel's starting point."""
    import metpy.calc as mpcalc

    u = _units()
    p, t, td, *_ = _profile(column)
    pq, tq, tdq = p * u.hPa, t * u.degC, td * u.degC

    if parcel == "sb":
        return pq[0], tq[0], tdq[0]
    if parcel == "ml":
        mp, mt, mtd = mpcalc.mixed_parcel(pq, tq, tdq, depth=MIXED_LAYER_DEPTH_HPA * u.hPa)
        return mp, mt, mtd
    idx = mpcalc.most_unstable_parcel(pq, tq, tdq, depth=MOST_UNSTABLE_DEPTH_HPA * u.hPa)[-1]
    return pq[idx], tq[idx], tdq[idx]


def parcel_levels(column, parcel: str = "ml") -> ParcelLevels:
    """LCL, LFC and EL for one parcel, as pressures and heights AGL.

    LCL height is meteorologically load-bearing in its own right: a cloud base
    well above the ground is a precondition a visible funnel has to satisfy,
    independent of anything the model can resolve about the funnel itself.
    """
    if parcel not in PARCELS:
        raise ValueError(f"parcel must be one of {PARCELS}, got {parcel!r}")

    import metpy.calc as mpcalc

    u = _units()
    p, t, td, _, _, z_agl = _profile(column)
    pq, tq, tdq = p * u.hPa, t * u.degC, td * u.degC

    def _agl(p_level: float) -> float:
        """Height AGL at a pressure, by log-p interpolation on the column.

        ``p`` is surface-first (descending), so ``-log(p)`` already increases with
        height, as ``np.interp`` requires -- reversing it as well silently yields
        the surface height for every level.
        """
        if not np.isfinite(p_level):
            return float("nan")
        return float(np.interp(-np.log(p_level), -np.log(p), z_agl))

    try:
        p_start, t_start, td_start = _parcel_start(column, parcel)
        lcl_p, _ = mpcalc.lcl(p_start, t_start, td_start)
        lcl_hpa = float(lcl_p.to("hPa").m)
    except (ValueError, IndexError):
        lcl_hpa = float("nan")

    lfc_hpa = el_hpa = float("nan")
    try:
        prof = mpcalc.parcel_profile(pq, t_start, td_start).to("degC")
        lfc_p, _ = mpcalc.lfc(pq, tq, tdq, parcel_temperature_profile=prof)
        el_p, _ = mpcalc.el(pq, tq, tdq, parcel_temperature_profile=prof)
        lfc_hpa = float(lfc_p.to("hPa").m) if lfc_p is not None else float("nan")
        el_hpa = float(el_p.to("hPa").m) if el_p is not None else float("nan")
    except (ValueError, IndexError, UnboundLocalError):
        pass

    return ParcelLevels(
        parcel=parcel,
        lcl_hpa=lcl_hpa,
        lcl_agl_m=_agl(lcl_hpa),
        lfc_hpa=lfc_hpa,
        lfc_agl_m=_agl(lfc_hpa),
        el_hpa=el_hpa,
        el_agl_m=_agl(el_hpa),
    )


def parcel_profile_c(column, parcel: str = "ml") -> np.ndarray:
    """Parcel temperature profile in degC on the column's own pressure levels."""
    import metpy.calc as mpcalc

    u = _units()
    p, *_ = _profile(column)
    p_start, t_start, td_start = _parcel_start(column, parcel)
    prof = mpcalc.parcel_profile(p * u.hPa, t_start, td_start).to("degC")
    return np.asarray(prof.m, dtype=float)


def bulk_shear(column, depth_m: float = 6000.0) -> BulkShear:
    """Bulk wind difference between the surface and ``depth_m`` AGL, in m/s.

    This is the *vector difference* between the layer's ends, which is what
    "0-6 km bulk shear" means -- not an integrated shear magnitude.  Returns NaNs
    if the profile does not reach ``depth_m``.
    """
    _, _, _, u, v, z = _profile(column)
    if not np.isfinite(z).all() or z[-1] < depth_m:
        return BulkShear(depth_m, float("nan"), float("nan"), float("nan"))
    u_top = float(np.interp(depth_m, z, u))
    v_top = float(np.interp(depth_m, z, v))
    du, dv = u_top - float(u[0]), v_top - float(v[0])
    return BulkShear(depth_m, du, dv, float(np.hypot(du, dv)))


def storm_relative_helicity(
    column, depth_m: float = 3000.0, *, storm_u: float | None = None, storm_v: float | None = None
) -> float:
    """SRH (m^2 s^-2) over ``0`` to ``depth_m`` AGL.

    Uses the Bunkers right mover unless a storm motion is given.  **Pass the
    observed motion when you have one**: SRH is defined against a storm's motion,
    so quoting a Bunkers-based value for a storm that moved differently measures
    a storm that did not exist.
    """
    import metpy.calc as mpcalc

    u = _units()
    _, _, _, uu, vv, z = _profile(column)
    if storm_u is None or storm_v is None:
        motion = bunkers_storm_motion(column)
        storm_u, storm_v = motion.right_u, motion.right_v
    try:
        _, _, total = mpcalc.storm_relative_helicity(
            z * u.m,
            uu * u("m/s"),
            vv * u("m/s"),
            depth=depth_m * u.m,
            storm_u=float(storm_u) * u("m/s"),
            storm_v=float(storm_v) * u("m/s"),
        )
    except (ValueError, IndexError):
        return float("nan")
    return float(total.m)


def bunkers_storm_motion(column) -> StormMotion:
    """Bunkers (2000) right and left movers, plus the 0-6 km mean wind, in m/s."""
    import metpy.calc as mpcalc

    u = _units()
    p, _, _, uu, vv, z = _profile(column)
    try:
        right, left, mean = mpcalc.bunkers_storm_motion(
            p * u.hPa, uu * u("m/s"), vv * u("m/s"), z * u.m
        )
    except (ValueError, IndexError):
        nan = float("nan")
        return StormMotion(nan, nan, nan, nan, nan, nan)
    return StormMotion(
        right_u=float(right[0].m),
        right_v=float(right[1].m),
        left_u=float(left[0].m),
        left_v=float(left[1].m),
        mean_u=float(mean[0].m),
        mean_v=float(mean[1].m),
    )


def environment_summary(column, parcel: str = "ml") -> dict[str, float]:
    """Every scalar above, as a flat dict for a table row or a figure annotation.

    Keys mirror the ``lookups.toml`` alias names where one exists, so a model row
    and an HRRR row line up without renaming.
    """
    cape, cin = cape_cin(column, parcel)
    levels = parcel_levels(column, parcel)
    shear6 = bulk_shear(column, 6000.0)
    shear1 = bulk_shear(column, 1000.0)
    motion = bunkers_storm_motion(column)
    return {
        f"cape_{parcel}": cape,
        f"cin_{parcel}": cin,
        "lcl_agl_m": levels.lcl_agl_m,
        "lfc_agl_m": levels.lfc_agl_m,
        "el_agl_m": levels.el_agl_m,
        "shear_mag_0to6km": shear6.magnitude,
        "shear_mag_0to1km": shear1.magnitude,
        "srh_0to3km": storm_relative_helicity(column, 3000.0),
        "srh_0to1km": storm_relative_helicity(column, 1000.0),
        "bunkers_right_u": motion.right_u,
        "bunkers_right_v": motion.right_v,
    }
