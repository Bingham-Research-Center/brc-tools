"""Terrain-following vertical cross-sections for WRF cold-pool analysis.

Renders a grid-axis-aligned :class:`~brc_tools.nwp.wrf_output.WRFSection`:
potential temperature filled on native eta levels (drawn at true geometric
height, so the mesh is terrain-following), model terrain filled beneath, the
in-plane wind as an exaggerated quiver, and two insets — a locator (where the
section cuts the domain, termini A-B / C-D) and a shallow-layer zoom for the
cold pool.

Like the rest of ``visualize`` this consumes plain arrays / dataclasses and owns
only the Matplotlib rendering; the extraction lives in ``nwp/wrf_output.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Accent colours per section so the termini read consistently between the main
# x-axis and the locator inset (warm for E-W, cool for N-S).
_ACCENT = {"EW": "#c62828", "NS": "#1565c0"}


def _terrain_floor(terrain: np.ndarray) -> float:
    return float(np.floor(np.nanmin(terrain) / 100.0) * 100.0 - 50.0)


def _quiver_in_plane(ax, x2d, z2d, along, w, exagg, stride):
    """Draw the in-plane (along-section, exaggerated w) wind quiver."""
    sz, sx = stride
    q = ax.quiver(
        x2d[::sz, ::sx],
        z2d[::sz, ::sx],
        np.asarray(along)[::sz, ::sx],
        np.asarray(w)[::sz, ::sx] * exagg,
        color="black",
        width=0.0016,
        alpha=0.85,
        zorder=8,
    )
    ax.quiverkey(
        q,
        0.83,
        1.02,
        10.0,
        rf"10 m s$^{{-1}}$ along, $w\times${int(exagg)}",
        labelpos="E",
        coordinates="axes",
        fontproperties={"size": 7},
    )


def _locator_inset(ax, section, terrain2d, accent):
    """Small terrain map showing where the section cuts the domain."""
    axins = ax.inset_axes([0.69, 0.68, 0.30, 0.30])
    t = np.asarray(terrain2d)
    ny, nx = t.shape
    axins.imshow(t, origin="lower", cmap="Greys", aspect="auto")
    kw = dict(color=accent, fontsize=8, fontweight="bold", ha="center", va="center")
    if section.orientation == "EW":
        axins.axhline(section.center_index, color=accent, lw=1.4)
        axins.text(-0.06 * nx, section.center_index, section.termini[0], **kw)
        axins.text(1.06 * nx, section.center_index, section.termini[1], **kw)
    else:
        axins.axvline(section.center_index, color=accent, lw=1.4)
        axins.text(section.center_index, -0.06 * ny, section.termini[0], **kw)
        axins.text(section.center_index, 1.06 * ny, section.termini[1], **kw)
    axins.set_xticks([])
    axins.set_yticks([])
    for spine in axins.spines.values():
        spine.set_edgecolor(accent)


def _shallow_inset(ax, section, style, x2d, z2d, field, dist, terrain, layer_m, levels):
    """Zoom of the lowest ``layer_m`` for cold-pool lamination."""
    axins = ax.inset_axes([0.03, 0.66, 0.42, 0.31])
    axins.set_facecolor("0.55")
    axins.pcolormesh(
        x2d, z2d, field, cmap=style.cmap, vmin=style.vmin, vmax=style.vmax,
        shading="gouraud",
    )
    y_bottom = _terrain_floor(terrain)
    axins.fill_between(dist, y_bottom, terrain, color="0.55", linewidth=0, zorder=6)
    axins.contour(x2d, z2d, field, levels=levels, colors="black", linewidths=0.3, alpha=0.5)
    axins.set_ylim(y_bottom, float(np.nanmin(terrain)) + layer_m)
    axins.set_xlim(float(dist.min()), float(dist.max()))
    axins.tick_params(labelsize=6)
    axins.set_title(f"cold-pool layer (lowest {int(layer_m)} m)", fontsize=7)


def plot_wrf_section(
    section,
    out_path: str | Path,
    *,
    style=None,
    title: str,
    annotation: str | None = None,
    contour_levels=None,
    w_exaggeration: float = 100.0,
    quiver_stride: tuple[int, int] = (2, 6),
    y_pad_top_m: float = 1500.0,
    shallow_inset: bool = True,
    shallow_layer_m: float = 1000.0,
    locator_terrain=None,
    figsize: tuple[float, float] = (11.0, 6.0),
    dpi: int = 300,
) -> Path:
    """Render a terrain-filled, height-ASL potential-temperature cross-section."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.style import get_style

    style = style or get_style("theta")
    dist = np.asarray(section.distance_km)
    z2d = np.asarray(section.height2d)
    field = np.asarray(section.theta2d)
    terrain = np.asarray(section.terrain1d)
    x2d = np.tile(dist, (z2d.shape[0], 1))
    accent = _ACCENT.get(section.orientation, "#c62828")
    out = Path(out_path)

    if contour_levels is None:
        lo = style.vmin if style.vmin is not None else float(np.floor(np.nanmin(field)))
        hi = style.vmax if style.vmax is not None else float(np.ceil(np.nanmax(field)))
        contour_levels = np.arange(lo, hi + 0.1, 2.0)

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("0.55")  # sub-terrain gap (lowest mass level is above HGT) reads as terrain
    mesh = ax.pcolormesh(
        x2d, z2d, field, cmap=style.cmap, vmin=style.vmin, vmax=style.vmax,
        shading="gouraud",
    )
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend=style.extend, label=style.label)

    lines = ax.contour(x2d, z2d, field, levels=contour_levels, colors="black",
                       linewidths=0.4, alpha=0.55)
    ax.clabel(lines, lines.levels[::2], fontsize=6, fmt="%.0f")

    _quiver_in_plane(ax, x2d, z2d, section.along2d, section.w2d, w_exaggeration, quiver_stride)

    y_bottom = _terrain_floor(terrain)
    ax.fill_between(dist, y_bottom, terrain, color="0.55", linewidth=0, zorder=6)
    ax.plot(dist, terrain, color="black", linewidth=0.7, zorder=7)

    ax.set_ylim(y_bottom, float(np.nanmax(terrain)) + y_pad_top_m)
    ax.set_xlim(float(dist.min()), float(dist.max()))
    ax.set_xlabel("distance (km)")
    ax.set_ylabel("height (m MSL)")
    ax.set_title(title)

    # termini on the main x-axis, colour-matched to the locator inset
    tkw = dict(color=accent, fontsize=11, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, -0.09, section.termini[0], ha="left", va="top", **tkw)
    ax.text(1.0, -0.09, section.termini[1], ha="right", va="top", **tkw)

    if shallow_inset:
        _shallow_inset(ax, section, style, x2d, z2d, field, dist, terrain,
                       shallow_layer_m, contour_levels)
    if locator_terrain is not None:
        _locator_inset(ax, section, locator_terrain, accent)

    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.55, "pad": 1.5})

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def _interp_columns_to_heights(field2d, height2d, target):
    """Interpolate each column of ``field2d`` (on ``height2d``) onto ``target`` heights."""
    field2d = np.asarray(field2d)
    height2d = np.asarray(height2d)
    n = field2d.shape[1]
    out = np.full((target.size, n), np.nan)
    for i in range(n):
        out[:, i] = np.interp(target, height2d[:, i], field2d[:, i], left=np.nan, right=np.nan)
    return out


