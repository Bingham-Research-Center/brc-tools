"""Case study 2: mesoscale foehn event at Vernal (KVEL).

Scans KVEL observations to identify a pure foehn event — one driven by
ageostrophic, terrain-channelled flow with concurrent warming and drying,
NOT a synoptic cold-front passage or convective outflow.

Detection criteria (late-day window 20–06 UTC):
  - Westerly wind (225–315°) sustained ≥3 hours
  - Wind speed increase ≥5 m/s
  - Temperature INCREASE ≥2 C concurrent with the wind ramp
  - Dewpoint DECREASE ≥2 C concurrent (the foehn drying signature)

Figures are tailored to diagnose foehn dynamics:
  - Hovmöller diagrams showing the "foehn front" progressing east
  - T-Td spread maps showing the drying plume
  - Cross-basin pressure gradient as the ageostrophic forcing
  - PBL height maps showing deep mixing behind the foehn front
  - Theta-e maps (should be ~uniform, confirming adiabatic descent)

Usage::

    conda run -n brc-tools python scripts/case_study_kvel_foehn.py --scan-only
    conda run -n brc-tools python scripts/case_study_kvel_foehn.py --date 2025-06-15
"""

import argparse
import datetime
import time
import traceback
from pathlib import Path

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import polars as pl
import xarray as xr

