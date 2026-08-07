"""Figures that answer *where did this air come from*, from passive tracers.

Three views of the same attribution, computed by
:mod:`brc_tools.nwp.wrf_tracers` and each answering a different question:

``plot_origin_curtain``
    A cross-section coloured by **which source dominates**, on the model's own
    cells.  This is the layering figure: a stratified pool draws as horizontal
    bands of different hue, a well-mixed one as a single colour from the ground
    up.  The two hypotheses are visually distinct, which is the whole point.

``plot_tracer_spectrum``
    The same information at one point, as a stacked profile: what fraction of
    the tagged air at each height carries each tag.  A section shows *where* the
    bands are; this shows *how sharp* their boundaries are, and reads against a
    theta profile so a band can be tied to a stable layer.

``plot_origin_map``
    A plan view of the dominant source in the lowest model level -- the drainage
    pathways, as the model routes them.

**Opacity is not decoration.**  Every one of these fades a cell toward the
background as the dominant source's share falls, because an argmax over eight
tracers is a confident-looking statement even when the winner holds 13% against
a runner-up's 12%.  A vivid cell is air from one place; a pale cell is a mixture
that happens to have a largest term; grey is air carrying no tag at all.  Those
are three different findings and a flat categorical map draws the first two the
same.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from brc_tools.nwp import wrf_tracers as wt
from brc_tools.visualize.basemap import add_reference_overlays, draw_waypoints
from brc_tools.visualize.nwp_maps import _draw_section_towns, _geo_locator_inset
from brc_tools.visualize.wrf_curtain import _edges1d, curtain_mesh

__all__ = ["SOURCE_COLOURS", "UNTAGGED_COLOUR", "source_colours",
           "purity_alpha", "plot_origin_curtain", "plot_tracer_spectrum",
           "plot_origin_map"]

#: Qualitative palette for source regions: the Okabe-Ito colour-blind-safe set,
#: with its black replaced by a dark green.  Eight entries because
#: ``tracer_opt = 2`` gives exactly eight tracers; longer source lists cycle, and
#: a cycled palette is a real ambiguity rather than a cosmetic one, so
#: :func:`source_colours` says so.
#:
#: The eighth entry was a slate blue-grey first, and that was wrong for a palette
#: drawn at variable opacity: faded toward white, a desaturated hue lands on the
#: same neutral as :data:`UNTAGGED_COLOUR`, so "mixed air" and "no tagged air"
#: became the same pixel.  Every entry now carries enough chroma to stay a
#: recognisable hue at :data:`_ALPHA_MIN`.  The cost is that indices 3 and 8 are
#: both greens -- the closest pair in the set -- so a case whose third and eighth
#: sources are both important should order its tracers to separate them.
SOURCE_COLOURS = ("#E69F00", "#56B4E9", "#009E73", "#F0E442",
                  "#0072B2", "#D55E00", "#CC79A7", "#117733")

#: Cells whose total tagged concentration is below the floor: air the tracers
#: never reached, which is a finding and not a gap.
UNTAGGED_COLOUR = "#d9d9d9"

#: ...and hatched as well as greyed, which is not decoration.  Opacity is already
#: carrying "how pure is this attribution", so a thoroughly mixed cell of ANY
#: hue fades to a pale grey indistinguishable from the untagged colour -- and
#: "mixed air from several tagged sources" and "air no tracer ever reached" are
#: completely different findings.  The hatch is the one channel opacity is not
#: already using.
UNTAGGED_HATCH = "///"
_UNTAGGED_HATCH_COLOUR = "#9a9a9a"

#: Alpha floor for a fully mixed cell.  Not zero: a cell where eight sources tie
#: still holds tagged air, and vanishing it entirely would make it look untagged.
_ALPHA_MIN = 0.25


def source_colours(n: int) -> list[str]:
    """``n`` distinguishable fill colours, cycling the palette if pushed past it."""
    if n > len(SOURCE_COLOURS):
        print(f"[WARN] {n} tracer sources but only {len(SOURCE_COLOURS)} distinct "
              "colours; two sources will share a colour")
    return [SOURCE_COLOURS[i % len(SOURCE_COLOURS)] for i in range(n)]


def purity_alpha(purity, n_sources: int) -> np.ndarray:
    """Map a dominant-source share onto opacity.

    An ``n``-way tie sits at ``1/n``, which is the least informative attribution
    possible, so that is where the ramp starts rather than at zero -- otherwise
    a four-source mixture and an eight-source one would be drawn equally solid
    on a scale whose bottom no data can ever reach.
    """
    p = np.asarray(purity, dtype=float)
    lo = 1.0 / max(int(n_sources), 1)
    with np.errstate(invalid="ignore"):
        scaled = (p - lo) / max(1.0 - lo, 1e-9)
    return np.clip(_ALPHA_MIN + (1.0 - _ALPHA_MIN) * scaled, _ALPHA_MIN, 1.0)


def _legend(ax, labels, colours, *, title="tracer source"):
    from matplotlib.patches import Patch

    handles = [Patch(facecolor=c, edgecolor="none", label=lab)
               for c, lab in zip(colours, labels)]
    handles.append(Patch(facecolor=UNTAGGED_COLOUR, edgecolor=_UNTAGGED_HATCH_COLOUR,
                         hatch=UNTAGGED_HATCH, linewidth=0.0, label="untagged air"))
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5),
              frameon=False, fontsize=7, title=title, title_fontsize=7.5,
              handlelength=1.2, borderaxespad=0.0)


def _draw_untagged(ax, xc, yc, index, *, zorder=1.8):
    """Hatch the cells no tracer reached, over the flat grey already painted.

    Drawn with ``contourf`` on the cell CENTRES rather than the mesh corners:
    a QuadMesh cannot carry a hatch, and the boundary of an untagged region is
    a qualitative "the plume stops here", so an outline good to half a cell is
    the right precision for it.
    """
    untagged = (np.asarray(index) < 0).astype(float)
    if not untagged.any() or untagged.all():
        return
    cs = ax.contourf(xc, yc, untagged, levels=[0.5, 1.5], colors="none",
                     hatches=[UNTAGGED_HATCH], zorder=zorder)
    cs.set_edgecolor(_UNTAGGED_HATCH_COLOUR)
    cs.set_linewidth(0.0)


def _categorical_layers(ax, X, Y, index, alpha, colours):
    """Paint one masked ``pcolormesh`` per source, faded by ``alpha``.

    One mesh per source rather than a ``ListedColormap``: the per-cell opacity
    has to vary, and an alpha array is applied to the whole mappable, so the
    colour has to come from the mesh's own single-hue map instead of from a
    lookup over the category.
    """
    from matplotlib.colors import LinearSegmentedColormap

    for k, colour in enumerate(colours):
        sel = index == k
        if not sel.any():
            continue
        cmap = LinearSegmentedColormap.from_list(f"src{k}", [colour, colour])
        ax.pcolormesh(X, Y, np.where(sel, 1.0, np.nan), cmap=cmap,
                      vmin=0.0, vmax=1.0, shading="flat",
                      alpha=np.where(sel, alpha, 0.0), zorder=2)


def plot_origin_curtain(
    section,
    out_path,
    *,
    labels,
    title: str,
    annotation: str | None = None,
    floor: float = wt.DEFAULT_TOTAL_FLOOR,
    theta_contours: bool = True,
    theta_interval: float = 1.0,
    y_top_m: float = 3000.0,
    y_bottom_m: float | None = None,
    vertical: str = "asl",
    waypoints: dict | None = None,
    waypoint_offset_km: float = 15.0,
    locator: dict | None = None,
    figsize: tuple[float, float] = (12.0, 6.2),
    dpi: int = 200,
) -> Path:
    """Cross-section coloured by the dominant tracer source, faded by its share.

    ``labels`` names the sources in the same order as ``section.tracers2d``.
    ``vertical`` matches :func:`brc_tools.visualize.wrf_curtain.plot_wrf_curtain`
    -- ``"agl"`` flattens the terrain, which is the frame in which a
    terrain-following drainage skin becomes a horizontal band.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if getattr(section, "tracers2d", None) is None:
        raise ValueError("section carries no tracers2d; sample it with "
                         "wrf_section.load_plane(extras=('tracers',))")
    stack = np.asarray(section.tracers2d, dtype=float)
    index, purity, _total = wt.dominant_source(stack, floor=floor)
    colours = source_colours(len(labels))

    dist = np.asarray(section.distance_km, dtype=float)
    terrain = np.asarray(section.terrain1d, dtype=float)
    zm = np.asarray(section.height2d, dtype=float)
    X, Y = curtain_mesh(section)
    if vertical == "agl":
        Y = Y - _edges1d(terrain)[None, :]
        zm = zm - terrain[None, :]
        terrain = np.zeros_like(terrain)
    y_bottom = (y_bottom_m if y_bottom_m is not None
                else float(np.floor(np.nanmin(terrain) / 100.0) * 100.0 - 50.0))

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("white")
    # Untagged first, so the faded categorical layers sit on white and only the
    # genuinely untracered cells read grey.
    from matplotlib.colors import LinearSegmentedColormap

    grey = LinearSegmentedColormap.from_list("untagged",
                                             [UNTAGGED_COLOUR, UNTAGGED_COLOUR])
    ax.pcolormesh(X, Y, np.where(index < 0, 1.0, np.nan), cmap=grey,
                  vmin=0.0, vmax=1.0, shading="flat", zorder=1.5)
    _categorical_layers(ax, X, Y, index, purity_alpha(purity, stack.shape[0]),
                        colours)

    dist2d = np.broadcast_to(dist, zm.shape)
    _draw_untagged(ax, dist2d, zm, index)
    if theta_contours:
        theta = np.asarray(section.theta2d, dtype=float)
        lo = np.floor(np.nanmin(theta) / theta_interval) * theta_interval
        hi = np.ceil(np.nanmax(theta) / theta_interval) * theta_interval
        cs = ax.contour(dist2d, zm, theta,
                        levels=np.arange(lo, hi + 0.1, theta_interval),
                        colors="black", linewidths=0.4, alpha=0.45, zorder=5)
        ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%.0f")

    ax.fill_between(dist, y_bottom, terrain, step="mid", color="0.6",
                    linewidth=0, zorder=6)
    ax.step(dist, terrain, where="mid", color="black", linewidth=0.7, zorder=7)

    ax.set_ylim(y_bottom, y_top_m)
    ax.set_xlim(float(dist.min()), float(dist.max()))
    ax.set_xlabel("distance along transect (km)")
    ax.set_ylabel("height (m ASL)" if vertical == "asl"
                  else "height above ground (m) -- terrain flattened")
    ax.set_title(title)
    _legend(ax, labels, colours)

    tkw = dict(color="#c0392b", fontsize=11, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, -0.09, section.termini[0], ha="left", va="top", **tkw)
    ax.text(1.0, -0.09, section.termini[1], ha="right", va="top", **tkw)
    ax.text(0.5, -0.09,
            "colour = largest tracer source; opacity = its share, so pale is a "
            "mixture and grey is untagged air",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, alpha=0.8)

    if waypoints:
        _draw_section_towns(ax, section, waypoints, waypoint_offset_km)
    if locator is not None:
        _geo_locator_inset(ax, section, locator)
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right",
                va="bottom", fontsize=6, alpha=0.65,
                bbox={"facecolor": "white", "edgecolor": "none",
                      "alpha": 0.55, "pad": 1.5})

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_tracer_spectrum(
    stack_col,
    height_agl,
    out_path,
    *,
    labels,
    title: str,
    annotation: str | None = None,
    theta_col=None,
    floor: float = wt.DEFAULT_TOTAL_FLOOR,
    top_m: float = 2000.0,
    figsize: tuple[float, float] = (8.4, 6.4),
    dpi: int = 200,
) -> Path:
    """Stacked source spectrum against height at one point -- the layering, directly.

    ``stack_col`` is ``(n_tracers, nz)`` and ``height_agl`` ``(nz,)``.  Drawn on
    the model's own levels: this profile's whole content is *where* the
    boundaries between source layers sit, and interpolating onto regular heights
    would round them off.

    A gap in the stack is not missing data -- it is a height at which the column
    holds no tagged air at all, and saying so is the honest rendering.  The right
    panel carries the total concentration on a log axis so a reader can tell a
    thin, real layer from a trace.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stack = np.asarray(stack_col, dtype=float)
    height = np.asarray(height_agl, dtype=float)
    shares, total = wt.tracer_shares(stack, floor=floor)
    keep = height <= float(top_m)
    shares, total, height = shares[:, keep], total[keep], height[keep]
    colours = source_colours(len(labels))

    fig, (ax, axr) = plt.subplots(
        1, 2, figsize=figsize, sharey=True, constrained_layout=True,
        gridspec_kw={"width_ratios": [3.0, 1.0]})

    left = np.zeros_like(height)
    for k, (colour, label) in enumerate(zip(colours, labels)):
        row = np.nan_to_num(shares[k], nan=0.0)
        valid = np.isfinite(shares[k])
        ax.fill_betweenx(np.where(valid, height, np.nan), left, left + row,
                         color=colour, linewidth=0, label=label)
        left = left + row
    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("share of the tagged air")
    ax.set_ylabel("height above ground (m)")
    ax.set_ylim(0.0, float(top_m))
    ax.legend(loc="center left", bbox_to_anchor=(1.30, 0.5), frameon=False,
              fontsize=7, title="tracer source", title_fontsize=7.5,
              handlelength=1.2)

    if theta_col is not None:
        # Theta on a twin axis, because a band boundary is only interesting if it
        # coincides with a stable layer -- that pairing is the finding, and it
        # cannot be made across two figures.
        axt = ax.twiny()
        axt.plot(np.asarray(theta_col, dtype=float)[keep], height,
                 color="black", linewidth=1.3, zorder=6)
        axt.set_xlabel(r"$\theta$ (K)")
        axt.tick_params(axis="x", labelsize=8)

    axr.plot(total, height, color="0.25", linewidth=1.2)
    axr.set_xscale("log")
    # The floor named in the axis label rather than beside the line: a rotated
    # annotation on a 1.5-inch-wide log panel is unreadable at any angle, and
    # the dotted line is what a gap in the stack to its left means.
    axr.set_xlabel("total tagged tracer\n(dotted: attribution floor —\n"
                   "left of it the stack is blank)")
    axr.axvline(floor, color="#c0392b", linewidth=0.8, linestyle=":")
    axr.grid(True, alpha=0.25, linewidth=0.4)

    fig.suptitle(title)
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right",
                va="bottom", fontsize=6, alpha=0.65)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_origin_map(
    lon2d,
    lat2d,
    terrain,
    stack_level,
    out_path,
    *,
    labels,
    title: str,
    annotation: str | None = None,
    floor: float = wt.DEFAULT_TOTAL_FLOOR,
    extent: tuple[float, float, float, float] | None = None,
    overlays: dict | None = None,
    waypoints: dict | None = None,
    wind: tuple[np.ndarray, np.ndarray] | None = None,
    barb_stride: int = 8,
    figsize: tuple[float, float] = (9.6, 7.6),
    dpi: int = 200,
) -> Path:
    """Plan view of the dominant tracer source, on one model level.

    ``stack_level`` is ``(n_tracers, ny, nx)`` -- normally the lowest mass level,
    which is the air a surface station would sample.  With ``wind`` supplied as
    ``(u, v)`` in m/s the barbs show where that air is going next, so the figure
    reads as a pathway rather than a snapshot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.grid import terrain_contour_levels

    stack = np.asarray(stack_level, dtype=float)
    index, purity, _total = wt.dominant_source(stack, floor=floor)
    colours = source_colours(len(labels))
    lon2d = np.asarray(lon2d, dtype=float)
    lat2d = np.asarray(lat2d, dtype=float)

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("white")
    from matplotlib.colors import LinearSegmentedColormap

    grey = LinearSegmentedColormap.from_list("untagged",
                                             [UNTAGGED_COLOUR, UNTAGGED_COLOUR])
    ax.pcolormesh(lon2d, lat2d, np.where(index < 0, 1.0, np.nan), cmap=grey,
                  vmin=0.0, vmax=1.0, shading="auto", zorder=1.2)
    alpha = purity_alpha(purity, stack.shape[0])
    for k, colour in enumerate(colours):
        sel = index == k
        if not sel.any():
            continue
        cmap = LinearSegmentedColormap.from_list(f"src{k}", [colour, colour])
        ax.pcolormesh(lon2d, lat2d, np.where(sel, 1.0, np.nan), cmap=cmap,
                      vmin=0.0, vmax=1.0, shading="auto",
                      alpha=np.where(sel, alpha, 0.0), zorder=1.5)
    _draw_untagged(ax, lon2d, lat2d, index)

    levels = terrain_contour_levels(np.asarray(terrain, dtype=float))
    if levels is not None:
        ax.contour(lon2d, lat2d, terrain, levels=levels, colors="0.35",
                   linewidths=0.3, alpha=0.55, zorder=2.5)

    if wind is not None:
        s = int(barb_stride)
        u, v = (np.asarray(a, dtype=float) * 1.94384 for a in wind)
        ax.barbs(lon2d[::s, ::s], lat2d[::s, ::s], u[::s, ::s], v[::s, ::s],
                 length=5.0, linewidth=0.4, zorder=4)

    view = extent if extent is not None else (
        float(lon2d.min()), float(lon2d.max()),
        float(lat2d.min()), float(lat2d.max()))
    add_reference_overlays(ax, view, layers=(overlays or {}))
    if waypoints:
        draw_waypoints(ax, waypoints, view, fontsize=6.5)

    ax.set_xlim(view[0], view[1])
    ax.set_ylim(view[2], view[3])
    ax.set_aspect(1.0 / np.cos(np.deg2rad(0.5 * (view[2] + view[3]))))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(title)
    _legend(ax, labels, colours)
    ax.text(0.5, -0.07,
            "colour = largest tracer source; opacity = its share, so pale is a "
            "mixture and grey is untagged air",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, alpha=0.8)
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right",
                va="bottom", fontsize=6, alpha=0.65,
                bbox={"facecolor": "white", "edgecolor": "none",
                      "alpha": 0.55, "pad": 1.5})

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out
