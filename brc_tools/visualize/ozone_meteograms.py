from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt
import polars as pl
from synoptic.services import TimeSeries

# ==================== CONFIGURATION ====================
# Timezone selection: Set to True for local time, False for UTC
USE_LOCAL_TIME = True  # Toggle between local time and UTC

# Local timezone (automatically handles DST)
LOCAL_TIMEZONE = ZoneInfo('America/Denver')  # Change to 'America/New_York', 'US/Pacific', etc.

# Working timezone (determined by USE_LOCAL_TIME flag)
TIMEZONE = LOCAL_TIMEZONE if USE_LOCAL_TIME else ZoneInfo('UTC')

# Date range in the selected timezone
START_DATE = datetime(2025, 1, 28, tzinfo=TIMEZONE)
END_DATE = datetime(2025, 2, 4, tzinfo=TIMEZONE)

# Station list
STATIONS = ["UBHSP", "UB7ST", "UBCSP"]

# Station names for legend
STATION_NAMES = {
    "UBHSP": "Horsepool",
    "UB7ST": "Seven Sisters",
    "UBCSP": "Castle Peak"
}

# Station-specific QC filters (min, max)
QC_FILTERS = {"UBHSP": (20, 70), "UBCSP": (20, 87)}

# Plot settings
PLOT_CONFIG = {
    "figsize": (12, 6),
    "ylim": (0, 100),
    "threshold": 70,  # NAAQS 8-hour standard
    "title": "High Ozone Event: End of January 2025",
}

# Font settings
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Helvetica Neue', 'Helvetica', 'Arial']
# Note: Calibri (Microsoft Office) is not accessible to matplotlib on this system
# plt.rcParams['font.sans-serif'] = ['Calibri', 'Helvetica Neue', 'Helvetica', 'Arial']  # Calibri not found
# =======================================================

if __name__ == "__main__":
    # Download ozone data (API handles timezone conversion)
    df_data = TimeSeries(
        stid=STATIONS,
        start=START_DATE.astimezone(ZoneInfo('UTC')),
        end=END_DATE.astimezone(ZoneInfo('UTC')),
        vars=["ozone_concentration"],
        verbose=True,
        obtimezone="utc",
    ).df().synoptic.pivot()

    # Convert UTC to selected timezone and remove timezone info for matplotlib
    df_data = df_data.with_columns(
        pl.col("date_time").dt.replace_time_zone("UTC").dt.convert_time_zone(
                                    str(TIMEZONE)).dt.replace_time_zone(None)
    )

    # Apply station-specific QC filters
    for stid, (min_val, max_val) in QC_FILTERS.items():
        df_data = df_data.with_columns(
            pl.when(
                (pl.col("stid") == stid) &
                ((pl.col("ozone_concentration") < min_val) | (
                            pl.col("ozone_concentration") > max_val))
            )
            .then(None)
            .otherwise(pl.col("ozone_concentration"))
            .alias("ozone_concentration")
        )

    # Create plot
    fig, ax = plt.subplots(figsize=PLOT_CONFIG["figsize"], dpi=250)

    # Plot each station
    for stid in STATIONS:
        df_station = df_data.filter(pl.col("stid") == stid)
        ax.plot(
            df_station["date_time"],
            df_station["ozone_concentration"],
            label=f"{STATION_NAMES[stid]} ({stid})",
            alpha=0.7,
            linewidth=1.5,
        )

    # Auto-generate list of dates to annotate (all days in range)
    current_date = START_DATE.date()
    # end_date = END_DATE.date()
    # Or we can stop after Feb 01.
    end_date = datetime(2025, 2, 2).date()

    while current_date < end_date:
        # Create timezone-naive datetimes to match the converted dataframe
        day_start = datetime.combine(current_date, datetime.min.time())
        day_end = datetime.combine(current_date, datetime.max.time())

        df_day = df_data.filter(
            pl.col("date_time").is_between(day_start, day_end) &
            pl.col("ozone_concentration").is_not_null()
        )

        if df_day.height > 0:
            max_row = df_day.sort("ozone_concentration", descending=True).row(0, named=True)

            ax.annotate(
                f"{max_row['ozone_concentration']:.1f} ppb\n{max_row['date_time'].strftime('%b %d')}",
                xy=(max_row["date_time"], max_row["ozone_concentration"]),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                fontsize=10,
                fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="black", lw=0.5),
            )

        current_date += timedelta(days=1)

    # Format plot
    ax.set_ylim(PLOT_CONFIG["ylim"])
    ax.axhline(PLOT_CONFIG["threshold"], color="red", linestyle="--",
               label=f"NAAQS 8-hour standard ({PLOT_CONFIG['threshold']} ppb)")

    # Get timezone abbreviation dynamically
    tz_name = START_DATE.strftime('%Z')
    ax.set_xlabel(f"Time ({tz_name})")
    ax.set_ylabel("Ozone concentration (ppb)")
    ax.set_title(PLOT_CONFIG["title"])
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

