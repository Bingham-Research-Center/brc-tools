"""Gate lines: the 2-D planes a drainage flux is measured through.

A gate is cut *perpendicular to the channel* at a rim crossing, long enough to span
the valley at a chosen height above the thalweg, and oriented so that walking a -> b
puts the downstream direction on the walker's right -- the convention of
``brc_tools.nwp.wrf_output.integrate_flux_transect``, whose ``Phi`` is then positive
for export out of the catchment.  A hand-drawn west-east line across a canyon that
bends can straddle a neighbour's gorge (the Dry Fork line of ub-wx part 1 did); this
is the fix.

Widths are measured on the DEM as the contiguous run of cells around the thalweg that
lie below thalweg + h, for several h, and reported in metres and -- through
``width_in_cells`` -- in multiples of a model grid spacing, which is what says whether
a mouth is resolved.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .d8 import walk_downstream, walk_upstream_main

DEFAULT_HEIGHTS = (50.0, 100.0, 150.0, 200.0)


@dataclass
class GateLine:
    """One gate: endpoints, orientation, thalweg and valley widths."""

    name: str
    a: tuple[float, float]              # (lat, lon); walk a -> b, rightward normal = downstream
    b: tuple[float, float]
    mouth: tuple[float, float]          # the crossing cell's centre
    upstream: tuple[float, float]       # a point up the main channel (for WBD queries)
    azimuth_deg: float                  # downstream channel direction, clockwise from north
    direction_xy: tuple[float, float]   # unit downstream vector in the grid CRS (east, north)
    thalweg_m: float
    widths_m: dict[float, float] = field(default_factory=dict)   # height above thalweg -> width
    line_length_m: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["widths_m"] = {f"{k:g}": v for k, v in self.widths_m.items()}
        return d


def channel_direction(rcv: np.ndarray, acc: np.ndarray, cell: int, nx: int, *, nsteps: int):
    """Unit downstream direction (east, north) at ``cell`` from the main stem ``nsteps``
    up to ``nsteps`` down, plus the two end cells."""
    up = walk_upstream_main(rcv, acc, cell, nsteps, nx)
    dn = walk_downstream(rcv, cell, nsteps)
    ju, iu = divmod(int(up), nx)
    jd, id_ = divmod(int(dn), nx)
    dx, dy = float(id_ - iu), float(-(jd - ju))        # rows increase southward
    norm = np.hypot(dx, dy)
    if norm == 0.0:
        return (0.0, -1.0), up, dn                     # a sink: point south by convention
    return (dx / norm, dy / norm), up, dn


def valley_widths(zf: np.ndarray, grid, cell: int, direction_xy, *, heights=DEFAULT_HEIGHTS,
                  half_km: float = 4.0) -> tuple[dict[float, float], float]:
    """Width of the valley cross-section perpendicular to ``direction_xy`` at ``cell``:
    the contiguous run around the thalweg lying below thalweg + h, for each h.  The
    thalweg is the lowest cell within 3 cells of ``cell`` along the section, and the run
    grows from there (a crossing cell can sit on the bank above the gorge).
    Returns ``({h: width_m}, thalweg_m)``; a run reaching the +/- half_km window edge
    means the valley is wider than the window."""
    ny, nx = zf.shape
    j0, i0 = divmod(int(cell), nx)
    dx, dy = direction_xy
    norm = np.hypot(dx, dy) or 1.0
    px, py = -dy / norm, dx / norm
    s = np.arange(-half_km * 1000, half_km * 1000 + grid.res, grid.res)
    ii = np.round(i0 + s * px / grid.res).astype(int)
    jj = np.round(j0 - s * py / grid.res).astype(int)
    ok = (ii >= 0) & (ii < nx) & (jj >= 0) & (jj < ny)
    prof = np.full(s.size, np.nan)
    prof[ok] = zf[jj[ok], ii[ok]]
    centre = int(np.argmin(np.abs(s)))
    lo = max(centre - 3, 0)
    # seed the run at the thalweg, not the crossing: from a bank cell above thalweg + h the
    # run would never start and the width would come out as one cell
    centre = lo + int(np.argmin(np.nan_to_num(prof[lo:centre + 4], nan=np.inf)))
    zc = float(prof[centre])
    widths = {}
    for h in heights:
        below = prof < zc + h
        a = centre
        while a > 0 and below[a - 1]:
            a -= 1
        b = centre
        while b < s.size - 1 and below[b + 1]:
            b += 1
        widths[float(h)] = float((b - a + 1) * grid.res)
    return widths, zc


def perpendicular_gate(
    zf: np.ndarray,
    grid,
    crossing_cell: int,
    *,
    rcv: np.ndarray,
    acc: np.ndarray,
    upstream_steps: int | None = None,
    half_km: float = 4.0,
    heights=DEFAULT_HEIGHTS,
    line_km: tuple[float, float] = (6.0, 12.0),
    line_factor: float = 1.5,
    width_key: float = 150.0,
    name: str = "",
) -> GateLine:
    """Cut a gate across the channel at ``crossing_cell``.

    The channel direction comes from the main stem ``upstream_steps`` cells either side
    (default: 500 m or 3 cells, whichever is more); the line is perpendicular to it
    through the crossing cell, of length ``clip(line_factor * width[width_key], *line_km)``
    in kilometres, and ordered so that the rightward normal walking a -> b points
    downstream.  Endpoints are computed in the grid CRS and converted, so the line is
    straight on the ground rather than in lat/lon.
    """
    nsteps = upstream_steps if upstream_steps is not None else max(int(500 / grid.res), 3)
    (dx, dy), up, _ = channel_direction(rcv, acc, crossing_cell, grid.nx, nsteps=nsteps)
    widths, zc = valley_widths(zf, grid, crossing_cell, (dx, dy), heights=heights, half_km=half_km)
    w = widths.get(float(width_key), np.nan)
    if not np.isfinite(w):
        w = line_km[0] * 1e3
    half = 0.5 * float(np.clip(line_factor * w, line_km[0] * 1e3, line_km[1] * 1e3))
    px, py = -dy, dx                                   # perpendicular (rotate downstream 90 deg CCW)
    j0, i0 = divmod(int(crossing_cell), grid.nx)
    xc, yc = grid.xy(j0, i0)
    lon_a, lat_a = grid.lonlat_xy(xc - half * px, yc - half * py)
    lon_b, lat_b = grid.lonlat_xy(xc + half * px, yc + half * py)
    lon_m, lat_m = grid.lonlat_xy(xc, yc)
    ju, iu = divmod(int(up), grid.nx)
    lon_u, lat_u = grid.lonlat(ju, iu)
    az = float(np.degrees(np.arctan2(dx, dy)) % 360.0)
    return GateLine(
        name=name, a=(float(lat_a), float(lon_a)), b=(float(lat_b), float(lon_b)),
        mouth=(float(lat_m), float(lon_m)), upstream=(float(lat_u), float(lon_u)),
        azimuth_deg=az, direction_xy=(float(dx), float(dy)), thalweg_m=zc,
        widths_m=widths, line_length_m=2.0 * half,
    )


def width_in_cells(width_m: float, dx_m: float) -> float:
    """How many model cells of spacing ``dx_m`` a width spans (a bulk flux wants >= 5)."""
    return float(width_m) / float(dx_m)


_TOML_ORDER = ("kind", "a", "b", "mouth", "upstream", "azimuth_deg", "rim_m", "thalweg_m",
               "width50_m", "width100_m", "width150_m", "width200_m", "catchment_km2",
               "huc10", "label", "source")


def gate_to_lookup_entry(gate: GateLine, *, kind: str, rim_m: float, catchment_km2: float,
                         huc10: str = "", source: str, label: str = "", ndp: int = 5) -> dict:
    """The ``[gates.<name>]`` row for lookups.toml: geometry rounded to ``ndp`` decimals,
    widths in metres, and the citation string that says how the line was made."""
    if kind not in ("rim", "floor", "port"):
        raise ValueError("kind must be rim, floor or port")
    d = {
        "kind": kind,
        "a": [round(gate.a[0], ndp), round(gate.a[1], ndp)],
        "b": [round(gate.b[0], ndp), round(gate.b[1], ndp)],
        "mouth": [round(gate.mouth[0], ndp), round(gate.mouth[1], ndp)],
        "upstream": [round(gate.upstream[0], ndp), round(gate.upstream[1], ndp)],
        "azimuth_deg": round(gate.azimuth_deg, 1),
        "rim_m": int(round(rim_m)),
        "thalweg_m": int(round(gate.thalweg_m)),
    }
    for h, w in sorted(gate.widths_m.items()):
        d[f"width{int(h)}_m"] = int(round(w))
    d["catchment_km2"] = round(float(catchment_km2), 1)
    d["huc10"] = huc10 or ""
    if label:
        d["label"] = label
    d["source"] = source
    return d


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return repr(float(v))
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot format {type(v)} for TOML")


def format_gate_toml(name: str, entry: dict) -> str:
    """One ``[gates.<name>]`` block, keys in schema order, ready to paste."""
    keys = [k for k in _TOML_ORDER if k in entry] + [k for k in entry if k not in _TOML_ORDER]
    width = max(len(k) for k in keys)
    lines = [f"[gates.{name}]"]
    for k in keys:
        lines.append(f"{k.ljust(width)} = {_toml_value(entry[k])}")
    return "\n".join(lines) + "\n"
