"""Reusable time-series plotting for NWP waypoint extractions and observations.

``plot_station_timeseries`` renders a multi-panel grid (one subplot per
waypoint) with optional NWP multi-run overlay and observation scatter.
``plot_verification_timeseries`` renders a single NWP-vs-obs comparison
with error shading.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

# Default line styles for multi-run comparison
DEFAULT_RUN_STYLES = {
    0: {"color": "tab:blue", "ls": "-", "lw": 1.5},
    1: {"color": "tab:red", "ls": "--", "lw": 1.5},
    2: {"color": "tab:green", "ls": "-.", "lw": 1.5},
    3: {"color": "tab:purple", "ls": ":", "lw": 1.5},
}


def plot_station_timeseries(
    nwp_series: dict[str | int, pl.DataFrame],
    variable: str,
    *,
    obs_df: pl.DataFrame | None = None,
    waypoint_names: Sequence[str] | None = None,
    waypoints_meta: dict | None = None,
    unit_label: str | None = None,
    unit_transform: Callable | None = None,
    secondary_variable: str | None = None,
    secondary_unit_label: str | None = None,
    secondary_unit_transform: Callable | None = None,
    run_styles: dict | None = None,
    ncols: int = 2,
    figsize: tuple | None = None,
    suptitle: str | None = None,
    dpi: int = 150,
) -> plt.Figure:
    """Multi-panel time series at waypoints with optional obs overlay.

    Parameters
    ----------
    nwp_series : dict
        ``{run_label: pl.DataFrame}`` where each DataFrame has columns
        ``waypoint``, ``valid_time``, and the requested *variable*.
        Labels are used in the legend (e.g. ``"15Z init"`` or an int).
    variable : str
        Primary variable to plot (y-axis left).
    obs_df : pl.DataFrame, optional
        Observation DataFrame with ``waypoint``, ``valid_time``, *variable*.
        Plotted as black scatter points.
    waypoint_names : list of str, optional
        Waypoints to include.  If *None*, union of all waypoints in
        *nwp_series* values.
    waypoints_meta : dict, optional
        ``{name: {"elevation_m": ...}}`` for subtitle annotation.
    unit_label : str, optional
        Y-axis label for the primary variable (e.g. ``"Temp (C)"``).
    unit_transform : callable, optional
        Applied to primary variable values before plotting (e.g. K-to-C).
    secondary_variable : str, optional
        A second variable plotted on the right y-axis (twin axes).
    secondary_unit_label : str, optional
        Right y-axis label.
    secondary_unit_transform : callable, optional
        Transform for the secondary variable values.
    run_styles : dict, optional
        ``{run_label: {"color": ..., "ls": ..., "lw": ...}}``.
    ncols : int
        Columns in the panel grid.
    figsize : tuple, optional
        Figure size; auto-computed if *None*.
    suptitle : str, optional
        Figure super-title.

    Returns
    -------
    fig : matplotlib Figure
    """
    if run_styles is None:
        run_styles = {}
        for i, key in enumerate(nwp_series):
            base = DEFAULT_RUN_STYLES.get(i % len(DEFAULT_RUN_STYLES), DEFAULT_RUN_STYLES[0])
            run_styles[key] = {**base, "label": str(key)}

    # Determine waypoints
    if waypoint_names is None:
        all_wps: set[str] = set()
        for df in nwp_series.values():
            if "waypoint" in df.columns:
                all_wps.update(df["waypoint"].unique().to_list())
        waypoint_names = sorted(all_wps)

    npanels = len(waypoint_names)
    nrows = max(1, -(-npanels // ncols))
    if figsize is None:
        figsize = (6 * ncols, 3.5 * nrows)

    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, sharex=True, squeeze=False)
    axes_flat = axes.flatten()

    for idx, wp_name in enumerate(waypoint_names):
        ax = axes_flat[idx]
        ax2 = ax.twinx() if secondary_variable else None

        for run_key, df in nwp_series.items():
            wp_df = df.filter(pl.col("waypoint") == wp_name).sort("valid_time")
            if wp_df.is_empty():
                continue

            times = wp_df["valid_time"].to_list()
            style = run_styles.get(run_key, DEFAULT_RUN_STYLES[0])
            label = style.get("label", str(run_key))

            # Primary variable
            if variable in wp_df.columns:
                vals = np.array(wp_df[variable].to_list(), dtype=float)
                if unit_transform is not None:
                    vals = unit_transform(vals)
                ax.plot(times, vals, color=style["color"], ls=style["ls"],
                        linewidth=style.get("lw", 1.5), label=label)

            # Secondary variable
            if secondary_variable and ax2 and secondary_variable in wp_df.columns:
                vals2 = np.array(wp_df[secondary_variable].to_list(), dtype=float)
                if secondary_unit_transform is not None:
                    vals2 = secondary_unit_transform(vals2)
                ax2.plot(times, vals2, color=style["color"], ls=style["ls"],
                         linewidth=style.get("lw", 1.0), alpha=0.5)

        # Obs overlay
        if obs_df is not None and "waypoint" in obs_df.columns:
            obs_wp = obs_df.filter(pl.col("waypoint") == wp_name).sort("valid_time")
            if not obs_wp.is_empty():
                obs_times = obs_wp["valid_time"].to_list()
                if variable in obs_wp.columns:
                    obs_vals = np.array(obs_wp[variable].to_list(), dtype=float)
                    if unit_transform is not None:
                        obs_vals = unit_transform(obs_vals)
                    ax.scatter(obs_times, obs_vals, c="black", s=10,
                               marker="o", zorder=5, label="Obs")
                if secondary_variable and ax2 and secondary_variable in obs_wp.columns:
                    obs_vals2 = np.array(obs_wp[secondary_variable].to_list(), dtype=float)
                    if secondary_unit_transform is not None:
                        obs_vals2 = secondary_unit_transform(obs_vals2)
                    ax2.scatter(obs_times, obs_vals2, c="black", s=10,
                                marker="x", zorder=5)

        # Formatting
        title_str = wp_name.replace("_", " ").title()
        if waypoints_meta and wp_name in waypoints_meta:
            elev = waypoints_meta[wp_name].get("elevation_m")
            if elev is not None:
                title_str += f" ({elev} m)"
        ax.set_title(title_str, fontsize=10)
        if unit_label:
            ax.set_ylabel(unit_label, fontsize=9)
        if secondary_unit_label and ax2:
            ax2.set_ylabel(secondary_unit_label, fontsize=9)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3)

        if idx == 0:
            ax.legend(fontsize=6, loc="upper left")

    # X-axis labels on bottom row
    for ax_bottom in axes[-1]:
        ax_bottom.set_xlabel("Valid Time (UTC)", fontsize=9)
        for label in ax_bottom.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

    # Hide unused panels
    for j in range(npanels, len(axes_flat)):
        axes_flat[j].set_visible(False)

    if suptitle:
        fig.suptitle(suptitle, fontsize=13)
    fig.tight_layout()
    return fig


def plot_verification_timeseries(
    nwp_df: pl.DataFrame,
    obs_df: pl.DataFrame,
    variable: str,
    waypoint: str,
    *,
    unit_label: str | None = None,
    unit_transform: Callable | None = None,
    ax: plt.Axes | None = None,
    show_error: bool = True,
    title: str | None = None,
) -> plt.Axes:
    """Plot NWP vs obs for a single station/variable with error shading.

    Parameters
    ----------
    nwp_df, obs_df : pl.DataFrame
        Point DataFrames with ``waypoint``, ``valid_time``, *variable*.
    variable : str
        Variable to compare.
    waypoint : str
        Single waypoint name.
    show_error : bool
        If *True*, shade the area between NWP and obs.

    Returns
    -------
    ax : matplotlib Axes
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 4))

    nwp_wp = nwp_df.filter(pl.col("waypoint") == waypoint).sort("valid_time")
    obs_wp = obs_df.filter(pl.col("waypoint") == waypoint).sort("valid_time")

    if nwp_wp.is_empty():
        return ax

    nwp_times = nwp_wp["valid_time"].to_list()
    nwp_vals = np.array(nwp_wp[variable].to_list(), dtype=float)
    if unit_transform:
        nwp_vals = unit_transform(nwp_vals)

    ax.plot(nwp_times, nwp_vals, "b-", linewidth=1.5, label="NWP")

    if not obs_wp.is_empty() and variable in obs_wp.columns:
        obs_times = obs_wp["valid_time"].to_list()
        obs_vals = np.array(obs_wp[variable].to_list(), dtype=float)
        if unit_transform:
            obs_vals = unit_transform(obs_vals)
        ax.scatter(obs_times, obs_vals, c="red", s=20, marker="o",
                   zorder=5, label="Obs")

        # Error shading: interpolate NWP to obs times for fill_between
        if show_error and len(obs_times) > 1:
            nwp_ts = np.array([t.timestamp() if hasattr(t, "timestamp") else 0
                               for t in nwp_times])
            obs_ts = np.array([t.timestamp() if hasattr(t, "timestamp") else 0
                               for t in obs_times])
            nwp_interp = np.interp(obs_ts, nwp_ts, nwp_vals)
            ax.fill_between(
                obs_times, obs_vals, nwp_interp,
                alpha=0.15, color="red", label="Error",
            )

    wp_label = waypoint.replace("_", " ").title()
    ax.set_title(title or f"{variable} at {wp_label}", fontsize=11)
    if unit_label:
        ax.set_ylabel(unit_label, fontsize=10)
    ax.set_xlabel("Valid Time (UTC)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    return ax
