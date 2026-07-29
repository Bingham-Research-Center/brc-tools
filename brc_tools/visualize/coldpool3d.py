"""3-D terrain view with the cold pool filled beneath a chosen isentrope.

Answers "how far has cold air filled the canyons and the basin floor?" in the one
projection where the answer is legible: the terrain as a shaded surface, and above
it the θ = θ_iso surface drawn as a translucent lid, coloured by the depth of air
it caps.  Where the ground is already warmer than θ_iso the lid is absent, so the
pool's shoreline is exactly where the coloured sheet stops -- the visual analogue
of a contour of the isentrope's intersection with the terrain.

Choosing θ_iso is the whole interpretation. It is an *absolute* threshold, so a
fixed value across a sweep of times shows the pool growing as the surface cools --
which is the point. Pick one a little below the current basin-floor θ and it starts
as a sliver on the coldest ground and fills upward and outward through the night.

Physics here, Matplotlib in the renderer, as elsewhere in the package.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["isentrope_lid", "extent_window", "plot_coldpool_3d"]

_KM_PER_DEG_LAT = 110.574
_KM_PER_DEG_LON = 111.320


def isentrope_lid(theta3d, height3d, terrain, theta_iso: float, *,
                  max_depth_m: float = 1500.0) -> np.ndarray:
    """Height (m ASL) of the lowest θ = ``theta_iso`` surface above ground.

    Returns NaN for columns with no cold pool -- either the ground is already at or
    above ``theta_iso`` (nothing to cap), or the isentrope sits more than
    ``max_depth_m`` above the surface, which means the column is well mixed rather
    than pooled and drawing a lid there would invent a feature.

    Assumes θ increases upward through the capping layer, which is what "pool
    beneath an isentrope" means; the search takes the *lowest* crossing, so a
    residual layer higher up does not spoof a deeper pool.
    """
    theta = np.asarray(theta3d, dtype=float)
    z = np.asarray(height3d, dtype=float)
    terr = np.asarray(terrain, dtype=float)

    above = theta >= float(theta_iso)
    has = above.any(axis=0)
    k = np.where(has, above.argmax(axis=0), 0)  # lowest crossing level

    ny, nx = terr.shape
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    th_hi, z_hi = theta[k, jj, ii], z[k, jj, ii]
    kl = np.maximum(k - 1, 0)
    th_lo, z_lo = theta[kl, jj, ii], z[kl, jj, ii]

    with np.errstate(invalid="ignore", divide="ignore"):
        frac = (float(theta_iso) - th_lo) / (th_hi - th_lo)
    lid = np.where(k > 0, z_lo + np.clip(frac, 0.0, 1.0) * (z_hi - z_lo), np.nan)

    lid = np.where(has, lid, np.nan)          # never reaches theta_iso
    lid = np.where(k > 0, lid, np.nan)        # ground already >= theta_iso: no pool
    depth = lid - terr
    return np.where((depth > 0.0) & (depth <= max_depth_m), lid, np.nan)


def extent_window(lon2d, lat2d, extent) -> tuple[slice, slice]:
    """``(row_slice, col_slice)`` for the smallest index rectangle covering a lon/lat box.

    Returning the *window* rather than cropped copies is what lets a caller apply
    the identical crop to 2-D and 3-D fields (``field[..., rows, cols]``); cropping
    in index space also keeps the arrays rectangular, which ``plot_surface`` needs
    on a curvilinear grid.
    """
    lon = np.asarray(lon2d, dtype=float)
    lat = np.asarray(lat2d, dtype=float)
    lon0, lon1, lat0, lat1 = extent
    inside = (lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1)
    if not inside.any():
        raise ValueError(f"extent {extent} does not overlap the grid")
    rows = np.where(inside.any(axis=1))[0]
    cols = np.where(inside.any(axis=0))[0]
    return slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1)


def plot_coldpool_3d(
    lon2d,
    lat2d,
    terrain,
    lid,
    out_path,
    *,
    theta_iso: float,
    title: str,
    annotation: str | None = None,
    stride: int = 2,
    elev: float = 22.0,
    azim: float = -90.0,
    z_frac: float = 0.45,
    depth_min_m: float = 25.0,
    depth_max_m: float = 300.0,
    terrain_cmap: str = "gray",
    pool_cmap: str = "YlGnBu",
    figsize: tuple[float, float] = (11.0, 8.0),
    dpi: int = 200,
) -> Path:
    """Render the terrain surface with the θ_iso lid floating above it.

    ``azim = -90`` puts the camera due south of the scene looking **north**, so a
    canyon draining southward runs toward the viewer.  ``z_frac`` sets the vertical
    exaggeration as a fraction of the wider horizontal side -- an absolute
    exaggeration factor would look wildly different between a 20 km and a 200 km
    window, whereas this keeps every view comparably readable.

    The terrain is deliberately **neutral hillshaded grey**, not a height ramp: an
    earth colormap puts blue at its low end, which on this figure reads as pooled
    air and competes with the thing being measured.  All colour is reserved for the
    lid, shaded by its own depth (lid − terrain) between ``depth_min_m`` and
    ``depth_max_m``.  The lower cut matters: with an isentrope only a kelvin above
    the surface, most of the domain carries a few metres of nominally "cold" air,
    and drawing it blankets the canyons the figure exists to show.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import colormaps, colors

    lon = np.asarray(lon2d, dtype=float)[::stride, ::stride]
    lat = np.asarray(lat2d, dtype=float)[::stride, ::stride]
    terr = np.asarray(terrain, dtype=float)[::stride, ::stride]
    lid = np.asarray(lid, dtype=float)[::stride, ::stride]

    # Local equirectangular km, so the box aspect is physical rather than degrees.
    lat_mid = float(np.mean(lat))
    x_km = (lon - lon.min()) * _KM_PER_DEG_LON * np.cos(np.deg2rad(lat_mid))
    y_km = (lat - lat.min()) * _KM_PER_DEG_LAT
    lx, ly = float(x_km.max()), float(y_km.max())
    dx_m = max(float(np.nanmean(np.diff(x_km, axis=1))) * 1000.0, 1.0)
    dy_m = max(float(np.nanmean(np.diff(y_km, axis=0))) * 1000.0, 1.0)

    depth = np.where(lid - terr >= depth_min_m, lid - terr, np.nan)
    norm = colors.Normalize(depth_min_m, depth_max_m)
    pool_rgba = colormaps[pool_cmap](norm(np.clip(depth, depth_min_m, depth_max_m)))
    pool_rgba[..., 3] = np.where(np.isfinite(depth), 0.92, 0.0)  # invisible off-pool

    # Pure hillshade, no elevation ramp: shape comes from the shading and height
    # from the z axis, which leaves darkness as well as hue free for the pool. A
    # height-coded terrain puts dark cells on the basin floor -- exactly where the
    # pool is -- and the two become impossible to tell apart.
    ls = colors.LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(terr, vert_exag=3.0, dx=dx_m, dy=dy_m)
    terr_rgb = colormaps[terrain_cmap](0.45 + 0.5 * hs)

    fig = plt.figure(figsize=figsize)
    # computed_zorder=False: let the draw order stand, so the lid is painted over
    # the terrain instead of Matplotlib's per-artist depth guess flickering between
    # frames of a sweep.
    ax = fig.add_subplot(projection="3d", computed_zorder=False)
    ax.plot_surface(x_km, y_km, terr, facecolors=terr_rgb, linewidth=0,
                    antialiased=False, rstride=1, cstride=1, shade=False, zorder=1)
    if np.isfinite(depth).any():
        ax.plot_surface(x_km, y_km, np.where(np.isfinite(depth), lid, np.nan),
                        facecolors=pool_rgba, linewidth=0, antialiased=False,
                        rstride=1, cstride=1, shade=False, zorder=3)
        cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=pool_cmap), ax=ax,
                          shrink=0.55, pad=0.02, extend="max")
        cb.set_label(rf"depth below $\theta$ = {theta_iso:g} K (m)")
    else:
        ax.text2D(0.5, 0.9, rf"no air below $\theta$ = {theta_iso:g} K",
                  transform=ax.transAxes, ha="center", fontsize=9, color="0.35")

    z_lo = float(np.floor(np.nanmin(terr) / 100.0) * 100.0)
    z_hi = float(np.ceil(np.nanmax(terr) / 100.0) * 100.0)
    ax.set_zlim(z_lo, z_hi)
    ax.set_box_aspect((lx, ly, max(lx, ly) * z_frac))
    ax.view_init(elev=elev, azim=azim)
    ax.set_xlabel("east (km)", labelpad=2)
    ax.set_ylabel("north (km)", labelpad=2)
    ax.set_zlabel("height (m ASL)", labelpad=2)
    ax.tick_params(labelsize=7)
    for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
        pane.pane.set_facecolor("white")
        pane.pane.set_edgecolor("0.85")
        pane._axinfo["grid"].update(color="0.9", linewidth=0.4)
    ax.set_title(title)
    # A 3-D axes leaves large empty margins by default; claw them back so the
    # terrain, not whitespace, is what the figure is mostly made of.
    fig.subplots_adjust(left=0.0, right=0.92, bottom=0.02, top=0.98)
    if annotation:
        ax.text2D(0.99, 0.01, annotation, transform=ax.transAxes, ha="right",
                  va="bottom", fontsize=6, alpha=0.65)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out
