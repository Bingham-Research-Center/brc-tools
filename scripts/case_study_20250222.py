"""Case study: 22 Feb 2025 Uinta Basin cold-pool erosion event.

Fetches HRRR surface and pressure-level data via NWPSource, optionally
fetches Synoptic observations via ObsSource, and produces six
publication-quality figures illustrating the foehn-driven cold-pool
erosion during the afternoon of 22 Feb 2025.

Usage::

    conda run -n brc-tools python scripts/case_study_20250222.py
"""

import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Cartopy imports
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# Local imports
from brc_tools.nwp import NWPSource
from brc_tools.nwp.source import load_lookups

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTDIR = Path(__file__).resolve().parent.parent / "figures" / "case_study_20250222"
OUTDIR.mkdir(parents=True, exist_ok=True)

DATE = "2025-02-22"
INIT_HOURS = [15, 16, 17]  # three HRRR runs to compare
SFC_VARS = ["temp_2m", "wind_u_10m", "wind_v_10m", "mslp", "pbl_height"]
PL_VARS = ["temp_pl", "wind_u_pl", "wind_v_pl", "height_pl"]
PL_LEVELS = [1000, 950, 925, 900, 850, 800, 750, 700]
FHOURS = range(0, 13)

WP_GROUP = "foehn_path"
WP_NAMES = [
    "daniels_summit", "fruitland", "duchesne", "myton", "roosevelt", "vernal"
]

ANNOTATION = "HRRR | 22 Feb 2025 | BRC Tools"
DPI = 150
BARB_SKIP = 5  # thin wind barbs every Nth grid point
KT_FACTOR = 1.94384  # m/s -> knots

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

def _load_waypoints():
    """Return dict of waypoint metadata from lookups.toml."""
    lu = load_lookups()
    return {name: lu["waypoints"][name] for name in WP_NAMES}


def _lon_to_180(lon):
    """Convert longitude from 0..360 to -180..180."""
    return np.where(lon > 180, lon - 360, lon)


def _get_latlon(ds):
    """Extract 2-D lat/lon arrays from the dataset, converting lon to -180..180."""
    lat = ds["latitude"].values
    lon = _lon_to_180(ds["longitude"].values)
    return lat, lon


def _compute_wind(ds):
    """Add wind_speed_10m and wind_dir_10m to a dataset (in-place semantics)."""
    u = ds["wind_u_10m"]
    v = ds["wind_v_10m"]
    speed = np.sqrt(u ** 2 + v ** 2)
    direction = (270 - np.degrees(np.arctan2(v, u))) % 360
    ds["wind_speed_10m"] = speed
    ds["wind_dir_10m"] = direction
    return ds


def _add_map_features(ax):
    """Add state borders to a Cartopy axes.

    Uses 10m states (locally cached). Counties and international borders
    are skipped because the NaturalEarth download server is unreliable
    and cartopy downloads lazily at render time, causing hard failures.
    """
    # 10m states are pre-cached; use NaturalEarthFeature explicitly so
    # we control the resolution and avoid any fallback download attempts.
    states = cfeature.NaturalEarthFeature(
        "cultural", "admin_1_states_provinces_lakes", "10m",
        facecolor="none", edgecolor="black", linewidth=0.8,
    )
    ax.add_feature(states)


def _add_waypoints(ax, waypoints, transform=ccrs.PlateCarree(), fontsize=7):
    """Plot waypoint markers and labels on a Cartopy axes."""
    for name, wp in waypoints.items():
        ax.plot(
            wp["lon"], wp["lat"], "k^", markersize=5, transform=transform, zorder=10,
        )
        ax.text(
            wp["lon"] + 0.05, wp["lat"] + 0.05, name.replace("_", " ").title(),
            fontsize=fontsize, transform=transform, zorder=10,
            ha="left", va="bottom",
            bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", pad=0.5),
        )


def _annotate(fig, text=ANNOTATION):
    """Add a small attribution annotation to the figure."""
    fig.text(
        0.99, 0.01, text, fontsize=6, ha="right", va="bottom",
        fontstyle="italic", color="gray",
    )


def _temp_K_to_C(temp_K):
    """Convert temperature from Kelvin to Celsius."""
    return temp_K - 273.15


def _pa_to_hpa(pa):
    """Convert pressure from Pa to hPa."""
    return pa / 100.0


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
        ds = _compute_wind(ds)
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


def extract_waypoint_series(src, datasets):
    """Extract time series at foehn_path waypoints for each run.

    Returns dict {init_hour: pl.DataFrame}.
    """
    wp_series = {}
    for ih, ds in datasets.items():
        print(f"  Extracting waypoints for {ih}Z run ...")
        df = src.extract_at_waypoints(ds, group=WP_GROUP)
        wp_series[ih] = df
    return wp_series


