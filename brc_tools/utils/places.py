"""Places by name from ``lookups.toml``: a waypoint's position, a gate's line.

The registry is the one definition of where a place is; this is the read side the
case repos call, so that no experiment carries a coordinate of its own.  It reads the
TOML itself (stdlib only) so that the terrain environment, which has no Herbie, can
import it without ``brc_tools.nwp``.
"""
from __future__ import annotations

import math
import tomllib
from functools import lru_cache
from pathlib import Path

LOOKUPS = Path(__file__).resolve().parent.parent / "nwp" / "lookups.toml"


@lru_cache(maxsize=1)
def load_lookups() -> dict:
    with open(LOOKUPS, "rb") as fh:
        return tomllib.load(fh)


def waypoint(name: str) -> tuple[float, float, float]:
    """``(lat, lon, elevation_m)`` of a ``[waypoints.<name>]`` entry; NaN when it has no
    elevation."""
    w = load_lookups()["waypoints"][name]
    return float(w["lat"]), float(w["lon"]), float(w.get("elevation_m", float("nan")))


def gate_line(name: str, extend_km: float = 0.0) -> tuple[float, float, float, float]:
    """``(lat_a, lon_a, lat_b, lon_b)`` of a ``[gates.<name>]`` entry, optionally extended
    by ``extend_km`` beyond both ends along the same line (flat earth: fine for tens of
    km at these latitudes)."""
    g = load_lookups()["gates"][name]
    (la, lo), (lb, lob) = g["a"], g["b"]
    if extend_km <= 0:
        return float(la), float(lo), float(lb), float(lob)
    kx = 111.32 * math.cos(math.radians(0.5 * (la + lb)))
    dx, dy = (lob - lo) * kx, (lb - la) * 111.32
    length = math.hypot(dx, dy)
    ex, ey = dx / length * extend_km, dy / length * extend_km
    return la - ey / 111.32, lo - ex / kx, lb + ey / 111.32, lob + ex / kx
