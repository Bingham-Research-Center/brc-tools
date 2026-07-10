"""Radiosonde sounding fetch (NOAA IGRA2 / Univ. Wyoming), normalised to one schema.

    from brc_tools.api.soundings import fetch_sounding, STATIONS
    df = fetch_sounding("KSLC", datetime(2013, 2, 2, 12))   # canonical polars frame

Auth-free (open archives).  See `docs/API-CLIENTS.md` for the canonical schema and
provider notes.
"""

from brc_tools.api.soundings.client import (
    CANONICAL_COLUMNS,
    STATIONS,
    SoundingStation,
    fetch_sounding,
    fetch_soundings,
    resolve_station,
)

__all__ = [
    "CANONICAL_COLUMNS",
    "STATIONS",
    "SoundingStation",
    "fetch_sounding",
    "fetch_soundings",
    "resolve_station",
]
