"""Forecast-funnel renderers: synoptic -> regional -> local -> surface montage.

The plotting half of the forecast funnel.  Like the rest of ``visualize`` these
renderers take **plain lon/lat arrays** (never datasets), call ``use_publication_style``
downstream for the shared Helvetica look, and dress each panel with the fail-soft
Natural-Earth overlays (state borders, rivers, lakes, population-ranked city labels).
The data layer :mod:`brc_tools.nwp.forecast_funnel` owns every GRIB concern and hands
this module ready-cropped arrays as :class:`~brc_tools.nwp.forecast_funnel.Panel`
objects; the panel functions are duck-typed on plain arrays so they unit-test with
synthetic input.

Panels:

* **isotach** (250 / 500 hPa) — wind-speed fill, geopotential-height contours, barbs.
* **moisture** (600 hPa) — specific-humidity fill, height contours, barbs, a bold
  low-level-jet isotach contour.
* **synoptic** (surface) — smoothed MSLP isobars, auto H/L centres, and diagnostic
  Thermal-Front-Parameter frontal zones (approximate — TFP marks baroclinic zones,
  it does not truly type warm/cold fronts).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

KT = 1.94384  # m/s -> knots

# Funnel overlays: borders + hydrography + city labels; roads off (too busy at
# synoptic scale).  ``cities`` is read from this dict by ``add_reference_overlays``.
_FUNNEL_OVERLAYS = {"states": True, "roads": False, "rivers": True,
                    "lakes": True, "cities": True}

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _validate_output_dir(path: Path) -> None:
    """Refuse to write a funnel figure into the repo checkout (runtime output rule)."""
    resolved = Path(path).resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        raise SystemExit(f"refusing to write figure into the repo checkout: {resolved}")


def _contour_levels(field, interval: float) -> np.ndarray:
    """Evenly spaced contour levels spanning a field's finite range."""
    vals = np.asarray(field, dtype=float)
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return np.array([])
    lo = np.floor(float(finite.min()) / interval) * interval
    hi = np.ceil(float(finite.max()) / interval) * interval
    return np.arange(lo, hi + interval, interval)


def _draw_overlays(ax, extent, waypoints=None):
    """Shared fail-soft dressing: Natural-Earth overlays + optional waypoints."""
    from brc_tools.visualize.basemap import add_reference_overlays, draw_waypoints

    add_reference_overlays(ax, extent, layers=_FUNNEL_OVERLAYS)
    if waypoints:
        draw_waypoints(ax, waypoints, extent, zorder=11)


def _finish_axes(ax, lat, extent, title):
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect(1.0 / np.cos(np.deg2rad(float(np.nanmean(lat)))))
    ax.tick_params(labelsize=7)
    ax.set_title(title)


