"""Historical snow depth ranges in the Uinta Basin (Apr 16-18).

Discovers all snow-depth-reporting stations below 2000 m in the Utah
portion of the Uinta Basin, fetches April 16-18 snow_depth for up to
15 years (2011-2026), and produces a publication-quality range chart.

Usage::

    conda run -n brc-tools python scripts/snow_depth_april_range.py
"""

import datetime
import time
import traceback
from pathlib import Path

import matplotlib.cm as mcm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import polars as pl

from brc_tools.nwp.case_study import annotate

# ==================== CONFIGURATION ====================

OUTDIR = Path(__file__).resolve().parent.parent / "figures" / "snow_depth_april_range"
DPI = 200
ANNOTATION = "Snow Depth Climatology | BRC Tools"

# Utah-only Uinta Basin bounding box.
# lookups.toml uinta_basin region extends into CO/WY (ne=[41.1, -108.5]).
# Clip at UT-CO border (~-109.05 W) and UT-WY border (41.0 N).
BBOX_WEST = -110.9
BBOX_SOUTH = 39.4
BBOX_EAST = -109.05
BBOX_NORTH = 41.0

MAX_ELEVATION_M = 2000.0
MAX_ELEVATION_FT = MAX_ELEVATION_M * 3.28084  # ~6561.7 ft

# April 16-18 inclusive, UTC
WINDOW_MONTH = 4
WINDOW_START_DAY = 16
WINDOW_END_DAY = 18
YEAR_RANGE = range(2011, 2027)  # 2011 through 2026

# Unit conversion
MM_TO_INCHES = 0.0393701
MM_TO_CM = 0.1
INCHES_TO_CM = 2.54
FT_TO_M = 0.3048

# =======================================================


def discover_snow_stations() -> pl.DataFrame:
    """Find all stations in the Utah Uinta Basin bbox reporting snow_depth."""
    from synoptic.services import Metadata

    bbox_str = f"{BBOX_WEST},{BBOX_SOUTH},{BBOX_EAST},{BBOX_NORTH}"
    print(f"  Querying Metadata: bbox={bbox_str}, vars=snow_depth")

    meta = Metadata(
        bbox=bbox_str,
        vars="snow_depth",
        verbose=False,
    )
    df = meta.df()
    print(f"  Raw metadata: {df.shape[0]} stations")

    # Elevation filter: Synoptic returns elevation in feet.
    # Use 'elevation' column, fall back to 'elev_dem' if null.
    if "elevation" in df.columns:
        elev_col = "elevation"
    elif "elev_dem" in df.columns:
        elev_col = "elev_dem"
    else:
        print("  [WARN] No elevation column found; skipping elevation filter")
        elev_col = None

    if elev_col is not None:
        df = df.filter(
            pl.col(elev_col).is_not_null() & (pl.col(elev_col) < MAX_ELEVATION_FT)
        )
        print(f"  After elevation filter (<{MAX_ELEVATION_M}m / <{MAX_ELEVATION_FT:.0f}ft): "
              f"{df.shape[0]} stations")

    # Double-check lat/lon within Utah bounds
    if "latitude" in df.columns and "longitude" in df.columns:
        df = df.filter(
            (pl.col("latitude") < BBOX_NORTH)
            & (pl.col("latitude") > BBOX_SOUTH)
            & (pl.col("longitude") > BBOX_WEST)
            & (pl.col("longitude") < BBOX_EAST)
        )
        print(f"  After coordinate filter (Utah-only): {df.shape[0]} stations")

    # Print summary
    cols_to_show = [c for c in ["stid", "name", "elevation", "latitude", "longitude"]
                    if c in df.columns]
    if cols_to_show:
        print(df.select(cols_to_show))

    return df


