"""Publication maps for gridded NWP fields (HRRR/RRFS) over a basin domain.

Two renderers that consume an :class:`xarray.Dataset` from
:meth:`brc_tools.nwp.NWPSource.fetch` (plus, for the section, an
:class:`~brc_tools.nwp.section.NWPSection`) and produce the offline-safe,
staged-shapefile style used across the group's figures:

* :func:`plot_nwp_surface_map` -- a plan-view field (e.g. 10 m wind speed) with
  wind barbs, terrain contours, and reference overlays (states / counties /
  roads / rivers / lakes) plus decluttered town labels.
* :func:`plot_nwp_section` -- a terrain-filled vertical cross-section at true
  altitude (m ASL), wind-speed shaded with in-plane vectors and potential-
  temperature contours, a geographic locator inset, and the same town set
  projected onto the transect.

Everything geographic comes from the staged Natural-Earth cache
(:mod:`brc_tools.visualize.basemap`), so these render on an offline compute node.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from brc_tools.visualize.basemap import add_reference_overlays, draw_waypoints
from brc_tools.visualize.grid import terrain_contour_levels
from brc_tools.visualize.style import get_style

_KT = 1.94384  # m/s -> knots
_ACCENT = "#c62828"
_DEFAULT_OVERLAYS = {"states": True, "counties": True, "roads": True,
                     "rivers": True, "lakes": True}


def _lon180(lon) -> np.ndarray:
    lon = np.asarray(lon, dtype=float)
    return np.where(lon > 180.0, lon - 360.0, lon)


def _sel(ds, name, time_index):
    da = ds[name]
    if "time" in da.dims:
        da = da.isel(time=time_index)
    return np.asarray(da.values, dtype=float)


def _annotate(ax, text):
    if text:
        ax.text(0.99, 0.01, text, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.55, "pad": 1.5})


# --------------------------------------------------------------------------- #
# Plan view
# --------------------------------------------------------------------------- #
def plot_nwp_surface_map(
    ds,
    field: str,
    out_path,
    *,
    time_index: int = 0,
    wind: tuple[str, str] | None = ("wind_u_10m", "wind_v_10m"),
    terrain_var: str | None = "terrain_height",
    style=None,
    cmap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    wind_barbs: bool = True,
    barb_stride: int = 4,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    extent: tuple[float, float, float, float] | None = None,
    terrain_contours: bool = True,
    title: str | None = None,
    annotation: str | None = None,
    figsize: tuple[float, float] = (9.0, 7.6),
    dpi: int = 150,
) -> Path:
    """Render a plan-view NWP field with wind barbs, terrain, overlays, and towns.

    ``field`` is a data-var name (e.g. ``"wind_speed_10m"``). ``extent`` is
    ``(lon0, lon1, lat0, lat1)`` in -180..180; if ``None`` the full grid is shown.
    ``overlays`` is a ``{layer: bool}`` map passed to
    :func:`~brc_tools.visualize.basemap.add_reference_overlays` (default: all,
    incl. counties).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lon2d = _lon180(ds["longitude"].values)
    lat2d = np.asarray(ds["latitude"].values, dtype=float)
    fld = _sel(ds, field, time_index)

    st = style if style is not None else _safe_style(field)
    cmap = cmap or (st.cmap if st else "viridis")
    if vmin is None and st is not None:
        vmin = st.vmin
    if vmax is None and st is not None:
        vmax = st.vmax
    label = st.label if st is not None else field

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    mesh = ax.pcolormesh(lon2d, lat2d, fld, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend=(st.extend if st else "neither"), label=label)

    if terrain_contours and terrain_var and terrain_var in ds:
        terr = _sel(ds, terrain_var, time_index)
        levels = terrain_contour_levels(terr)
        if levels is not None:
            ax.contour(lon2d, lat2d, terr, levels=levels, colors="0.35",
                       linewidths=0.3, alpha=0.5, zorder=1.5)

    if wind_barbs and wind and wind[0] in ds and wind[1] in ds:
        u = _sel(ds, wind[0], time_index) * _KT
        v = _sel(ds, wind[1], time_index) * _KT
        s = barb_stride
        ax.barbs(lon2d[::s, ::s], lat2d[::s, ::s], u[::s, ::s], v[::s, ::s],
                 length=5.0, linewidth=0.4, zorder=4)

    view = extent if extent is not None else (
        float(lon2d.min()), float(lon2d.max()), float(lat2d.min()), float(lat2d.max()))
    add_reference_overlays(ax, view, layers=(overlays or _DEFAULT_OVERLAYS))
    if waypoints:
        draw_waypoints(ax, waypoints, view, fontsize=6.5)

    ax.set_xlim(view[0], view[1])
    ax.set_ylim(view[2], view[3])
    ax.set_aspect(1.0 / np.cos(np.deg2rad(0.5 * (view[2] + view[3]))))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    if title:
        ax.set_title(title)
    _annotate(ax, annotation)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out


def _safe_style(field):
    try:
        return get_style(field)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Cross-section
