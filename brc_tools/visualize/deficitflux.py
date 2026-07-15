"""Cold-pool deficit-transport plan-view maps (flux vectors + advective tendency).

The advection companion to ``visualize/heatdeficit.py``: integrated deficit transport
(:func:`brc_tools.nwp.wrf_output.deficit_flux_field`, W m^-1 — the IVT analogue of the
Whiteman heat deficit) rendered as quivers over the heat-deficit field, plus the
advective tendency ``-div(F)`` (MJ m^-2 h^-1) as a symmetric diverging map.  The pair
closes a budget with the heat-deficit map (dH/dt = -div F + diabatic), so the two
families share the crest convention and the ``heat_deficit`` colour scale.

Same offline-robust dressing as the heat-deficit maps (plain lon/lat matplotlib,
fail-soft Natural-Earth overlays, decluttered waypoints, crest terrain contour).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from brc_tools.visualize.heatdeficit import _annotate, _decorate

# Fixed quiver reference (MW per metre of transect width) so arrow lengths stay
# comparable across cases and forecast hours, like the fixed colour scales.
_QUIVER_KEY_MW = 5.0


def _draw_transects(ax, transects, lon, lat):
    """Overlay configured transect lines (A->B) so canyon gates are visible in context."""
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    for tr in transects or []:
        la, lo_a = float(tr.lat_a), float(tr.lon_a)
        lb, lo_b = float(tr.lat_b), float(tr.lon_b)
        inside = (
            lat.min() <= min(la, lb) and max(la, lb) <= lat.max()
            and lon.min() <= min(lo_a, lo_b) and max(lo_a, lo_b) <= lon.max()
        )
        if not inside:
            continue
        ax.plot([lo_a, lo_b], [la, lb], color="crimson", lw=1.4, zorder=7)
        ax.annotate(tr.name, ((lo_a + lo_b) / 2, (la + lb) / 2), fontsize=6,
                    color="crimson", ha="center", va="bottom", zorder=7)


def plot_deficitflux_map(
    lon,
    lat,
    h_mj,
    fx,
    fy,
    out_path: str | Path,
    *,
    style,
    crest_terrain=None,
    crest_m=None,
    title: str,
    annotation: str | None = None,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    transects=None,
    quiver_target: int = 24,
    dpi: int = 300,
) -> Path:
    """Deficit transport F (quivers, MW m^-1) over the heat-deficit field (MJ m^-2).

    ``quiver_target`` sets roughly how many arrows span the short axis; the stride is
    derived from the grid so a 111 m and a 3 km nest both stay legible.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out_path)
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    fig, ax = plt.subplots(figsize=(7.2, 6.4), constrained_layout=True)
    mesh = ax.pcolormesh(lon, lat, np.asarray(h_mj), shading="auto",
                         cmap=style.cmap, vmin=style.vmin, vmax=style.vmax)
    stride = max(1, min(lon.shape) // max(quiver_target, 1))
    s = np.s_[::stride, ::stride]
    q = ax.quiver(
        lon[s], lat[s], np.asarray(fx)[s] / 1e6, np.asarray(fy)[s] / 1e6,
        color="white", edgecolor="0.2", linewidth=0.3,
        width=0.0035, scale_units="width", scale=20 * _QUIVER_KEY_MW, zorder=5,
    )
    ax.quiverkey(q, 0.88, 1.03, _QUIVER_KEY_MW, rf"{_QUIVER_KEY_MW:g} MW m$^{{-1}}$",
                 labelpos="E", coordinates="axes", fontproperties={"size": 7})
    _draw_transects(ax, transects, lon, lat)
    _decorate(ax, lon, lat, crest_terrain=crest_terrain, crest_m=crest_m,
              waypoints=waypoints, overlays=overlays)
    fig.colorbar(mesh, ax=ax, shrink=0.9, extend=style.extend, label=style.label)
    ax.set_title(title)
    _annotate(ax, annotation)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_deficitflux_divergence(
    lon,
    lat,
    adv_mj_h,
    out_path: str | Path,
    *,
    style,
    smooth_sigma: float = 2.0,
    crest_terrain=None,
    crest_m=None,
    title: str,
    annotation: str | None = None,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    dpi: int = 300,
) -> Path:
    """Advective heat-deficit tendency ``-div(F)`` (MJ m^-2 h^-1), diverging map.

    Red = advection deepening the pool (matching the heat-deficit difference maps,
    where red = deeper).  ``smooth_sigma`` (grid cells) is display-only smoothing —
    at 111 m the raw divergence is grid-scale noisy, like the upper-air advection.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.style import symmetric_limit

    out = Path(out_path)
    adv = np.asarray(adv_mj_h, dtype=float)
    if smooth_sigma and smooth_sigma > 0:
        from scipy.ndimage import gaussian_filter

        adv = gaussian_filter(adv, sigma=float(smooth_sigma))
    if style.vmin is None or style.vmax is None:
        lim = symmetric_limit(adv) or 1.0
        vmin, vmax = -lim, lim
    else:
        vmin, vmax = style.vmin, style.vmax
    fig, ax = plt.subplots(figsize=(7.2, 6.4), constrained_layout=True)
    mesh = ax.pcolormesh(lon, lat, adv, shading="auto",
                         cmap=style.cmap, vmin=vmin, vmax=vmax)
    _decorate(ax, lon, lat, crest_terrain=crest_terrain, crest_m=crest_m,
              waypoints=waypoints, overlays=overlays)
    fig.colorbar(mesh, ax=ax, shrink=0.9, extend="both", label=style.label)
    ax.set_title(f"{title}\n(red = advection deepening the pool)")
    _annotate(ax, annotation)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
