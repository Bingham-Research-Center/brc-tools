# Demonstration script for using Herbie with the AQM model
import os
import sys

import pandas as pd

sys.path.append('/Users/johnlawson/PycharmProjects/Herbie/herbie/models/aqm.py')

from herbie import Herbie
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature  # Add this import
import numpy as np

import pathlib

# TODO - Decide if i actually like pathlib, lol - JRL
# Get the project root directory
project_root = pathlib.Path(__file__).parent.parent  # Adjust number of parents based on script depth

# Create output directory in the project root
output_dir = project_root / "test_figs"
os.makedirs(output_dir, exist_ok=True)

# Ozone concentration averages are between two forecast hours
# Here, we set fxx to represent the second (end) hour

# Define common parameters once to avoid repetition
herbie_params = {
    # "date": "2025-01-31 12:00",
    "date": "2025-04-21 12:00",
    "model": "aqm",
    "product": "ave_8hr_o3",
    "domain": "CS",
    "fxx": 12,
}
assert herbie_params["fxx"] > 7 # Ensure fxx is greater than 7 due to 8-hr ave


def plot_ozone_forecast(ds, title, herbie_params, output_fpath,
                        focus_on_utah=True, min_threshold=50, max_cap=100):
    """
    Plot AQM ozone forecast with enhanced visualization features.

    Parameters:
    -----------
    ds : xarray.Dataset
        Dataset containing ozone data
    title : str
        Title for the plot
    herbie_params : dict
        Parameters used for Herbie
    focus_on_utah : bool
        Whether to zoom in on Utah
    min_threshold : float
        Minimum ozone value to display (ppb), lower values will be transparent
    max_cap : float
        Maximum ozone value to display (ppb), higher values will be capped
    """
    # Create figure and axes
    fig = plt.figure(figsize=(8, 8))
    ax = plt.axes(projection=ccrs.Mercator(central_longitude=-95))

    # Set map extent based on focus preference
    if focus_on_utah:
        # Utah-focused extent: [west, east, south, north]
        ax.set_extent([-112.15, -108.6, 40.0, 41.65], crs=ccrs.PlateCarree())
    else:
        # North America extent
        ax.set_extent([-130, -65, 25, 50], crs=ccrs.PlateCarree())

    # Add map features with enhanced styling
    ax.add_feature(cfeature.LAND, edgecolor='black', facecolor='lightgray', zorder=0)
    ax.add_feature(cfeature.OCEAN, edgecolor='black', facecolor='lightblue', zorder=0)
    ax.add_feature(cfeature.LAKES, edgecolor='black', facecolor='lightblue', zorder=1)
    ax.add_feature(cfeature.STATES, linewidth=0.5, edgecolor='gray', zorder=2)
    ax.add_feature(cfeature.BORDERS, linewidth=0.7, zorder=3)

    # Add utah counties if focus_on_utah is True
    if focus_on_utah:
        ax.add_feature(cfeature.NaturalEarthFeature(category='cultural',
                                                    name='admin_1_states_provinces_lakes',
                                                    scale='10m',
                                                    facecolor='none'),
                       edgecolor='black', linewidth=0.5, zorder=4)
        # Add county boundaries
        counties = cfeature.NaturalEarthFeature(
            category='cultural',
            name='admin_2_counties',
            scale='10m',
            facecolor='none'
        )
        ax.add_feature(counties, edgecolor='gray', linewidth=0.3, zorder=3)


    ax.coastlines(resolution='10m', zorder=5)

    # Process ozone data - apply threshold and cap
    ozone_data = ds["ozcon"].squeeze().copy()

    # Cap high values
    ozone_data = ozone_data.where(ozone_data <= max_cap, max_cap)

    # Create a masked version for filled contours that hides values below threshold
    ozone_masked = ozone_data.where(ozone_data >= min_threshold)

    # Plot filled contours only for values above threshold
    cs_sp = 2
    levels_fill = np.arange(min_threshold, max_cap+cs_sp, cs_sp)
    cs_fill = ax.contourf(
        ds.longitude,
        ds.latitude,
        ozone_masked,
        levels=levels_fill,
        transform=ccrs.PlateCarree(),
        cmap='plasma_r',
        extend='max',
        zorder=6,
        alpha=0.4
    )

    # Plot contour lines for all values
    levels_lines = np.arange(30, max_cap+cs_sp, cs_sp)  # Wider spacing for lines
    cs_lines = ax.contour(
        ds.longitude,
        ds.latitude,
        ozone_data,
        levels=levels_lines,
        transform=ccrs.PlateCarree(),
        colors='black',
        linewidths=0.5,
        zorder=7
    )

    # Add contour labels (only on the more spaced out contours)
    plt.clabel(cs_lines, inline=True, fontsize=8, fmt='%d')

    # Add horizontal colorbar at the bottom
    cbar = plt.colorbar(cs_fill, orientation='horizontal', pad=0.05, aspect=40, shrink=0.8)
    cbar.set_label(f'Ozone (ppb) - Values < {min_threshold} ppb not shown')

    # Extract forecast hour range for time labels
    forecast_range = title.split(' - ')[1].replace(' hour average forecast', '')

    hours = forecast_range.split('-')
    start_hr = int(hours[0])
    end_hr = int(hours[1].split()[0])

    # Calculate UTC time range
    date_parts = herbie_params["date"].split()
    if len(date_parts) >= 2:
        time_parts = date_parts[1].split(':')
        if len(time_parts) >= 1:
            utc_start = (int(time_parts[0]) + start_hr) % 24
            utc_end = (int(time_parts[0]) + end_hr) % 24
            utc_label = f"UTC: {utc_start:02d}:00-{utc_end:02d}:00"

            # Calculate Mountain Time (UTC-6 for standard time, UTC-7 for daylight saving)
            # Using UTC-6 for this example
            mt_start = (utc_start - 6) % 24
            mt_end = (utc_end - 6) % 24
            mt_label = f"MT: {mt_start:02d}:00-{mt_end:02d}:00"

            # Add time information to the plot
            plt.figtext(0.01, 0.01, utc_label, fontsize=10)
            plt.figtext(0.01, 0.03, mt_label, fontsize=10)

    # Set title and layout
    plt.title(title)
    plt.tight_layout()
    plt.show()

    # Save with a reasonable DPI and close
    plt.savefig(output_fpath, dpi=250)
    plt.close(fig)
    print(f"\nPlot saved as {output_fpath}")
    return fig, ax