def plot_wrf_section_difference(
    section_a,
    section_b,
    out_path: str | Path,
    *,
    var: str = "theta",
    limit: float | None = None,
    target_heights=None,
    title: str,
    annotation: str | None = None,
    y_pad_top_m: float = 1500.0,
    locator_terrain=None,
    figsize: tuple[float, float] = (11.0, 6.0),
    dpi: int = 300,
) -> Path:
    """Render (section_a - section_b) potential temperature on a shared height axis.

    The two sections share the (identical) d03 grid, but perturbation geopotential
    differs slightly, so both are interpolated onto a common ASL axis before the
    difference is taken.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.style import diff_style

    style = diff_style(var, limit=limit)
    dist = np.asarray(section_a.distance_km)
    terrain = np.asarray(section_a.terrain1d)
    accent = _ACCENT.get(section_a.orientation, "#c62828")
    out = Path(out_path)

    y_bottom = _terrain_floor(terrain)
    y_top = float(np.nanmax(terrain)) + y_pad_top_m
    if target_heights is None:
        target_heights = np.arange(y_bottom, y_top + 1.0, 25.0)
    target_heights = np.asarray(target_heights)

    fa = _interp_columns_to_heights(section_a.theta2d, section_a.height2d, target_heights)
    fb = _interp_columns_to_heights(section_b.theta2d, section_b.height2d, target_heights)
    diff = fa - fb

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("0.55")  # below-ground NaN cells read as terrain, not white
    mesh = ax.pcolormesh(dist, target_heights, diff, cmap=style.cmap,
                         vmin=style.vmin, vmax=style.vmax, shading="nearest")
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend="both", label=style.label)
    ax.contour(dist, target_heights, diff, levels=[0.0], colors="black", linewidths=0.5)

    ax.fill_between(dist, y_bottom, terrain, color="0.55", linewidth=0, zorder=6)
    ax.plot(dist, terrain, color="black", linewidth=0.7, zorder=7)
    ax.set_ylim(y_bottom, y_top)
    ax.set_xlim(float(dist.min()), float(dist.max()))
    ax.set_xlabel("distance (km)")
    ax.set_ylabel("height (m MSL)")
    ax.set_title(title)

    tkw = dict(color=accent, fontsize=11, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, -0.09, section_a.termini[0], ha="left", va="top", **tkw)
    ax.text(1.0, -0.09, section_a.termini[1], ha="right", va="top", **tkw)

    if locator_terrain is not None:
        _locator_inset(ax, section_a, locator_terrain, accent)
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.55, "pad": 1.5})

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