def _draw_barbs(ax, lon, lat, u, v, stride):
    sy = max(1, u.shape[0] // stride)
    sx = max(1, u.shape[1] // stride)
    ax.barbs(lon[::sy, ::sx], lat[::sy, ::sx],
             (np.asarray(u) * KT)[::sy, ::sx], (np.asarray(v) * KT)[::sy, ::sx],
             length=5, linewidth=0.5, zorder=5)


def _draw_heights(ax, lon, lat, height_m, interval_dam):
    dam = np.asarray(height_m, dtype=float) / 10.0  # metres -> decametres
    levels = _contour_levels(dam, interval_dam)
    if levels.size:
        cs = ax.contour(lon, lat, dam, levels=levels, colors="black",
                        linewidths=0.6, alpha=0.8, zorder=4)
        ax.clabel(cs, fontsize=6, fmt="%d", inline=True)


def plot_upperair_panel(ax, lon, lat, fill, height, u, v, *, style, level_label,
                        extent, waypoints=None, barbs=True, height_interval_dam=6.0,
                        barb_stride=18, title=None):
    """Scalar fill (isotachs or absolute vorticity) + height contours + barbs."""
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    mesh = ax.pcolormesh(lon, lat, np.asarray(fill, dtype=float), shading="auto",
                         cmap=style.cmap, vmin=style.vmin, vmax=style.vmax, alpha=0.95)
    ax.figure.colorbar(mesh, ax=ax, shrink=0.85, extend=style.extend, label=style.label)
    _draw_heights(ax, lon, lat, height, height_interval_dam)
    if barbs and u is not None and v is not None:
        _draw_barbs(ax, lon, lat, u, v, barb_stride)
    _draw_overlays(ax, extent, waypoints)
    _finish_axes(ax, lat, extent, title or f"{level_label}")
    return mesh


# Temperature-advection contour levels (K/h): warm (red, solid) / cold (blue, dashed).
_ADV_LEVELS = np.array([-3.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 3.0])


def plot_moisture_panel(ax, lon, lat, spfh, height, u, v, *, style, level_label,
                        extent, waypoints=None, t_adv=None, height_interval_dam=6.0,
                        barb_stride=14, title=None):
    """Specific-humidity fill + heights + warm/cold-air (temperature) advection + barbs."""
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    mesh = ax.pcolormesh(lon, lat, np.asarray(spfh, dtype=float), shading="auto",
                         cmap=style.cmap, vmin=style.vmin, vmax=style.vmax, alpha=0.95)
    ax.figure.colorbar(mesh, ax=ax, shrink=0.85, extend=style.extend, label=style.label)
    _draw_heights(ax, lon, lat, height, height_interval_dam)
    if t_adv is not None:
        adv = np.asarray(t_adv, dtype=float)
        if np.isfinite(adv).any() and float(np.nanmax(np.abs(adv))) >= _ADV_LEVELS[-1] * 0.15:
            colors = ["#1565c0" if lv < 0 else "#c62828" for lv in _ADV_LEVELS]
            styles = ["dashed" if lv < 0 else "solid" for lv in _ADV_LEVELS]
            cs = ax.contour(lon, lat, adv, levels=_ADV_LEVELS, colors=colors,
                            linestyles=styles, linewidths=0.8, alpha=0.9, zorder=4.5)
            ax.clabel(cs, fontsize=5.5, fmt="%.1f", inline=True)
    if u is not None and v is not None:
        _draw_barbs(ax, lon, lat, u, v, barb_stride)
    _draw_overlays(ax, extent, waypoints)
    _finish_axes(ax, lat, extent, title or f"{level_label}")
    return mesh


def plot_synoptic_panel(ax, lon, lat, mslp_hpa, *, centers=None, tfp=None, t_adv=None,
                        extent, waypoints=None, isobar_interval=4.0, smooth_sigma=1.5,
                        tfp_threshold=1.5, title=None):
    """Surface analysis: smoothed MSLP isobars, H/L centres, and TFP frontal zones."""
    from brc_tools.visualize.upperair import _nan_gaussian

    lon = np.asarray(lon)
    lat = np.asarray(lat)
    p = np.asarray(mslp_hpa, dtype=float)
    if smooth_sigma and smooth_sigma > 0:
        p = _nan_gaussian(p, smooth_sigma)

    levels = _contour_levels(p, isobar_interval)
    if levels.size:
        cs = ax.contour(lon, lat, p, levels=levels, colors="0.25",
                        linewidths=0.7, zorder=4)
        ax.clabel(cs, fontsize=6, fmt="%d", inline=True)

    # Diagnostic TFP frontal zones: contour the threshold isopleth, split by 850 hPa
    # advection so the line is coloured cold (blue) / warm (red).  Mask by advection
    # sign only — NOT by the threshold — so the field still crosses ``tfp_threshold``
    # inside each region and ``contour`` actually draws a line.
    if tfp is not None:
        tfp = np.asarray(tfp, dtype=float)
        adv = np.zeros_like(tfp) if t_adv is None else np.asarray(t_adv, dtype=float)
        cold = np.where(adv < 0, tfp, np.nan)
        warm = np.where(adv >= 0, tfp, np.nan)
        for f, c in ((cold, "#1565c0"), (warm, "#c62828")):
            if np.isfinite(f).any() and np.nanmax(f) >= tfp_threshold:
                ax.contour(lon, lat, f, levels=[tfp_threshold], colors=c,
                           linewidths=1.6, alpha=0.9, zorder=4.5)

    for c in centers or []:
        col = "#1565c0" if c["kind"] == "L" else "#c62828"
        ax.text(c["lon"], c["lat"], c["kind"], fontsize=15, fontweight="bold",
                color=col, ha="center", va="center", zorder=12)
        off = 0.03 * (extent[3] - extent[2])
        ax.text(c["lon"], c["lat"] - off, f"{c['value']:.0f}", fontsize=6.5,
                color=col, ha="center", va="top", zorder=12)

    _draw_overlays(ax, extent, waypoints)
    _finish_axes(ax, lat, extent, title or "mean sea level")
    return None


# ── panel dispatch + montage ────────────────────────────────────────────────
def _render_panel(ax, panel):
    """Dispatch one funnel Panel onto an axis by its kind."""
    from brc_tools.visualize.style import resolve_style

    f = panel.fields
    if panel.kind in ("isotach", "vorticity"):
        default_style = "wind_speed" if panel.kind == "isotach" else "abs_vorticity_500"
        style = resolve_style(panel.style_key or default_style)
        interval = 12.0 if "250" in panel.level_label else 6.0
        plot_upperair_panel(ax, panel.lon, panel.lat, f["scalar"], f["height"],
                            f["u"], f["v"], style=style, level_label=panel.level_label,
                            extent=panel.extent, waypoints=panel.waypoints,
                            height_interval_dam=interval,
                            title=f"{panel.key}) {panel.title}")
    elif panel.kind == "moisture":
        style = resolve_style(panel.style_key or "spec_humidity_600")
        plot_moisture_panel(ax, panel.lon, panel.lat, f["scalar"], f["height"],
                            f["u"], f["v"], style=style, level_label=panel.level_label,
                            extent=panel.extent, waypoints=panel.waypoints,
                            t_adv=f.get("t_adv"), title=f"{panel.key}) {panel.title}")
    elif panel.kind == "synoptic":
        fr = panel.fronts or {}
        plot_synoptic_panel(ax, panel.lon, panel.lat, f["mslp"],
                            centers=panel.centers, tfp=fr.get("tfp"),
                            t_adv=fr.get("t_adv"), extent=panel.extent,
                            waypoints=panel.waypoints,
                            title=f"{panel.key}) {panel.title}")
    else:  # pragma: no cover - defensive
        ax.set_axis_off()


def plot_forecast_funnel(data, out_path, *, dpi: int = 300, title: str | None = None,
                         figsize: tuple[float, float] = (13.0, 11.0),
                         annotation: str | None = None) -> Path:
    """Assemble the four funnel panels into one 2x2 montage figure.

    ``data`` is a :class:`~brc_tools.nwp.forecast_funnel.FunnelData` (duck-typed:
    ``.panels``, ``.init_time``, ``.valid_time``, ``.model_label``).  Refuses to write
    inside the repo checkout.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out_path)
    _validate_output_dir(out.parent)

    by_key = {p.key: p for p in data.panels}
    order = ["1a", "1b", "1c", "1d"]

    fig, axes = plt.subplots(2, 2, figsize=figsize, constrained_layout=True)
    flat = axes.ravel()
    for ax, key in zip(flat, order):
        panel = by_key.get(key)
        if panel is None:
            ax.set_axis_off()
            ax.text(0.5, 0.5, f"{key}: unavailable", transform=ax.transAxes,
                    ha="center", va="center", fontsize=9, color="0.5")
            continue
        _render_panel(ax, panel)

    init_s = data.init_time.strftime("%Y-%m-%d %H:%MZ")
    suptitle = title or f"Forecast funnel — {data.model_label}\nanalysis valid {init_s}"
    fig.suptitle(suptitle, fontsize=12, fontweight="bold")
    stamp = annotation or f"{data.model_label} | init {init_s} | BRC Tools"
    fig.text(0.995, 0.004, stamp, ha="right", va="bottom", fontsize=6, alpha=0.6)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