# --------------------------------------------------------------------------- #
def _terrain_floor(terrain: np.ndarray) -> float:
    return float(np.floor(np.nanmin(terrain) / 100.0) * 100.0 - 50.0)


def _project_waypoints(section, waypoints, max_offset_km):
    """(distance_km, name, offset_km, terrain_m) for waypoints near the line."""
    if not waypoints:
        return []
    lon = _lon180(section.lon_line)
    lat = np.asarray(section.lat_line, dtype=float)
    dist = np.asarray(section.distance_km, dtype=float)
    terr = np.asarray(section.terrain1d, dtype=float)
    kx = 111.320 * np.cos(np.deg2rad(float(np.mean(lat))))
    ky = 110.574
    found = []
    for name, wp in waypoints.items():
        d2 = ((lon - float(wp["lon"])) * kx) ** 2 + ((lat - float(wp["lat"])) * ky) ** 2
        i = int(np.argmin(d2))
        off = float(np.sqrt(d2[i]))
        if off <= max_offset_km and 0 < i < dist.size - 1:
            found.append((float(dist[i]), str(name), off, float(terr[i])))
    return sorted(found)


def _draw_section_towns(ax, section, waypoints, max_offset_km):
    y_top = ax.get_ylim()[1]
    for d_km, name, _off, terr_m in _project_waypoints(section, waypoints, max_offset_km):
        ax.axvline(d_km, color="0.15", lw=0.6, ls=(0, (4, 3)), alpha=0.6, zorder=5)
        ax.plot(d_km, terr_m, marker="v", color=_ACCENT, ms=5, zorder=9)
        ax.text(d_km, y_top, f"{name} ", rotation=90, va="top", ha="right", fontsize=6.5,
                color="0.1", zorder=9,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.6, "pad": 0.6})


def _geo_locator_inset(ax, section, locator):
    """Small basin map (top-right) with terrain, overlays, the transect line, towns."""
    lon2d = _lon180(locator["lon2d"])
    lat2d = np.asarray(locator["lat2d"], dtype=float)
    terr2d = np.asarray(locator["terrain2d"], dtype=float)
    extent = locator.get("extent") or (
        float(lon2d.min()), float(lon2d.max()), float(lat2d.min()), float(lat2d.max()))
    # A tall/narrow transect (e.g. S->N) wants a different inset box than a wide one,
    # so the caller may override the default top-right placement.
    axins = ax.inset_axes(locator.get("rect") or [0.66, 0.60, 0.34, 0.40])
    axins.contourf(lon2d, lat2d, terr2d, levels=12, cmap="terrain", alpha=0.85, zorder=0)
    add_reference_overlays(axins, extent,
                           layers={"states": True, "counties": True, "roads": False,
                                   "rivers": True, "lakes": True})
    axins.plot(_lon180(section.lon_line), section.lat_line, color=_ACCENT, lw=1.6, zorder=6)
    axins.plot([_lon180(section.lon_line)[0]], [section.lat_line[0]], marker="o",
               color=_ACCENT, ms=4, zorder=7)
    axins.plot([_lon180(section.lon_line)[-1]], [section.lat_line[-1]], marker="s",
               color=_ACCENT, ms=4, zorder=7)
    if locator.get("waypoints"):
        draw_waypoints(axins, locator["waypoints"], extent, fontsize=5.0, ms=3.0)
    axins.set_xlim(extent[0], extent[1])
    axins.set_ylim(extent[2], extent[3])
    axins.set_aspect(1.0 / np.cos(np.deg2rad(0.5 * (extent[2] + extent[3]))))
    axins.set_xticks([])
    axins.set_yticks([])
    # Sit above the quivers (zorder 8), which would otherwise stripe straight across the
    # locator map, but below the town markers/labels (zorder 9) so a transect whose
    # landmarks run under the inset still reads them.
    axins.set_zorder(8.5)
    axins.patch.set_facecolor("white")
    axins.patch.set_alpha(1.0)
    for sp in axins.spines.values():
        sp.set_edgecolor(_ACCENT)


def _interp_to_heights(section, field2d, heights, *, fill_to_ground=True):
    """Interpolate each column of ``field2d`` (on ``section.height2d``) onto a common
    regular ``heights`` axis, turning coarse isobaric levels into a smooth curtain.

    Over high terrain the lowest above-ground isobaric level can sit a few hundred
    metres up; with ``fill_to_ground`` the column is held at that lowest valid value
    down to the surface (the usual "fill to ground" choice for isobaric curtains --
    the true 10 m wind lives on the plan-view map), else it stays NaN below it."""
    z = np.asarray(section.height2d, dtype=float)
    f = np.asarray(field2d, dtype=float)
    n = z.shape[1]
    out = np.full((heights.size, n), np.nan)
    for i in range(n):
        zc, fc = z[:, i], f[:, i]
        m = np.isfinite(zc) & np.isfinite(fc)
        if m.sum() >= 2:
            order = np.argsort(zc[m])
            zz, ff = zc[m][order], fc[m][order]
            out[:, i] = np.interp(heights, zz, ff,
                                  left=(ff[0] if fill_to_ground else np.nan),
                                  right=np.nan)
    return out


