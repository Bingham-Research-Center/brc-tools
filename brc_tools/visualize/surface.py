"""Multi-domain surface / near-surface panels and 2-D difference maps.

The surface suite shows the same field at d01 / d02 / d03 with a *shared* colour
scale (and, optionally, a shared geographic crop) so the resolution comparison is
fair.  Difference maps reuse ``grid.plot_grid_field`` with a diverging style.

Plain-matplotlib (lon/lat) for offline robustness; the richer cartopy political /
hydrographic overlays are layered in via ``planview`` (Phase 4).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def plot_domain_panels(
    panels,
    out_path: str | Path,
    *,
    style,
    wind: bool = False,
    wind_scale: float = 300.0,
    wind_ref: float = 5.0,
    terrain_contours: bool = True,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    extent: tuple[float, float, float, float] | None = None,
    suptitle: str,
    dpi: int = 300,
) -> Path:
    """Render one field across several domains with a shared colorbar.

    ``panels`` is a list of dicts with keys ``label``, ``lon``, ``lat``, ``field``
    and optionally ``terrain``, ``u``, ``v``.  ``extent`` (lon0, lon1, lat0, lat1)
    crops every panel to the same area for a like-for-like resolution comparison.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.grid import terrain_contour_levels
    from brc_tools.visualize.style import shared_range

    out = Path(out_path)
    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(4.8 * n, 5.2), constrained_layout=True)
    if n == 1:
        axes = [axes]

    vmin, vmax = style.vmin, style.vmax
    if vmin is None or vmax is None:
        vmin, vmax = shared_range(*[p["field"] for p in panels])

    mesh = None
    quiver = None
    for ax, p in zip(axes, panels):
        lon = np.asarray(p["lon"])
        lat = np.asarray(p["lat"])
        field = np.asarray(p["field"])
        mesh = ax.pcolormesh(lon, lat, field, shading="auto", cmap=style.cmap,
                             vmin=vmin, vmax=vmax, alpha=0.95)
        if terrain_contours and p.get("terrain") is not None:
            levels = terrain_contour_levels(np.asarray(p["terrain"]))
            if levels is not None:
                ax.contour(lon, lat, np.asarray(p["terrain"]), levels=levels,
                           colors="black", linewidths=0.3, alpha=0.4)
        if wind and p.get("u") is not None and p.get("v") is not None:
            u = np.asarray(p["u"])
            v = np.asarray(p["v"])
            sy = max(1, u.shape[0] // 22)
            sx = max(1, u.shape[1] // 22)
            quiver = ax.quiver(lon[::sy, ::sx], lat[::sy, ::sx], u[::sy, ::sx], v[::sy, ::sx],
                               color="black", scale=wind_scale, width=0.004, alpha=0.7)
        panel_extent = extent or (
            float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())
        )
        if overlays and any(overlays.values()):
            from brc_tools.visualize.basemap import add_reference_overlays

            add_reference_overlays(ax, panel_extent, layers=overlays)
        if waypoints:
            from brc_tools.visualize.basemap import draw_waypoints

            draw_waypoints(ax, waypoints, panel_extent, zorder=6)
        if extent is not None:
            ax.set_xlim(extent[0], extent[1])
            ax.set_ylim(extent[2], extent[3])
        ax.set_title(p["label"])
        ax.set_xlabel("longitude")
        ax.set_aspect(1.0 / np.cos(np.deg2rad(float(np.mean(lat)))))
    axes[0].set_ylabel("latitude")
    if quiver is not None:
        axes[-1].quiverkey(quiver, 0.88, 1.02, wind_ref, f"{wind_ref:g} m s$^{{-1}}$",
                           labelpos="E", coordinates="axes", fontproperties={"size": 7})

    fig.colorbar(mesh, ax=axes, shrink=0.85, extend=style.extend, label=style.label)
    fig.suptitle(suptitle)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_field_difference(
    lon,
    lat,
    field_a,
    field_b,
    out_path: str | Path,
    *,
    var: str,
    limit: float | None = None,
    title: str,
    terrain=None,
    wind_u=None,
    wind_v=None,
    annotation: str | None = None,
    dpi: int = 300,
) -> Path:
    """Render (field_a - field_b) as a diverging map (reuses grid.plot_grid_field)."""
    from brc_tools.visualize.grid import plot_grid_field, terrain_contour_levels
    from brc_tools.visualize.style import diff_style

    style = diff_style(var, limit=limit)
    diff = np.asarray(field_a) - np.asarray(field_b)
    contour_levels = terrain_contour_levels(np.asarray(terrain)) if terrain is not None else None
    return plot_grid_field(
        lon, lat, diff, out_path,
        title=title, colorbar_label=style.label, cmap=style.cmap,
        vmin=style.vmin, vmax=style.vmax,
        contour=terrain, contour_levels=contour_levels,
        wind_u=wind_u, wind_v=wind_v, annotation=annotation, dpi=dpi,
    )
