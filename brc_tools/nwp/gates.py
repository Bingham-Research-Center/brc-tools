"""Reader for the ``[gates.*]`` table of lookups.toml: the 2-D planes drainage crosses.

A gate is analysis *geometry*, not a place: a line with two endpoints, walked a -> b so
that the rightward normal points downstream (out of the catchment), the convention of
:func:`brc_tools.nwp.wrf_output.integrate_flux_transect`.  Three kinds:

``rim``    a canyon mouth where a channel crosses the basin rim into the floor
``floor``  a line across the floor's own drainage (a bench spilling into the sink)
``port``   where a river corridor the domain cannot hold enters or leaves it

The rows are written by ``brc_tools.terrain.gates.format_gate_toml`` from the DEM and
carry a ``source`` string saying so (``docs/TERRAIN-D8.md``).  This module only reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from brc_tools.nwp.source import load_lookups

__all__ = ["GATE_KINDS", "Gate", "gates", "gate", "gate_lines", "in_region"]

GATE_KINDS = ("rim", "floor", "port")
Line = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class Gate:
    name: str
    kind: str
    a: tuple[float, float]                    # (lat, lon)
    b: tuple[float, float]
    mouth: tuple[float, float] | None = None
    upstream: tuple[float, float] | None = None
    rim_m: float | None = None
    thalweg_m: float | None = None
    width150_m: float | None = None
    catchment_km2: float | None = None
    huc10: str = ""
    source: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def line(self) -> Line:
        return (self.a, self.b)

    @property
    def normal_en(self) -> tuple[float, float]:
        """Unit rightward normal of a -> b as (east, north): the export direction."""
        import math
        coslat = math.cos(math.radians(0.5 * (self.a[0] + self.b[0])))
        ex = (self.b[1] - self.a[1]) * coslat
        ey = self.b[0] - self.a[0]
        n = math.hypot(ex, ey) or 1.0
        return (ey / n, -ex / n)


def _pair(v):
    return (float(v[0]), float(v[1])) if v is not None else None


def _gate(name: str, d: dict) -> Gate:
    known = {"kind", "a", "b", "mouth", "upstream", "rim_m", "thalweg_m", "width150_m", "catchment_km2",
             "huc10", "source"}
    if d.get("kind") not in GATE_KINDS:
        raise ValueError(f"gate {name!r}: kind must be one of {GATE_KINDS}, got {d.get('kind')!r}")
    return Gate(
        name=name, kind=d["kind"], a=_pair(d["a"]), b=_pair(d["b"]), mouth=_pair(d.get("mouth")),
        upstream=_pair(d.get("upstream")),
        rim_m=float(d["rim_m"]) if "rim_m" in d else None,
        thalweg_m=float(d["thalweg_m"]) if "thalweg_m" in d else None,
        width150_m=float(d["width150_m"]) if "width150_m" in d else None,
        catchment_km2=float(d["catchment_km2"]) if "catchment_km2" in d else None,
        huc10=str(d.get("huc10", "")), source=str(d.get("source", "")),
        extra={k: v for k, v in d.items() if k not in known},
    )


def gates(kind: str | None = None, *, lookups: dict | None = None) -> dict[str, Gate]:
    """Every gate in lookups.toml, optionally one ``kind``, keyed by name."""
    lu = lookups if lookups is not None else load_lookups()
    table = lu.get("gates", {})
    out = {name: _gate(name, d) for name, d in table.items()}
    if kind is not None:
        if kind not in GATE_KINDS:
            raise ValueError(f"kind must be one of {GATE_KINDS}")
        out = {n: g for n, g in out.items() if g.kind == kind}
    return out


def gate(name: str, *, lookups: dict | None = None) -> Gate:
    """One gate by name; exits naming the file when it is unknown (like ``wrf_engine.waypoint``)."""
    all_gates = gates(lookups=lookups)
    if name not in all_gates:
        raise SystemExit(f"unknown gate {name!r}: not in lookups.toml [gates] "
                         f"(known: {', '.join(sorted(all_gates)) or 'none'})")
    return all_gates[name]


def gate_lines(kind: str | None = None, *, lookups: dict | None = None) -> dict[str, Line]:
    """``{name: ((lat_a, lon_a), (lat_b, lon_b))}`` -- the shape the ub-wx analysis scripts use."""
    return {n: g.line for n, g in gates(kind, lookups=lookups).items()}


def in_region(g: Gate, region: str = "uinta_airshed", *, lookups: dict | None = None) -> bool:
    """Both endpoints (and the mouth, if any) inside a lookups.toml region box."""
    lu = lookups if lookups is not None else load_lookups()
    r = lu["regions"][region]
    (lat0, lon0), (lat1, lon1) = r["sw"], r["ne"]
    pts = [g.a, g.b] + ([g.mouth] if g.mouth else [])
    return all(lat0 <= la <= lat1 and lon0 <= lo <= lon1 for la, lo in pts)
