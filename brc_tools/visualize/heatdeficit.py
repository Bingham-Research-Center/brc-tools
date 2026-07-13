"""Cold-pool heat-deficit plan-view maps (field + case-minus-case difference).

The spatial companion to the ``heatdeficit`` time-series family: the Whiteman valley
heat deficit (:func:`brc_tools.nwp.wrf_output.heat_deficit_field`, MJ m^-2) rendered as a
map on a single nest, plus a paired difference map.  Sequential ``viridis`` for the field
(fixed 0..8 MJ scale, so the pool is directly comparable across cases and forecast hours);
symmetric ``RdBu_r`` for the difference (red = the *first* case has the deeper pool).

Plain lon/lat matplotlib for offline robustness, with the shared Natural-Earth overlays +
decluttered waypoint labels and a crest-height terrain contour, all fail-soft like the rest
of the suite.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _decorate(ax, lon, lat, *, crest_terrain=None, crest_m=None, waypoints=None, overlays=None):
    """Shared axis dressing: crest contour, overlays, waypoints, geographic aspect."""
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    extent = (float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max()))
    if crest_terrain is not None and crest_m is not None:
        ax.contour(lon, lat, np.asarray(crest_terrain), levels=[float(crest_m)],
                   colors="0.2", linewidths=0.7, alpha=0.85)
    if overlays and any(overlays.values()):
        from brc_tools.visualize.basemap import add_reference_overlays

        add_reference_overlays(ax, extent, layers=overlays)
    if waypoints:
        from brc_tools.visualize.basemap import draw_waypoints

        draw_waypoints(ax, waypoints, extent, zorder=6)
    ax.set_aspect(1.0 / np.cos(np.deg2rad(float(lat.mean()))))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")


def _annotate(ax, annotation):
    if annotation:
        ax.text(0.0, -0.08, annotation, transform=ax.transAxes, fontsize=6,
                color="0.4", ha="left", va="top")


def plot_heatdeficit_field(
    lon,
    lat,
    field_mj,
    out_path: str | Path,
    *,
    style,
    crest_terrain=None,
    crest_m=None,
    title: str,
    annotation: str | None = None,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    dpi: int = 300,
) -> Path:
    """Render a single-case heat-deficit field (MJ m^-2) as a sequential map."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out_path)
    fig, ax = plt.subplots(figsize=(7.2, 6.4), constrained_layout=True)
    mesh = ax.pcolormesh(lon, lat, np.asarray(field_mj), shading="auto",
                         cmap=style.cmap, vmin=style.vmin, vmax=style.vmax)
    _decorate(ax, lon, lat, crest_terrain=crest_terrain, crest_m=crest_m,
              waypoints=waypoints, overlays=overlays)
    fig.colorbar(mesh, ax=ax, shrink=0.9, extend=style.extend, label=style.label)
    ax.set_title(title)
    _annotate(ax, annotation)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_heatdeficit_difference(
    lon,
    lat,
    field_a_mj,
    field_b_mj,
    out_path: str | Path,
    *,
    limit: float | None = None,
    crest_terrain=None,
    crest_m=None,
    title: str,
    annotation: str | None = None,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    dpi: int = 300,
) -> Path:
    """Render (case_a - case_b) heat deficit (MJ m^-2) as a symmetric diverging map.

    ``limit`` fixes the symmetric colour magnitude (MJ m^-2) for cross-hour comparability;
    when ``None`` it is taken adaptively from the robust 99th percentile of the difference.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.style import symmetric_limit

    out = Path(out_path)
    diff = np.asarray(field_a_mj) - np.asarray(field_b_mj)
    lim = abs(limit) if limit is not None else symmetric_limit(diff)
    lim = lim or 1.0
    fig, ax = plt.subplots(figsize=(7.2, 6.4), constrained_layout=True)
    mesh = ax.pcolormesh(lon, lat, diff, shading="auto", cmap="RdBu_r", vmin=-lim, vmax=lim)
    _decorate(ax, lon, lat, crest_terrain=crest_terrain, crest_m=crest_m,
              waypoints=waypoints, overlays=overlays)
    fig.colorbar(mesh, ax=ax, shrink=0.9, extend="both",
                 label=r"$\Delta$ heat deficit (MJ m$^{-2}$)")
    ax.set_title(f"{title}\n($\\pm${lim:.1f} MJ m$^{{-2}}$; red = 1st deeper)")
    _annotate(ax, annotation)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
