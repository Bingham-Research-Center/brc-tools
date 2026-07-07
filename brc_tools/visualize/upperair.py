"""Upper-air / constant-surface maps for WRF cold-pool analysis.

Interpolate a 3-D field to a constant geometric-height (or pressure) surface,
mask below-ground points, and render the surface with wind barbs and temperature
advection.  The crest-height surface (~2200 m ASL / ~780 hPa) is where warm-air
advection caps and reinforces the cold pool.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

KT = 1.94384


def interp_to_height_surface(field3d, z3d_asl, target_m: float) -> np.ndarray:
    """Interpolate ``field3d`` (nz, ny, nx) to a constant height; NaN below ground.

    ``z3d_asl`` must increase along axis 0 (mass levels, geometric height ASL).
    """
    field3d = np.asarray(field3d, dtype=float)
    z3d = np.asarray(z3d_asl, dtype=float)
    nz, ny, nx = field3d.shape
    above = z3d >= target_m
    inside = above.any(axis=0) & (z3d[0] <= target_m)
    k_above = np.clip(np.argmax(above, axis=0), 1, nz - 1)
    k_below = k_above - 1
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    z_b = z3d[k_below, jj, ii]
    z_a = z3d[k_above, jj, ii]
    f_b = field3d[k_below, jj, ii]
    f_a = field3d[k_above, jj, ii]
    with np.errstate(invalid="ignore", divide="ignore"):
        weight = (target_m - z_b) / (z_a - z_b)
    out = f_b + weight * (f_a - f_b)
    out[~inside] = np.nan
    return out


def interp_to_pressure_surface(field3d, p3d_pa, target_pa: float) -> np.ndarray:
    """Interpolate ``field3d`` to a constant pressure; NaN below ground.

    Pressure decreases with level, so we interpolate on ``-p`` (which increases).
    """
    return interp_to_height_surface(field3d, -np.asarray(p3d_pa, dtype=float), -float(target_pa))


def below_ground_mask(target_m: float, terrain2d) -> np.ndarray:
    """True where ``target_m`` is below the terrain (surface intersects the plane)."""
    return target_m < np.asarray(terrain2d)


def temperature_advection(temp2d, u2d, v2d, dx_m: float, dy_m: float) -> np.ndarray:
    """Horizontal temperature advection ``-V . grad(T)`` (K s-1)."""
    temp2d = np.asarray(temp2d, dtype=float)
    d_dy, d_dx = np.gradient(temp2d, dy_m, dx_m)
    return -(np.asarray(u2d) * d_dx + np.asarray(v2d) * d_dy)


def plot_height_surface(
    lon,
    lat,
    theta2d,
    u2d,
    v2d,
    out_path: str | Path,
    *,
    temp_adv2d=None,
    terrain=None,
    target_label: str,
    style=None,
    mask=None,
    adv_smooth_sigma: float = 1.0,
    waypoints: dict | None = None,
    wind_barbs: bool = True,
    barb_stride: int = 20,
    title: str,
    annotation: str | None = None,
    figsize: tuple[float, float] = (9.0, 7.5),
    dpi: int = 300,
) -> Path:
    """Render a constant-surface field with wind barbs and temperature advection."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.grid import terrain_contour_levels
    from brc_tools.visualize.style import get_style

    style = style or get_style("theta_crest")
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    theta = np.asarray(theta2d, dtype=float)
    if mask is not None:
        theta = np.where(mask, np.nan, theta)
    out = Path(out_path)

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    mesh = ax.pcolormesh(lon, lat, theta, shading="auto", cmap=style.cmap,
                         vmin=style.vmin, vmax=style.vmax, alpha=0.95)
    fig.colorbar(mesh, ax=ax, shrink=0.8, extend=style.extend, label=style.label)

    if temp_adv2d is not None:
        adv = np.asarray(temp_adv2d, dtype=float) * 3600.0  # K h-1
        if adv_smooth_sigma and adv_smooth_sigma > 0:
            # NaN-aware Gaussian smoothing to tame noisy gradients near terrain
            from scipy.ndimage import gaussian_filter

            finite = np.isfinite(adv)
            filled = gaussian_filter(np.where(finite, adv, 0.0), adv_smooth_sigma)
            weight = gaussian_filter(finite.astype(float), adv_smooth_sigma)
            adv = np.where(weight > 0, filled / weight, np.nan)
        if mask is not None:
            adv = np.where(mask, np.nan, adv)
        levels = np.array([-3, -2, -1, -0.5, 0.5, 1, 2, 3], dtype=float)
        colors = ["blue" if lv < 0 else "red" for lv in levels]
        lines = ax.contour(lon, lat, adv, levels=levels, colors=colors, linewidths=0.6)
        ax.clabel(lines, fontsize=6, fmt="%.1f")

    if wind_barbs and u2d is not None and v2d is not None:
        u = np.asarray(u2d)
        v = np.asarray(v2d)
        sy = max(1, u.shape[0] // barb_stride)
        sx = max(1, u.shape[1] // barb_stride)
        ax.barbs(lon[::sy, ::sx], lat[::sy, ::sx],
                 (u * KT)[::sy, ::sx], (v * KT)[::sy, ::sx], length=5, linewidth=0.5)

    if terrain is not None:
        levels_t = terrain_contour_levels(np.asarray(terrain))
        if levels_t is not None:
            ax.contour(lon, lat, np.asarray(terrain), levels=levels_t,
                       colors="0.4", linewidths=0.25, alpha=0.4)

    if waypoints:
        for name, wp in waypoints.items():
            ax.plot(wp["lon"], wp["lat"], marker="^", color="black", ms=4)
            ax.text(wp["lon"], wp["lat"], f" {name}", fontsize=6)

    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"{title} | {target_label}")
    ax.set_aspect(1.0 / np.cos(np.deg2rad(float(np.mean(lat)))))
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
