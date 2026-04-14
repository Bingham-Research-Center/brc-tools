"""Case study: 22 Feb 2025 Uinta Basin cold-pool erosion / quasi-warm-front.

Fetches HRRR surface and pressure-level data via NWPSource, optionally
fetches Synoptic observations via ObsSource, and produces publication-
quality figures illustrating the foehn-driven warming and its eastward
progression during the afternoon of 22 Feb 2025.

Figures 1-6 are the original analysis; figures 7-11 add theta-e / dewpoint
evolution, obs-on-NWP overlay, deterministic verification, and a dense
14-station time-series panel using the ``us40_dense`` waypoint group.

Usage::

    conda run -n brc-tools python scripts/case_study_20250222.py
"""

import datetime
import traceback
from pathlib import Path

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np

from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import (
    add_theta_e,
    add_wind_fields,
    pa_to_hpa,
    temp_K_to_C,
)
from brc_tools.nwp.source import load_lookups
from brc_tools.visualize.planview import (
    KT_FACTOR,
    _get_latlon,
    add_map_features,
    add_waypoints,
    plot_planview_evolution,
)
from brc_tools.visualize.timeseries import plot_station_timeseries

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTDIR = Path(__file__).resolve().parent.parent / "figures" / "case_study_20250222"
OUTDIR.mkdir(parents=True, exist_ok=True)

DATE = "2025-02-22"
INIT_HOURS = [15, 16, 17]  # three HRRR runs to compare
SFC_VARS = [
    "temp_2m", "dewpoint_2m", "wind_u_10m", "wind_v_10m", "mslp", "pbl_height",
]
PL_VARS = ["temp_pl", "wind_u_pl", "wind_v_pl", "height_pl"]
PL_LEVELS = [1000, 950, 925, 900, 850, 800, 750, 700]
FHOURS = range(0, 13)

# Original 6-station foehn path (figures 1-6)
WP_GROUP = "foehn_path"
WP_NAMES = [
    "daniels_summit", "fruitland", "duchesne", "myton", "roosevelt", "vernal",
]

# Dense 14-station US-40 transect (new figures)
DENSE_GROUP = "us40_dense"

ANNOTATION = "HRRR | 22 Feb 2025 | BRC Tools"
DPI = 150
BARB_SKIP = 5  # thin wind barbs every Nth grid point

# Styling constants
TITLE_SIZE = 12
LABEL_SIZE = 10
TICK_SIZE = 8

