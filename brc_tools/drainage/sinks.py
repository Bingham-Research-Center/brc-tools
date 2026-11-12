"""Reader for the ``[sinks.*]`` table of lookups.toml: the basins a cold pool fills.

A sink is a basin with one exit: everything whose drainage leaves through ``exit`` (and
through no sink further upstream), the ``throat`` that exit leads into, and the sink the
throat feeds.  The rows are places and so live in ``lookups.toml``; this module only
reads them, with ``tomllib`` alone, so it works in the terrain environment, which cannot
import ``brc_tools.nwp``.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SINK_KINDS", "Sink", "load_lookups", "sinks", "upstream_first", "chain", "waypoint_latlon", "region_extent"]

SINK_KINDS = ("floor", "corridor")
_LOOKUPS_PATH = Path(__file__).resolve().parents[1] / "nwp" / "lookups.toml"


@dataclass(frozen=True)
class Sink:
    name: str
    kind: str                                   # "floor" (the Uinta Basin proper) or "corridor"
    label: str
    exit: tuple[float, float]                   # (lat, lon): where the outlet channel enters the throat
    snap_m: float                               # search radius for the largest-accumulation cell
    throat: str
    throat_end: tuple[float, float] | None      # (lat, lon): where the throat opens into the next basin
    downstream: str | None                      # None = leaves the system


def load_lookups(path: str | Path | None = None) -> dict:
    with open(path or _LOOKUPS_PATH, "rb") as fh:
        return tomllib.load(fh)


def sinks(path: str | Path | None = None) -> dict[str, Sink]:
    """Every sink, in file order (which is upstream to downstream along the Green)."""
    table = load_lookups(path).get("sinks", {})
    out = {}
    for name, d in table.items():
        if d.get("kind") not in SINK_KINDS:
            raise ValueError(f"sink {name!r}: kind must be one of {SINK_KINDS}, got {d.get('kind')!r}")
        end = d.get("throat_end")
        out[name] = Sink(name=name, kind=d["kind"], label=str(d.get("label", name)),
                         exit=(float(d["exit"][0]), float(d["exit"][1])), snap_m=float(d.get("snap_m", 1000.0)),
                         throat=str(d.get("throat", "")),
                         throat_end=(float(end[0]), float(end[1])) if end else None,
                         downstream=(d.get("downstream") or None))
    for s in out.values():
        if s.downstream is not None and s.downstream not in out:
            raise ValueError(f"sink {s.name!r}: downstream {s.downstream!r} is not a sink")
    upstream_first(out)                         # raises on a cycle
    return out


def chain(table: dict[str, Sink], name: str) -> list[str]:
    """``name`` and every sink downstream of it, in order."""
    out, seen = [], set()
    cur: str | None = name
    while cur is not None:
        if cur in seen:
            raise ValueError("the sinks form a cycle")
        seen.add(cur)
        out.append(cur)
        cur = table[cur].downstream
    return out


def upstream_first(table: dict[str, Sink]) -> list[str]:
    """Sink names ordered so that each comes after everything that drains into it."""
    depth = {n: len(chain(table, n)) for n in table}
    return sorted(table, key=lambda n: -depth[n])


def waypoint_latlon(name: str, path: str | Path | None = None) -> tuple[float, float]:
    wp = load_lookups(path)["waypoints"][name]
    return float(wp["lat"]), float(wp["lon"])


def region_extent(name: str, path: str | Path | None = None) -> tuple[float, float, float, float]:
    """A lookups region as (lon_w, lon_e, lat_s, lat_n) -- the order ``terrain.dem`` takes."""
    r = load_lookups(path)["regions"][name]
    return float(r["sw"][1]), float(r["ne"][1]), float(r["sw"][0]), float(r["ne"][0])