def fetch_observations():
    """Attempt to fetch Synoptic observations; returns None on failure."""
    try:
        from brc_tools.obs import ObsSource
        obs = ObsSource()
        print("  Fetching Synoptic observations ...")
        obs_df = obs.timeseries(
            waypoint_group=WP_GROUP,
            start=f"{DATE} 12Z",
            end="2025-02-23 06Z",
            variables=["temp_2m", "wind_speed_10m", "wind_dir_10m", "mslp"],
        )
        print(f"    -> {obs_df.shape[0]} obs rows")
        return obs_df
    except Exception as exc:
        print(f"  [WARN] ObsSource failed (Synoptic API not configured?): {exc}")
        print("         NWP-only plots will still be produced.")
        return None


# ---------------------------------------------------------------------------
# Figure 1: Surface temp + wind barbs, 3-panel comparison at valid 23Z
# ---------------------------------------------------------------------------

def figure1_surface_comparison(datasets, waypoints):
    """3-panel map: temp_2m + wind barbs + MSLP contours, valid 23Z."""
    fig, axes = plt.subplots(
        1, 3, figsize=(18, 6),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    # Valid 23Z corresponds to: 15Z+f08, 16Z+f07, 17Z+f06
    fxx_map = {15: 8, 16: 7, 17: 6}

    for idx, ih in enumerate(INIT_HOURS):
        ax = axes[idx]
        ds = datasets[ih]
        fxx = fxx_map[ih]

        # Find the time index for valid 23Z
        target_valid = np.datetime64(f"{DATE}T23:00:00")
        time_vals = ds.time.values
        t_idx = int(np.argmin(np.abs(time_vals - target_valid)))
        ds_t = ds.isel(time=t_idx)

        lat, lon = _get_latlon(ds_t)
        temp_C = _temp_K_to_C(ds_t["temp_2m"].values)
        mslp_hpa = _pa_to_hpa(ds_t["mslp"].values)
        u = ds_t["wind_u_10m"].values
        v = ds_t["wind_v_10m"].values

        # Temperature fill
        cf = ax.pcolormesh(
            lon, lat, temp_C,
            cmap="RdYlBu_r", vmin=-10, vmax=15,
            shading="nearest", transform=ccrs.PlateCarree(),
        )

        # MSLP contours
        try:
            ax.contour(
                lon, lat, mslp_hpa,
                levels=np.arange(960, 1060, 2),
                colors="black", linewidths=0.6,
                transform=ccrs.PlateCarree(),
            )
        except Exception:
            pass

        # Wind barbs (thinned, in knots)
        s = BARB_SKIP
        ax.barbs(
            lon[::s, ::s], lat[::s, ::s],
            u[::s, ::s] * KT_FACTOR, v[::s, ::s] * KT_FACTOR,
            length=5, linewidth=0.4,
            transform=ccrs.PlateCarree(),
        )

        _add_map_features(ax)
        _add_waypoints(ax, waypoints)

        actual_valid = str(ds.time.values[t_idx])[:16]
        ax.set_title(
            f"Init {ih:02d}Z (f{fxx:03d})\nValid {actual_valid}Z",
            fontsize=TITLE_SIZE,
        )

    # Shared colorbar
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


# ---------------------------------------------------------------------------
# Figure 2: Wind speed evolution, 16Z run (4x3 panels)
# ---------------------------------------------------------------------------

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

        _add_map_features(ax)
        _add_waypoints(ax, waypoints, fontsize=5)

        valid_str = str(ds.time.values[t_idx])[:16]
        ax.set_title(f"f{t_idx:03d} | Valid {valid_str}Z", fontsize=TICK_SIZE)

    # Hide unused panels
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


# ---------------------------------------------------------------------------
# Figure 3: Time series comparison at waypoints (temp + wind speed)
# ---------------------------------------------------------------------------

def figure3_timeseries(wp_series, obs_df, waypoints):
    """3x2 panel: temp_2m and wind_speed at each foehn_path waypoint."""
    fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    axes_flat = axes.flatten()

    for idx, wp_name in enumerate(WP_NAMES):
        ax = axes_flat[idx]
        ax2 = ax.twinx()

        for ih in INIT_HOURS:
            df = wp_series[ih]
            wp_df = df.filter(df["waypoint"] == wp_name).sort("valid_time")
            if wp_df.is_empty():
                continue

            times = wp_df["valid_time"].to_list()
            style = RUN_STYLES[ih]

            # Temperature (K -> C)
            if "temp_2m" in wp_df.columns:
                temp_C = [t - 273.15 if t is not None else np.nan
                          for t in wp_df["temp_2m"].to_list()]
                ax.plot(times, temp_C, color=style["color"], ls=style["ls"],
                        linewidth=1.5, label=f"T {style['label']}")

            # Wind speed
            if "wind_speed_10m" in wp_df.columns:
                wspd = wp_df["wind_speed_10m"].to_list()
                ax2.plot(times, wspd, color=style["color"], ls=style["ls"],
                         linewidth=1.0, alpha=0.6, label=f"WS {style['label']}")

        # Overlay obs if available
        if obs_df is not None:
            try:
                obs_wp = obs_df.filter(obs_df["waypoint"] == wp_name).sort("valid_time")
                if not obs_wp.is_empty():
                    obs_times = obs_wp["valid_time"].to_list()
                    if "temp_2m" in obs_wp.columns:
                        obs_temp = obs_wp["temp_2m"].to_list()
                        ax.scatter(obs_times, obs_temp, c="black", s=8, marker="o",
                                   zorder=5, label="Obs T")
                    if "wind_speed_10m" in obs_wp.columns:
                        obs_ws = obs_wp["wind_speed_10m"].to_list()
                        ax2.scatter(obs_times, obs_ws, c="black", s=8, marker="x",
                                    zorder=5, label="Obs WS")
            except Exception:
                pass

        elev = waypoints[wp_name]["elevation_m"]
        ax.set_title(
            f"{wp_name.replace('_', ' ').title()} ({elev} m)",
            fontsize=TITLE_SIZE,
        )
        ax.set_ylabel("Temp (C)", fontsize=LABEL_SIZE, color="tab:red")
        ax2.set_ylabel("Wind Speed (m/s)", fontsize=LABEL_SIZE, color="tab:blue")
        ax.tick_params(labelsize=TICK_SIZE)
        ax2.tick_params(labelsize=TICK_SIZE)
        ax.grid(True, alpha=0.3)

        if idx == 0:
            lines1, labels1 = ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(lines1 + lines2, labels1 + labels2, fontsize=6, loc="upper left")

    # Format x-axis
    for ax_row in axes[-1]:
        ax_row.set_xlabel("Valid Time (UTC)", fontsize=LABEL_SIZE)
        for label in ax_row.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

    fig.suptitle(
        "HRRR 2-m Temp & 10-m Wind Speed at Foehn Path Waypoints | 22 Feb 2025",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig3_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ---------------------------------------------------------------------------
# Figure 4: PBL height evolution
# ---------------------------------------------------------------------------

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

        # Shade the erosion window (roughly 20Z-00Z)
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


# ---------------------------------------------------------------------------
# Figure 5: Pressure-level cross-section (W->E along ~40.3N)
# ---------------------------------------------------------------------------

def figure5_cross_section(ds_pl, waypoints):
    """W-E cross-section of temperature and wind at ~40.3N, valid 23Z."""
    ds_t = ds_pl.isel(time=0)  # only one time step (f07 -> valid 23Z)
    lat2d = ds_t["latitude"].values
    lon2d = _lon_to_180(ds_t["longitude"].values)

    # Find the y-index closest to 40.3N (average across x dimension)
    lat_mean = lat2d.mean(axis=1) if lat2d.ndim == 2 else lat2d
    y_target = int(np.argmin(np.abs(lat_mean - 40.3)))

    # Extract longitude along this row
    if lon2d.ndim == 2:
        lons = lon2d[y_target, :]
    else:
        lons = lon2d

    # Gather temperature and wind for each pressure level
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

    # Compute potential temperature: theta = T * (1000/p)^(R/cp)
    # R/cp = 0.286
    p_arr = np.array(levels).reshape(-1, 1)
    theta_xsec = temp_xsec * (1000.0 / p_arr) ** 0.286

    fig, ax = plt.subplots(figsize=(12, 6))

    # Potential temperature fill
    cf = ax.pcolormesh(
        lons, levels, theta_xsec,
        cmap="RdYlBu_r", shading="nearest",
    )
    cbar = fig.colorbar(cf, ax=ax, pad=0.02)
    cbar.set_label("Potential Temperature (K)", fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)

    # Wind speed contours
    try:
        cs = ax.contour(
            lons, levels, wspd_xsec,
            levels=np.arange(2, 30, 2),
            colors="black", linewidths=0.6,
        )
        ax.clabel(cs, fontsize=6, fmt="%.0f")
    except Exception:
        pass

    # Wind barbs on the cross-section (zonal component only; no omega available)
    barb_skip_x = 4
    barb_skip_z = 1
    lon_barb = lons[::barb_skip_x]
    lev_barb = np.array(levels)[::barb_skip_z]
    u_barb = u_xsec[::barb_skip_z, ::barb_skip_x] * KT_FACTOR
    # No vertical component, set to zero
    w_barb = np.zeros_like(u_barb)
    lon_grid, lev_grid = np.meshgrid(lon_barb, lev_barb)
    ax.barbs(lon_grid, lev_grid, u_barb, w_barb, length=5, linewidth=0.4)

    ax.set_ylim(max(levels), min(levels))  # pressure inverted
    ax.set_ylabel("Pressure (hPa)", fontsize=LABEL_SIZE)
    ax.set_xlabel("Longitude", fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)

    # Mark waypoint longitudes with vertical lines and top-axis labels
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


# ---------------------------------------------------------------------------
# Figure 6: MSLP + temperature tendency
# ---------------------------------------------------------------------------

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
    mslp_hpa = _pa_to_hpa(ds_23["mslp"].values)
    temp_23_C = _temp_K_to_C(ds_23["temp_2m"].values)
    temp_20_C = _temp_K_to_C(ds_20["temp_2m"].values)
    dtemp = temp_23_C - temp_20_C

    fig, axes = plt.subplots(
        1, 2, figsize=(16, 6),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    # Left: MSLP
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
    _add_map_features(ax)
    _add_waypoints(ax, waypoints)
    cbar = fig.colorbar(cf, ax=ax, orientation="horizontal", shrink=0.8, pad=0.08)
    cbar.set_label("MSLP (hPa)", fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)
    actual_valid = str(ds.time.values[t_idx_23])[:16]
    ax.set_title(f"MSLP | Valid {actual_valid}Z", fontsize=TITLE_SIZE)

    # Right: Temperature tendency
    ax = axes[1]
    cf2 = ax.pcolormesh(
        lon, lat, dtemp,
        cmap="RdBu_r", vmin=-8, vmax=8,
        shading="nearest", transform=ccrs.PlateCarree(),
    )
    _add_map_features(ax)
    _add_waypoints(ax, waypoints)
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
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the full case study pipeline."""
    plt.style.use("default")

    print("=" * 60)
    print("Case Study: 22 Feb 2025 Uinta Basin Cold-Pool Erosion")
    print("=" * 60)

    waypoints = _load_waypoints()
    src = NWPSource("hrrr")

    # -- 1. Fetch surface data for all three runs --
    print("\n[1/4] Fetching HRRR surface data (3 runs x 13 hours) ...")
    sfc_datasets = fetch_surface_runs(src)

    # -- 2. Fetch pressure-level data for 16Z run --
    print("\n[2/4] Fetching HRRR pressure-level data (16Z, f07 only) ...")
    ds_pl = fetch_pressure_levels(src)

    # -- 3. Extract waypoint time series --
    print("\n[3/4] Extracting waypoint time series ...")
    wp_series = extract_waypoint_series(src, sfc_datasets)

    # -- 4. Fetch observations (optional) --
    print("\n[4/4] Fetching observations (optional) ...")
    obs_df = fetch_observations()

    # -- Generate figures --
    print("\n" + "-" * 60)
    print("Generating figures ...")
    print("-" * 60)

    print("\nFigure 1: Surface temperature comparison ...")
    try:
        figure1_surface_comparison(sfc_datasets, waypoints)
    except Exception as exc:
        print(f"  [ERROR] Figure 1 failed: {exc}")
        import traceback; traceback.print_exc()

    print("\nFigure 2: Wind speed evolution ...")
    try:
        figure2_wind_evolution(sfc_datasets, waypoints)
    except Exception as exc:
        print(f"  [ERROR] Figure 2 failed: {exc}")
        import traceback; traceback.print_exc()

    print("\nFigure 3: Time series at waypoints ...")
    try:
        figure3_timeseries(wp_series, obs_df, waypoints)
    except Exception as exc:
        print(f"  [ERROR] Figure 3 failed: {exc}")
        import traceback; traceback.print_exc()

    print("\nFigure 4: PBL height evolution ...")
    try:
        figure4_pbl_height(wp_series, waypoints)
    except Exception as exc:
        print(f"  [ERROR] Figure 4 failed: {exc}")
        import traceback; traceback.print_exc()

    print("\nFigure 5: Pressure-level cross-section ...")
    try:
        figure5_cross_section(ds_pl, waypoints)
    except Exception as exc:
        print(f"  [ERROR] Figure 5 failed: {exc}")
        import traceback; traceback.print_exc()

    print("\nFigure 6: MSLP + temperature tendency ...")
    try:
        figure6_mslp_tendency(sfc_datasets, waypoints)
    except Exception as exc:
        print(f"  [ERROR] Figure 6 failed: {exc}")
        import traceback; traceback.print_exc()

    print("\n" + "=" * 60)
    print("Done. Figures saved to:", OUTDIR)
    print("=" * 60)


if __name__ == "__main__":
    main()