def _smooth1d(a, window=3):
    a = np.asarray(a, dtype=float)
    if a.size < window:
        return a
    k = np.ones(window) / window
    out = np.convolve(a, k, mode="same")
    out[0], out[-1] = a[0], a[-1]
    return out


_SECTION_SHADE = {"speed": "speed2d", "theta_e": "thetae2d", "theta": "theta2d",
                  "temp": "temp2d", "along": "along2d"}


def plot_nwp_section(
    section,
    out_path,
    *,
    shade: str = "speed",
    style=None,
    title: str,
    annotation: str | None = None,
    theta_contours: bool = True,
    theta_interval: float = 2.0,
    w_exaggeration: float = 100.0,
    quiver_stride: tuple[int, int] = (6, 12),
    dz_m: float = 40.0,
    y_top_m: float = 3000.0,
    waypoints: dict | None = None,
    waypoint_offset_km: float = 15.0,
    locator: dict | None = None,
    figsize: tuple[float, float] = (11.0, 6.2),
    dpi: int = 150,
) -> Path:
    """Render an :class:`~brc_tools.nwp.section.NWPSection` as a terrain-filled curtain.

    ``shade`` selects the shaded field -- ``"speed"`` (default, the wind case),
    ``"theta_e"`` (moist instability; needs a section built with dewpoint),
    ``"theta"``, ``"temp"``, or ``"along"`` -- and is shaded on a true-altitude
    (m ASL) axis capped at ``y_top_m``. Pass a matching ``style`` for anything but
    the default. In-plane vectors show along-transect + (exaggerated) vertical
    wind; thin contours mark potential temperature. Columns are interpolated onto
    a regular ``dz_m`` height grid for a smooth curtain. ``locator`` (``{lon2d,
    lat2d, terrain2d, extent?, waypoints?}``) draws the geographic inset;
    ``waypoints`` marks towns within ``waypoint_offset_km`` of the line; an optional
    ``locator["rect"]`` (axes-fraction ``[x, y, w, h]``) moves/resizes that inset.

    ``w_exaggeration`` scales the vertical component of the in-plane vectors. A
    sensible default is the plot's own aspect ratio (transect length / ``y_top_m``),
    so a deep section wants a much smaller value than a shallow one.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if shade not in _SECTION_SHADE:
        raise ValueError(f"shade must be one of {sorted(_SECTION_SHADE)}, got {shade!r}")
    shade_arr = getattr(section, _SECTION_SHADE[shade])
    if shade_arr is None:
        raise ValueError(
            f"section has no {_SECTION_SHADE[shade]} for shade={shade!r} -- rebuild it "
            "with extract_nwp_section(..., dewpoint_prefix=...)")
    st = style if style is not None else get_style("wind_speed_10m")
    dist = np.asarray(section.distance_km, dtype=float)
    terrain = np.asarray(section.terrain1d, dtype=float)
    terr_disp = _smooth1d(terrain, 5)
    y_bottom = _terrain_floor(terrain)

    heights = np.arange(y_bottom, y_top_m + dz_m, dz_m)
    shaded = _interp_to_heights(section, shade_arr, heights)
    theta = _interp_to_heights(section, section.theta2d, heights)
    along = _interp_to_heights(section, section.along2d, heights)
    w = _interp_to_heights(section, section.w2d, heights)
    below = heights[:, None] < terr_disp[None, :]
    for a in (shaded, theta, along, w):
        a[below] = np.nan

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("0.6")  # below-ground / below-lowest-level cells read as terrain
    mesh = ax.pcolormesh(dist, heights, shaded, cmap=st.cmap, vmin=st.vmin, vmax=st.vmax,
                         shading="gouraud")
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend=st.extend, label=st.label)

    if theta_contours:
        lo = np.floor(np.nanmin(theta) / theta_interval) * theta_interval
        hi = np.ceil(np.nanmax(theta) / theta_interval) * theta_interval
        levels = np.arange(lo, hi + 0.1, theta_interval)
        cs = ax.contour(dist, heights, theta, levels=levels, colors="black",
                        linewidths=0.4, alpha=0.5)
        ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%.0f")

    # in-plane wind: along-transect + exaggerated vertical, on the regular grid
    sz, sx = quiver_stride
    dd, hh = np.meshgrid(dist, heights)
    q = ax.quiver(dd[::sz, ::sx], hh[::sz, ::sx], along[::sz, ::sx],
                  w[::sz, ::sx] * w_exaggeration, color="black", width=0.0016,
                  alpha=0.85, zorder=8)
    ax.quiverkey(q, 0.86, 1.02, 10.0, rf"10 m s$^{{-1}}$ along, $w\times${int(w_exaggeration)}",
                 labelpos="E", coordinates="axes", fontproperties={"size": 7})

    ax.fill_between(dist, y_bottom, terr_disp, color="0.6", linewidth=0, zorder=6)
    ax.plot(dist, terr_disp, color="black", linewidth=0.7, zorder=7)

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
    _annotate(ax, annotation)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out
