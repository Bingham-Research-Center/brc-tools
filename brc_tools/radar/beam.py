"""Radar beam geometry under the standard 4/3-Earth refraction model.

Pure geometry: numpy only, no I/O, no matplotlib.  Everything radar-related
depends on this module, so it deliberately has no dependencies of its own.

Why it exists
-------------
A WSR-88D beam climbs away from the ground with range, from both the elevation
angle and the curvature of the Earth.  At long range that climb dominates: the
nearest radar to the Uinta Basin, KGJX on Grand Mesa, is 189 km from Vernal, and
its lowest scan passes ~3.5 km *above* the valley floor.  Anything shallower than
that was never sampled, and simulated reflectivity may only be compared to what
such a radar saw on the matching beam surface -- never at a fixed height AGL.

The standard model treats propagation as straight-line through an atmosphere
whose curvature is absorbed into an effective Earth radius ``k * a`` with
``k = 4/3`` (Doviak & Zrnic 1993, eq. 2.28):

    h = sqrt(r^2 + (k a)^2 + 2 r k a sin(theta)) - k a + h_radar

which is exact for the geometry and needs no small-angle approximation.
"""

from __future__ import annotations

import numpy as np

#: Mean Earth radius (m).
EARTH_RADIUS_M = 6_371_000.0

#: Effective-radius multiplier for standard atmospheric refraction.
REFRACTION_K = 4.0 / 3.0

#: WSR-88D half-power (3 dB) beamwidth in degrees.
WSR88D_BEAMWIDTH_DEG = 0.95


def great_circle_distance_m(lat0, lon0, lat1, lon1):
    """Great-circle distance (m) from ``(lat0, lon0)`` to ``(lat1, lon1)``.

    Haversine, so it stays well-conditioned at short range.  Broadcasts, so the
    target may be scalars or 2-D grids.
    """
    phi0, phi1 = np.radians(lat0), np.radians(np.asarray(lat1, dtype=float))
    dphi = phi1 - phi0
    dlam = np.radians(np.asarray(lon1, dtype=float) - lon0)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi0) * np.cos(phi1) * np.sin(dlam / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def beam_height_asl(range_m, elev_deg, radar_alt_m, *, refraction: float = REFRACTION_K):
    """Height above sea level (m) of the beam centre at slant range ``range_m``.

    Parameters
    ----------
    range_m
        Slant range from the radar (m).  Scalar or array.
    elev_deg
        Beam elevation angle (degrees above horizontal).
    radar_alt_m
        Height of the antenna above sea level (m).
    refraction
        Effective-Earth-radius multiplier; ``4/3`` is the standard atmosphere.
        Pass ``1.0`` to switch refraction off and get pure geometric curvature.
    """
    r = np.asarray(range_m, dtype=float)
    ka = refraction * EARTH_RADIUS_M
    sin_e = np.sin(np.radians(elev_deg))
    return np.sqrt(r**2 + ka**2 + 2.0 * r * ka * sin_e) - ka + radar_alt_m


def beam_height_agl(
    range_m, elev_deg, radar_alt_m, ground_alt_m, *, refraction: float = REFRACTION_K
):
    """Height of the beam centre above the *ground under it* (m).

    ``ground_alt_m`` is the terrain height at the sampled point, not at the
    radar.  This is the number that decides whether a feature could have been
    seen at all: over the Uinta Basin floor it is what shows that the observed
    velocity couplet was mid-level.
    """
    return (
        beam_height_asl(range_m, elev_deg, radar_alt_m, refraction=refraction)
        - np.asarray(ground_alt_m, dtype=float)
    )


def beam_edges_asl(
    range_m,
    elev_deg,
    radar_alt_m,
    *,
    beamwidth_deg: float = WSR88D_BEAMWIDTH_DEG,
    refraction: float = REFRACTION_K,
):
    """Height ASL of the lower and upper half-power beam edges.

    Returns ``(lower_m, upper_m)``.  The *lower* edge is the honest bound on how
    shallow a feature could have been and still returned power: nothing below it
    was sampled by that scan.
    """
    half = beamwidth_deg / 2.0
    lower = beam_height_asl(range_m, elev_deg - half, radar_alt_m, refraction=refraction)
    upper = beam_height_asl(range_m, elev_deg + half, radar_alt_m, refraction=refraction)
    return lower, upper


def beam_surface_asl(lat2d, lon2d, site, elev_deg, *, refraction: float = REFRACTION_K):
    """Height ASL (m) of a radar beam surface sampled over a model grid.

    Parameters
    ----------
    lat2d, lon2d
        Latitude/longitude of the grid, ``(ny, nx)``.  Longitudes may be in
        either -180..180 or 0..360 convention.
    site
        A :class:`brc_tools.radar.sites.RadarSite`, or any object exposing
        ``lat``, ``lon`` and ``alt_m``.
    elev_deg
        Elevation angle of the sweep.

    Notes
    -----
    Ground range is used as the slant range.  At the ranges this is built for
    (100-300 km) and the shallow angles a WSR-88D actually scans, the difference
    is far smaller than the beamwidth, so it is not worth iterating for.
    """
    lon = np.asarray(lon2d, dtype=float)
    lon = np.where(lon > 180.0, lon - 360.0, lon)
    rng = great_circle_distance_m(site.lat, site.lon, lat2d, lon)
    return beam_height_asl(rng, elev_deg, site.alt_m, refraction=refraction)


def sample_on_beam(field3d, z3d_asl, beam_asl2d):
    """Sample a 3-D model field onto a radar beam surface.

    ``field3d`` is ``(nz, ny, nx)``, ``z3d_asl`` the matching geometric heights
    ASL increasing with level, and ``beam_asl2d`` an ``(ny, nx)`` surface such as
    :func:`beam_surface_asl` returns.  Columns where the beam is below ground or
    above the model top come back NaN.

    Delegates to :func:`brc_tools.visualize.upperair.interp_to_height_surface`,
    which handles a varying target surface -- this is the same interpolation the
    constant-height plots use, not a second implementation of it.
    """
    from brc_tools.visualize.upperair import interp_to_height_surface

    return interp_to_height_surface(field3d, z3d_asl, np.asarray(beam_asl2d, dtype=float))
