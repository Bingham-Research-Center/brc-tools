"""WSR-88D site register.

Site coordinates are *capability*, not case configuration: a case TOML names a
site, it does not carry the antenna's latitude.  Antenna heights are tower feed
height ASL as published in the NOAA radar station list.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RadarSite:
    """A ground radar, with whatever is needed to do beam geometry against it."""

    id: str
    name: str
    lat: float
    lon: float
    alt_m: float
    note: str = ""


#: Sites relevant to the Uinta Basin.  KGJX is the nearest WSR-88D and the only
#: one with any view of the Basin at all; the others are listed because they are
#: the plausible alternatives a reader will ask about, and each is *further*.
RADAR_SITES: dict[str, RadarSite] = {
    "KGJX": RadarSite(
        id="KGJX",
        name="Grand Junction, CO",
        lat=39.0619,
        lon=-108.2137,
        alt_m=3046.0,
        note=(
            "On Grand Mesa. 189 km from Vernal; the beam clears the Book Cliffs, so "
            "blockage is not the limitation -- range and Earth curvature are. Its "
            "lowest scan is ~3.5 km above the Basin floor."
        ),
    ),
    "KMTX": RadarSite(
        id="KMTX",
        name="Salt Lake City, UT",
        lat=41.2628,
        lon=-112.4478,
        alt_m=1969.0,
        note="Promontory Point. Blocked from the Basin by the Wasatch.",
    ),
    "KRIW": RadarSite(
        id="KRIW",
        name="Riverton, WY",
        lat=43.0661,
        lon=-108.4772,
        alt_m=1712.0,
        note="North of the Uintas; the range is longer than KGJX and the Uinta crest blocks it.",
    ),
    "KCYS": RadarSite(
        id="KCYS",
        name="Cheyenne, WY",
        lat=41.1519,
        lon=-104.8061,
        alt_m=1875.0,
        note="Far east; listed for completeness only.",
    ),
}


def get_site(site_id: str) -> RadarSite:
    """Look up a radar by ICAO id, case-insensitively."""
    key = site_id.strip().upper()
    try:
        return RADAR_SITES[key]
    except KeyError:
        raise KeyError(
            f"unknown radar site {site_id!r}; known sites: {sorted(RADAR_SITES)}"
        ) from None
