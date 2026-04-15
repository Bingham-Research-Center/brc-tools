"""Case study: strong late-day westerly wind increase at Vernal (KVEL).

Scans KVEL (Vernal Airport ASOS) observations for spring 2025 to identify
the strongest late-day westerly wind ramp event, then fetches HRRR data
and produces diagnostic figures aimed at understanding the meteorological
forcing (frontal passage, gap flow, pressure-driven channelling, etc.).

Usage::

    # Scan only — print candidate event dates:
    conda run -n brc-tools python scripts/case_study_kvel_westerly.py --scan-only

    # Full run — scan, select top event, generate figures:
    conda run -n brc-tools python scripts/case_study_kvel_westerly.py
"""

import argparse
import datetime
import time
import traceback
from pathlib import Path

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import (
    add_theta_e,
    add_wind_fields,
    horizontal_gradient_magnitude,
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

OUTDIR = Path(__file__).resolve().parent.parent / "figures" / "case_study_kvel_westerly"
OUTDIR.mkdir(parents=True, exist_ok=True)

# Set after scanning; override manually if you already know the date.
EVENT_DATE: str | None = None

INIT_HOURS = [12, 18]
SFC_VARS = [
    "temp_2m", "dewpoint_2m", "wind_u_10m", "wind_v_10m", "mslp", "pbl_height",
]
FHOURS_12Z = range(0, 19)   # 12Z init: f00–f18 → covers 12Z–06Z+1
FHOURS_18Z = range(0, 13)   # 18Z init: f00–f12 → covers 18Z–06Z+1
WP_GROUP = "foehn_path"
WP_NAMES = [
    "daniels_summit", "fruitland", "duchesne", "myton", "roosevelt", "vernal",
]
OBS_VARS = ["temp_2m", "dewpoint_2m", "wind_speed_10m", "wind_dir_10m", "mslp"]

ANNOTATION = "HRRR | KVEL Westerly Wind | BRC Tools"
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
    """Return date string for the day after *date_str* (YYYY-MM-DD)."""
    d = datetime.date.fromisoformat(date_str)
    return (d + datetime.timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Phase 1 — Event scanning
# ---------------------------------------------------------------------------

def scan_kvel_wind_events(months=(3, 4, 5), year=2025):
    """Scan KVEL wind obs for strong late-day westerly ramp events.

    Returns list of dicts sorted by wind_increase (descending).
    """
    from brc_tools.obs import ObsSource
    obs = ObsSource()
    candidates = []

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
                start=start,
                end=end,
                variables=["wind_speed_10m", "wind_dir_10m"],
            )
        except Exception as exc:
            print(f"    Failed: {exc}")
            continue
        time.sleep(0.5)  # courtesy pause between API calls

        if df.is_empty():
            print("    No data returned")
            continue

        print(f"    {df.shape[0]} rows returned")

        # Analyse each day
        df = df.with_columns(pl.col("valid_time").cast(pl.Date).alias("date"))
        for date_val in df["date"].unique().sort().to_list():
            day_df = df.filter(pl.col("date") == date_val).sort("valid_time")
            result = _detect_wind_ramp(day_df, date_val)
            if result is not None:
                candidates.append(result)

    candidates.sort(key=lambda c: c["wind_increase"], reverse=True)
    return candidates


def _detect_wind_ramp(day_df, date_val):
    """Check a single day for a late-day westerly wind increase.

    Late-day window: 22–06 UTC (≈ 4 PM – midnight MDT).
    Criteria:
      - Westerly wind (225–315°) for ≥3 consecutive hours in the window
      - Wind speed increase ≥5 m/s (max minus baseline at window start)
      - Peak sustained wind ≥8 m/s
    """
    # Build the late-day window (22Z same day through 06Z next day)
    if isinstance(date_val, datetime.date) and not isinstance(date_val, datetime.datetime):
        d = date_val
    else:
        d = date_val.date() if hasattr(date_val, "date") else date_val

    win_start = datetime.datetime(d.year, d.month, d.day, 22, 0)
    win_end = win_start + datetime.timedelta(hours=8)

    window = day_df.filter(
        (pl.col("valid_time") >= win_start) & (pl.col("valid_time") <= win_end)
    )

    if window.shape[0] < 4:
        return None

    # Drop rows with null wind data
    window = window.drop_nulls(subset=["wind_speed_10m", "wind_dir_10m"])
    if window.shape[0] < 4:
        return None

    speeds = window["wind_speed_10m"].to_list()
    dirs_ = window["wind_dir_10m"].to_list()

    # Count consecutive westerly hours (225–315°)
    max_consec_westerly = 0
    current_run = 0
    for d_val in dirs_:
        if 225 <= d_val <= 315:
            current_run += 1
            max_consec_westerly = max(max_consec_westerly, current_run)
        else:
            current_run = 0

    if max_consec_westerly < 3:
        return None

    peak_speed = max(speeds)
    if peak_speed < 8.0:
        return None

    # Wind increase: max minus value at window start (first 2 hours average)
    baseline = np.mean(speeds[:2]) if len(speeds) >= 2 else speeds[0]
    increase = peak_speed - baseline

    if increase < 5.0:
        return None

    # Find the time of peak wind
    peak_idx = speeds.index(peak_speed)
    peak_time = window["valid_time"].to_list()[peak_idx]

    return {
        "date": str(d),
        "peak_speed_ms": round(peak_speed, 1),
        "peak_speed_kt": round(peak_speed * 1.94384, 1),
        "wind_increase": round(increase, 1),
        "baseline_ms": round(baseline, 1),
        "peak_time_utc": str(peak_time),
        "consec_westerly_hrs": max_consec_westerly,
    }


def print_candidate_table(candidates):
    """Print a ranked table of candidate events."""
    if not candidates:
        print("\n  No qualifying events found.")
        return

    print(f"\n  {'Rank':<5} {'Date':<12} {'Peak (m/s)':<11} {'Peak (kt)':<10} "
          f"{'Increase':<10} {'Baseline':<10} {'Westerly hrs':<13} {'Peak time (UTC)'}")
    print("  " + "-" * 95)

    for i, c in enumerate(candidates[:15], 1):
        print(f"  {i:<5} {c['date']:<12} {c['peak_speed_ms']:<11} {c['peak_speed_kt']:<10} "
              f"{c['wind_increase']:<10} {c['baseline_ms']:<10} {c['consec_westerly_hrs']:<13} "
              f"{c['peak_time_utc']}")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_surface_runs(src, date):
    """Fetch surface HRRR data for 12Z and 18Z inits.

    Returns dict {init_hour: xr.Dataset}.
    """
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
        datasets[ih] = ds
        print(f"    -> {ds.sizes}")
    return datasets


def extract_waypoint_series(src, datasets, group=WP_GROUP):
    """Extract time series at waypoints for each run."""
    wp_series = {}
    for ih, ds in datasets.items():
        print(f"  Extracting waypoints ({group}) for {ih}Z run ...")
        df = src.extract_at_waypoints(ds, group=group)
        wp_series[ih] = df
    return wp_series


def fetch_foehn_obs(date):
    """Fetch observations for the foehn-path waypoint group."""
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
    """Fetch KVEL observations directly (24-hour window)."""
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

def figure1_kvel_wind_timeseries(kvel_obs, date):
    """KVEL obs only: wind speed + direction on dual axes (24-hr window)."""
    if kvel_obs is None or kvel_obs.is_empty():
        print("  [SKIP] No KVEL obs data")
        return

    df = kvel_obs.sort("valid_time")
    times = df["valid_time"].to_list()

    fig, ax1 = plt.subplots(figsize=(12, 5))

    # Wind speed (left y-axis)
    if "wind_speed_10m" in df.columns:
        speeds = [float(v) if v is not None else np.nan
                  for v in df["wind_speed_10m"].to_list()]
        ax1.plot(times, speeds, "b-", linewidth=1.8, label="Wind speed")
        ax1.fill_between(times, 0, speeds, alpha=0.15, color="tab:blue")
        ax1.set_ylabel("Wind Speed (m/s)", color="tab:blue", fontsize=LABEL_SIZE)
        ax1.tick_params(axis="y", labelcolor="tab:blue", labelsize=TICK_SIZE)
        ax1.set_ylim(bottom=0)

    # Wind direction (right y-axis)
    ax2 = ax1.twinx()
    if "wind_dir_10m" in df.columns:
        dirs_ = [float(v) if v is not None else np.nan
                 for v in df["wind_dir_10m"].to_list()]
        ax2.scatter(times, dirs_, c="tab:red", s=12, alpha=0.6, label="Wind dir", zorder=3)
        ax2.set_ylabel("Wind Direction (°)", color="tab:red", fontsize=LABEL_SIZE)
        ax2.tick_params(axis="y", labelcolor="tab:red", labelsize=TICK_SIZE)
        ax2.set_ylim(0, 360)
        ax2.set_yticks([0, 90, 180, 270, 360])
        ax2.set_yticklabels(["N", "E", "S", "W", "N"])

        # Shade the "westerly band" (225–315°)
        ax2.axhspan(225, 315, alpha=0.08, color="orange", label="Westerly (225–315°)")

    # Shade the late-day window (22–06 UTC)
    d = datetime.date.fromisoformat(date)
    win_start = datetime.datetime(d.year, d.month, d.day, 22, 0)
    win_end = win_start + datetime.timedelta(hours=8)
    ax1.axvspan(win_start, win_end, alpha=0.08, color="gray", label="Late-day window")

    ax1.set_xlabel("Time (UTC)", fontsize=LABEL_SIZE)
    ax1.tick_params(axis="x", labelsize=TICK_SIZE, rotation=30)
    ax1.grid(True, alpha=0.3)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")

    ax1.set_title(
        f"KVEL (Vernal Airport) Wind Observations | {date}",
        fontsize=TITLE_SIZE,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig01_kvel_wind_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure2_foehn_wind_timeseries(wp_series, obs_df, waypoints):
    """6-panel foehn-path: wind speed (primary) + wind dir (secondary)."""
    nwp_for_plot = {RUN_STYLES[ih]["label"]: wp_series[ih] for ih in INIT_HOURS}
    styles = {RUN_STYLES[ih]["label"]: {**RUN_STYLES[ih]} for ih in INIT_HOURS}

    fig = plot_station_timeseries(
        nwp_for_plot,
        "wind_speed_10m",
        obs_df=obs_df,
        waypoint_names=WP_NAMES,
        waypoints_meta=waypoints,
        unit_label="Wind Speed (m/s)",
        secondary_variable="wind_dir_10m",
        secondary_unit_label="Wind Dir (°)",
        run_styles=styles,
        ncols=2,
        suptitle=f"HRRR Wind Speed & Direction at Foehn Path | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig02_foehn_wind_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure3_foehn_temp_mslp(wp_series, obs_df, waypoints):
    """6-panel foehn-path: temperature (primary) + MSLP (secondary)."""
    nwp_for_plot = {RUN_STYLES[ih]["label"]: wp_series[ih] for ih in INIT_HOURS}
    styles = {RUN_STYLES[ih]["label"]: {**RUN_STYLES[ih]} for ih in INIT_HOURS}

    fig = plot_station_timeseries(
        nwp_for_plot,
        "temp_2m",
        obs_df=obs_df,
        waypoint_names=WP_NAMES,
        waypoints_meta=waypoints,
        unit_label="Temp (C)",
        unit_transform=lambda x: x - 273.15,
        secondary_variable="mslp",
        secondary_unit_label="MSLP (hPa)",
        secondary_unit_transform=lambda x: x / 100.0,
        run_styles=styles,
        ncols=2,
        suptitle=f"HRRR 2-m Temp & MSLP at Foehn Path | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig03_foehn_temp_mslp.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure4_wind_speed_evolution(datasets, waypoints):
    """Plan-view wind speed + barbs evolution (18Z run)."""
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
    out = OUTDIR / "fig04_wind_speed_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure5_mslp_evolution(datasets, waypoints):
    """Plan-view MSLP evolution + wind barbs (18Z run)."""
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
    out = OUTDIR / "fig05_mslp_evolution.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure6_temp_with_mslp(datasets, waypoints):
    """Plan-view temperature + MSLP contours (18Z run)."""
    ds = datasets[18]
    fig = plot_planview_evolution(
        ds, "temp_2m",
        ncols=3,
        waypoints=waypoints,
        cmap="RdYlBu_r",
        contour_var="mslp",
        contour_levels=np.arange(96000, 106000, 200),  # Pa, 2-hPa spacing
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle=f"HRRR 18Z | 2-m Temp (K) + MSLP Contours | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig06_temp_mslp_contours.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure7_wind_direction_evolution(datasets, waypoints):
    """Plan-view wind direction evolution (18Z run)."""
    ds = datasets[18]
    if "wind_dir_10m" not in ds.data_vars:
        print("  [SKIP] wind_dir_10m not in dataset")
        return

    fig = plot_planview_evolution(
        ds, "wind_dir_10m",
        ncols=3,
        waypoints=waypoints,
        cmap="twilight",
        vmin=0, vmax=360,
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle=f"HRRR 18Z | Wind Direction (°) + Barbs | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig07_wind_direction.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure8_theta_e_evolution(datasets, waypoints):
    """Plan-view theta-e evolution (18Z run)."""
    ds = datasets[18]
    if "theta_e_2m" not in ds.data_vars:
        print("  [SKIP] theta_e_2m not in dataset")
        return

    fig = plot_planview_evolution(
        ds, "theta_e_2m",
        ncols=3,
        waypoints=waypoints,
        cmap="RdYlBu_r",
        wind_barbs=True, barb_skip=BARB_SKIP,
        suptitle=f"HRRR 18Z | Equivalent Potential Temperature | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig08_theta_e.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure9_temp_tendency(datasets, waypoints):
    """Plan-view hourly temperature tendency (18Z run)."""
    ds = datasets[18].copy(deep=True)
    ds = hourly_tendency(ds, "temp_2m")

    if "temp_2m_tendency" not in ds.data_vars:
        print("  [SKIP] tendency computation failed")
        return

    fig = plot_planview_evolution(
        ds, "temp_2m_tendency",
        ncols=3,
        waypoints=waypoints,
        cmap="RdBu_r",
        vmin=-5, vmax=5,
        suptitle=f"HRRR 18Z | Hourly Temp Tendency (K/hr) | {EVENT_DATE}",
    )
    _annotate(fig)
    out = OUTDIR / "fig09_temp_tendency.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def figure10_verification(wp_series, obs_df, waypoints):
    """NWP vs obs verification at KVEL / foehn path stations."""
    from brc_tools.verify.deterministic import paired_scores

    nwp_df = wp_series[18]
    if obs_df is None:
        print("  [SKIP] No obs data for verification")
        return

    verify_vars = ["temp_2m", "wind_speed_10m"]
    scores = paired_scores(nwp_df, obs_df, verify_vars, tolerance_minutes=30)

    if scores.is_empty():
        print("  [SKIP] No paired obs for verification")
        return

    # -- Panel A: Verification time series at Vernal --
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Top row: NWP vs obs timeseries at Vernal for temp and wind
    for col, (var, label, transform) in enumerate([
        ("temp_2m", "Temp (C)", lambda x: x - 273.15),
        ("wind_speed_10m", "Wind Speed (m/s)", None),
    ]):
        ax = axes[0, col]
        plot_verification_timeseries(
            nwp_df, obs_df, var, "vernal",
            unit_label=label,
            unit_transform=transform,
            ax=ax,
            show_error=True,
            title=f"HRRR 18Z vs Obs | {var} at Vernal",
        )

    # Bottom row: bar chart of RMSE and bias per station
    for ax_idx, metric in enumerate(["rmse", "bias"]):
        ax = axes[1, ax_idx]
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

            for bar, n in zip(bars, n_obs):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"n={n}", ha="center", va="bottom", fontsize=6)

        short_names = [w.replace("_", "\n") for w in wps]
        ax.set_xticks(x)
        ax.set_xticklabels(short_names, fontsize=7)
        ax.set_ylabel(metric.upper(), fontsize=LABEL_SIZE)
        ax.set_title(f"{metric.upper()} by Station (18Z run)", fontsize=TITLE_SIZE)
        ax.legend(fontsize=8)
        ax.grid(True, axis="y", alpha=0.3)
        if metric == "bias":
            ax.axhline(0, color="black", linewidth=0.5)

    fig.suptitle(
        f"Verification | HRRR 18Z vs Obs | {EVENT_DATE}",
        fontsize=TITLE_SIZE + 2,
    )
    _annotate(fig)
    fig.tight_layout()
    out = OUTDIR / "fig10_verification.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global EVENT_DATE

    parser = argparse.ArgumentParser(description="KVEL westerly wind case study")
    parser.add_argument("--scan-only", action="store_true",
                        help="Only scan for events; do not fetch HRRR or generate figures")
    parser.add_argument("--date", type=str, default=None,
                        help="Override event date (YYYY-MM-DD); skip scanning")
    args = parser.parse_args()

    plt.style.use("default")

    print("=" * 60)
    print("Case Study: KVEL Westerly Wind Event — Spring 2025")
    print("=" * 60)

    # -- Phase 1: Find the event date --
    if args.date:
        EVENT_DATE = args.date
        print(f"\nUsing user-specified date: {EVENT_DATE}")
    else:
        print("\n[Phase 1] Scanning KVEL wind observations (Mar–May 2025) ...")
        candidates = scan_kvel_wind_events(months=(3, 4, 5), year=2025)
        print_candidate_table(candidates)

        if not candidates:
            print("\nNo qualifying events. Try relaxing criteria or a different period.")
            return

        EVENT_DATE = candidates[0]["date"]
        print(f"\n  -> Auto-selected top event: {EVENT_DATE}")
        print(f"     Peak wind: {candidates[0]['peak_speed_ms']} m/s "
              f"({candidates[0]['peak_speed_kt']} kt)")
        print(f"     Increase:  {candidates[0]['wind_increase']} m/s over baseline")

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

    # -- Phase 3: Generate figures --
    print(f"\n{'=' * 60}")
    print("[Phase 3] Generating 10 figures ...")
    print(f"{'=' * 60}")

    for name, func, args_tuple in [
        ("Fig 1: KVEL wind time series",
         figure1_kvel_wind_timeseries, (kvel_obs, EVENT_DATE)),
        ("Fig 2: Foehn-path wind time series",
         figure2_foehn_wind_timeseries, (wp_series, obs_df, waypoints)),
        ("Fig 3: Foehn-path temp + MSLP",
         figure3_foehn_temp_mslp, (wp_series, obs_df, waypoints)),
        ("Fig 4: Wind speed evolution map",
         figure4_wind_speed_evolution, (sfc_datasets, waypoints)),
        ("Fig 5: MSLP evolution map",
         figure5_mslp_evolution, (sfc_datasets, waypoints)),
        ("Fig 6: Temperature + MSLP contours",
         figure6_temp_with_mslp, (sfc_datasets, waypoints)),
        ("Fig 7: Wind direction evolution",
         figure7_wind_direction_evolution, (sfc_datasets, waypoints)),
        ("Fig 8: Theta-e evolution",
         figure8_theta_e_evolution, (sfc_datasets, waypoints)),
        ("Fig 9: Temperature tendency",
         figure9_temp_tendency, (sfc_datasets, waypoints)),
        ("Fig 10: Verification",
         figure10_verification, (wp_series, obs_df, waypoints)),
    ]:
        print(f"\n{name} ...")
        try:
            func(*args_tuple)
        except Exception as exc:
            print(f"  [ERROR] {name} failed: {exc}")
            traceback.print_exc()

    # -- Summary --
    print(f"\n{'=' * 60}")
    print(f"Done. 10 figures saved to: {OUTDIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
