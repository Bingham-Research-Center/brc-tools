"""Cold-pool deficit-transport maps and time-series diagnostics.

The advection companion to ``visualize/heatdeficit.py``: integrated deficit transport
(:func:`brc_tools.nwp.wrf_output.deficit_flux_field`, W m^-1 — the IVT analogue of the
Whiteman heat deficit) rendered as quivers over the heat-deficit field, plus the
horizontal flux-convergence contribution ``-div(F)`` (MJ m^-2 h^-1) as a symmetric
diverging map.  Finite-difference storage minus that contribution is retained as an
*unresolved* tendency rather than attributed uniquely to diabatic physics.

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
    # below the axes (the title row is already full), arrow right of its label
    ax.quiverkey(q, 0.93, -0.09, _QUIVER_KEY_MW, rf"{_QUIVER_KEY_MW:g} MW m$^{{-1}}$",
                 labelpos="W", coordinates="axes", fontproperties={"size": 7})
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
    """Horizontal heat-deficit flux convergence ``-div(F)`` (MJ m^-2 h^-1).

    Red = advection deepening the pool (matching the heat-deficit difference maps,
    where red = deeper).  ``smooth_sigma`` (grid cells) is display-only smoothing;
    the engine derives it from a *physical* scale (``deficitflux_smooth_km`` / DX)
    because the raw divergence is saturated gravity-wave noise at 111 m — a
    fixed cell count would under-smooth fine nests and blur coarse ones.
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
    ax.set_title(f"{title}\n(red = horizontal convergence increasing deficit)")
    _annotate(ax, annotation)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_deficit_bulk_diagnostics(
    lon,
    lat,
    depth_m,
    speed_m_s,
    froude,
    out_path: str | Path,
    *,
    styles,
    crest_terrain=None,
    crest_m=None,
    title: str,
    annotation: str | None = None,
    waypoints: dict | None = None,
    overlays: dict | None = None,
    dpi: int = 300,
) -> Path:
    """Render exploratory depth, deficit-weighted speed, and bulk Froude maps.

    These fields share the same crest-referenced active layer.  The Froude panel is a
    reduced-gravity proxy only; the renderer deliberately labels it as exploratory and
    does not imply a hydraulic-control diagnosis.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out_path)
    fields = (np.asarray(depth_m), np.asarray(speed_m_s), np.asarray(froude))
    labels = ("diagnosed layer depth", "deficit-weighted speed |F|/H", "exploratory bulk Froude proxy")
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.6), constrained_layout=True)
    for ax, field, style, subtitle in zip(axes, fields, styles, labels):
        mesh = ax.pcolormesh(
            lon, lat, field, shading="auto", cmap=style.cmap,
            vmin=style.vmin, vmax=style.vmax,
        )
        _decorate(
            ax, lon, lat, crest_terrain=crest_terrain, crest_m=crest_m,
            waypoints=waypoints, overlays=overlays,
        )
        fig.colorbar(mesh, ax=ax, shrink=0.82, extend=style.extend, label=style.label)
        ax.set_title(subtitle, fontsize=9)
    fig.suptitle(title)
    if annotation:
        fig.text(0.01, 0.005, annotation, fontsize=6, color="0.4", ha="left", va="bottom")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_deficit_budget(
    times,
    heat_mj_m2,
    interval_times,
    storage_tendency,
    convergence_tendency,
    unresolved_tendency,
    out_path: str | Path,
    *,
    title: str,
    spinup_end=None,
    annotation: str | None = None,
    dpi: int = 300,
) -> Path:
    """Plot area-mean storage, horizontal convergence, and unresolved tendency.

    ``storage_tendency`` and ``convergence_tendency`` must already use a common time
    interval and spatial mask.  This function does not label their difference as
    diabatic because reference-state, clipped-layer, vertical/boundary, and numerical
    terms may also contribute.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    out = Path(out_path)
    times = list(times)
    interval_times = list(interval_times)
    heat = np.asarray(heat_mj_m2, dtype=float)
    storage = np.asarray(storage_tendency, dtype=float)
    convergence = np.asarray(convergence_tendency, dtype=float)
    unresolved = np.asarray(unresolved_tendency, dtype=float)

    fig = plt.figure(figsize=(10.6, 6.2), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, width_ratios=(1.45, 1.0))
    ax_h = fig.add_subplot(gs[0, 0])
    ax_t = fig.add_subplot(gs[1, 0], sharex=ax_h)
    ax_s = fig.add_subplot(gs[:, 1])

    ax_h.plot(times, heat, color="black", marker="o", ms=2.8, lw=1.2)
    ax_h.set_ylabel(r"area-mean $H$ (MJ m$^{-2}$)")
    ax_h.grid(True, alpha=0.25)

    ax_t.plot(interval_times, storage, label=r"storage $\partial H/\partial t$", lw=1.3)
    ax_t.plot(interval_times, convergence, label=r"horizontal convergence $-\nabla_h\cdot F$", lw=1.3)
    ax_t.plot(interval_times, unresolved, label="unresolved tendency", lw=1.1, color="0.35")
    ax_t.axhline(0.0, color="0.5", lw=0.7)
    ax_t.set_ylabel(r"MJ m$^{-2}$ h$^{-1}$")
    ax_t.set_xlabel("valid time (UTC)")
    ax_t.grid(True, alpha=0.25)
    ax_t.legend(fontsize=7, ncol=1)

    if spinup_end is not None and times:
        for ax in (ax_h, ax_t):
            ax.axvspan(times[0], spinup_end, color="0.75", alpha=0.35, lw=0)
        ax_h.text(0.02, 0.92, "spin-up context", transform=ax_h.transAxes,
                  fontsize=7, color="0.35", ha="left", va="top")

    finite = np.isfinite(storage) & np.isfinite(convergence)
    if spinup_end is not None:
        finite &= np.asarray([valid >= spinup_end for valid in interval_times])
    if finite.any():
        color = mdates.date2num(np.asarray(interval_times, dtype=object)[finite])
        scat = ax_s.scatter(convergence[finite], storage[finite], c=color, cmap="viridis", s=28)
        lo = float(min(np.nanmin(storage[finite]), np.nanmin(convergence[finite])))
        hi = float(max(np.nanmax(storage[finite]), np.nanmax(convergence[finite])))
        pad = 0.08 * max(hi - lo, 1.0)
        ax_s.plot([lo - pad, hi + pad], [lo - pad, hi + pad], color="0.35", ls="--", lw=0.8)
        ax_s.set_xlim(lo - pad, hi + pad)
        ax_s.set_ylim(lo - pad, hi + pad)
        if (finite.sum() >= 2 and np.nanstd(storage[finite]) > 0.0
                and np.nanstd(convergence[finite]) > 0.0):
            corr = float(np.corrcoef(storage[finite], convergence[finite])[0, 1])
        else:
            corr = float("nan")
        rmse = float(np.sqrt(np.mean(np.square(unresolved[finite]))))
        comparison_label = "retained 10-min" if spinup_end is not None else "10-min"
        ax_s.set_title(
            f"{comparison_label} interval comparison\n"
            f"r={corr:.2f}; residual RMSE={rmse:.2f}"
        )
        cb = fig.colorbar(scat, ax=ax_s, shrink=0.72)
        cb.set_label("interval midpoint (UTC)")
        cb.ax.yaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_s.set_xlabel(r"$-\nabla_h\cdot F$ (MJ m$^{-2}$ h$^{-1}$)")
    ax_s.set_ylabel(r"$\partial H/\partial t$ (MJ m$^{-2}$ h$^{-1}$)")
    ax_s.grid(True, alpha=0.25)

    fig.suptitle(title)
    if annotation:
        fig.text(0.01, 0.005, annotation, fontsize=6, color="0.4", ha="left", va="bottom")
    fig.autofmt_xdate(rotation=25)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