# Initialize a Herbie object for the AQM model
H = Herbie(**herbie_params)

# Print the details of this Herbie object
print(f"Model: {H.model.upper()}")
print(f"Product: {H.product} - {H.product_description}")
print(f"Initial time: {H.date}")
print(f"File exists: {H.grib is not None}")
print(f"Source: {H.grib_source}")

def extract_first_hour(forecast_str):
    # Extract the first number from strings like "7-15 hour ave fcst"
    parts = forecast_str.split()
    if not parts:
        return 999  # Default high value for empty strings

    hour_range = parts[0]
    if '-' in hour_range:
        try:
            first_hour = int(hour_range.split('-')[0])
            return first_hour
        except (ValueError, IndexError):
            return 999
    return 999

def plot_forecast(forecast_hour_range):
    """Plot a specific forecast hour range from the dataset"""
    print(f"\nPlotting forecast: {forecast_hour_range}")

    # Get the dataset for this forecast
    ds = H.xarray(forecast_hour_range)
    print(f"Dataset valid time: {ds.valid_time.values}")

    # Extract time information
    forecast_parts = forecast_hour_range.split()
    forecast_range = forecast_parts[0]
    start_hr, end_hr = map(int, forecast_range.split('-'))

    # Calculate times properly
    init_datetime = H.date
    start_valid_time = init_datetime + pd.Timedelta(hours=start_hr)
    end_valid_time = init_datetime + pd.Timedelta(hours=end_hr)

    # Format for filename
    init_time_str = f"{init_datetime:%Y%m%d%H}"
    valid_time_str = f"{end_valid_time:%Y%m%d%H}"

    # Construct filename
    output_fpath = os.path.join(output_dir,
                        f"aqm_{init_time_str}Z_{valid_time_str}Z_utah_o3_8h.png")

    # Create a comprehensive title
    date_str = f"{init_datetime:%Y-%m-%d}"
    title = (f"AQM {H.product.upper()} - {forecast_range} hour average\n"
             f"Init: {init_datetime:%Y-%m-%d %HZ}, Valid: {start_valid_time:%m-%d %HZ}-{end_valid_time:%m-%d %HZ}")

    # Plot the data
    plot_ozone_forecast(ds, title, herbie_params,
                        output_fpath=output_fpath,
                        focus_on_utah=True)

    return ds, output_fpath

# Download the GRIB2 file
if H.grib is not None:
    local_file = H.download()
    print(f"\nDownloaded to: {local_file}")

    # Update Herbie object with the local file path
    H = Herbie(
        **herbie_params,
        file_path=str(local_file)
    )

    # Now inventory will work with the local file directly
    inventory_df = H.inventory()
    print(inventory_df[["grib_message", "variable", "level", "forecast_time"]].head())

    # Sort forecasts chronologically
    available_forecasts = sorted(
        inventory_df["forecast_time"].unique(),
        key=extract_first_hour
    )

    print("\nAvailable forecast hours in file (sorted chronologically):")
    for i, fcst in enumerate(available_forecasts):
        print(f"{i}: {fcst}")

    # Find the specific forecast hour we want based on fxx parameter
    target_forecast = f"{herbie_params['fxx']-8}-{herbie_params['fxx']} hour ave fcst"

    if target_forecast in available_forecasts:
        forecast_to_use = target_forecast
        print(f"\nUsing specified forecast: {forecast_to_use}")
    else:
        # Fall back to first forecast if target not found
        forecast_to_use = available_forecasts[0]
        print(f"\nTarget forecast '{target_forecast}' not found. Using: {forecast_to_use}")

    # Plot the selected forecast
    ds, output_file = plot_forecast(forecast_to_use)

else:
    print("\nFile not found. Please check that the date and product are valid.")
    print("This example uses a 2025 date to match the documentation, but you may need")
    print("to use a more recent or available date.")