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

# COOP snow depth stations
STATIONS = ['COOPDINU1', 'COOPROSU1', 'COOPVELU1', 'COOPFTDU1',
            'COOPALMU1', 'COOPDSNU1', 'COOPNELU1']

# Station names for legend
STATION_NAMES = {
    'COOPDINU1': 'Dinosaur NM',
    'COOPROSU1': 'Roosevelt',
    'COOPVELU1': 'Vernal',
    'COOPFTDU1': 'Fort Duchesne',
    'COOPALMU1': 'Altamont',
    'COOPDSNU1': 'Duchesne',
    'COOPNELU1': 'Neola'
}

# Plot settings
PLOT_CONFIG = {
    "figsize": (12, 6),
    "ylim": (0, None),  # Auto-scale upper limit
    "title": "Uinta Basin Snow Depth",
}

# Font settings
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Helvetica Neue', 'Helvetica', 'Arial']
# =======================================================

if __name__ == "__main__":
    # Download snow depth data (API handles timezone conversion)
    df_data = TimeSeries(
        stid=STATIONS,
        start=START_DATE.astimezone(ZoneInfo('UTC')),
        end=END_DATE.astimezone(ZoneInfo('UTC')),
        vars=["snow_depth"],
        verbose=True,
        obtimezone="utc",
    ).df().synoptic.pivot()

    # Convert UTC to selected timezone and remove timezone info for matplotlib
    df_data = df_data.with_columns(
        pl.col("date_time").dt.replace_time_zone("UTC").dt.convert_time_zone(
                                    str(TIMEZONE)).dt.replace_time_zone(None)
    )

    # Convert snow depth from mm to inches (1 mm = 0.0393701 inches)
    df_data = df_data.with_columns(
        (pl.col("snow_depth") * 0.0393701).alias("snow_depth_inches")
    )

    # Create plot
    fig, ax = plt.subplots(figsize=PLOT_CONFIG["figsize"], dpi=250)

    # Plot each station
    for stid in STATIONS:
        df_station = df_data.filter(pl.col("stid") == stid)
        if df_station.height > 0:  # Only plot if data exists
            ax.plot(
                df_station["date_time"],
                df_station["snow_depth_inches"],
                label=f"{STATION_NAMES[stid]} ({stid})",
                alpha=0.7,
                linewidth=1.5,
            )

    # Format plot
    ax.set_ylim(bottom=0)  # Start at 0, auto-scale top

    # Get timezone abbreviation dynamically
    tz_name = START_DATE.strftime('%Z')
    ax.set_xlabel(f"Time ({tz_name})")
    ax.set_ylabel("Snow depth (inches)")
    ax.set_title(PLOT_CONFIG["title"])
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
