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
from brc_tools.radar.iem import (
    RIDGE_PRODUCTS,
    RidgeField,
    observed_sweep,
    read_ridge,
)
from brc_tools.radar.nexrad import (
    MIRRORS,
    MOMENT_REFLECTIVITY,
    MOMENT_VELOCITY,
    RadarSweep,
    available_volumes,
    fetch_volume,
    geolocate_sweep,
    nearest_volume,
    iter_tar_volumes,
    list_keys,
    read_sweep,
    sweep_elevations,
    sweep_from_level2,
)
from brc_tools.radar.sites import RADAR_SITES, RadarSite, get_site

__all__ = [
    "MIRRORS",
    "RIDGE_PRODUCTS",
    "RidgeField",
    "observed_sweep",
    "read_ridge",
    "MOMENT_REFLECTIVITY",
    "MOMENT_VELOCITY",
    "RadarSweep",
    "available_volumes",
    "fetch_volume",
    "geolocate_sweep",
    "iter_tar_volumes",
    "list_keys",
    "nearest_volume",
    "read_sweep",
    "sweep_elevations",
    "sweep_from_level2",
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
