"""Optional Natural-Earth reference overlays for the cartopy-free WRF renderers.

The figure engine draws on plain lon/lat Matplotlib axes so it renders on offline
compute nodes.  Highway / river / lake / state-border overlays are **opt-in** and
**fail-soft**: they read Natural-Earth shapefiles via cartopy's shapereader *only if
the data is already staged* (``BRC_TOOLS_BASEMAP_DIR``, ``CARTOPY_DATA_DIR`` or the
cartopy default cache — stage it once with ``scripts/fetch_basemap.py``).  A missing
shapefile, an absent cartopy /
shapely, or a geometry error is swallowed so the figure still renders — just without
the overlay, never a crash on an offline node.

Geometry coordinates are plotted directly as lon/lat, which is exactly right for the
PlateCarree-equivalent plain axes the renderers use; pass ``transform`` when drawing on
a true cartopy GeoAxes instead.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

import numpy as np

# Natural-Earth ``roads`` ``type`` values we keep as "highways" (drop Track / Ferry
# Route / Unknown minor roads so US interstates & US/state highways stand out).
_HIGHWAY_TYPES = {"Major Highway", "Secondary Highway", "Beltway", "Bypass"}

# Engine layer key -> (Natural-Earth category, dataset name).
_LAYERS: dict[str, tuple[str, str]] = {
    "states": ("cultural", "admin_1_states_provinces_lakes"),
    "roads": ("cultural", "roads"),
    "rivers": ("physical", "rivers_lake_centerlines"),
    "lakes": ("physical", "lakes"),
}

# Layer draw order and default line styling (rivers/roads over lakes, borders on top).
_LINE_STYLE = {
    "rivers": dict(color="#3a6ea5", linewidth=0.5, alpha=0.75, zorder=3.0),
    "roads": dict(color="#8a5a2b", linewidth=0.6, alpha=0.85, zorder=3.1),
    "states": dict(color="0.15", linewidth=0.8, alpha=0.9, zorder=3.2),
}


def _candidate_data_dirs() -> tuple[Path, ...]:
    """cartopy data dirs to search, in order — env-driven persistent caches first.

    ``BRC_TOOLS_BASEMAP_DIR`` (a persistent group-storage cache) and the cartopy-native
    ``CARTOPY_DATA_DIR`` are honoured directly from the environment first, so a staged
    layer is found even when cartopy's config was not pre-seeded (e.g. the env var was
    exported after ``import cartopy``).  cartopy then files ``CARTOPY_DATA_DIR`` under
    ``config['pre_existing_data_dir']`` (a read-only search path) and keeps
    ``config['data_dir']`` as its own writable default (``~/.local/share/cartopy``), so a
    batch-staged layer lives under the former while the stock ``states`` layer may sit
    under the latter — we check both too, then de-dup preserving order.
    """
    dirs: list[Path] = []
    for env in ("BRC_TOOLS_BASEMAP_DIR", "CARTOPY_DATA_DIR"):
        val = os.environ.get(env)
        if val:
            dirs.append(Path(val))
    try:
        import cartopy
    except Exception:  # pragma: no cover - cartopy absent
        cartopy = None
    if cartopy is not None:
        for key in ("pre_existing_data_dir", "data_dir"):
            val = cartopy.config.get(key)
            if val:
                dirs.append(Path(val))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return tuple(ordered)


@functools.lru_cache(maxsize=8)
def _load_records(layer: str, resolution: str) -> tuple:
    """Read a staged Natural-Earth layer once per process -> ((geometry, attrs), ...).

    Searches the cartopy data dirs for the expected shapefile and reads it *only if
    present* — it never triggers a download, so an offline compute node returns ``()``
    instantly instead of hanging on a network fetch.  Returns ``()`` (never raises) if
    cartopy or the shapefile is absent.
    """
    cat_name = _LAYERS.get(layer)
    if cat_name is None:
        return ()
    category, name = cat_name
    rel = Path("shapefiles") / "natural_earth" / category / f"ne_{resolution}_{name}.shp"
    for data_dir in _candidate_data_dirs():
        shp = data_dir / rel
        if not shp.exists():
            continue
        try:
            import cartopy.io.shapereader as shpreader

            reader = shpreader.Reader(str(shp))
            return tuple((rec.geometry, dict(rec.attributes)) for rec in reader.records())
        except Exception:  # pragma: no cover - corrupt / unreadable shapefile
            return ()
    return ()


def _iter_lines(geom):
    """Yield ``(xs, ys)`` coordinate arrays for any line/ring/polygon geometry."""
    gt = getattr(geom, "geom_type", None)
    if gt in ("LineString", "LinearRing"):
        x, y = geom.xy
        yield np.asarray(x), np.asarray(y)
    elif gt == "Polygon":
        yield from _iter_lines(geom.exterior)
        for ring in geom.interiors:
            yield from _iter_lines(ring)
    elif gt in ("MultiLineString", "MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _iter_lines(part)


def _draw_lines(ax, records, bbox, pbox, base_kw, *, transform_kw):
    """Clip line/border records to ``bbox`` and stroke them."""
    for geom, _attrs in records:
        try:
            if not pbox.intersects(geom):
                continue
            clipped = geom.intersection(bbox)
        except Exception:  # pragma: no cover - invalid geometry
            continue
        for xs, ys in _iter_lines(clipped):
            if xs.size >= 2:
                ax.plot(xs, ys, **base_kw, **transform_kw)


def _draw_lake_fills(ax, records, bbox, pbox, *, transform_kw, zorder=2.5):
    """Clip lake polygons to ``bbox`` and fill them a muted water blue."""
    fill_kw = dict(facecolor="#aacbe6", edgecolor="#5d87ab", linewidth=0.4, alpha=0.65,
                   zorder=zorder)
    for geom, _attrs in records:
        try:
            if not pbox.intersects(geom):
                continue
            clipped = geom.intersection(bbox)
        except Exception:  # pragma: no cover - invalid geometry
            continue
        polys = getattr(clipped, "geoms", [clipped])
        for poly in polys:
            if getattr(poly, "geom_type", None) != "Polygon":
                continue
            x, y = poly.exterior.xy
            ax.fill(np.asarray(x), np.asarray(y), **fill_kw, **transform_kw)


def draw_waypoints(
    ax,
    waypoints,
    extent=None,
    *,
    transform=None,
    fontsize: float = 6.0,
    declutter: bool = True,
    marker: str = "^",
    color: str = "black",
    ms: float = 4.0,
    zorder: float = 11.0,
) -> None:
    """Plot waypoint markers + decluttered labels, skipping any outside ``extent``.

    ``extent`` is ``(lon0, lon1, lat0, lat1)``; waypoints beyond it (plus a small margin)
    are dropped so a cropped panel does not leak edge labels for far-away sites.  With
    ``declutter`` a label is suppressed when it would land within ~4 % of the extent span
    of an already-placed label — the marker is still drawn, so dense town clusters stay
    legible ("more locations marked" without turning labels to mush).
    """
    if not waypoints:
        return
    tkw = {} if transform is None else {"transform": transform}
    if extent is not None:
        lo_x, hi_x = sorted((float(extent[0]), float(extent[1])))
        lo_y, hi_y = sorted((float(extent[2]), float(extent[3])))
        span_x, span_y = hi_x - lo_x, hi_y - lo_y
        mx, my = 0.02 * span_x, 0.02 * span_y
        sep_x, sep_y = 0.04 * span_x, 0.04 * span_y
    placed: list[tuple[float, float]] = []
    for name, wp in waypoints.items():
        lon, lat = float(wp["lon"]), float(wp["lat"])
        if extent is not None and not (
            lo_x - mx <= lon <= hi_x + mx and lo_y - my <= lat <= hi_y + my
        ):
            continue
        ax.plot(lon, lat, marker=marker, color=color, ms=ms, zorder=zorder, **tkw)
        if declutter and extent is not None and any(
            abs(lon - px) < sep_x and abs(lat - py) < sep_y for px, py in placed
        ):
            continue
        ax.text(lon, lat, f" {name}", fontsize=fontsize, zorder=zorder, clip_on=True, **tkw)
        placed.append((lon, lat))


def add_reference_overlays(
    ax,
    extent,
    *,
    layers=None,
    states: bool = True,
    roads: bool = True,
    rivers: bool = True,
    lakes: bool = True,
    highways_only: bool = True,
    resolution: str = "10m",
    transform=None,
) -> None:
    """Overlay staged Natural-Earth reference features clipped to ``extent``.

    ``extent`` is ``(lon0, lon1, lat0, lat1)``.  ``layers`` (a ``{name: bool}`` mapping,
    e.g. a case's ``[map]`` table) overrides the individual flags when given.  Pass
    ``transform=ccrs.PlateCarree()`` for a cartopy GeoAxes; leave it ``None`` for the
    plain lon/lat axes the renderers use.  Fail-soft: any absent layer is skipped.
    """
    if layers is not None:
        states = bool(layers.get("states", states))
        roads = bool(layers.get("roads", roads))
        rivers = bool(layers.get("rivers", rivers))
        lakes = bool(layers.get("lakes", lakes))
    if not (states or roads or rivers or lakes):
        return
    try:
        from shapely.geometry import box as _box
        from shapely.prepared import prep
    except Exception:  # pragma: no cover - shapely absent
        return

    lon0, lon1, lat0, lat1 = extent
    bbox = _box(min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))
    pbox = prep(bbox)
    transform_kw = {} if transform is None else {"transform": transform}

    if lakes:
        _draw_lake_fills(ax, _load_records("lakes", resolution), bbox, pbox,
                         transform_kw=transform_kw)
    if rivers:
        _draw_lines(ax, _load_records("rivers", resolution), bbox, pbox,
                    _LINE_STYLE["rivers"], transform_kw=transform_kw)
    if roads:
        recs = _load_records("roads", resolution)
        if highways_only:
            recs = tuple((g, a) for (g, a) in recs if a.get("type") in _HIGHWAY_TYPES)
        _draw_lines(ax, recs, bbox, pbox, _LINE_STYLE["roads"], transform_kw=transform_kw)
    if states:
        _draw_lines(ax, _load_records("states", resolution), bbox, pbox,
                    _LINE_STYLE["states"], transform_kw=transform_kw)
