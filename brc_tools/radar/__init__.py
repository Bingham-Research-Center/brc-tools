"""Ground-based weather radar: beam geometry and NEXRAD Level-II access.

Observational, not NWP -- the sibling of :mod:`brc_tools.satellite`.  The beam
geometry here is what makes a model-versus-radar comparison honest: a WSR-88D at
long range samples a surface that climbs steeply with distance, so comparing
simulated reflectivity at a fixed height AGL to what a distant radar saw is not
an apples-to-apples comparison at all.
"""

from brc_tools.radar.beam import (
    EARTH_RADIUS_M,
    REFRACTION_K,
    WSR88D_BEAMWIDTH_DEG,
    beam_edges_asl,
    beam_height_agl,
    beam_height_asl,
    beam_surface_asl,
    great_circle_distance_m,
    sample_on_beam,
)
from brc_tools.radar.sites import RADAR_SITES, RadarSite, get_site

__all__ = [
    "EARTH_RADIUS_M",
    "RADAR_SITES",
    "REFRACTION_K",
    "RadarSite",
    "WSR88D_BEAMWIDTH_DEG",
    "beam_edges_asl",
    "beam_height_agl",
    "beam_height_asl",
    "beam_surface_asl",
    "get_site",
    "great_circle_distance_m",
    "sample_on_beam",
]