def fetch_snow_depth_history(stids: list[str]) -> pl.DataFrame:
    """Fetch snow_depth for Apr 16-18 UTC across all years."""
    from synoptic.services import TimeSeries

    all_frames = []
    for year in YEAR_RANGE:
        start = datetime.datetime(year, WINDOW_MONTH, WINDOW_START_DAY, 0, 0,
                                  tzinfo=datetime.timezone.utc)
        end = datetime.datetime(year, WINDOW_MONTH, WINDOW_END_DAY, 23, 59,
                                tzinfo=datetime.timezone.utc)
        try:
            raw = TimeSeries(
                stid=stids,
                start=start,
                end=end,
                vars=["snow_depth"],
                verbose=False,
            ).df().synoptic.pivot()

            if isinstance(raw, pl.DataFrame):
                df = raw
            else:
                df = pl.from_pandas(raw.reset_index() if hasattr(raw, "reset_index") else raw)

            df = df.with_columns(pl.lit(year).alias("year"))
            n = df.shape[0]
            n_stids = df["stid"].n_unique() if "stid" in df.columns else "?"
            all_frames.append(df)
            print(f"  {year}: {n} rows, {n_stids} stations")
        except Exception as exc:
            print(f"  {year}: no data ({exc})")

        time.sleep(0.5)

    if not all_frames:
        raise RuntimeError("No snow depth data retrieved for any year")

    return pl.concat(all_frames, how="diagonal_relaxed")


