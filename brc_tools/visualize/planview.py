"""Plan-view (lat-lon) map plotting with optional obs overlay.

Provides reusable functions for rendering NWP gridded fields on Cartopy
maps, including station observation markers coloured by value on the same
colour scale as the NWP fill.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

# ---------------------------------------------------------------------------
# Map helpers (extracted from case_study_20250222.py)
# ---------------------------------------------------------------------------

KT_FACTOR = 1.94384  # m/s -> knots


def _lon_to_180(lon):
    """Convert longitude from 0..360 to -180..180."""
    return np.where(lon > 180, lon - 360, lon)


def _get_latlon(ds):
    """Extract 2-D lat/lon arrays, converting lon to -180..180."""
    lat = ds["latitude"].values
    lon = _lon_to_180(ds["longitude"].values)
    return lat, lon


def add_map_features(ax):
    """Add state/province borders to a Cartopy axes (10m resolution)."""
    states = cfeature.NaturalEarthFeature(
        "cultural", "admin_1_states_provinces_lakes", "10m",
        facecolor="none", edgecolor="black", linewidth=0.8,
    )
    ax.add_feature(states)


def add_waypoints(ax, waypoints, *, transform=None, fontsize=7, annotate=True):
    """Plot waypoint markers and labels on a Cartopy axes.

    Parameters
    ----------
    waypoints : dict
        ``{name: {"lat": ..., "lon": ...}}`` mapping.
    """
    if transform is None:
        transform = ccrs.PlateCarree()
    for name, wp in waypoints.items():
        ax.plot(
            wp["lon"], wp["lat"], "k^", markersize=5,
            transform=transform, zorder=10,
        )
        if annotate:
            ax.text(
                wp["lon"] + 0.05, wp["lat"] + 0.05,
                name.replace("_", " ").title(),
                fontsize=fontsize, transform=transform, zorder=10,
                ha="left", va="bottom",
                bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", pad=0.5),
            )


# ---------------------------------------------------------------------------
# Main plotting functions
# ---------------------------------------------------------------------------

def plot_planview(
    ds,
    variable: str,
    *,
    time_idx: int | None = None,
    valid_time: datetime.datetime | np.datetime64 | None = None,
    ax: plt.Axes | None = None,
    cmap: str = "RdYlBu_r",
    vmin: float | None = None,
    vmax: float | None = None,
    contour_var: str | None = None,
    contour_levels: np.ndarray | None = None,
    contour_colors: str = "black",
    wind_barbs: bool = False,
    barb_skip: int = 5,
    waypoints: dict | None = None,
    obs_overlay: pl.DataFrame | None = None,
    obs_variable: str | None = None,
    obs_marker_size: float = 80,
    obs_annotate_values: bool = True,
    title: str | None = None,
) -> plt.Axes:
    """Render a single plan-view time step.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded NWP dataset with ``latitude``, ``longitude``, and *variable*.
    variable : str
        Data variable name to fill (pcolormesh).
    time_idx : int, optional
        Index along the ``time`` dimension.  Mutually exclusive with *valid_time*.
    valid_time : datetime-like, optional
        Exact valid time to select.
    ax : matplotlib Axes, optional
        If *None*, a new figure/axes with PlateCarree projection is created.
    cmap, vmin, vmax : colour-map controls.
    contour_var : str, optional
        Variable to overlay as contour lines (e.g. ``"mslp"``).
    contour_levels : array, optional
        Contour levels.
    wind_barbs : bool
        If *True*, overlay wind barbs from ``wind_u_10m`` / ``wind_v_10m``.
    barb_skip : int
        Thin barbs by plotting every Nth grid point.
    waypoints : dict, optional
        ``{name: {"lat": ..., "lon": ...}}`` for waypoint markers.
    obs_overlay : pl.DataFrame, optional
        Observation DataFrame (from ``ObsSource.timeseries()``).  Stations at
        the matching valid time are plotted as filled circles coloured by
        *obs_variable* (or *variable* if not specified) on the same colour
        scale as the NWP fill.
    obs_variable : str, optional
        Column name in *obs_overlay* to colour by.  Defaults to *variable*.
    obs_marker_size : float
        Size of obs marker (scatter ``s`` parameter).
    obs_annotate_values : bool
        If *True*, annotate each station marker with the observed value.
    title : str, optional
        Axes title.

    Returns
    -------
    ax : matplotlib Axes
    """
    # Select time slice
    ds_t = _select_time(ds, time_idx, valid_time)

    lat, lon = _get_latlon(ds_t)
    field = ds_t[variable].values

    # Create axes if needed
    if ax is None:
        fig, ax = plt.subplots(
            figsize=(10, 8),
            subplot_kw={"projection": ccrs.PlateCarree()},
        )

    transform = ccrs.PlateCarree()
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    # Main fill
    cf = ax.pcolormesh(
        lon, lat, field,
        cmap=cmap, norm=norm,
        shading="nearest", transform=transform,
    )

    # Contour overlay
    if contour_var is not None and contour_var in ds_t.data_vars:
        cfield = ds_t[contour_var].values
        try:
            cs = ax.contour(
                lon, lat, cfield,
                levels=contour_levels,
                colors=contour_colors, linewidths=0.6,
                transform=transform,
            )
            ax.clabel(cs, fontsize=6, fmt="%.0f")
        except Exception:
            pass

    # Wind barbs
    if wind_barbs and "wind_u_10m" in ds_t.data_vars and "wind_v_10m" in ds_t.data_vars:
        u = ds_t["wind_u_10m"].values
        v = ds_t["wind_v_10m"].values
        s = barb_skip
        ax.barbs(
            lon[::s, ::s], lat[::s, ::s],
            u[::s, ::s] * KT_FACTOR, v[::s, ::s] * KT_FACTOR,
            length=5, linewidth=0.4, transform=transform,
        )

    # Map features
    add_map_features(ax)

    # Waypoints
    if waypoints is not None:
        add_waypoints(ax, waypoints, fontsize=6)

    # Obs overlay — station markers coloured by observed value
    if obs_overlay is not None:
        _overlay_obs(
            ax, ds_t, obs_overlay,
            obs_variable or variable,
            cmap=cmap, norm=norm,
            marker_size=obs_marker_size,
            annotate=obs_annotate_values,
            transform=transform,
        )

    # Colorbar
    cbar = ax.figure.colorbar(cf, ax=ax, orientation="horizontal", shrink=0.7, pad=0.06)
    cbar.set_label(variable, fontsize=9)
    cbar.ax.tick_params(labelsize=7)

    if title:
        ax.set_title(title, fontsize=11)
    else:
        vt = _get_valid_time_str(ds_t)
        ax.set_title(f"{variable}  |  Valid {vt}", fontsize=11)

    return ax


def plot_planview_evolution(
    ds,
    variable: str,
    *,
    time_indices: Sequence[int] | None = None,
    ncols: int = 3,
    figsize: tuple | None = None,
    shared_colorbar: bool = True,
    waypoints: dict | None = None,
    obs_overlay: pl.DataFrame | None = None,
    suptitle: str | None = None,
    dpi: int = 150,
    **planview_kwargs,
) -> plt.Figure:
    """Multi-panel plan-view showing field evolution over time.

    Parameters
    ----------
    ds : xr.Dataset
        Multi-time gridded dataset.
    variable : str
        Variable to render in each panel.
    time_indices : list of int, optional
        Which time steps to plot.  If *None*, all time steps are used.
    ncols : int
        Columns in the panel grid.
    shared_colorbar : bool
        If *True*, use a single colorbar with uniform vmin/vmax.
    obs_overlay : pl.DataFrame, optional
        If provided, station markers are overlaid at each panel's valid time.
    suptitle : str, optional
        Figure super-title.
    dpi : int
        Output resolution.
    **planview_kwargs
        Forwarded to ``plot_planview`` (e.g. *cmap*, *contour_var*, *wind_barbs*).

    Returns
    -------
    fig : matplotlib Figure
    """
    ntimes = ds.sizes.get("time", 1)
    if time_indices is None:
        time_indices = list(range(ntimes))
    npanels = len(time_indices)
    nrows = max(1, -(-npanels // ncols))  # ceiling division

    if figsize is None:
        figsize = (5.5 * ncols, 4.5 * nrows)

    fig, axes = plt.subplots(
        nrows, ncols, figsize=figsize,
        subplot_kw={"projection": ccrs.PlateCarree()},
        squeeze=False,
    )
    axes_flat = axes.flatten()

    # Compute shared vmin/vmax if not provided
    if shared_colorbar:
        if "vmin" not in planview_kwargs or planview_kwargs.get("vmin") is None:
            all_vals = ds[variable].values
            planview_kwargs["vmin"] = float(np.nanpercentile(all_vals, 2))
        if "vmax" not in planview_kwargs or planview_kwargs.get("vmax") is None:
            all_vals = ds[variable].values
            planview_kwargs["vmax"] = float(np.nanpercentile(all_vals, 98))

    for panel_idx, t_idx in enumerate(time_indices):
        ax = axes_flat[panel_idx]
        vt = _get_valid_time_str(ds.isel(time=t_idx))
        plot_planview(
            ds, variable,
            time_idx=t_idx,
            ax=ax,
            waypoints=waypoints,
            obs_overlay=obs_overlay,
            title=f"f{t_idx:02d} | {vt}",
            **planview_kwargs,
        )

    # Hide unused panels
    for j in range(npanels, len(axes_flat)):
        axes_flat[j].set_visible(False)

    if suptitle:
        fig.suptitle(suptitle, fontsize=13, y=1.01)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_time(ds, time_idx, valid_time):
    """Return a single-time slice of the dataset."""
    if valid_time is not None:
        target = np.datetime64(valid_time)
        time_vals = ds.time.values
        t_idx = int(np.argmin(np.abs(time_vals - target)))
        return ds.isel(time=t_idx)
    if time_idx is not None:
        return ds.isel(time=time_idx)
    if "time" in ds.dims and ds.sizes["time"] == 1:
        return ds.isel(time=0)
    raise ValueError("Provide time_idx= or valid_time= for multi-time datasets")


def _get_valid_time_str(ds_t) -> str:
    """Extract a human-readable valid-time string from a single-time dataset."""
    if "time" in ds_t.coords:
        val = ds_t.time.values
        if hasattr(val, "item"):
            val = val.item()
        return str(val)[:16] + "Z"
    return ""


def _overlay_obs(
    ax, ds_t, obs_df, variable, *, cmap, norm, marker_size, annotate, transform,
):
    """Plot station observations as coloured markers on an NWP map."""
    from brc_tools.nwp.source import load_lookups

    lu = load_lookups()
    waypoints_meta = lu["waypoints"]

    # Find the valid time of this NWP slice
    vt = ds_t.time.values
    if hasattr(vt, "item"):
        vt = vt.item()
    # Convert to a datetime-like that Polars can compare
    import datetime as _dt
    if isinstance(vt, np.datetime64):
        vt_py = vt.astype("datetime64[ms]").astype(_dt.datetime)
    else:
        vt_py = vt

    # Filter obs to within 30 min of this valid time
    if "valid_time" in obs_df.columns:
        delta = pl.duration(minutes=30)
        obs_near = obs_df.filter(
            (pl.col("valid_time") >= vt_py - delta) &
            (pl.col("valid_time") <= vt_py + delta)
        )
        # Take the obs closest to valid time per waypoint
        if "waypoint" in obs_near.columns and not obs_near.is_empty():
            obs_near = obs_near.with_columns(
                (pl.col("valid_time") - pl.lit(vt_py)).abs().alias("_dt")
            ).sort("_dt").group_by("waypoint").first().drop("_dt")
    else:
        obs_near = obs_df

    if obs_near.is_empty() or variable not in obs_near.columns:
        return

    # Get lat/lon for each station via waypoint metadata
    lats, lons, vals = [], [], []
    for row in obs_near.iter_rows(named=True):
        wp_name = row.get("waypoint")
        if wp_name is None or wp_name not in waypoints_meta:
            continue
        val = row.get(variable)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            continue
        wp = waypoints_meta[wp_name]
        lats.append(wp["lat"])
        lons.append(wp["lon"])
        vals.append(val)

    if not vals:
        return

    cmap_obj = plt.get_cmap(cmap) if isinstance(cmap, str) else cmap

    ax.scatter(
        lons, lats, c=vals,
        cmap=cmap_obj, norm=norm,
        s=marker_size, edgecolors="black", linewidths=1.5,
        marker="o", zorder=15, transform=transform,
    )

    if annotate:
        for lon, lat, val in zip(lons, lats, vals):
            ax.annotate(
                f"{val:.1f}",
                xy=(lon, lat), xytext=(4, 4),
                textcoords="offset points",
                fontsize=6, fontweight="bold",
                color="black",
                bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=0.3),
                transform=transform, zorder=16,
            )
