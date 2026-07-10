"""Nested-domain map for WRF configurations (a prettier geogrid-style figure).

Draws each domain's boundary ring (from :func:`brc_tools.nwp.wrf_output.domain_outline`)
over an optional d01 terrain basemap.  Kept cartopy-free so it renders on offline
compute nodes; the richer political/hydrographic overlays live in ``planview``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def plot_domain_boxes(
    outlines,
    out_path: str | Path,
    *,
    terrain=None,
    terrain_lonlat=None,
    extent: tuple[float, float, float, float] | None = None,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    box_colors=None,
    title: str,
    figsize: tuple[float, float] = (8.5, 8.0),
    dpi: int = 300,
) -> Path:
    """Render nested domain boxes over an optional terrain basemap."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.grid import terrain_contour_levels

    out = Path(out_path)
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)

    if terrain is not None and terrain_lonlat is not None:
        lon2d, lat2d = (np.asarray(a) for a in terrain_lonlat)
        levels = terrain_contour_levels(np.asarray(terrain))
        cf = ax.contourf(
            lon2d, lat2d, np.asarray(terrain),
            levels=levels if levels is not None else 20, cmap="terrain", alpha=0.9,
        )
        fig.colorbar(cf, ax=ax, shrink=0.8, label="terrain height (m MSL)")

    colors = box_colors or ["#111111", "#c62828", "#1565c0", "#2e7d32"]
    for k, outline in enumerate(outlines):
        color = colors[k % len(colors)]
        ax.plot(outline.lon_ring, outline.lat_ring, color=color, lw=1.8, label=outline.label)
        ax.text(
            float(np.min(outline.lon_ring)), float(np.max(outline.lat_ring)), outline.label,
            color=color, fontsize=9, fontweight="bold", va="bottom", ha="left",
        )

    if terrain_lonlat is not None:
        lon2d, lat2d = (np.asarray(a) for a in terrain_lonlat)
        ov_extent = (float(lon2d.min()), float(lon2d.max()),
                     float(lat2d.min()), float(lat2d.max()))
    else:
        lons = np.concatenate([o.lon_ring for o in outlines])
        lats = np.concatenate([o.lat_ring for o in outlines])
        ov_extent = (float(lons.min()), float(lons.max()),
                     float(lats.min()), float(lats.max()))

    if overlays and any(overlays.values()):
        from brc_tools.visualize.basemap import add_reference_overlays

        add_reference_overlays(ax, ov_extent, layers=overlays)

    if waypoints:
        from brc_tools.visualize.basemap import draw_waypoints

        draw_waypoints(ax, waypoints, ov_extent, ms=5)

    if extent is not None:
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8)
    mid_lat = float(np.mean(ax.get_ylim()))
    ax.set_aspect(1.0 / np.cos(np.deg2rad(mid_lat)))  # keep lon/lat visually proportional

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