# Line style for multi-run comparison
RUN_STYLES = {
    15: {"color": "tab:blue",   "ls": "-",  "label": "15Z init"},
    16: {"color": "tab:red",    "ls": "--", "label": "16Z init"},
    17: {"color": "tab:green",  "ls": "-.", "label": "17Z init"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_waypoints(group=WP_GROUP):
    """Return dict of waypoint metadata from lookups.toml."""
    lu = load_lookups()
    names = lu["waypoint_groups"][group]
    return {name: lu["waypoints"][name] for name in names}


def _annotate(fig, text=ANNOTATION):
    """Add a small attribution annotation to the figure."""
    fig.text(
        0.99, 0.01, text, fontsize=6, ha="right", va="bottom",
        fontstyle="italic", color="gray",
    )


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_surface_runs(src):
    """Fetch surface data for all three HRRR init times.

    Returns dict {init_hour: xr.Dataset}.
    """
    datasets = {}
    for ih in INIT_HOURS:
        init_str = f"{DATE} {ih:02d}Z"
        print(f"  Fetching HRRR sfc init={init_str} f00-f12 ...")
        ds = src.fetch(
            init_time=init_str,
            forecast_hours=FHOURS,
            variables=SFC_VARS,
            region="uinta_basin",
        )
        ds = add_wind_fields(ds)
        ds = add_theta_e(ds)
        datasets[ih] = ds
        print(f"    -> {ds.sizes}")
    return datasets


def fetch_pressure_levels(src):
    """Fetch pressure-level data from the 16Z run (f07 only for the cross-section)."""
    print("  Fetching HRRR pressure-level data init=16Z f07 ...")
    ds = src.fetch(
        init_time=f"{DATE} 16Z",
        forecast_hours=[7],
        variables=PL_VARS,
        levels=PL_LEVELS,
        region="uinta_basin_wide",
    )
    print(f"    -> {ds.sizes}")
    return ds


def extract_waypoint_series(src, datasets, group=WP_GROUP):
    """Extract time series at waypoints for each run.

    Returns dict {init_hour: pl.DataFrame}.
    """
    wp_series = {}
    for ih, ds in datasets.items():
        print(f"  Extracting waypoints ({group}) for {ih}Z run ...")
        df = src.extract_at_waypoints(ds, group=group)
        wp_series[ih] = df
    return wp_series


def fetch_observations(group=WP_GROUP):
    """Attempt to fetch Synoptic observations; returns None on failure."""
    try:
        from brc_tools.obs import ObsSource
        obs = ObsSource()
        print(f"  Fetching Synoptic observations ({group}) ...")
        obs_df = obs.timeseries(
            waypoint_group=group,
            start=f"{DATE} 12Z",
            end="2025-02-23 06Z",
            variables=["temp_2m", "dewpoint_2m", "wind_speed_10m", "wind_dir_10m", "mslp"],
        )
        print(f"    -> {obs_df.shape[0]} obs rows")
        return obs_df
    except Exception as exc:
        print(f"  [WARN] ObsSource failed (Synoptic API not configured?): {exc}")
        print("         NWP-only plots will still be produced.")
        return None


# ---------------------------------------------------------------------------
# Original figures (1-6)
# ---------------------------------------------------------------------------

def figure1_surface_comparison(datasets, waypoints):
    """3-panel map: temp_2m + wind barbs + MSLP contours, valid 23Z."""
    fig, axes = plt.subplots(
        1, 3, figsize=(18, 6),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    fxx_map = {15: 8, 16: 7, 17: 6}

    for idx, ih in enumerate(INIT_HOURS):
        ax = axes[idx]
        ds = datasets[ih]
        fxx = fxx_map[ih]

        target_valid = np.datetime64(f"{DATE}T23:00:00")
        time_vals = ds.time.values
        t_idx = int(np.argmin(np.abs(time_vals - target_valid)))
        ds_t = ds.isel(time=t_idx)

        lat, lon = _get_latlon(ds_t)
        temp_C = temp_K_to_C(ds_t["temp_2m"].values)
        mslp_hpa = pa_to_hpa(ds_t["mslp"].values)
        u = ds_t["wind_u_10m"].values
        v = ds_t["wind_v_10m"].values

        cf = ax.pcolormesh(
            lon, lat, temp_C,
            cmap="RdYlBu_r", vmin=-10, vmax=15,
            shading="nearest", transform=ccrs.PlateCarree(),
        )

        try:
            ax.contour(
                lon, lat, mslp_hpa,
                levels=np.arange(960, 1060, 2),
                colors="black", linewidths=0.6,
                transform=ccrs.PlateCarree(),
            )
        except Exception:
            pass

        s = BARB_SKIP
        ax.barbs(
            lon[::s, ::s], lat[::s, ::s],
            u[::s, ::s] * KT_FACTOR, v[::s, ::s] * KT_FACTOR,
            length=5, linewidth=0.4,
            transform=ccrs.PlateCarree(),
        )

        add_map_features(ax)
        add_waypoints(ax, waypoints)

        actual_valid = str(ds.time.values[t_idx])[:16]
        ax.set_title(
            f"Init {ih:02d}Z (f{fxx:03d})\nValid {actual_valid}Z",
            fontsize=TITLE_SIZE,
        )

    cbar = fig.colorbar(cf, ax=axes, orientation="horizontal", shrink=0.6, pad=0.08)
    cbar.set_label("2-m Temperature (C)", fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)

    fig.suptitle(
        "HRRR 2-m Temperature, 10-m Wind, MSLP | Valid ~23Z 22 Feb 2025",
        fontsize=TITLE_SIZE + 2, y=1.02,
    )
    _annotate(fig)
    fig.subplots_adjust(wspace=0.05)
    out = OUTDIR / "fig1_surface_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure2_wind_evolution(datasets, waypoints):
    """4x3 panel grid of wind speed from the 16Z run, f00-f12."""
    ds = datasets[16]
    ntimes = ds.sizes["time"]
    nrows, ncols = 4, 3
    npanels = nrows * ncols

    fig, axes = plt.subplots(
        nrows, ncols, figsize=(16, 18),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    axes_flat = axes.flatten()

    cf = None
    for t_idx in range(min(ntimes, npanels)):
        ax = axes_flat[t_idx]
        ds_t = ds.isel(time=t_idx)
        lat, lon = _get_latlon(ds_t)
        wspd = ds_t["wind_speed_10m"].values
        u = ds_t["wind_u_10m"].values
        v = ds_t["wind_v_10m"].values

        cf = ax.pcolormesh(
            lon, lat, wspd,
            cmap="YlOrRd", vmin=0, vmax=15,
            shading="nearest", transform=ccrs.PlateCarree(),
        )

        s = BARB_SKIP
        ax.barbs(
            lon[::s, ::s], lat[::s, ::s],
            u[::s, ::s] * KT_FACTOR, v[::s, ::s] * KT_FACTOR,
            length=4, linewidth=0.3,
            transform=ccrs.PlateCarree(),
        )

        add_map_features(ax)
        add_waypoints(ax, waypoints, fontsize=5)

        valid_str = str(ds.time.values[t_idx])[:16]
        ax.set_title(f"f{t_idx:03d} | Valid {valid_str}Z", fontsize=TICK_SIZE)

    for j in range(min(ntimes, npanels), npanels):
        axes_flat[j].set_visible(False)

    cbar = fig.colorbar(cf, ax=axes, orientation="horizontal", shrink=0.5, pad=0.03)
    cbar.set_label("10-m Wind Speed (m/s)", fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)

    fig.suptitle(
        "HRRR 16Z Init | 10-m Wind Speed + Barbs | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2, y=1.0,
    )
    _annotate(fig)
    fig.subplots_adjust(hspace=0.15, wspace=0.05)
    out = OUTDIR / "fig2_wind_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure3_timeseries(wp_series, obs_df, waypoints):
    """3x2 panel: temp_2m and wind_speed at each foehn_path waypoint."""
    nwp_for_plot = {RUN_STYLES[ih]["label"]: wp_series[ih] for ih in INIT_HOURS}
    styles = {RUN_STYLES[ih]["label"]: {**RUN_STYLES[ih], "label": RUN_STYLES[ih]["label"]}
              for ih in INIT_HOURS}

    fig = plot_station_timeseries(
        nwp_for_plot,
        "temp_2m",
        obs_df=obs_df,
        waypoint_names=WP_NAMES,
        waypoints_meta=waypoints,
        unit_label="Temp (C)",
        unit_transform=lambda x: x - 273.15,
        secondary_variable="wind_speed_10m",
        secondary_unit_label="Wind Speed (m/s)",
        run_styles=styles,
        ncols=2,
        suptitle="HRRR 2-m Temp & 10-m Wind Speed at Foehn Path Waypoints | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig3_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure4_pbl_height(wp_series, waypoints):
    """3x2 panel: PBL height vs time at each waypoint."""
    fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    axes_flat = axes.flatten()

    for idx, wp_name in enumerate(WP_NAMES):
        ax = axes_flat[idx]

        for ih in INIT_HOURS:
            df = wp_series[ih]
            wp_df = df.filter(df["waypoint"] == wp_name).sort("valid_time")
            if wp_df.is_empty() or "pbl_height" not in wp_df.columns:
                continue

            times = wp_df["valid_time"].to_list()
            pbl = wp_df["pbl_height"].to_list()
            style = RUN_STYLES[ih]
            ax.plot(times, pbl, color=style["color"], ls=style["ls"],
                    linewidth=1.5, label=style["label"])

        try:
            erosion_start = datetime.datetime(2025, 2, 22, 20, 0)
            erosion_end = datetime.datetime(2025, 2, 23, 0, 0)
            ax.axvspan(erosion_start, erosion_end, alpha=0.1, color="orange",
                       label="Erosion window")
        except Exception:
            pass

        elev = waypoints[wp_name]["elevation_m"]
        ax.set_title(
            f"{wp_name.replace('_', ' ').title()} ({elev} m)",
            fontsize=TITLE_SIZE,
        )
        ax.set_ylabel("PBL Height (m)", fontsize=LABEL_SIZE)
        ax.tick_params(labelsize=TICK_SIZE)
        ax.grid(True, alpha=0.3)

        if idx == 0:
            ax.legend(fontsize=7, loc="upper left")

    for ax_row in axes[-1]:
        ax_row.set_xlabel("Valid Time (UTC)", fontsize=LABEL_SIZE)
        for label in ax_row.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

    fig.suptitle(
        "HRRR PBL Height at Foehn Path Waypoints | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig4_pbl_height.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure5_cross_section(ds_pl, waypoints):
    """W-E cross-section of temperature and wind at ~40.3N, valid 23Z."""
    from brc_tools.nwp.derived import potential_temperature

    ds_t = ds_pl.isel(time=0)
    lat2d = ds_t["latitude"].values
    lon2d = np.where(ds_t["longitude"].values > 180,
                     ds_t["longitude"].values - 360,
                     ds_t["longitude"].values)

    lat_mean = lat2d.mean(axis=1) if lat2d.ndim == 2 else lat2d
    y_target = int(np.argmin(np.abs(lat_mean - 40.3)))

    if lon2d.ndim == 2:
        lons = lon2d[y_target, :]
    else:
        lons = lon2d

    levels = PL_LEVELS
    temp_xsec = np.full((len(levels), len(lons)), np.nan)
    wspd_xsec = np.full((len(levels), len(lons)), np.nan)
    u_xsec = np.full((len(levels), len(lons)), np.nan)

    for li, lv in enumerate(levels):
        tname = f"temp_{lv}"
        uname = f"wind_u_{lv}"
        vname = f"wind_v_{lv}"
        if tname in ds_t.data_vars:
            tdata = ds_t[tname].values
            temp_xsec[li, :] = tdata[y_target, :] if tdata.ndim == 2 else tdata
        if uname in ds_t.data_vars and vname in ds_t.data_vars:
            udata = ds_t[uname].values
            vdata = ds_t[vname].values
            u_row = udata[y_target, :] if udata.ndim == 2 else udata
            v_row = vdata[y_target, :] if vdata.ndim == 2 else vdata
            wspd_xsec[li, :] = np.sqrt(u_row ** 2 + v_row ** 2)
            u_xsec[li, :] = u_row

    p_arr = np.array(levels).reshape(-1, 1)
    theta_xsec = potential_temperature(temp_xsec, p_arr)

    fig, ax = plt.subplots(figsize=(12, 6))

    cf = ax.pcolormesh(
        lons, levels, theta_xsec,
        cmap="RdYlBu_r", shading="nearest",
    )
    cbar = fig.colorbar(cf, ax=ax, pad=0.02)
    cbar.set_label("Potential Temperature (K)", fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)

    try:
        cs = ax.contour(
            lons, levels, wspd_xsec,
            levels=np.arange(2, 30, 2),
            colors="black", linewidths=0.6,
        )
        ax.clabel(cs, fontsize=6, fmt="%.0f")
    except Exception:
        pass

    barb_skip_x = 4
    barb_skip_z = 1
    lon_barb = lons[::barb_skip_x]
    lev_barb = np.array(levels)[::barb_skip_z]
    u_barb = u_xsec[::barb_skip_z, ::barb_skip_x] * KT_FACTOR
    w_barb = np.zeros_like(u_barb)
    lon_grid, lev_grid = np.meshgrid(lon_barb, lev_barb)
    ax.barbs(lon_grid, lev_grid, u_barb, w_barb, length=5, linewidth=0.4)

    ax.set_ylim(max(levels), min(levels))
    ax.set_ylabel("Pressure (hPa)", fontsize=LABEL_SIZE)
    ax.set_xlabel("Longitude", fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)

    ax2 = ax.twiny()
    wp_lons = []
    wp_labels = []
    for name, wp in waypoints.items():
        ax.axvline(wp["lon"], color="gray", ls=":", lw=0.5)
        wp_lons.append(wp["lon"])
        wp_labels.append(name.replace("_", " ").title())
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(wp_lons)
    ax2.set_xticklabels(wp_labels, fontsize=6, rotation=35, ha="left")

    ax.set_title(
        "W-E Cross-Section ~40.3N | HRRR 16Z f07 (Valid 23Z) | 22 Feb 2025",
        fontsize=TITLE_SIZE,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig5_cross_section.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure6_mslp_tendency(datasets, waypoints):
    """2-panel: MSLP at 23Z and 3-hr temperature change (23Z - 20Z)."""
    ds = datasets[16]
    target_23z = np.datetime64(f"{DATE}T23:00:00")
    target_20z = np.datetime64(f"{DATE}T20:00:00")
    time_vals = ds.time.values

    t_idx_23 = int(np.argmin(np.abs(time_vals - target_23z)))
    t_idx_20 = int(np.argmin(np.abs(time_vals - target_20z)))

    ds_23 = ds.isel(time=t_idx_23)
    ds_20 = ds.isel(time=t_idx_20)

    lat, lon = _get_latlon(ds_23)
    mslp_hpa = pa_to_hpa(ds_23["mslp"].values)
    temp_23_C = temp_K_to_C(ds_23["temp_2m"].values)
    temp_20_C = temp_K_to_C(ds_20["temp_2m"].values)
    dtemp = temp_23_C - temp_20_C

    fig, axes = plt.subplots(
        1, 2, figsize=(16, 6),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    ax = axes[0]
    mslp_levels = np.arange(
        np.floor(np.nanmin(mslp_hpa) / 2) * 2,
        np.ceil(np.nanmax(mslp_hpa) / 2) * 2 + 2,
        2,
    )
    cf = ax.pcolormesh(
        lon, lat, mslp_hpa,
        cmap="viridis", shading="nearest",
        transform=ccrs.PlateCarree(),
    )
    try:
        cs = ax.contour(
            lon, lat, mslp_hpa,
            levels=mslp_levels, colors="black", linewidths=0.6,
            transform=ccrs.PlateCarree(),
        )
        ax.clabel(cs, fontsize=6, fmt="%.0f")
    except Exception:
        pass
    add_map_features(ax)
    add_waypoints(ax, waypoints)
    cbar = fig.colorbar(cf, ax=ax, orientation="horizontal", shrink=0.8, pad=0.08)
    cbar.set_label("MSLP (hPa)", fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)
    actual_valid = str(ds.time.values[t_idx_23])[:16]
    ax.set_title(f"MSLP | Valid {actual_valid}Z", fontsize=TITLE_SIZE)

    ax = axes[1]
    cf2 = ax.pcolormesh(
        lon, lat, dtemp,
        cmap="RdBu_r", vmin=-8, vmax=8,
        shading="nearest", transform=ccrs.PlateCarree(),
    )
    add_map_features(ax)
    add_waypoints(ax, waypoints)
    cbar2 = fig.colorbar(cf2, ax=ax, orientation="horizontal", shrink=0.8, pad=0.08)
    cbar2.set_label("3-hr Temp Change (C)", fontsize=LABEL_SIZE)
    cbar2.ax.tick_params(labelsize=TICK_SIZE)
    valid_20 = str(ds.time.values[t_idx_20])[:16]
    valid_23 = str(ds.time.values[t_idx_23])[:16]
    ax.set_title(
        f"Temp Tendency ({valid_23}Z - {valid_20}Z)",
        fontsize=TITLE_SIZE,
    )

    fig.suptitle(
        "HRRR 16Z Init | MSLP & Temperature Tendency | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2, y=1.02,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig6_mslp_tendency.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ---------------------------------------------------------------------------
# New figures (7-11): quasi-warm-front analysis
# ---------------------------------------------------------------------------

def figure7_theta_e_evolution(datasets, waypoints):
    """Plan-view theta-e evolution (16Z run) showing the quasi-front."""
    ds = datasets[16]
    if "theta_e_2m" not in ds.data_vars:
        print("  [SKIP] theta_e_2m not in dataset (dewpoint_2m may be missing)")
        return

    fig = plot_planview_evolution(
        ds, "theta_e_2m",
        ncols=3,
        waypoints=waypoints,
        cmap="RdYlBu_r",
        suptitle="HRRR 16Z Init | Equivalent Potential Temperature | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig7_theta_e_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure8_dewpoint_evolution(datasets, waypoints):
    """Plan-view dewpoint evolution (16Z run)."""
    ds = datasets[16]
    if "dewpoint_2m" not in ds.data_vars:
        print("  [SKIP] dewpoint_2m not in dataset")
        return

    fig = plot_planview_evolution(
        ds, "dewpoint_2m",
        ncols=3,
        waypoints=waypoints,
        cmap="BrBG",
        suptitle="HRRR 16Z Init | 2-m Dewpoint (K) | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig8_dewpoint_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure9_obs_overlay(datasets, waypoints_dense, obs_dense):
    """Obs overlay on NWP temp at key valid times."""
    from brc_tools.visualize.planview import plot_planview

    ds = datasets[16]
    valid_times_str = ["18", "20", "22", "00"]
    targets = [
        np.datetime64(f"{DATE}T{h}:00:00") if int(h) >= 12
        else np.datetime64(f"2025-02-23T{h}:00:00")
        for h in valid_times_str
    ]

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 12),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for ax, target in zip(axes.flatten(), targets):
        plot_planview(
            ds, "temp_2m",
            valid_time=target,
            ax=ax,
            cmap="RdYlBu_r", vmin=240, vmax=290,
            wind_barbs=True, barb_skip=BARB_SKIP,
            waypoints=waypoints_dense,
            obs_overlay=obs_dense,
            obs_variable="temp_2m",
            obs_annotate_values=True,
            title=f"Temp 2m + Obs | Valid {str(target)[:16]}Z",
        )

    fig.suptitle(
        "HRRR 16Z + Obs Overlay | 2-m Temperature | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig9_obs_overlay.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure10_verification_summary(wp_series, obs_df):
    """Bar chart of RMSE/bias per station per variable."""
    from brc_tools.verify.deterministic import paired_scores

    # Use the 16Z run for verification
    nwp_df = wp_series[16]
    if obs_df is None:
        print("  [SKIP] No obs data for verification")
        return

    verify_vars = ["temp_2m", "wind_speed_10m"]
    scores = paired_scores(nwp_df, obs_df, verify_vars, tolerance_minutes=30)

    if scores.is_empty():
        print("  [SKIP] No paired observations for verification")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ax_idx, metric in enumerate(["rmse", "bias"]):
        ax = axes[ax_idx]
        for v_idx, var in enumerate(verify_vars):
            var_scores = scores.filter(scores["variable"] == var)
            if var_scores.is_empty():
                continue
            wps = var_scores["waypoint"].to_list()
            vals = var_scores[metric].to_list()
            n_obs = var_scores["n_obs"].to_list()

            x = np.arange(len(wps))
            width = 0.35
            offset = (v_idx - 0.5) * width
            bars = ax.bar(x + offset, vals, width, label=var)

            # Annotate with n_obs
            for bar, n in zip(bars, n_obs):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"n={n}", ha="center", va="bottom", fontsize=6)

        short_names = [w.replace("_", "\n") for w in wps]
        ax.set_xticks(x)
        ax.set_xticklabels(short_names, fontsize=7)
        ax.set_ylabel(metric.upper(), fontsize=LABEL_SIZE)
        ax.set_title(f"{metric.upper()} by Station (16Z run)", fontsize=TITLE_SIZE)
        ax.legend(fontsize=8)
        ax.grid(True, axis="y", alpha=0.3)

        if metric == "bias":
            ax.axhline(0, color="black", linewidth=0.5)

    fig.suptitle(
        "Deterministic Verification | HRRR 16Z vs Obs | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig10_verification.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure11_dense_timeseries(wp_series_dense, obs_dense, waypoints_dense):
    """Dense 14-station time series: temp + wind along US-40."""
    nwp_for_plot = {RUN_STYLES[ih]["label"]: wp_series_dense[ih] for ih in INIT_HOURS}
    styles = {RUN_STYLES[ih]["label"]: {**RUN_STYLES[ih], "label": RUN_STYLES[ih]["label"]}
              for ih in INIT_HOURS}

    lu = load_lookups()
    dense_names = lu["waypoint_groups"][DENSE_GROUP]

    fig = plot_station_timeseries(
        nwp_for_plot,
        "temp_2m",
        obs_df=obs_dense,
        waypoint_names=dense_names,
        waypoints_meta=waypoints_dense,
        unit_label="Temp (C)",
        unit_transform=lambda x: x - 273.15,
        secondary_variable="wind_speed_10m",
        secondary_unit_label="Wind Speed (m/s)",
        run_styles=styles,
        ncols=2,
        suptitle="HRRR Temp & Wind at US-40 Stations | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig11_dense_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ---------------------------------------------------------------------------
# Comprehensive map figures (12-22): full quasi-front diagnostic suite
# ---------------------------------------------------------------------------

def figure12_temp_evolution(datasets, waypoints_dense):
    """Plan-view 2-m temperature evolution (16Z run, f00-f12)."""
    ds = datasets[16]
    fig = plot_planview_evolution(
        ds, "temp_2m",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="RdYlBu_r",
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle="HRRR 16Z | 2-m Temperature (K) + Wind Barbs | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig12_temp_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure13_mslp_evolution(datasets, waypoints_dense):
    """Plan-view MSLP evolution (16Z run, f00-f12)."""
    ds = datasets[16]
    fig = plot_planview_evolution(
        ds, "mslp",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="viridis",
        suptitle="HRRR 16Z | Mean Sea-Level Pressure (Pa) | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig13_mslp_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure14_pbl_evolution(datasets, waypoints_dense):
    """Plan-view PBL height evolution (16Z run)."""
    ds = datasets[16]
    if "pbl_height" not in ds.data_vars:
        print("  [SKIP] pbl_height not in dataset")
        return
    fig = plot_planview_evolution(
        ds, "pbl_height",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="YlOrRd",
        suptitle="HRRR 16Z | PBL Height (m) | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig14_pbl_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure15_theta_e_gradient(datasets, waypoints_dense):
    """Plan-view theta-e gradient magnitude — highlights the quasi-front."""
    from brc_tools.nwp.derived import horizontal_gradient_magnitude

    ds = datasets[16]
    if "theta_e_2m" not in ds.data_vars:
        print("  [SKIP] theta_e_2m not in dataset")
        return

    # Compute gradient for each time step and add to dataset
    import xarray as xr
    grads = []
    for t in range(ds.sizes["time"]):
        ds_t = ds.isel(time=t)
        grad = horizontal_gradient_magnitude(ds_t["theta_e_2m"], dx_m=3000.0)
        # Convert to K/km for readability
        grad_kkm = grad * 1000.0
        grads.append(grad_kkm)
    ds["theta_e_grad"] = xr.concat(grads, dim="time")
    ds["theta_e_grad"].attrs["units"] = "K/km"

    fig = plot_planview_evolution(
        ds, "theta_e_grad",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="hot_r",
        vmin=0, vmax=5,
        suptitle="HRRR 16Z | Theta-e Gradient Magnitude (K/km) — Front Detection | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig15_theta_e_gradient.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure16_temp_gradient(datasets, waypoints_dense):
    """Plan-view temperature gradient magnitude — frontal zone detection."""
    from brc_tools.nwp.derived import horizontal_gradient_magnitude

    ds = datasets[16]
    import xarray as xr
    grads = []
    for t in range(ds.sizes["time"]):
        ds_t = ds.isel(time=t)
        grad = horizontal_gradient_magnitude(ds_t["temp_2m"], dx_m=3000.0)
        grads.append(grad * 1000.0)  # K/km
    ds["temp_grad"] = xr.concat(grads, dim="time")

    fig = plot_planview_evolution(
        ds, "temp_grad",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="hot_r",
        vmin=0, vmax=5,
        suptitle="HRRR 16Z | Temperature Gradient (K/km) — Frontal Zone | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig16_temp_gradient.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure17_temp_tendency(datasets, waypoints_dense):
    """Plan-view hourly temperature tendency — shows warming wave moving east."""
    from brc_tools.nwp.derived import hourly_tendency

    ds = datasets[16].copy(deep=True)
    ds = hourly_tendency(ds, "temp_2m")

    if "temp_2m_tendency" not in ds.data_vars:
        print("  [SKIP] tendency computation failed")
        return

    fig = plot_planview_evolution(
        ds, "temp_2m_tendency",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="RdBu_r",
        vmin=-5, vmax=5,
        suptitle="HRRR 16Z | Hourly Temp Tendency (K/hr) — Warming Wave | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig17_temp_tendency.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure18_multi_init_comparison(datasets, waypoints_dense):
    """Multi-init comparison at 4 valid times (4 rows x 3 columns).

    Rows: valid 18Z, 20Z, 22Z, 00Z.  Columns: 15Z, 16Z, 17Z inits.
    Shows whether different inits agree on front timing/position.
    """
    from brc_tools.visualize.planview import plot_planview

    valid_hours = [18, 20, 22]
    valid_labels = ["18Z", "20Z", "22Z"]
    # 00Z is next day
    targets = [np.datetime64(f"{DATE}T{h:02d}:00:00") for h in valid_hours]
    targets.append(np.datetime64("2025-02-23T00:00:00"))
    valid_labels.append("00Z")

    fig, axes = plt.subplots(
        4, 3, figsize=(18, 22),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for row, (target, vlabel) in enumerate(zip(targets, valid_labels)):
        for col, ih in enumerate(INIT_HOURS):
            ax = axes[row, col]
            ds = datasets[ih]

            plot_planview(
                ds, "temp_2m",
                valid_time=target,
                ax=ax,
                cmap="RdYlBu_r", vmin=250, vmax=285,
                wind_barbs=True, barb_skip=BARB_SKIP,
                waypoints=waypoints_dense,
                obs_annotate_values=False,
                title=f"{ih:02d}Z init | Valid {vlabel}",
            )

    fig.suptitle(
        "Multi-Init Comparison | 2-m Temp + Wind | 22 Feb 2025\n"
        "Does the quasi-front arrive at the same time in all inits?",
        fontsize=TITLE_SIZE + 2, y=1.01,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig18_multi_init_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure19_obs_overlay_wind(datasets, waypoints_dense, obs_dense):
    """Obs overlay on NWP wind speed at key valid times."""
    from brc_tools.visualize.planview import plot_planview

    ds = datasets[16]
    targets = [
        np.datetime64(f"{DATE}T18:00:00"),
        np.datetime64(f"{DATE}T20:00:00"),
        np.datetime64(f"{DATE}T22:00:00"),
        np.datetime64("2025-02-23T00:00:00"),
    ]

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 12),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for ax, target in zip(axes.flatten(), targets):
        plot_planview(
            ds, "wind_speed_10m",
            valid_time=target,
            ax=ax,
            cmap="YlOrRd", vmin=0, vmax=15,
            wind_barbs=True, barb_skip=BARB_SKIP,
            waypoints=waypoints_dense,
            obs_overlay=obs_dense,
            obs_variable="wind_speed_10m",
            obs_annotate_values=True,
            title=f"Wind Speed + Obs | Valid {str(target)[:16]}Z",
        )

    fig.suptitle(
        "HRRR 16Z + Obs | 10-m Wind Speed (m/s) | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig19_obs_overlay_wind.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure20_obs_overlay_dewpoint(datasets, waypoints_dense, obs_dense):
    """Obs overlay on NWP dewpoint at key valid times."""
    from brc_tools.visualize.planview import plot_planview

    ds = datasets[16]
    if "dewpoint_2m" not in ds.data_vars:
        print("  [SKIP] dewpoint_2m not in dataset")
        return

    targets = [
        np.datetime64(f"{DATE}T18:00:00"),
        np.datetime64(f"{DATE}T20:00:00"),
        np.datetime64(f"{DATE}T22:00:00"),
        np.datetime64("2025-02-23T00:00:00"),
    ]

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 12),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for ax, target in zip(axes.flatten(), targets):
        plot_planview(
            ds, "dewpoint_2m",
            valid_time=target,
            ax=ax,
            cmap="BrBG",
            waypoints=waypoints_dense,
            obs_overlay=obs_dense,
            obs_variable="dewpoint_2m",
            obs_annotate_values=True,
            title=f"Dewpoint + Obs | Valid {str(target)[:16]}Z",
        )

    fig.suptitle(
        "HRRR 16Z + Obs | 2-m Dewpoint (K) | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig20_obs_overlay_dewpoint.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure21_obs_overlay_theta_e(datasets, waypoints_dense, obs_dense):
    """Obs overlay on NWP theta-e at key valid times.

    Note: obs theta-e is not directly observed, but if temp and dewpoint
    obs are available we can compute it.  For now we just overlay temp obs
    as a proxy indicator.
    """
    from brc_tools.visualize.planview import plot_planview

    ds = datasets[16]
    if "theta_e_2m" not in ds.data_vars:
        print("  [SKIP] theta_e_2m not in dataset")
        return

    targets = [
        np.datetime64(f"{DATE}T18:00:00"),
        np.datetime64(f"{DATE}T20:00:00"),
        np.datetime64(f"{DATE}T22:00:00"),
        np.datetime64("2025-02-23T00:00:00"),
    ]

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 12),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for ax, target in zip(axes.flatten(), targets):
        plot_planview(
            ds, "theta_e_2m",
            valid_time=target,
            ax=ax,
            cmap="RdYlBu_r",
            waypoints=waypoints_dense,
            obs_annotate_values=False,
            title=f"Theta-e | Valid {str(target)[:16]}Z",
        )

    fig.suptitle(
        "HRRR 16Z | Equivalent Potential Temperature (K) | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig21_obs_overlay_theta_e.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure22_wind_direction_evolution(datasets, waypoints_dense):
    """Plan-view wind direction evolution (16Z run).

    Wind direction fill with barbs overlaid — shows the wind shift
    associated with the quasi-front passage.
    """
    ds = datasets[16]
    if "wind_dir_10m" not in ds.data_vars:
        print("  [SKIP] wind_dir_10m not in dataset")
        return

    fig = plot_planview_evolution(
        ds, "wind_dir_10m",
        ncols=3,
        waypoints=waypoints_dense,
        cmap="twilight",
        vmin=0, vmax=360,
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle="HRRR 16Z | 10-m Wind Direction (deg) + Barbs | 22 Feb 2025",
    )
    _annotate(fig)
    out = OUTDIR / "fig22_wind_direction.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure23_init_difference(datasets, waypoints_dense):
    """Difference maps: 17Z init minus 15Z init at valid 22Z and 00Z.

    Shows where the later init has changed its forecast — highlights
    areas of forecast sensitivity near the quasi-front.
    """
    targets = [
        (np.datetime64(f"{DATE}T22:00:00"), "22Z"),
        (np.datetime64("2025-02-23T00:00:00"), "00Z"),
    ]

    fig, axes = plt.subplots(
        1, 2, figsize=(16, 7),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for ax, (target, vlabel) in zip(axes, targets):
        ds17 = datasets[17]
        ds15 = datasets[15]

        t17 = int(np.argmin(np.abs(ds17.time.values - target)))
        t15 = int(np.argmin(np.abs(ds15.time.values - target)))

        ds_t17 = ds17.isel(time=t17)
        ds_t15 = ds15.isel(time=t15)

        lat, lon = _get_latlon(ds_t17)
        diff = temp_K_to_C(ds_t17["temp_2m"].values) - temp_K_to_C(ds_t15["temp_2m"].values)

        cf = ax.pcolormesh(
            lon, lat, diff,
            cmap="RdBu_r", vmin=-5, vmax=5,
            shading="nearest", transform=ccrs.PlateCarree(),
        )
        add_map_features(ax)
        add_waypoints(ax, waypoints_dense, fontsize=5, annotate=False)
        cbar = fig.colorbar(cf, ax=ax, orientation="horizontal", shrink=0.8, pad=0.06)
        cbar.set_label("Temp Difference (C): 17Z - 15Z init", fontsize=9)
        cbar.ax.tick_params(labelsize=7)
        ax.set_title(f"Valid {vlabel} | 17Z minus 15Z init", fontsize=TITLE_SIZE)

    fig.suptitle(
        "Init Sensitivity | Temperature Difference (17Z - 15Z) | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2, y=1.02,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig23_init_difference.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the full case study pipeline."""
    plt.style.use("default")

    print("=" * 60)
    print("Case Study: 22 Feb 2025 Uinta Basin Quasi-Warm-Front")
    print("=" * 60)

    waypoints = _load_waypoints(WP_GROUP)
    waypoints_dense = _load_waypoints(DENSE_GROUP)
    src = NWPSource("hrrr")

    # -- 1. Fetch surface data for all three runs --
    print("\n[1/6] Fetching HRRR surface data (3 runs x 13 hours) ...")
    sfc_datasets = fetch_surface_runs(src)

    # -- 2. Fetch pressure-level data for 16Z run --
    print("\n[2/6] Fetching HRRR pressure-level data (16Z, f07 only) ...")
    ds_pl = fetch_pressure_levels(src)

    # -- 3. Extract waypoint time series (original + dense) --
    print("\n[3/6] Extracting waypoint time series ...")
    wp_series = extract_waypoint_series(src, sfc_datasets, group=WP_GROUP)
    wp_series_dense = extract_waypoint_series(src, sfc_datasets, group=DENSE_GROUP)

    # -- 4. Fetch observations (original + dense) --
    print("\n[4/6] Fetching observations ...")
    obs_df = fetch_observations(WP_GROUP)
    obs_dense = fetch_observations(DENSE_GROUP)

    # -- 5. Generate original figures (1-6) --
    print("\n" + "-" * 60)
    print("[5/8] Generating original figures (1-6) ...")
    print("-" * 60)

    for name, func, args in [
        ("Figure 1: Surface comparison", figure1_surface_comparison, (sfc_datasets, waypoints)),
        ("Figure 2: Wind evolution", figure2_wind_evolution, (sfc_datasets, waypoints)),
        ("Figure 3: Timeseries", figure3_timeseries, (wp_series, obs_df, waypoints)),
        ("Figure 4: PBL height", figure4_pbl_height, (wp_series, waypoints)),
        ("Figure 5: Cross-section", figure5_cross_section, (ds_pl, waypoints)),
        ("Figure 6: MSLP + tendency", figure6_mslp_tendency, (sfc_datasets, waypoints)),
    ]:
        print(f"\n{name} ...")
        try:
            func(*args)
        except Exception as exc:
            print(f"  [ERROR] {name} failed: {exc}")
            traceback.print_exc()

    # -- 6. Quasi-warm-front analysis figures (7-11) --
    print("\n" + "-" * 60)
    print("[6/8] Generating quasi-warm-front figures (7-11) ...")
    print("-" * 60)

    for name, func, args in [
        ("Figure 7: Theta-e evolution", figure7_theta_e_evolution, (sfc_datasets, waypoints_dense)),
        ("Figure 8: Dewpoint evolution", figure8_dewpoint_evolution, (sfc_datasets, waypoints_dense)),
        ("Figure 9: Obs overlay (temp)", figure9_obs_overlay, (sfc_datasets, waypoints_dense, obs_dense)),
        ("Figure 10: Verification", figure10_verification_summary, (wp_series_dense, obs_dense)),
        ("Figure 11: Dense timeseries", figure11_dense_timeseries, (wp_series_dense, obs_dense, waypoints_dense)),
    ]:
        print(f"\n{name} ...")
        try:
            func(*args)
        except Exception as exc:
            print(f"  [ERROR] {name} failed: {exc}")
            traceback.print_exc()

    # -- 7. Comprehensive map diagnostic suite (12-23) --
    print("\n" + "-" * 60)
    print("[7/8] Generating comprehensive map suite (12-23) ...")
    print("-" * 60)

    for name, func, args in [
        ("Figure 12: Temp evolution", figure12_temp_evolution, (sfc_datasets, waypoints_dense)),
        ("Figure 13: MSLP evolution", figure13_mslp_evolution, (sfc_datasets, waypoints_dense)),
        ("Figure 14: PBL evolution", figure14_pbl_evolution, (sfc_datasets, waypoints_dense)),
        ("Figure 15: Theta-e gradient", figure15_theta_e_gradient, (sfc_datasets, waypoints_dense)),
        ("Figure 16: Temp gradient", figure16_temp_gradient, (sfc_datasets, waypoints_dense)),
        ("Figure 17: Temp tendency", figure17_temp_tendency, (sfc_datasets, waypoints_dense)),
        ("Figure 18: Multi-init comparison", figure18_multi_init_comparison, (sfc_datasets, waypoints_dense)),
        ("Figure 19: Obs overlay (wind)", figure19_obs_overlay_wind, (sfc_datasets, waypoints_dense, obs_dense)),
        ("Figure 20: Obs overlay (dewpoint)", figure20_obs_overlay_dewpoint, (sfc_datasets, waypoints_dense, obs_dense)),
        ("Figure 21: Theta-e snapshots", figure21_obs_overlay_theta_e, (sfc_datasets, waypoints_dense, obs_dense)),
        ("Figure 22: Wind direction", figure22_wind_direction_evolution, (sfc_datasets, waypoints_dense)),
        ("Figure 23: Init difference", figure23_init_difference, (sfc_datasets, waypoints_dense)),
    ]:
        print(f"\n{name} ...")
        try:
            func(*args)
        except Exception as exc:
            print(f"  [ERROR] {name} failed: {exc}")
            traceback.print_exc()

    # -- 8. Summary --
    print("\n" + "=" * 60)
    print("Done. 23 figures saved to:", OUTDIR)
    print("=" * 60)


if __name__ == "__main__":
    main()