def aggregate_by_year(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Aggregate snow depth per station-year and then per year.

    Returns (year_agg, station_year) where:
      - station_year: one row per (year, stid) with max snow_depth
      - year_agg: one row per year with min/median/max across stations
    """
    # Per station-year: max snow depth in the 3-day window
    station_year = (
        df.group_by(["year", "stid"])
        .agg(pl.col("snow_depth").max().alias("snow_depth_mm"))
        .filter(pl.col("snow_depth_mm").is_not_null())
        .with_columns([
            (pl.col("snow_depth_mm") * MM_TO_INCHES).alias("snow_depth_in"),
            (pl.col("snow_depth_mm") * MM_TO_CM).alias("snow_depth_cm"),
        ])
        .sort(["year", "stid"])
    )

    # Per year: range across stations
    year_agg = (
        station_year.group_by("year")
        .agg([
            pl.col("snow_depth_in").min().alias("min_in"),
            pl.col("snow_depth_in").median().alias("median_in"),
            pl.col("snow_depth_in").max().alias("max_in"),
            pl.col("snow_depth_cm").min().alias("min_cm"),
            pl.col("snow_depth_cm").median().alias("median_cm"),
            pl.col("snow_depth_cm").max().alias("max_cm"),
            pl.col("stid").n_unique().alias("n_stations"),
        ])
        .sort("year")
    )

    return year_agg, station_year


def figure_snow_depth_range(
    year_agg: pl.DataFrame,
    station_year: pl.DataFrame,
) -> None:
    """Range-bar + dot chart: snow depth spread across stations by year.

    Station dots are coloured by elevation (darker = higher).  The y-axis
    is capped and any clipped values are annotated with the true reading.
    """
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]

    years = year_agg["year"].to_list()
    mins = year_agg["min_in"].to_list()
    medians = year_agg["median_in"].to_list()
    maxes = year_agg["max_in"].to_list()

    # Tight y-cap: second-largest max * 1.2
    sorted_maxes = sorted(m for m in maxes if m > 0)
    if len(sorted_maxes) >= 2 and sorted_maxes[-1] > sorted_maxes[-2] * 1.5:
        y_cap_in = sorted_maxes[-2] * 1.2
    else:
        y_cap_in = (max(maxes) * 1.15) if maxes else 10
    y_cap_in = max(y_cap_in, 1.0)

    # Elevation colormap
    all_elevs = station_year["elevation_m"].drop_nulls().to_list()
    elev_min = min(all_elevs) if all_elevs else 1400
    elev_max = max(all_elevs) if all_elevs else 2000
    norm = mcolors.Normalize(vmin=elev_min, vmax=elev_max)
    cmap = plt.colormaps["YlOrBr"]

    fig, ax_in = plt.subplots(figsize=(14, 7), dpi=DPI)

    # Range bars (clipped at cap)
    for i, yr in enumerate(years):
        bar_top = min(maxes[i], y_cap_in)
        ax_in.plot(
            [yr, yr], [mins[i], bar_top],
            color="steelblue", linewidth=2.5, solid_capstyle="round", zorder=2,
        )
        if maxes[i] > y_cap_in:
            # Wavy break marks
            wave_x = np.array([yr - 0.12, yr - 0.04, yr + 0.04, yr + 0.12])
            wave_y = np.array([y_cap_in - y_cap_in * 0.02,
                               y_cap_in + y_cap_in * 0.02,
                               y_cap_in - y_cap_in * 0.02,
                               y_cap_in + y_cap_in * 0.02])
            ax_in.plot(wave_x, wave_y, color="steelblue", linewidth=1.8, zorder=5)
            ax_in.annotate(
                f"{maxes[i]:.1f}\"",
                (yr, y_cap_in), xytext=(0, 8), textcoords="offset points",
                ha="center", va="bottom", fontsize=8, fontweight="bold",
                color="steelblue",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="steelblue",
                          alpha=0.85, lw=0.8),
            )

    # Median markers
    clipped_medians = [min(m, y_cap_in) for m in medians]
    ax_in.scatter(
        years, clipped_medians, color="steelblue", s=60, zorder=4,
        marker="D", edgecolors="white", linewidths=0.8, label="Median",
    )

    # Station dots coloured by elevation
    rng = np.random.default_rng(42)
    first_scatter = True
    for yr in years:
        yr_df = station_year.filter(pl.col("year") == yr)
        stn_vals = yr_df["snow_depth_in"].to_list()
        stn_elevs = yr_df["elevation_m"].to_list()
        jitter = rng.uniform(-0.15, 0.15, size=len(stn_vals))
        plot_vals = [min(v, y_cap_in) for v in stn_vals]
        colors = [cmap(norm(e)) if e is not None else "gray" for e in stn_elevs]
        sc = ax_in.scatter(
            [yr + j for j in jitter],
            plot_vals,
            c=colors, s=30, alpha=0.8, zorder=3,
            edgecolors="k", linewidths=0.3,
            label="Station" if first_scatter else None,
        )
        first_scatter = False

    # Colorbar for elevation
    sm = mcm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax_in, pad=0.12, shrink=0.8, aspect=30)
    cbar.set_label("Station Elevation (m)", fontsize=10)

    # Left axis (inches)
    ax_in.set_xlabel("Year", fontsize=11)
    ax_in.set_ylabel("Snow Depth (inches)", fontsize=11)
    ax_in.set_xlim(min(years) - 0.8, max(years) + 0.8)
    ax_in.set_ylim(0, y_cap_in * 1.12)
    ax_in.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax_in.grid(True, axis="y", alpha=0.3)

    # Right axis (cm) — between main plot and colorbar
    ax_cm = ax_in.twinx()
    ax_cm.set_ylabel("Snow Depth (cm)", fontsize=11)
    ax_cm.set_ylim(0, y_cap_in * 1.12 * INCHES_TO_CM)

    ax_in.set_title(
        "Uinta Basin Snow Depth Range (Apr 16\u201318 UTC)\n"
        f"Low-Elevation Stations (<{MAX_ELEVATION_M:.0f} m), Utah Only",
        fontsize=13, fontweight="bold",
    )

    # Legend (just median diamond)
    handles, labels = ax_in.get_legend_handles_labels()
    ax_in.legend(handles[:1], labels[:1], loc="upper left", fontsize=9, framealpha=0.8)

    annotate(fig, ANNOTATION)

    out = OUTDIR / "snow_depth_april_range.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Snow Depth April Range — Uinta Basin Low-Elevation Stations")
    print("=" * 60)

    # Phase 1: Discover stations
    print("\n[1/3] Discovering snow depth stations ...")
    meta_df = discover_snow_stations()
    stids = meta_df["stid"].to_list()
    if not stids:
        print("[ERROR] No stations found. Check bbox and elevation filters.")
        return
    print(f"\n  -> {len(stids)} qualifying stations: {stids}")

    # Phase 2: Fetch historical data
    print(f"\n[2/3] Fetching snow_depth for Apr {WINDOW_START_DAY}-{WINDOW_END_DAY}, "
          f"{YEAR_RANGE.start}-{YEAR_RANGE.stop - 1} ...")
    raw_df = fetch_snow_depth_history(stids)
    print(f"\n  -> {raw_df.shape[0]} total rows")

    # Phase 3: Aggregate and plot
    print("\n[3/3] Aggregating and generating figure ...")
    year_agg, station_year = aggregate_by_year(raw_df)

    # Join elevation (ft → m) onto station_year for colour mapping
    elev_lookup = meta_df.select([
        pl.col("stid"),
        (pl.col("elevation") * FT_TO_M).alias("elevation_m"),
    ])
    station_year = station_year.join(elev_lookup, on="stid", how="left")
    print(year_agg)

    figure_snow_depth_range(year_agg, station_year)

    print(f"\nDone. Output: {OUTDIR}")


if __name__ == "__main__":
    main()
