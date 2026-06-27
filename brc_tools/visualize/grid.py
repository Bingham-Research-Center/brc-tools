"""Array-based gridded plotting helpers.

These helpers intentionally accept plain arrays instead of project-specific
datasets.  Callers keep the responsibility for opening files and deriving
variables; this module standardises the actual Matplotlib rendering choices.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def terrain_contour_levels(values: Any) -> np.ndarray | None:
    """Return readable terrain contour levels for a wide range of domains."""
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return None

    low = float(np.nanmin(finite))
    high = float(np.nanmax(finite))
    if low == high:
        return None

    for interval in (50.0, 100.0, 150.0, 200.0, 250.0, 500.0):
        start = np.floor(low / interval) * interval
        stop = np.ceil(high / interval) * interval
        levels = np.arange(start, stop + interval, interval)
        if 4 <= levels.size <= 34:
            return levels

    return np.linspace(low, high, 24)


def data_contour_levels(values: Any, *, target_count: int = 12) -> np.ndarray | None:
    """Return simple evenly spaced contour levels for a finite field."""
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return None

    low = float(np.nanmin(finite))
    high = float(np.nanmax(finite))
    if low == high:
        return None
    return np.linspace(low, high, target_count)


def plot_grid_field(
    lon: Any,
    lat: Any,
    field: Any,
    out_path: str | Path,
    *,
    title: str,
    colorbar_label: str,
    cmap: str = "RdYlBu_r",
    vmin: float | None = None,
    vmax: float | None = None,
    alpha: float = 0.92,
    contour: Any | None = None,
    contour_levels: Any | None = None,
    contour_label: bool = False,
    contour_colors: str = "black",
    contour_linewidths: float = 0.35,
    contour_alpha: float = 0.55,
    wind_u: Any | None = None,
    wind_v: Any | None = None,
    wind_label: str = "5 m s-1",
    wind_reference: float = 5.0,
    wind_scale: float = 450.0,
    wind_max_vectors: int = 24,
    annotation: str | None = None,
    figsize: tuple[float, float] = (8.5, 6.5),
    dpi: int = 150,
) -> Path:
    """Render a lat-lon pcolormesh field with optional contours and vectors."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lon = np.asarray(lon)
    lat = np.asarray(lat)
    field = np.asarray(field)
    out = Path(out_path)

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    mesh = ax.pcolormesh(
        lon,
        lat,
        field,
        shading="nearest",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        alpha=alpha,
    )
    fig.colorbar(mesh, ax=ax, shrink=0.8, label=colorbar_label)

    if contour is not None:
        contour_values = np.asarray(contour)
        levels = contour_levels
        if levels is None:
            levels = data_contour_levels(contour_values)
        if levels is not None:
            lines = ax.contour(
                lon,
                lat,
                contour_values,
                levels=levels,
                colors=contour_colors,
                linewidths=contour_linewidths,
                alpha=contour_alpha,
            )
            if contour_label:
                ax.clabel(lines, fontsize=5, fmt="%.0f")

    if wind_u is not None and wind_v is not None:
        u = np.asarray(wind_u)
        v = np.asarray(wind_v)
        stride_y = max(1, u.shape[0] // wind_max_vectors)
        stride_x = max(1, u.shape[1] // wind_max_vectors)
        quiver = ax.quiver(
            lon[::stride_y, ::stride_x],
            lat[::stride_y, ::stride_x],
            u[::stride_y, ::stride_x],
            v[::stride_y, ::stride_x],
            color="black",
            scale=wind_scale,
            width=0.0022,
            alpha=0.75,
        )
        ax.quiverkey(
            quiver,
            0.08,
            0.94,
            wind_reference,
            wind_label,
            coordinates="axes",
            labelpos="E",
            fontproperties={"size": 7},
        )

    ax.set_title(title)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    if annotation:
        ax.text(
            0.99,
            0.01,
            annotation,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=6,
            alpha=0.65,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.55, "pad": 1.5},
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_vertical_section(
    distance_km: Any,
    height_m: Any,
    field: Any,
    out_path: str | Path,
    *,
    title: str,
    colorbar_label: str,
    xlabel: str = "distance (km)",
    ylabel: str = "height AGL (m)",
    cmap: str = "RdYlBu_r",
    alpha: float = 0.94,
    contour_levels: Any | None = None,
    line_y: Any | None = None,
    line_label: str | None = None,
    y_max: float | None = 3000.0,
    annotation: str | None = None,
    figsize: tuple[float, float] = (10.5, 5.5),
    dpi: int = 150,
) -> Path:
    """Render a vertical cross-section from precomputed distance/height arrays."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    distance = np.asarray(distance_km)
    height = np.asarray(height_m)
    values = np.asarray(field)
    out = Path(out_path)

    x_grid = np.tile(distance, (values.shape[0], 1))
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    mesh = ax.pcolormesh(x_grid, height, values, shading="nearest", cmap=cmap, alpha=alpha)
    fig.colorbar(mesh, ax=ax, shrink=0.85, label=colorbar_label)

    levels = contour_levels
    if levels is None:
        finite = values[np.isfinite(values) & np.isfinite(height)]
        if y_max is not None:
            finite = values[np.isfinite(values) & np.isfinite(height) & (height <= y_max)]
        if finite.size:
            levels = np.arange(
                np.floor(float(np.nanmin(finite))),
                np.ceil(float(np.nanmax(finite))) + 1.0,
                1.0,
            )
    if levels is not None and len(levels) > 1:
        lines = ax.contour(
            x_grid,
            height,
            values,
            levels=levels,
            colors="black",
            linewidths=0.35,
            alpha=0.5,
        )
        ax.clabel(lines, fontsize=5, fmt="%.0f")

    if line_y is not None:
        line = np.asarray(line_y)
        ax.plot(distance, line, color="black", linewidth=2.4, alpha=0.75)
        ax.plot(distance, line, color="white", linewidth=1.3, label=line_label)
        if line_label:
            ax.legend(loc="upper right")

    if y_max is not None:
        ax.set_ylim(0.0, y_max)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if annotation:
        ax.text(
            0.99,
            0.01,
            annotation,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=6,
            alpha=0.65,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.55, "pad": 1.5},
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
