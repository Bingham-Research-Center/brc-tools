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
from brc_tools.visualize.style import get_style, norm_kwargs

__all__ = ["curtain_mesh", "plot_wrf_curtain", "shade_style_key", "SHADE_FIELD"]

_ACCENT = "#c0392b"

#: Shade name -> the :class:`~brc_tools.nwp.section.NWPSection` attribute it draws.
SHADE_FIELD = {"speed": "speed2d", "theta": "theta2d", "temp": "temp2d",
               "along": "along2d", "normal": "normal2d", "w": "w2d",
               "theta_e": "thetae2d", "refl": "refl2d"}
_SHADE_FIELD = SHADE_FIELD  # back-compat for existing importers

#: Shade name -> the default ``VAR_STYLES`` key used to colour it.
#:
#: This table exists because the engines used to guess.  One passed
#: ``wind_speed_10m`` for *every* shade, so a theta curtain came out on a
#: 0-15 m/s wind ramp under a wind colourbar label; the other fell back to
#: ``refl``, which did the same thing to theta-e with a reflectivity scale.  The
#: mapping is keyed on the same names as :data:`SHADE_FIELD` and tested against
#: it, so a shade can no longer exist without a scale that means something.
SHADE_STYLE = {"speed": "wind_speed_10m", "theta": "theta", "temp": "temp_2m",
               "along": "wind_along", "normal": "wind_normal", "w": "w",
               "theta_e": "theta", "refl": "refl"}


def shade_style_key(shade: str) -> str:
    """The default style key for ``shade`` (``KeyError`` if it is not a shade)."""
    return SHADE_STYLE[shade]


#: Shade name -> the colourbar label, which is the *definition* of what is drawn.
#:
#: These override the style's own label on a curtain, on purpose.  A style label
#: describes a variable ("10 m wind"); a curtain needs the label to describe a
#: *measurement on a plane* -- whether the number is a magnitude, a component
#: along the cut, or the flow crossing it -- and those three are indistinguishable
#: once painted.  A reader given "wind (m/s)" over a vertical section cannot tell
#: a 12 m/s along-valley jet from 12 m/s of cross-valley flow, and nothing else in
#: the figure disambiguates it.
SHADE_LABEL = {
    "speed": r"horizontal wind speed $|V|$ (m s$^{-1}$) -- magnitude, no direction",
    "along": r"along-transect wind (m s$^{-1}$), $+$ toward B",
    "normal": r"section-normal wind (m s$^{-1}$), $+$ into page",
    "w": r"vertical velocity $w$ (m s$^{-1}$), $+$ upward",
    "theta": r"$\theta$ (K)",
    "theta_e": r"$\theta_e$ (K)",
    "temp": r"$T$ (K)",
    "refl": "reflectivity (dBZ)",
}

_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _cardinal(bearing_deg: float) -> str:
    """Nearest 8-point compass name for a bearing in degrees from north."""
    return _COMPASS[int(round((bearing_deg % 360.0) / 45.0)) % 8]


def orientation_note(section) -> str:
    """``'A->B 090 deg (W-E) | into page = N'`` for one section.

    The single line that makes a signed fill readable: without knowing which way
    the viewer faces, "into the page" names no direction at all.
    """
    lat = np.asarray(section.lat_line, dtype=float)
    lon = np.asarray(section.lon_line, dtype=float)
    coslat = np.cos(np.deg2rad(0.5 * (lat[0] + lat[-1])))
    east, north = (lon[-1] - lon[0]) * coslat, lat[-1] - lat[0]
    bearing = float(np.degrees(np.arctan2(east, north))) % 360.0
    # +normal is the LEFT-hand normal of A->B, i.e. 90 degrees anticlockwise.
    into_page = _cardinal(bearing - 90.0)
    return (f"A$\\rightarrow$B {bearing:03.0f}$\\degree$ "
            f"({_cardinal(bearing + 180.0)}$\\rightarrow${_cardinal(bearing)})"
            f"  |  into page = {into_page}")


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
    cbar_label: str | None = None,
    title: str,
    annotation: str | None = None,
    show_orientation: bool = True,
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

    ``shade`` picks the shaded field — see :data:`SHADE_FIELD`. Three of them are
    winds and they are *different measurements on the same plane*:

    * ``speed`` — horizontal magnitude :math:`|V|`. Carries no direction at all,
      so a cross-valley gale and an along-valley jet look identical.
    * ``along`` — the in-plane horizontal component, positive toward B. This is
      the component the vectors draw.
    * ``normal`` — the flow *crossing* the section, positive **into the page**,
      on a diverging map because it is signed. For a west-to-east transect this
      is the north-south component.

    The colourbar label comes from :data:`SHADE_LABEL` rather than the style, and
    an orientation stamp names the bearing and which compass direction "into the
    page" is, because a signed field without a stated viewing direction is not
    interpretable. Pass ``cbar_label`` to override, ``show_orientation=False`` to
    drop the stamp.

    ``theta_interval`` defaults to 1 K rather than the isobaric renderer's 2 K: a
    nocturnal inversion does its work in the first few kelvin, and on the native
    grid there is resolution to show it.

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

    st = style if style is not None else get_style(shade_style_key(shade))
    dist = np.asarray(section.distance_km, dtype=float)
    terrain = np.asarray(section.terrain1d, dtype=float)
    zm = np.asarray(section.height2d, dtype=float)
    X, Y = curtain_mesh(section)

    y_bottom = (y_bottom_m if y_bottom_m is not None
                else float(np.floor(np.nanmin(terrain) / 100.0) * 100.0 - 50.0))

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("0.6")
    mesh = ax.pcolormesh(X, Y, np.asarray(field, dtype=float), cmap=st.cmap,
                         shading="flat", **norm_kwargs(st))
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend=st.extend,
                 label=cbar_label if cbar_label is not None
                 else SHADE_LABEL.get(shade, st.label))

    dist2d = np.broadcast_to(dist, zm.shape)
    if theta_contours:
        theta = np.asarray(section.theta2d, dtype=float)
        lo = np.floor(np.nanmin(theta) / theta_interval) * theta_interval
        hi = np.ceil(np.nanmax(theta) / theta_interval) * theta_interval
        cs = ax.contour(dist2d, zm, theta, levels=np.arange(lo, hi + 0.1, theta_interval),
                        colors="black", linewidths=0.4, alpha=0.5)
        ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%.0f")

    # In-plane vectors only: along-transect + vertical. The component normal to
    # the section is DISCARDED here, not folded in -- say so, because a vector
    # field on a vertical plane reads as "the wind" unless told otherwise, and
    # the flow crossing the plane can be the larger part of it.
    sz, sx = quiver_stride
    q = ax.quiver(dist2d[::sz, ::sx], zm[::sz, ::sx],
                  np.asarray(section.along2d, dtype=float)[::sz, ::sx],
                  np.asarray(section.w2d, dtype=float)[::sz, ::sx] * w_exaggeration,
                  color="black", width=0.0016, alpha=0.85, zorder=8)
    # Key stays short -- it sits at the top right and a long one runs off the
    # figure (the clipped-title failure, again).  What the vectors *mean* goes in
    # the orientation stamp below the axes, where there is width for a sentence.
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

    if show_orientation:
        note = (f"{orientation_note(section)}  |  vectors: in-plane only "
                f"(along-transect + $w\\times${w_exaggeration:g}), "
                "normal component not shown")
        ax.text(0.5, -0.09, note, transform=ax.transAxes,
                ha="center", va="top", fontsize=7, alpha=0.8)

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
