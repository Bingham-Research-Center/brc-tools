"""Radiosonde (upper-air sounding) fetch clients: NOAA IGRA2 and Univ. Wyoming.

Mechanical API layer.  Pulls a single station's sounding for one valid time from
an external archive and **normalises it to one canonical schema** so the rest of
brc-tools never sees provider quirks (differing column names, m/s-vs-knots winds,
station-id schemes).  Both archives are open, so -- unlike the other ``api/``
clients -- there is no ``_auth`` wiring.

Providers
---------
* ``igra2``   -- NOAA IGRA2 via siphon ``IGRAUpperAir`` (hosted at NCEI).  All
                 reported levels; winds in m/s; works back to the 2013 case.
                 ~40 s/station (siphon downloads the station's period-of-record
                 file, then filters to the requested launch).  **Default.**
* ``wyoming`` -- University of Wyoming via siphon ``WyomingUpperAir``; winds in
                 knots.  NOTE: the UWyo service was migrated/offline as of
                 2026-07 (both ``weather.uwyo.edu`` and ``weather.arcc.uwyo.edu``
                 404), so ``igra2`` is the reliable default.

Canonical schema (one row per level, sorted surface->top)
    station str | valid_time datetime(UTC, naive) | pressure_hpa | height_m
    | temperature_c | dewpoint_c | u_kt | v_kt | provider str

``height_m`` is the reported geopotential height (m); both archives carry it and
the theta(z) profile plot needs it, so it is kept in the canonical frame (the
skew-T ignores it).

Times are treated as UTC throughout (naive, matching the wrfout filename stamps
the figure batch parses); no tz object is attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Canonical wind unit is knots (Wyoming's native unit; the skew-T barbs expect it).
MS_TO_KT = 1.9438444924406

CANONICAL_COLUMNS = [
    "station", "valid_time", "pressure_hpa", "height_m",
    "temperature_c", "dewpoint_c", "u_kt", "v_kt", "provider",
]


@dataclass(frozen=True)
class SoundingStation:
    """An operational RAOB site: friendly name + per-provider ids + location."""

    name: str          # friendly / ICAO-ish key, e.g. "KSLC"
    wyoming: str       # Univ. Wyoming (== WMO) numeric id, e.g. "72572"
    igra2: str         # IGRA2 id, e.g. "USM00072572"
    lat: float
    lon: float
    elev_m: float
    location: str


# Operational RAOB stations that fall inside the pelican2013 WRF domains and were
# active in 2013 (from the IGRA2 station inventory).  All four sit in d01 (3 km);
# the basin itself launches no sonde, so these are proxies for the free atmosphere
# around it.  Extend freely -- callers may also pass a raw provider id for any site.
STATIONS: dict[str, SoundingStation] = {
    "KSLC": SoundingStation("KSLC", "72572", "USM00072572", 40.772, -111.955, 1289.0, "Salt Lake City, UT"),
    "KGJT": SoundingStation("KGJT", "72476", "USM00072476", 39.120, -108.525, 1474.0, "Grand Junction, CO"),
    "KRIW": SoundingStation("KRIW", "72672", "USM00072672", 43.065, -108.477, 1699.0, "Riverton, WY"),
    "KDPG": SoundingStation("KDPG", "74003", "USM00074003", 40.167, -112.933, 1325.0, "Dugway PG, UT"),
}


def resolve_station(name: str, provider: str) -> str:
    """Map a friendly station name to a provider id; pass unknown names through.

    Unknown names are returned verbatim so a caller can hand a raw provider id
    (``"USM00072572"`` or ``"72572"``) straight to the fetcher.
    """
    st = STATIONS.get(name.upper())
    if st is None:
        return name
    return st.igra2 if provider == "igra2" else st.wyoming


def _fetch_igra2(site_id: str, valid: datetime) -> dict:
    from siphon.simplewebservice.igra2 import IGRAUpperAir

    df, _header = IGRAUpperAir.request_data(valid, site_id)
    return {
        "pressure_hpa": df["pressure"].to_numpy(),
        "height_m": df["height"].to_numpy(),          # reported geopotential height
        "temperature_c": df["temperature"].to_numpy(),
        "dewpoint_c": df["dewpoint"].to_numpy(),
        "u_kt": df["u_wind"].to_numpy() * MS_TO_KT,   # IGRA2 winds are m/s
        "v_kt": df["v_wind"].to_numpy() * MS_TO_KT,
    }


def _fetch_wyoming(site_id: str, valid: datetime) -> dict:
    from siphon.simplewebservice.wyoming import WyomingUpperAir

    df = WyomingUpperAir.request_data(valid, site_id)
    return {
        "pressure_hpa": df["pressure"].to_numpy(),
        "height_m": df["height"].to_numpy(),          # reported geopotential height
        "temperature_c": df["temperature"].to_numpy(),
        "dewpoint_c": df["dewpoint"].to_numpy(),
        "u_kt": df["u_wind"].to_numpy(),              # Wyoming winds already knots
        "v_kt": df["v_wind"].to_numpy(),
    }


_PROVIDERS = {"igra2": _fetch_igra2, "wyoming": _fetch_wyoming}
# Try IGRA2 first: the UWyo archive is offline as of 2026-07.
_AUTO_ORDER = ("igra2", "wyoming")


def fetch_sounding(station: str, valid_time: datetime, *, provider: str = "auto"):
    """Return a normalised ``polars.DataFrame`` (``CANONICAL_COLUMNS``) for one launch.

    ``provider`` is ``"igra2"``, ``"wyoming"``, or ``"auto"`` (try igra2 then
    wyoming).  Returns ``None`` if no provider yields data -- a missing launch, a
    network failure, or an offline archive all collapse to ``None`` so batch
    callers can skip the station without special-casing.
    """
    import numpy as np
    import polars as pl

    order = _AUTO_ORDER if provider == "auto" else (provider,)
    for prov in order:
        site_id = resolve_station(station, prov)
        try:
            cols = _PROVIDERS[prov](site_id, valid_time)
        except Exception:
            continue  # try the next provider
        n = len(cols["pressure_hpa"])
        if n == 0:
            continue
        df = pl.DataFrame(
            {
                "station": [station] * n,
                "valid_time": [valid_time] * n,
                **{k: np.asarray(v, dtype="float64") for k, v in cols.items()},
                "provider": [prov] * n,
            }
        )
        # Levels need a real pressure and temperature; dewpoint/wind may be missing
        # aloft and are kept (the skew-T simply leaves gaps).  Sort surface->top.
        df = df.filter(
            pl.col("pressure_hpa").is_not_nan() & pl.col("pressure_hpa").is_not_null()
            & pl.col("temperature_c").is_not_nan() & pl.col("temperature_c").is_not_null()
        ).sort("pressure_hpa", descending=True)
        if df.height:
            return df.select(CANONICAL_COLUMNS)
    return None


def fetch_soundings(stations, valid_time: datetime, *, provider: str = "auto"):
    """Fetch several stations for one time.

    Returns ``(df, status)`` where ``df`` is the concatenated canonical frame (or
    ``None`` if nothing was retrieved) and ``status`` maps each station name to the
    provider that answered, or ``None`` if it had no data.
    """
    import polars as pl

    frames, status = [], {}
    for name in stations:
        df = fetch_sounding(name, valid_time, provider=provider)
        if df is None:
            status[name] = None
        else:
            status[name] = df["provider"][0]
            frames.append(df)
    return (pl.concat(frames) if frames else None), status
