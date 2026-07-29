"""Cross-section curtains drawn on WRF's own grid — no resampling, no smoothing.

The isobaric renderer in :mod:`brc_tools.visualize.nwp_maps` has to interpolate
each column onto a regular height axis and shade it ``gouraud``: with 13 pressure
levels a flat-shaded curtain would be a stack of 13 fat bands, so the smoothing is
buying back detail that GRIB never had.

A WRF section is the opposite case. It arrives on ~80 stretched eta levels whose
spacing near the ground is metres, and the model's own cells *are* the resolution.
Resampling them onto a regular ``dz`` axis and blurring across cells throws away
exactly the near-surface structure a drainage study is looking for, and quietly
invents a smooth field where the model has a staircase. So: shade the true cells
with ``pcolormesh(..., shading="flat")`` on the w-level edges, contour and quiver
on the mass points, and let the terrain-following staircase show.

Everything else — the locator inset, the along-line town markers, the terminus
labels — is the shared basin-winds furniture, reused from ``nwp_maps`` so the two
figure families still read as one system.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# Private, deliberately: these draw the shared section furniture and are frozen
# alongside the rest of visualize/* for the pelican2013 study.  Re-implementing
# them here to avoid touching a private name would fork the look of every figure
# the moment one copy is retuned.
from brc_tools.visualize.nwp_maps import _draw_section_towns, _geo_locator_inset
from brc_tools.visualize.style import get_style

__all__ = ["curtain_mesh", "plot_wrf_curtain"]

_ACCENT = "#c0392b"
_SHADE_FIELD = {"speed": "speed2d", "theta": "theta2d", "temp": "temp2d",
                "along": "along2d", "w": "w2d", "theta_e": "thetae2d"}


def _edges1d(centres: np.ndarray) -> np.ndarray:
    """``(n,)`` cell centres → ``(n+1,)`` edges, extrapolating half a cell at each end."""
    c = np.asarray(centres, dtype=float)
    if c.size == 1:
        return np.array([c[0] - 0.5, c[0] + 0.5])
    mid = 0.5 * (c[1:] + c[:-1])
    return np.concatenate([[2 * c[0] - mid[0]], mid, [2 * c[-1] - mid[-1]]])


def curtain_mesh(section) -> tuple[np.ndarray, np.ndarray]:
    """Cell-corner arrays ``(X, Y)``, each ``(nz+1, n+1)``, for flat shading.

    Vertical corners come from ``section.height_w2d`` — WRF's w levels, which are
    the true cell edges — when present, and from midpoints between mass levels
    otherwise.  Horizontal corners are midpoints between the sampled columns.
    """
    dist = np.asarray(section.distance_km, dtype=float)
    zm = np.asarray(section.height2d, dtype=float)  # (nz, n)
    nz, n = zm.shape

    if getattr(section, "height_w2d", None) is not None:
        z_edge = np.asarray(section.height_w2d, dtype=float)  # (nz+1, n)
    else:
        inner = 0.5 * (zm[1:, :] + zm[:-1, :])
        z_edge = np.vstack([2 * zm[:1, :] - inner[:1, :],
                            inner,
                            2 * zm[-1:, :] - inner[-1:, :]])

    # (nz+1, n) column-centred edges -> (nz+1, n+1) corners.
    inner = 0.5 * (z_edge[:, 1:] + z_edge[:, :-1])
    Y = np.hstack([(2 * z_edge[:, :1] - inner[:, :1]),
                   inner,
                   (2 * z_edge[:, -1:] - inner[:, -1:])])
    X = np.broadcast_to(_edges1d(dist), (nz + 1, n + 1))
    return np.asarray(X), Y


def plot_wrf_curtain(
    section,
    out_path,
    *,
    shade: str = "speed",
    style=None,
    title: str,
    annotation: str | None = None,
    theta_contours: bool = True,
    theta_interval: float = 1.0,
    w_exaggeration: float = 10.0,
    quiver_stride: tuple[int, int] = (4, 10),
    y_top_m: float = 3000.0,
    y_bottom_m: float | None = None,
    waypoints: dict | None = None,
    waypoint_offset_km: float = 15.0,
    locator: dict | None = None,
    figsize: tuple[float, float] = (11.0, 6.2),
    dpi: int = 200,
) -> Path:
    """Render an :class:`~brc_tools.nwp.section.NWPSection` on its native grid.

    ``shade`` picks the shaded field (``speed``, ``theta``, ``temp``, ``along``,
    ``w``, ``theta_e``). ``theta_interval`` defaults to 1 K rather than the
    isobaric renderer's 2 K: a nocturnal inversion does its work in the first few
    kelvin, and on the native grid there is resolution to show it.

    ``w_exaggeration`` scales the vertical component of the in-plane vectors and is
    a property of the *regime*, not the plot geometry — see ``docs/WRF-WINDS.md``.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if shade not in _SHADE_FIELD:
        raise ValueError(f"shade must be one of {sorted(_SHADE_FIELD)}, got {shade!r}")
    field = getattr(section, _SHADE_FIELD[shade], None)
    if field is None:
        raise ValueError(f"section carries no {_SHADE_FIELD[shade]} for shade={shade!r}")

    st = style if style is not None else get_style("wind_speed_10m")
    dist = np.asarray(section.distance_km, dtype=float)
    terrain = np.asarray(section.terrain1d, dtype=float)
    zm = np.asarray(section.height2d, dtype=float)
    X, Y = curtain_mesh(section)

    y_bottom = (y_bottom_m if y_bottom_m is not None
                else float(np.floor(np.nanmin(terrain) / 100.0) * 100.0 - 50.0))

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("0.6")
    mesh = ax.pcolormesh(X, Y, np.asarray(field, dtype=float), cmap=st.cmap,
                         vmin=st.vmin, vmax=st.vmax, shading="flat")
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend=st.extend, label=st.label)

    dist2d = np.broadcast_to(dist, zm.shape)
    if theta_contours:
        theta = np.asarray(section.theta2d, dtype=float)
        lo = np.floor(np.nanmin(theta) / theta_interval) * theta_interval
        hi = np.ceil(np.nanmax(theta) / theta_interval) * theta_interval
        cs = ax.contour(dist2d, zm, theta, levels=np.arange(lo, hi + 0.1, theta_interval),
                        colors="black", linewidths=0.4, alpha=0.5)
        ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%.0f")

    sz, sx = quiver_stride
    q = ax.quiver(dist2d[::sz, ::sx], zm[::sz, ::sx],
                  np.asarray(section.along2d, dtype=float)[::sz, ::sx],
                  np.asarray(section.w2d, dtype=float)[::sz, ::sx] * w_exaggeration,
                  color="black", width=0.0016, alpha=0.85, zorder=8)
    ax.quiverkey(q, 0.86, 1.02, 10.0,
                 rf"10 m s$^{{-1}}$ along, $w\times${w_exaggeration:g}",
                 labelpos="E", coordinates="axes", fontproperties={"size": 7})

    # Terrain as the model steps it, not a smoothed curve: the staircase IS the
    # boundary the flow feels, and hiding it would misrepresent the resolution.
    ax.fill_between(dist, y_bottom, terrain, step="mid", color="0.6",
                    linewidth=0, zorder=6)
    ax.step(dist, terrain, where="mid", color="black", linewidth=0.7, zorder=7)

    ax.set_ylim(y_bottom, y_top_m)
    ax.set_xlim(float(dist.min()), float(dist.max()))
    ax.set_xlabel("distance along transect (km)")
    ax.set_ylabel("height (m ASL)")
    ax.set_title(title)

    tkw = dict(color=_ACCENT, fontsize=11, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, -0.09, section.termini[0], ha="left", va="top", **tkw)
    ax.text(1.0, -0.09, section.termini[1], ha="right", va="top", **tkw)

    if waypoints:
        _draw_section_towns(ax, section, waypoints, waypoint_offset_km)
    if locator is not None:
        _geo_locator_inset(ax, section, locator)
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.55, "pad": 1.5})

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out