from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import (
    add_theta_e,
    add_wind_fields,
    hourly_tendency,
    pa_to_hpa,
    temp_K_to_C,
)
from brc_tools.nwp.source import load_lookups
from brc_tools.visualize.planview import (
    KT_FACTOR,
    _get_latlon,
    add_map_features,
    add_waypoints,
    plot_planview,
    plot_planview_evolution,
)
from brc_tools.visualize.timeseries import (
    plot_station_timeseries,
    plot_verification_timeseries,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTDIR = Path(__file__).resolve().parent.parent / "figures" / "case_study_kvel_foehn"
OUTDIR.mkdir(parents=True, exist_ok=True)

EVENT_DATE: str | None = None

INIT_HOURS = [12, 18]
SFC_VARS = [
    "temp_2m", "dewpoint_2m", "wind_u_10m", "wind_v_10m",
    "mslp", "pbl_height", "rh_2m",
]
FHOURS_12Z = range(0, 19)   # 12Z→06Z+1
FHOURS_18Z = range(0, 13)   # 18Z→06Z+1
WP_GROUP = "foehn_path"
WP_NAMES = [
    "daniels_summit", "fruitland", "duchesne", "myton", "roosevelt", "vernal",
]
OBS_VARS = [
    "temp_2m", "dewpoint_2m", "wind_speed_10m", "wind_dir_10m", "mslp",
]

ANNOTATION = "HRRR | Foehn Case Study | BRC Tools"
DPI = 150
BARB_SKIP = 5
TITLE_SIZE = 12
LABEL_SIZE = 10
TICK_SIZE = 8

RUN_STYLES = {
    12: {"color": "tab:blue",  "ls": "-",  "label": "12Z init"},
    18: {"color": "tab:red",   "ls": "--", "label": "18Z init"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_waypoints(group=WP_GROUP):
    lu = load_lookups()
    names = lu["waypoint_groups"][group]
    return {name: lu["waypoints"][name] for name in names}


def _annotate(fig, text=ANNOTATION):
    fig.text(
        0.99, 0.01, text, fontsize=6, ha="right", va="bottom",
        fontstyle="italic", color="gray",
    )


def _next_day(date_str: str) -> str:
    d = datetime.date.fromisoformat(date_str)
    return (d + datetime.timedelta(days=1)).isoformat()


def _safe_float_list(series):
    """Convert a Polars series to a list of plain floats (np.nan for nulls)."""
    return [float(v) if v is not None else np.nan for v in series.to_list()]


# ---------------------------------------------------------------------------
# Phase 1 — Foehn event scanning
# ---------------------------------------------------------------------------

def scan_foehn_events(months=(5, 6, 7, 8, 9), year=2025):
    """Scan KVEL for foehn events: warming + drying + westerly wind ramp."""
    from brc_tools.obs import ObsSource
    obs = ObsSource()
    candidates = []

    scan_vars = ["wind_speed_10m", "wind_dir_10m", "temp_2m", "dewpoint_2m"]

    for month in months:
        start = f"{year}-{month:02d}-01 00Z"
        if month == 12:
            end = f"{year + 1}-01-01 00Z"
        else:
            end = f"{year}-{month + 1:02d}-01 00Z"

        print(f"  Querying KVEL {year}-{month:02d} ...")
        try:
            df = obs.timeseries(
                stids=["KVEL"],
                start=start, end=end,
                variables=scan_vars,
            )
        except Exception as exc:
            print(f"    Failed: {exc}")
            continue
        time.sleep(0.5)

        if df.is_empty():
            print("    No data")
            continue

        print(f"    {df.shape[0]} rows")

        df = df.with_columns(pl.col("valid_time").cast(pl.Date).alias("date"))
        for date_val in df["date"].unique().sort().to_list():
            day_df = df.filter(pl.col("date") == date_val).sort("valid_time")
            result = _detect_foehn(day_df, date_val)
            if result is not None:
                candidates.append(result)

    candidates.sort(key=lambda c: c["foehn_score"], reverse=True)
    return candidates


def _detect_foehn(day_df, date_val):
    """Detect a foehn event: westerly wind ramp with warming AND drying.

    Window: 20–06 UTC (≈ 2 PM – midnight MDT).
    Criteria:
      - Westerly (225–315°) for ≥3 consecutive hours
      - Wind speed increase ≥5 m/s
      - Temperature increase ≥2 C concurrent with the wind ramp
      - Dewpoint decrease ≥2 C concurrent (drying signature)
      - No large temperature DROP after the warming (rules out fronts)
    """
    if isinstance(date_val, datetime.date) and not isinstance(date_val, datetime.datetime):
        d = date_val
    else:
        d = date_val.date() if hasattr(date_val, "date") else date_val

    win_start = datetime.datetime(d.year, d.month, d.day, 20, 0)
    win_end = win_start + datetime.timedelta(hours=10)  # 20Z–06Z

    window = day_df.filter(
        (pl.col("valid_time") >= win_start) & (pl.col("valid_time") <= win_end)
    )

    required = ["wind_speed_10m", "wind_dir_10m", "temp_2m", "dewpoint_2m"]
    for col in required:
        if col not in window.columns:
            return None

    window = window.drop_nulls(subset=required)
    if window.shape[0] < 5:
        return None

    speeds = window["wind_speed_10m"].to_list()
    dirs_ = window["wind_dir_10m"].to_list()
    temps = window["temp_2m"].to_list()
    dewpts = window["dewpoint_2m"].to_list()

    # -- Wind criteria: consecutive westerly hours --
    max_consec = 0
    run = 0
    for dv in dirs_:
        if 225 <= dv <= 315:
            run += 1
            max_consec = max(max_consec, run)
        else:
            run = 0
    if max_consec < 3:
        return None

    # -- Wind speed increase --
    peak_speed = max(speeds)
    if peak_speed < 7.0:
        return None
    baseline_speed = np.nanmean(speeds[:3]) if len(speeds) >= 3 else speeds[0]
    wind_increase = peak_speed - baseline_speed
    if wind_increase < 4.0:
        return None

    peak_idx = speeds.index(peak_speed)

    # -- Temperature increase concurrent with wind ramp --
    # Compare first 3 values to the max in the ramp period
    baseline_temp = np.nanmean(temps[:3])
    # Use values around peak wind to measure warming
    ramp_end = min(peak_idx + 3, len(temps))
    ramp_temps = temps[max(0, peak_idx - 2):ramp_end]
    peak_temp = max(ramp_temps) if ramp_temps else max(temps)
    temp_increase = peak_temp - baseline_temp
    if temp_increase < 2.0:
        return None

    # -- Dewpoint decrease (drying) --
    baseline_dewpt = np.nanmean(dewpts[:3])
    ramp_dewpts = dewpts[max(0, peak_idx - 2):ramp_end]
    min_dewpt = min(ramp_dewpts) if ramp_dewpts else min(dewpts)
    dewpt_decrease = baseline_dewpt - min_dewpt
    if dewpt_decrease < 2.0:
        return None

    # -- Anti-front check: temperature should NOT drop sharply after peak --
    # If temp drops > 5 C after peak_idx, it's likely a frontal passage
    post_peak_temps = temps[peak_idx:]
    if len(post_peak_temps) >= 3:
        post_min = min(post_peak_temps)
        if (peak_temp - post_min) > 6.0:
            return None  # likely a frontal passage followed by cooling

    # -- Composite foehn score: reward warming + drying + wind --
    foehn_score = round(wind_increase + temp_increase + dewpt_decrease, 1)

    peak_time = window["valid_time"].to_list()[peak_idx]

    return {
        "date": str(d),
        "foehn_score": foehn_score,
        "peak_speed_ms": round(peak_speed, 1),
        "wind_increase": round(wind_increase, 1),
        "temp_increase_C": round(temp_increase, 1),
        "dewpt_decrease_C": round(dewpt_decrease, 1),
        "consec_westerly": max_consec,
        "peak_time_utc": str(peak_time),
    }


def print_foehn_table(candidates):
    if not candidates:
        print("\n  No qualifying foehn events found.")
        return

    print(f"\n  {'Rank':<5} {'Date':<12} {'Score':<7} {'Wind+':<7} {'Temp+':<7} "
          f"{'Td-':<7} {'Peak m/s':<9} {'W hrs':<6} {'Peak time (UTC)'}")
    print("  " + "-" * 85)
    for i, c in enumerate(candidates[:15], 1):
        print(f"  {i:<5} {c['date']:<12} {c['foehn_score']:<7} "
              f"{c['wind_increase']:<7} {c['temp_increase_C']:<7} "
              f"{c['dewpt_decrease_C']:<7} {c['peak_speed_ms']:<9} "
              f"{c['consec_westerly']:<6} {c['peak_time_utc']}")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_surface_runs(src, date):
    fhour_map = {12: FHOURS_12Z, 18: FHOURS_18Z}
    datasets = {}
    for ih in INIT_HOURS:
        init_str = f"{date} {ih:02d}Z"
        fhours = fhour_map[ih]
        print(f"  Fetching HRRR sfc init={init_str} f00-f{max(fhours):02d} ...")
        ds = src.fetch(
            init_time=init_str,
            forecast_hours=fhours,
            variables=SFC_VARS,
            region="uinta_basin",
        )
        ds = add_wind_fields(ds)
        ds = add_theta_e(ds)
        # Compute T-Td spread (K)
        if "temp_2m" in ds.data_vars and "dewpoint_2m" in ds.data_vars:
            ds["t_td_spread"] = ds["temp_2m"] - ds["dewpoint_2m"]
            ds["t_td_spread"].attrs["units"] = "K"
        datasets[ih] = ds
        print(f"    -> {ds.sizes}")
    return datasets


def extract_waypoint_series(src, datasets, group=WP_GROUP):
    wp_series = {}
    for ih, ds in datasets.items():
        print(f"  Extracting waypoints ({group}) for {ih}Z run ...")
        df = src.extract_at_waypoints(ds, group=group)
        wp_series[ih] = df
    return wp_series


def fetch_foehn_obs(date):
    try:
        from brc_tools.obs import ObsSource
        obs = ObsSource()
        end = _next_day(date)
        print(f"  Fetching foehn-path obs {date} 12Z — {end} 06Z ...")
        obs_df = obs.timeseries(
            waypoint_group=WP_GROUP,
            start=f"{date} 12Z",
            end=f"{end} 06Z",
            variables=OBS_VARS,
        )
        print(f"    -> {obs_df.shape[0]} obs rows")
        return obs_df
    except Exception as exc:
        print(f"  [WARN] Obs fetch failed: {exc}")
        return None


def fetch_kvel_obs(date):
    try:
        from brc_tools.obs import ObsSource
        obs = ObsSource()
        end = _next_day(date)
        print(f"  Fetching KVEL obs {date} 06Z — {end} 12Z ...")
        obs_df = obs.timeseries(
            stids=["KVEL"],
            start=f"{date} 06Z",
            end=f"{end} 12Z",
            variables=OBS_VARS,
        )
        print(f"    -> {obs_df.shape[0]} rows")
        return obs_df
    except Exception as exc:
        print(f"  [WARN] KVEL obs fetch failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def figure1_foehn_meteogram(kvel_obs, date):
    """KVEL obs: wind speed + temp/dewpoint/RH showing the foehn signature.

    Two vertically stacked panels:
      Top: Temperature and dewpoint (the T-Td spread opening is the hallmark)
      Bottom: Wind speed with direction as colored scatter
    """
    if kvel_obs is None or kvel_obs.is_empty():
        print("  [SKIP] No KVEL obs")
        return

    df = kvel_obs.sort("valid_time")
    times = df["valid_time"].to_list()

    fig, (ax_t, ax_w) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

    # -- Top panel: Temperature + Dewpoint --
    if "temp_2m" in df.columns:
        t_vals = _safe_float_list(df["temp_2m"])
        ax_t.plot(times, t_vals, "r-", linewidth=1.8, label="Temperature")
    if "dewpoint_2m" in df.columns:
        td_vals = _safe_float_list(df["dewpoint_2m"])
        ax_t.plot(times, td_vals, "b-", linewidth=1.8, label="Dewpoint")
        # Shade the T-Td spread
        if "temp_2m" in df.columns:
            ax_t.fill_between(times, td_vals, t_vals, alpha=0.12, color="orange",
                              label="T-Td spread")
    ax_t.set_ylabel("Temperature (C)", fontsize=LABEL_SIZE)
    ax_t.legend(fontsize=8, loc="upper left")
    ax_t.grid(True, alpha=0.3)
    ax_t.tick_params(labelsize=TICK_SIZE)

    # -- Bottom panel: Wind speed + direction (color-coded scatter) --
    if "wind_speed_10m" in df.columns:
        wspd = _safe_float_list(df["wind_speed_10m"])
        ax_w.plot(times, wspd, "k-", linewidth=1.2, label="Wind speed")
        ax_w.fill_between(times, 0, wspd, alpha=0.1, color="gray")
        ax_w.set_ylabel("Wind Speed (m/s)", fontsize=LABEL_SIZE)
        ax_w.set_ylim(bottom=0)

    if "wind_dir_10m" in df.columns:
        wdir = _safe_float_list(df["wind_dir_10m"])
        wspd_for_sc = _safe_float_list(df["wind_speed_10m"]) if "wind_speed_10m" in df.columns else [5] * len(times)
        sc = ax_w.scatter(times, wspd_for_sc, c=wdir, cmap="twilight",
                          vmin=0, vmax=360, s=18, zorder=3, edgecolors="none")
        cbar = fig.colorbar(sc, ax=ax_w, pad=0.01, aspect=30)
        cbar.set_label("Wind Dir (°)", fontsize=8)
        cbar.set_ticks([0, 90, 180, 270, 360])
        cbar.set_ticklabels(["N", "E", "S", "W", "N"])

    # Shade the late-day window
    d = datetime.date.fromisoformat(date)
    win_start = datetime.datetime(d.year, d.month, d.day, 20, 0)
    win_end = win_start + datetime.timedelta(hours=10)
    for ax in (ax_t, ax_w):
        ax.axvspan(win_start, win_end, alpha=0.06, color="gray")

    ax_w.set_xlabel("Time (UTC)", fontsize=LABEL_SIZE)
    ax_w.tick_params(labelsize=TICK_SIZE)
    ax_w.grid(True, alpha=0.3)
    fig.autofmt_xdate(rotation=30)

    fig.suptitle(
        f"KVEL Foehn Signature | {date}\n"
        "Look for: warming + drying (T-Td spread opens) + westerly wind ramp",
        fontsize=TITLE_SIZE,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig01_foehn_meteogram.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure2_hovmoller_temp(wp_series, waypoints, date):
    """Hovmöller: longitude (west→east) vs time, colored by temperature.

    Shows the warm foehn air penetrating eastward along the foehn path.
    """
    df = wp_series[18]  # Use 18Z init (freshest for event window)
    _plot_hovmoller(df, "temp_2m", waypoints, date,
                    unit_label="2-m Temperature (C)",
                    unit_transform=lambda x: x - 273.15,
                    cmap="RdYlBu_r",
                    title_field="Temperature",
                    fname="fig02_hovmoller_temp.png")


def figure3_hovmoller_wind(wp_series, waypoints, date):
    """Hovmöller: longitude vs time, colored by wind speed."""
    df = wp_series[18]
    _plot_hovmoller(df, "wind_speed_10m", waypoints, date,
                    unit_label="10-m Wind Speed (m/s)",
                    cmap="YlOrRd",
                    title_field="Wind Speed",
                    fname="fig03_hovmoller_wind.png")


def _plot_hovmoller(df, variable, waypoints, date, *,
                    unit_label, cmap, title_field, fname,
                    unit_transform=None):
    """Generic Hovmöller along the foehn path.

    X-axis: waypoint (sorted west→east by longitude)
    Y-axis: valid time (top=early, bottom=late)
    """
    wp_order = sorted(WP_NAMES, key=lambda n: waypoints[n]["lon"])
    wp_lons = [waypoints[n]["lon"] for n in wp_order]

    if variable not in df.columns:
        print(f"  [SKIP] {variable} not in waypoint series")
        return

    # Build 2-D array: rows=times, cols=waypoints
    times_all = sorted(df["valid_time"].unique().to_list())
    data = np.full((len(times_all), len(wp_order)), np.nan)

    for j, wp in enumerate(wp_order):
        sub = df.filter(pl.col("waypoint") == wp).sort("valid_time")
        if sub.is_empty():
            continue
        for row in sub.iter_rows(named=True):
            vt = row["valid_time"]
            val = row.get(variable)
            if vt in times_all and val is not None:
                i = times_all.index(vt)
                data[i, j] = float(val)

    if unit_transform is not None:
        data = unit_transform(data)

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.pcolormesh(
        np.arange(len(wp_order) + 1) - 0.5,
        np.arange(len(times_all) + 1) - 0.5,
        data, cmap=cmap, shading="flat",
    )
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label(unit_label, fontsize=LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)

    # X-axis: waypoint names
    short_labels = [n.replace("_", "\n").title() for n in wp_order]
    ax.set_xticks(range(len(wp_order)))
    ax.set_xticklabels(short_labels, fontsize=8)
    ax.set_xlabel("Waypoint (West → East)", fontsize=LABEL_SIZE)

    # Y-axis: valid times
    tick_every = max(1, len(times_all) // 12)
    y_ticks = list(range(0, len(times_all), tick_every))
    y_labels = [str(times_all[i])[11:16] + "Z" for i in y_ticks]
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels, fontsize=TICK_SIZE)
    ax.set_ylabel("Valid Time (UTC)", fontsize=LABEL_SIZE)

    # Secondary x-axis with longitudes
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(range(len(wp_order)))
    ax2.set_xticklabels([f"{lon:.1f}°" for lon in wp_lons], fontsize=7)

    ax.set_title(
        f"Hovmöller: {title_field} along Foehn Path | HRRR 18Z | {date}",
        fontsize=TITLE_SIZE, pad=30,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / fname
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure4_foehn_path_t_td(wp_series, obs_df, waypoints):
    """6-panel foehn-path: temp AND dewpoint on same axis.

    The foehn signature is T and Td diverging as warm dry air arrives.
    The sequential west→east arrival is the "foehn front" progression.
    """
    nwp_for_plot = {RUN_STYLES[ih]["label"]: wp_series[ih] for ih in INIT_HOURS}
    styles = {RUN_STYLES[ih]["label"]: {**RUN_STYLES[ih]} for ih in INIT_HOURS}

    # Plot temperature as primary
    fig = plot_station_timeseries(
        nwp_for_plot,
        "temp_2m",
        obs_df=obs_df,
        waypoint_names=WP_NAMES,
        waypoints_meta=waypoints,
        unit_label="Temp (C)",
        unit_transform=lambda x: x - 273.15,
        secondary_variable="dewpoint_2m",
        secondary_unit_label="Dewpoint (C)",
        secondary_unit_transform=lambda x: x - 273.15,
        run_styles=styles,
        ncols=2,
        suptitle=(f"HRRR Temp (solid) & Dewpoint (right axis) at Foehn Path | {EVENT_DATE}\n"
                  "Foehn arrival: T rises, Td drops, T-Td spread opens"),
    )
    _annotate(fig)
    out = OUTDIR / "fig04_foehn_path_t_td.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure5_wind_speed_evolution(datasets, waypoints):
    """Plan-view wind speed + barbs (18Z run)."""
    ds = datasets[18]
    fig = plot_planview_evolution(
        ds, "wind_speed_10m",
        ncols=3,
        waypoints=waypoints,
        cmap="YlOrRd",
        vmin=0, vmax=20,
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle=f"HRRR 18Z | 10-m Wind Speed + Barbs | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig05_wind_speed_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure6_t_td_spread_maps(datasets, waypoints):
    """Plan-view T-Td spread evolution — the drying plume.

    High T-Td spread (>15 K) = very dry foehn air.
    The boundary where the spread jumps is the "foehn front".
    """
    ds = datasets[18]
    if "t_td_spread" not in ds.data_vars:
        print("  [SKIP] t_td_spread not in dataset")
        return

    fig = plot_planview_evolution(
        ds, "t_td_spread",
        ncols=3,
        waypoints=waypoints,
        cmap="YlOrBr",
        vmin=0, vmax=25,
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle=(f"HRRR 18Z | T − Td Spread (K) — Foehn Drying | {EVENT_DATE}\n"
                  "High values = dry foehn air; sharp gradient = foehn front"),
    )
    _annotate(fig)
    out = OUTDIR / "fig06_t_td_spread.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure7_pressure_gradient(wp_series, kvel_obs, waypoints, date):
    """Cross-basin pressure gradient (west minus east) vs KVEL wind speed.

    The pressure difference between Daniels Summit and Vernal is the
    ageostrophic forcing that drives the foehn.  Plot it alongside KVEL
    wind speed to show cause → effect.
    """
    df = wp_series[18]

    # Extract MSLP at westernmost and easternmost foehn-path waypoints
    west_wp = "daniels_summit"
    east_wp = "vernal"

    west = df.filter(pl.col("waypoint") == west_wp).sort("valid_time")
    east = df.filter(pl.col("waypoint") == east_wp).sort("valid_time")

    if west.is_empty() or east.is_empty() or "mslp" not in df.columns:
        print("  [SKIP] Missing MSLP data for pressure gradient")
        return

    # Merge on valid_time
    merged = west.select(["valid_time", "mslp"]).rename({"mslp": "mslp_west"}).join(
        east.select(["valid_time", "mslp"]).rename({"mslp": "mslp_east"}),
        on="valid_time",
    ).sort("valid_time")

    times = merged["valid_time"].to_list()
    dp_hpa = [(float(w) - float(e)) / 100.0
              for w, e in zip(merged["mslp_west"].to_list(),
                              merged["mslp_east"].to_list())]

    # Also get wind speed at vernal
    vernal_nwp = df.filter(pl.col("waypoint") == "vernal").sort("valid_time")
    vernal_times = vernal_nwp["valid_time"].to_list()
    vernal_wspd = (_safe_float_list(vernal_nwp["wind_speed_10m"])
                   if "wind_speed_10m" in vernal_nwp.columns else [])

    fig, ax1 = plt.subplots(figsize=(12, 5))

    # Pressure gradient (left axis)
    ax1.plot(times, dp_hpa, "b-", linewidth=2, label=(
        f"ΔMSLP: {west_wp.replace('_', ' ').title()} − {east_wp.replace('_', ' ').title()}"))
    ax1.axhline(0, color="gray", linewidth=0.5, ls="--")
    ax1.set_ylabel("MSLP Difference (hPa, west − east)", color="tab:blue",
                    fontsize=LABEL_SIZE)
    ax1.tick_params(axis="y", labelcolor="tab:blue", labelsize=TICK_SIZE)
    ax1.tick_params(axis="x", labelsize=TICK_SIZE, rotation=30)
    ax1.grid(True, alpha=0.3)

    # NWP wind speed at Vernal (right axis)
    ax2 = ax1.twinx()
    if vernal_wspd:
        ax2.plot(vernal_times, vernal_wspd, "r-", linewidth=1.5,
                 label="NWP wind speed (Vernal)")

    # KVEL obs wind speed overlay
    if kvel_obs is not None and not kvel_obs.is_empty() and "wind_speed_10m" in kvel_obs.columns:
        obs_sorted = kvel_obs.sort("valid_time")
        obs_t = obs_sorted["valid_time"].to_list()
        obs_w = _safe_float_list(obs_sorted["wind_speed_10m"])
        ax2.scatter(obs_t, obs_w, c="red", s=15, alpha=0.5, zorder=3,
                    label="KVEL obs wind speed")

    ax2.set_ylabel("Wind Speed at Vernal (m/s)", color="tab:red",
                    fontsize=LABEL_SIZE)
    ax2.tick_params(axis="y", labelcolor="tab:red", labelsize=TICK_SIZE)
    ax2.set_ylim(bottom=0)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")

    ax1.set_title(
        f"Cross-Basin Pressure Gradient → Foehn Wind | HRRR 18Z | {date}\n"
        "Negative ΔP = higher pressure to the east (opposing foehn); "
        "positive = west-to-east forcing",
        fontsize=TITLE_SIZE - 1,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig07_pressure_gradient.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure8_mslp_evolution(datasets, waypoints):
    """Plan-view MSLP + wind barbs (18Z run)."""
    ds = datasets[18]
    fig = plot_planview_evolution(
        ds, "mslp",
        ncols=3,
        waypoints=waypoints,
        cmap="viridis",
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle=f"HRRR 18Z | MSLP + Wind Barbs | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig08_mslp_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure9_pbl_theta_e(datasets, waypoints):
    """Side-by-side evolution panels: PBL height (left) and theta-e (right).

    Foehn events show deep PBL (well-mixed boundary layer from downslope
    descent) and relatively uniform theta-e (air mass is NOT changing,
    just descending adiabatically — contrast with a front).
    """
    ds = datasets[18]

    fig, all_axes = plt.subplots(
        2, 6, figsize=(24, 10),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    # Select 6 key time steps (every other hour for 12 hours)
    ntimes = ds.sizes["time"]
    step = max(1, ntimes // 6)
    t_indices = list(range(0, ntimes, step))[:6]

    # Top row: PBL height
    for col, ti in enumerate(t_indices):
        ax = all_axes[0, col]
        if "pbl_height" in ds.data_vars:
            plot_planview(
                ds, "pbl_height", time_idx=ti, ax=ax,
                cmap="YlOrRd", vmin=0, vmax=3000,
                waypoints=waypoints,
                title=f"PBL | f{ti:02d}",
            )
        else:
            ax.set_visible(False)

    # Bottom row: theta-e
    for col, ti in enumerate(t_indices):
        ax = all_axes[1, col]
        if "theta_e_2m" in ds.data_vars:
            plot_planview(
                ds, "theta_e_2m", time_idx=ti, ax=ax,
                cmap="RdYlBu_r",
                waypoints=waypoints,
                title=f"θe | f{ti:02d}",
            )
        else:
            ax.set_visible(False)

    fig.suptitle(
        f"HRRR 18Z | PBL Height (top) & θe (bottom) | {EVENT_DATE}\n"
        "Foehn: deep PBL + uniform θe (no air-mass boundary = not a front)",
        fontsize=TITLE_SIZE, y=1.02,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig09_pbl_theta_e.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure10_obs_overlay_wind(datasets, waypoints, obs_df, date):
    """4-snapshot obs overlay on NWP wind speed — model validation."""
    if obs_df is None:
        print("  [SKIP] No obs data for overlay")
        return

    ds = datasets[18]
    d = datetime.date.fromisoformat(date)

    # Pick 4 valid times spanning the event: pre-event, onset, peak, post
    targets = [
        np.datetime64(f"{date}T20:00:00"),
        np.datetime64(f"{date}T22:00:00"),
        np.datetime64(f"{_next_day(date)}T00:00:00"),
        np.datetime64(f"{_next_day(date)}T02:00:00"),
    ]

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 12),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    for ax, target in zip(axes.flatten(), targets):
        plot_planview(
            ds, "wind_speed_10m",
            valid_time=target, ax=ax,
            cmap="YlOrRd", vmin=0, vmax=20,
            wind_barbs=True, barb_skip=BARB_SKIP,
            waypoints=waypoints,
            obs_overlay=obs_df,
            obs_variable="wind_speed_10m",
            obs_annotate_values=True,
            title=f"Wind Speed + Obs | {str(target)[:16]}Z",
        )

    fig.suptitle(
        f"HRRR 18Z + Obs | 10-m Wind Speed (m/s) | {date}",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig10_obs_overlay_wind.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global EVENT_DATE

    parser = argparse.ArgumentParser(description="KVEL foehn case study")
    parser.add_argument("--scan-only", action="store_true",
                        help="Scan only; do not fetch HRRR or generate figures")
    parser.add_argument("--date", type=str, default=None,
                        help="Override event date (YYYY-MM-DD)")
    parser.add_argument("--months", type=str, default="5,6,7,8,9",
                        help="Comma-separated months to scan (default: 5,6,7,8,9)")
    parser.add_argument("--year", type=int, default=2025,
                        help="Year to scan (default: 2025)")
    args = parser.parse_args()

    plt.style.use("default")

    print("=" * 60)
    print("Case Study 2: KVEL Mesoscale Foehn Event")
    print("=" * 60)

    if args.date:
        EVENT_DATE = args.date
        print(f"\nUsing user-specified date: {EVENT_DATE}")
    else:
        months = tuple(int(m) for m in args.months.split(","))
        print(f"\n[Phase 1] Scanning KVEL for foehn events "
              f"({args.year}, months {months}) ...")
        candidates = scan_foehn_events(months=months, year=args.year)
        print_foehn_table(candidates)

        if not candidates:
            print("\nNo qualifying foehn events found.")
            print("Try: --months 4,5,6,7,8,9 or --year 2024")
            return

        EVENT_DATE = candidates[0]["date"]
        c = candidates[0]
        print(f"\n  -> Auto-selected top event: {EVENT_DATE}")
        print(f"     Foehn score: {c['foehn_score']} "
              f"(wind +{c['wind_increase']} m/s, "
              f"temp +{c['temp_increase_C']} C, "
              f"Td −{c['dewpt_decrease_C']} C)")

    if args.scan_only:
        print("\n--scan-only: stopping here.")
        return

    # -- Phase 2: Fetch data --
    print(f"\n{'=' * 60}")
    print(f"[Phase 2] Fetching HRRR + Obs for {EVENT_DATE}")
    print(f"{'=' * 60}")

    waypoints = _load_waypoints(WP_GROUP)
    src = NWPSource("hrrr")

    print("\n[1/4] Fetching HRRR surface data (2 runs) ...")
    sfc_datasets = fetch_surface_runs(src, EVENT_DATE)

    print("\n[2/4] Extracting waypoint time series ...")
    wp_series = extract_waypoint_series(src, sfc_datasets, group=WP_GROUP)

    print("\n[3/4] Fetching foehn-path observations ...")
    obs_df = fetch_foehn_obs(EVENT_DATE)

    print("\n[4/4] Fetching KVEL observations ...")
    kvel_obs = fetch_kvel_obs(EVENT_DATE)

    # -- Phase 3: Figures --
    print(f"\n{'=' * 60}")
    print("[Phase 3] Generating 10 figures ...")
    print(f"{'=' * 60}")

    for name, func, func_args in [
        ("Fig 1: Foehn meteogram (KVEL obs)",
         figure1_foehn_meteogram, (kvel_obs, EVENT_DATE)),
        ("Fig 2: Hovmöller — Temperature",
         figure2_hovmoller_temp, (wp_series, waypoints, EVENT_DATE)),
        ("Fig 3: Hovmöller — Wind speed",
         figure3_hovmoller_wind, (wp_series, waypoints, EVENT_DATE)),
        ("Fig 4: Foehn-path T + Td timeseries",
         figure4_foehn_path_t_td, (wp_series, obs_df, waypoints)),
        ("Fig 5: Wind speed evolution maps",
         figure5_wind_speed_evolution, (sfc_datasets, waypoints)),
        ("Fig 6: T-Td spread maps (drying plume)",
         figure6_t_td_spread_maps, (sfc_datasets, waypoints)),
        ("Fig 7: Cross-basin pressure gradient",
         figure7_pressure_gradient, (wp_series, kvel_obs, waypoints, EVENT_DATE)),
        ("Fig 8: MSLP evolution maps",
         figure8_mslp_evolution, (sfc_datasets, waypoints)),
        ("Fig 9: PBL height + theta-e comparison",
         figure9_pbl_theta_e, (sfc_datasets, waypoints)),
        ("Fig 10: Obs overlay on wind speed",
         figure10_obs_overlay_wind, (sfc_datasets, waypoints, obs_df, EVENT_DATE)),
    ]:
        print(f"\n{name} ...")
        try:
            func(*func_args)
        except Exception as exc:
            print(f"  [ERROR] {name} failed: {exc}")
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"Done. 10 figures saved to: {OUTDIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
