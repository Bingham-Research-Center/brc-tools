#!/usr/bin/env python
# AQM Model Testing Framework for Herbie
# Author: Seth Lyman
# Date: April 2024

# TODO with specific products, daily max + 8-hour ave


import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pathlib import Path
from datetime import datetime, timedelta

from herbie import Herbie

import concurrent.futures
from functools import partial



# -----------------------------------------------------------------------
# Configuration settings - Edit these parameters for your specific needs
# -----------------------------------------------------------------------

# Get the project root directory
project_root = Path(__file__).parent.parent

# Create output directory in the project root
output_dir = project_root / "test_figs"
os.makedirs(output_dir, exist_ok=True)

project_root = Path(__file__).parent.parent

# -----------------------------------------------------------------------
# Global Configuration - Edit these parameters for your specific needs
# -----------------------------------------------------------------------

# For 06Z runs
fxx = 20

# For 12 Z runs
# fxx = 14

AQM_CONFIG = {
    # Default date and time settings
    "dates": {
        "init_date": "2025-01-31 06:00",  # Current day, 12Z run
        "lookback_days": 2,               # How many days to look back for comparisons
    },

    # Default forecast settings
    "forecast": {
        "fxx": fxx,                        # Default forecast hour
        "fxx_range": list(range(8,fxx+1,1)),   # Default hours to process in batch mode
        "product": "ave_8hr_o3",          # Default product
        "domain": "CS",                   # Default domain (CONUS)
    },

    # Visualization settings
    "viz": {
        "min_threshold": 50,    # Min value to display (ppb), lower values will be transparent
        "max_cap": 100,         # Max value to display (ppb), higher values will be capped
        "focus_on_utah": True,  # Whether to zoom in on Utah
        "dpi": 250,             # Output image resolution
        "contour_spacing": 2,   # Spacing between contour lines (ppb)
        "colormap": "plasma_r"  # Colormap for filled contours
    },

    # Output settings
    "output_dir": project_root / "test_figs",
}

# Get the project root directory
 # Adjust number of parents based on script depth

# Set output directory dynamically
os.makedirs(AQM_CONFIG["output_dir"], exist_ok=True)

# -----------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------
def setup_output_directory(base_dir):
    """Create output directory structure if it doesn't exist"""
    output_path = Path(base_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path

def process_forecast_range_parallel(init_date, product="ave_8hr_o3", domain="CS",
                                       config=AQM_CONFIG, max_workers=None):
    """Process multiple forecast lead times in parallel"""
    results = {}

    # Convert init_date to string if it's a datetime object
    if isinstance(init_date, (datetime, pd.Timestamp)):
        init_date = init_date.strftime("%Y-%m-%d %H:%M")

    fxx_range = config["forecast"]["fxx_range"]

    # Use ProcessPoolExecutor for CPU-bound tasks
    max_workers = os.cpu_count() - 1 if max_workers is None else max_workers

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs - pass all parameters explicitly to avoid using lambda        # Submit all jobs - pass all parameters explicitly to avoid using lambda
        futures = []
        for fxx in fxx_range:
            future = executor.submit(
                process_single_forecast,
                init_date=init_date,
                fxx=fxx,
                product=product,
                domain=domain,
                config=config,
                save=True,
                show=False
            )
            futures.append((future, fxx))

        # Process results as they complete
        for future, fxx in futures:
            try:
                ds, fig = future.result()
                results[fxx] = {"dataset": ds, "figure": fig}
                print(f"Completed forecast hour {fxx}")
            except Exception as exc:
                print(f"Forecast hour {fxx} generated an exception: {exc}")

    return results

def extract_first_hour(forecast_str):
    """Extract the first number from strings like '7-15 hour ave fcst'"""
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

def utc_to_local(utc_hour, offset=-6):
    """Convert UTC time to local time (default Mountain Time)"""
    return (utc_hour + offset) % 24

# -----------------------------------------------------------------------
# Core AQM Data Functions
# -----------------------------------------------------------------------
def initialize_herbie(init_date, product="ave_8hr_o3", domain="CS", fxx=12, **kwargs):
    """Initialize a Herbie object with AQM parameters"""

    # if date is a string of YYYYMMDDHH, convert to datetime
    if isinstance(init_date, str) and ' ' in init_date:
        # This is pandas datetime format
        pass
    elif isinstance(init_date, str):
        # This is YYYYMMDDHH format
        init_date = datetime.strptime(init_date, "%Y%m%d%H")
    else:
        # This is already a datetime
        pass

    herbie_params = {
        "date": init_date,
        "model": "aqm",
        "product": product,
        "domain": domain,
        "fxx": fxx,
    }
    herbie_params.update(kwargs)

    # For 8-hour averages, ensure fxx is greater than 7
    if "8hr" in product and fxx <= 7:
        print("Warning: For 8-hour averages, fxx should be > 7. Adjusting to 8.")
        herbie_params["fxx"] = 8

    return Herbie(**herbie_params)

def download_aqm_data(H, verbose=True):
    """Download AQM data using Herbie"""
    if H.grib is None:
        print(f"No data found for {H.date} - product {H.product}")
        return None

    if verbose:
        print(f"Model: {H.model.upper()}")
        print(f"Product: {H.product} - {H.product_description}")
        print(f"Initial time: {H.date}")
        print(f"Source: {H.grib_source}")

    local_file = H.download()
    if verbose:
        print(f"Downloaded to: {local_file}")

    return local_file

def get_available_forecasts(H, sort=True):
    """Get all available forecast periods in a file"""
    inventory_df = H.inventory()

    if inventory_df.empty:
        print("No inventory data available")
        return []

    forecast_times = inventory_df["forecast_time"].unique()

    if sort:
        return sorted(forecast_times, key=extract_first_hour)
    return forecast_times

def get_forecast_for_fxx(H, target_fxx=None):
    """
    Find the appropriate forecast string based on fxx

    For 8-hour averages, treats fxx as the central time with 4 hours before and after
    """
    if target_fxx is None:
        target_fxx = H.fxx

    forecasts = get_available_forecasts(H)
    print(f"Available forecasts: {forecasts}")
    if not forecasts:
        print("No forecasts available")
        return None

    # Determine expected forecast range based on product type
    if "8hr" in H.product or "8_hour" in H.product:
        # For 8-hour, center around target_fxx (±4 hours)
        # Calculate start and end hours
        start_hr = target_fxx - 4
        end_hr = target_fxx + 4

        # Check for negative start hour
        if start_hr < 0:
            start_hr = 0
            end_hr = 8  # Maintain 8-hour window

        target_forecast = f"{start_hr}-{end_hr} hour ave fcst"

    elif "24hr" in H.product or "24_hour" in H.product:
        # For 24-hour averages, forecast range ends at target_fxx
        target_forecast = f"{target_fxx-24}-{target_fxx} hour ave fcst"
    else:
        # Default case
        target_forecast = f"{target_fxx} hour fcst"

    # Check if target exists
    if target_forecast in forecasts:
        return target_forecast

    # If not found, find the closest match
    print(f"Target forecast '{target_forecast}' not found. Looking for alternatives...")

    # Find closest matching forecast period
    closest_forecast = None
    min_diff = float('inf')

    for forecast in forecasts:
        try:
            # Parse the forecast range
            range_parts = forecast.split()[0]

            if "-" in range_parts:
                start_hr, end_hr = map(int, range_parts.split("-"))
                mid_point = (start_hr + end_hr) / 2
            else:
                # Single hour forecast
                mid_point = int(range_parts)

            # Calculate difference to target
            diff = abs(mid_point - target_fxx)

            if diff < min_diff:
                min_diff = diff
                closest_forecast = forecast

        except (ValueError, IndexError):
            continue

    if closest_forecast:
        print(f"Using closest available: {closest_forecast}")
        return closest_forecast
    else:
        # Last resort - use first available forecast
        print(f"No suitable match found. Using first available: {forecasts[0]}")
        return forecasts[0]

def load_aqm_dataset(H, forecast_hour_range=None):
    """Load an AQM dataset into xarray based on specific forecast hour range"""
    if forecast_hour_range is None:
        forecast_hour_range = get_forecast_for_fxx(H)

    if forecast_hour_range is None:
        print("No suitable forecast range found")
        return None

    try:
        # Get the data, then handle decode_timedelta in a separate step
        ds = H.xarray(forecast_hour_range)
        return ds
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return None

# -----------------------------------------------------------------------
# Visualization Functions
# -----------------------------------------------------------------------
def plot_aqm_forecast(ds, title, init_datetime, config=AQM_CONFIG):
    """Plot AQM ozone/PM2.5 forecast with enhanced visualization features"""
    # Extract configuration
    viz_config = config["viz"]
    focus_on_utah = viz_config["focus_on_utah"]
    min_threshold = viz_config["min_threshold"]
    max_cap = viz_config["max_cap"]
    contour_spacing = viz_config["contour_spacing"]
    colormap = viz_config["colormap"]

    # Create figure and axes
    fig = plt.figure(figsize=(12, 8))
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

    # Add Utah counties if focusing on Utah
    if focus_on_utah:
        ax.add_feature(cfeature.NaturalEarthFeature(
            category='cultural',
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

    # Determine data variable to plot based on product type
    if "o3" in ds.attrs.get("search", ""):
        data_var = "ozcon"
        var_label = "Ozone (ppb)"
    elif "pm25" in ds.attrs.get("search", ""):
        data_var = "pmtf"
        var_label = "PM2.5 (μg/m³)"
    else:
        # Try to determine from dataset variables
        if "ozcon" in ds:
            data_var = "ozcon"
            var_label = "Ozone (ppb)"
        elif "pmtf" in ds:
            data_var = "pmtf"
            var_label = "PM2.5 (μg/m³)"
        else:
            # Use the first data variable that's not a coordinate
            for var in ds.data_vars:
                if var not in ds.coords:
                    data_var = var
                    var_label = var
                    break

    # Process data - apply threshold and cap
    plot_data = ds[data_var].squeeze().copy()

    # Cap high values
    plot_data = plot_data.where(plot_data <= max_cap, max_cap)

    # Create a masked version for filled contours that hides values below threshold
    data_masked = plot_data.where(plot_data >= min_threshold)

    # Plot filled contours only for values above threshold
    cs_fill = ax.contourf(
        ds.longitude,
        ds.latitude,
        data_masked,
        levels=np.arange(min_threshold, max_cap+contour_spacing, contour_spacing),
        transform=ccrs.PlateCarree(),
        cmap=colormap,
        extend='max',
        zorder=6,
        alpha=0.7
    )

    # Plot contour lines for all values
    cs_lines = ax.contour(
        ds.longitude,
        ds.latitude,
        plot_data,
        levels=np.arange(min_threshold, max_cap+contour_spacing, contour_spacing),
        transform=ccrs.PlateCarree(),
        colors='black',
        linewidths=0.5,
        zorder=7
    )

    # Add contour labels
    plt.clabel(cs_lines, inline=True, fontsize=8, fmt='%d')

    # Add horizontal colorbar at the bottom
    cbar = plt.colorbar(cs_fill, orientation='horizontal', pad=0.05, aspect=40, shrink=0.8)
    cbar.set_label(f'{var_label} - Values < {min_threshold} not shown')

    # Add timestamp and time zone information
    forecast_time_info = extract_forecast_time_info(ds, init_datetime)

    if forecast_time_info:
        plt.figtext(0.01, 0.01, forecast_time_info["utc_label"], fontsize=10)
        plt.figtext(0.01, 0.03, forecast_time_info["mt_label"], fontsize=10)

    # Set title and layout
    plt.title(title, fontsize=12)
    plt.tight_layout()

    return fig, ax

def extract_forecast_time_info(ds, init_datetime):
    """Extract forecast time information for plot labels"""
    # Try to extract from search string first
    search_str = ds.attrs.get('search', '')

    if 'hour ave fcst' not in search_str and 'hour fcst' not in search_str:
        return None

    if 'hour ave fcst' in search_str:
        # Extract from patterns like "7-15 hour ave fcst"
        hour_parts = search_str.split('hour ave fcst')[0].strip().split()
        if hour_parts:
            forecast_range = hour_parts[-1]
            try:
                start_hr, end_hr = map(int, forecast_range.split('-'))

                # Calculate UTC time range
                utc_start = (init_datetime.hour + start_hr) % 24
                utc_end = (init_datetime.hour + end_hr) % 24

                # Calculate Mountain Time (UTC-6 for standard time, adjust for DST as needed)
                mt_offset = -6
                mt_start = utc_to_local(utc_start, mt_offset)
                mt_end = utc_to_local(utc_end, mt_offset)

                return {
                    "utc_label": f"UTC: {utc_start:02d}:00-{utc_end:02d}:00",
                    "mt_label": f"MT: {mt_start:02d}:00-{mt_end:02d}:00"
                }
            except (ValueError, IndexError):
                pass

    return None

def generate_output_filename(H, init_datetime, valid_time, config=AQM_CONFIG):
    """Generate standardized output filename for plots"""
    output_dir = Path(config.get("output_dir", "./"))

    product_type = "o3" if "o3" in H.product else "pm25"
    averaging = ""

    if "1hr" in H.product:
        averaging = "1h"
    elif "8hr" in H.product:
        averaging = "8h"
    elif "24hr" in H.product:
        averaging = "24h"

    bias_corrected = "_bc" if "_bc" in H.product else ""

    domain_focus = "_utah" if config["viz"]["focus_on_utah"] else ""

    filename = (
        f"aqm_{init_datetime:%Y%m%d%H}Z_"
        f"{valid_time:%Y%m%d%H}Z"
        f"{domain_focus}_{product_type}{averaging}{bias_corrected}.png"
    )

    return output_dir / filename

# -----------------------------------------------------------------------
# Batch Processing Functions
# -----------------------------------------------------------------------
def process_single_forecast(init_date, fxx, product="ave_8hr_o3", domain="CS",
                            config=AQM_CONFIG, save=True, show=True):
    """Process and visualize a single AQM forecast"""
    # Initialize Herbie
    H = initialize_herbie(init_date, product, domain, fxx)

    # Download data if needed
    local_file = download_aqm_data(H)
    if local_file is None:
        return None, None

    # Create a new Herbie instance with the local file path
    H = initialize_herbie(init_date, product, domain, fxx, file_path=str(local_file))

    # Print all available products in the xarray
    # print("Available products in xarray:")
    # print(H.product_description)
    # print(H.product)
    # print(H.inventory)

    # Try to get the forecast range using improved function
    try:
        forecast_range = get_forecast_for_fxx(H)
        print(f"Forecast range: {forecast_range}")
        ds = load_aqm_dataset(H, forecast_range)
    except Exception as e:
        # If inventory fails, try loading the entire file
        print(f"Inventory error: {e}. Loading entire file...")
        ds = H.xarray(":")
        # Try to determine the forecast range from dataset attributes
        if "search" in ds.attrs:
            forecast_range = ds.attrs["search"]
        else:
            forecast_range = f"{fxx} hour fcst"

    if ds is None:
        print(f"Failed to load dataset for {init_date}, fxx={fxx}")
        return None, None

    # Extract time information
    init_datetime = H.date

    # Calculate valid time from forecast range
    try:
        range_parts = forecast_range.split()[0]
        if "-" in range_parts:
            start_hr, end_hr = map(int, range_parts.split("-"))

            # For 8-hour products, calculate the valid time as mid-point
            if "8hr" in product or "8_hour" in product:
                mid_point = (start_hr + end_hr) / 2
                valid_time = init_datetime + pd.Timedelta(hours=mid_point)
            else:
                # For other products, use end time
                valid_time = init_datetime + pd.Timedelta(hours=end_hr)
        else:
            valid_time = init_datetime + pd.Timedelta(hours=int(range_parts))
    except (ValueError, IndexError):
        # Fallback to fxx
        valid_time = init_datetime + pd.Timedelta(hours=fxx)

    # Create title
    product_desc = ("Ozone" if "o3" in product.lower() else
                    "PM2.5" if "pm25" in product.lower() else
                    product.upper().replace('_', ' '))

    # Include averaging period in title
    if "1hr" in product or "1_hour" in product:
        avg_type = "1-hr Avg"
    elif "8hr" in product or "8_hour" in product:
        avg_type = "8-hr Avg"
    elif "24hr" in product or "24_hour" in product:
        avg_type = "24-hr Avg"
    else:
        avg_type = ""

    title = (f"AQM {product_desc} {avg_type} - {forecast_range}\n"
             f"Init: {init_datetime:%Y-%m-%d %HZ}, Valid: {valid_time:%Y-%m-%d %HZ}")

    # Plot the data
    fig, ax = plot_aqm_forecast(ds, title, init_datetime, config)

    # Save the plot if requested
    if save:
        output_path = generate_output_filename(H, init_datetime, valid_time, config)
        plt.savefig(output_path, dpi=config["viz"]["dpi"])
        print(f"Plot saved as {output_path}")

    # Show the plot if requested, otherwise close it
    if show:
        plt.show()
    else:
        plt.close(fig)

    return ds, fig

def process_forecast_range(init_date, product="ave_8hr_o3", domain="CS",
                           config=AQM_CONFIG):
    """Process and visualize multiple forecast lead times"""
    results = {}

    fxx_range = config["forecast"]["fxx_range"]

    for fxx in fxx_range:
        print(f"\nProcessing forecast hour {fxx}")
        ds, fig = process_single_forecast(
            init_date, fxx, product, domain, config, save=True, show=True
        )
        results[fxx] = {"dataset": ds, "figure": fig}

    return results

def process_init_range(init_dates, fxx, product="ave_8hr_o3", domain="CS",
                      config=AQM_CONFIG):
    """Process multiple initialization dates for the same forecast lead time"""
    results = {}
    max_workers = os.cpu_count() - 1

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for init_date in init_dates:
            future = executor.submit(
                process_single_forecast,
                init_date, fxx, product, domain, config, True, False
            )
            futures.append((future, init_date))

        # Process results as they complete
        for future, init_date in futures:
            try:
                ds, fig = future.result()
                results[init_date] = {"dataset": ds, "figure": fig}
                print(f"Completed initialization date {init_date}")
            except Exception as exc:
                print(f"Error processing init date {init_date}: {exc}")

    return results

def create_valid_time_comparison(valid_date, lookback_days=3, products=None,
                                domains=None, config=AQM_CONFIG):
    """Compare multiple forecasts valid at the same time from different initialization times"""
    if products is None:
        products = ["ave_8hr_o3"]

    if domains is None:
        domains = ["CS"]

    # Convert valid_date to datetime if it's a string
    if isinstance(valid_date, str):
        valid_date = pd.to_datetime(valid_date)

    # Generate initialization times (going back lookback_days)
    init_times = []
    for day in range(lookback_days, -1, -1):
        for hour in [6, 12]:  # AQM runs at 06Z and 12Z
            init_datetime = valid_date - timedelta(days=day, hours=valid_date.hour - hour)
            # Only include initializations before the valid time
            if init_datetime < valid_date:
                init_times.append(init_datetime)

    results = {}
    max_workers = os.cpu_count() - 1

    for product in products:
        for domain in domains:
            product_results = {}

            # Create a list of tasks to process in parallel
            tasks = []
            for init_time in init_times:
                # Calculate required forecast lead time
                fxx = int((valid_date - init_time).total_seconds() / 3600)

                # Skip if fxx > 72 (AQM forecast limit)
                if fxx > 72:
                    continue

                tasks.append((init_time, fxx, product, domain))

            # Process tasks in parallel
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for init_time, fxx, prod, dom in tasks:
                    future = executor.submit(
                        process_single_forecast,
                        init_time, fxx, prod, dom, config, True, False
                    )
                    futures.append((future, init_time, fxx))

                # Process results as they complete
                for future, init_time, fxx in futures:
                    try:
                        ds, fig = future.result()
                        init_key = f"{init_time:%Y%m%d_%HZ}_fxx{fxx}"
                        product_results[init_key] = {"dataset": ds, "figure": fig}
                        print(f"Completed {product} for {domain}, init: {init_time}, fxx: {fxx}")
                    except Exception as exc:
                        print(f"Error processing init: {init_time}, fxx: {fxx}: {exc}")

            results[f"{product}_{domain}"] = product_results

    return results

# -----------------------------------------------------------------------
# Main Execution Functions
# -----------------------------------------------------------------------
def run_demo(config=None, use_parallel=True):
    """Run a simple demonstration"""
    if config is None:
        config = AQM_CONFIG

    print("Running AQM Model Demo")

    # Create output directory
    setup_output_directory(config["output_dir"])

    # Get parameters from config
    init_date = config["dates"]["init_date"]
    fxx = config["forecast"]["fxx"]
    product = config["forecast"]["product"]
    domain = config["forecast"]["domain"]
    fxx_range = config["forecast"]["fxx_range"]

    # Process a single forecast
    # print(f"\n===== Processing Single Forecast (Init: {init_date}, FXX: {fxx}) =====")
    # ds, fig = process_single_forecast(
    #     init_date, fxx=fxx, product=product,
    #     config=config, save=True, show=True
    # )

    # Process a range of forecast hours (in parallel if requested)
    print(f"\n===== Processing Forecast Hour Range {fxx_range} =====")
    if use_parallel:
        fxx_results = process_forecast_range_parallel(
            init_date, product=product,
            config=config
        )
    else:
        fxx_results = process_forecast_range(
            init_date, product=product,
            config=config
        )

    print("\nDemo completed successfully!")
    return

def compare_products(init_date, fxx=13, domain="CS", config=AQM_CONFIG):
    """Compare different AQM products for the same initialization time and lead time"""
    products = [
        "ave_1hr_o3", "ave_1hr_o3_bc",
        "ave_8hr_o3", "ave_8hr_o3_bc",
        "max_1hr_o3", "max_1hr_o3_bc",
        "max_8hr_o3", "max_8hr_o3_bc"
    ]

    results = {}
    max_workers = os.cpu_count() - 1

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for product in products:
            future = executor.submit(
                process_single_forecast,
                init_date, fxx, product, domain, config, True, False
            )
            futures.append((future, product))

        # Process results as they complete
        for future, product in futures:
            try:
                ds, fig = future.result()
                results[product] = {"dataset": ds, "figure": fig}
                print(f"Completed processing {product}")
            except Exception as exc:
                print(f"Error processing {product}: {exc}")

    return results

if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='AQM Data Exploration Tool')

    # Create mode groups to prevent conflicting options
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--demo', action='store_true', help='Run demo mode')
    mode_group.add_argument('--compare_products', action='store_true',
                          help='Compare all products for same init date/fxx')
    mode_group.add_argument('--valid_time', type=str,
                          help='Compare forecasts by valid time (YYYY-MM-DD HH:MM)')
    mode_group.add_argument('--process_range', action='store_true',
                          help='Process a range of forecast hours')

    # Basic parameters
    parser.add_argument('--init_date', type=str, help='Initialization date (YYYY-MM-DD HH:MM or YYYYMMDDHH)')
    parser.add_argument('--fxx', type=int, help='Forecast lead time')
    parser.add_argument('--product', type=str, help='AQM product')
    parser.add_argument('--domain', type=str, help='AQM domain')
    parser.add_argument('--output_dir', type=str, help='Output directory')

    # Advanced options
    parser.add_argument('--lookback_days', type=int, default=3,
                      help='Days to look back for valid_time comparisons')
    parser.add_argument('--fxx_min', type=int, help='Minimum forecast hour in range')
    parser.add_argument('--fxx_max', type=int, help='Maximum forecast hour in range')
    parser.add_argument('--fxx_step', type=int, default=1, help='Step between forecast hours')
    parser.add_argument('--parallel', action='store_true', default=True,
                      help='Use parallel processing')
    parser.add_argument('--no-parallel', dest='parallel', action='store_false',
                      help='Disable parallel processing')

    args = parser.parse_args()

    # Create a working copy of the configuration
    config = AQM_CONFIG.copy()

    # Update configuration based on command line arguments
    if args.output_dir:
        config["output_dir"] = args.output_dir

    # Format the init_date properly
    if args.init_date:
        # Check if init_date is in YYYYMMDDHH format
        if len(args.init_date) == 10 and args.init_date.isdigit():
            formatted_date = f"{args.init_date[:4]}-{args.init_date[4:6]}-{args.init_date[6:8]} {args.init_date[8:10]}:00"
            config["dates"]["init_date"] = formatted_date
        else:
            config["dates"]["init_date"] = args.init_date

    if args.fxx:
        config["forecast"]["fxx"] = args.fxx
    if args.product:
        config["forecast"]["product"] = args.product
    if args.domain:
        config["forecast"]["domain"] = args.domain
    if args.lookback_days:
        config["dates"]["lookback_days"] = args.lookback_days

    # Update forecast range if specified
    if args.fxx_min is not None or args.fxx_max is not None:
        fxx_min = args.fxx_min if args.fxx_min is not None else 8
        fxx_max = args.fxx_max if args.fxx_max is not None else config["forecast"]["fxx"]
        config["forecast"]["fxx_range"] = list(range(fxx_min, fxx_max + 1, args.fxx_step))

    # Ensure fxx_range has multiple values when process_range is specified
    if args.process_range and len(config["forecast"]["fxx_range"]) <= 1:
        # Default range from 8 to current fxx
        config["forecast"]["fxx_range"] = list(range(8, config["forecast"]["fxx"] + 1, args.fxx_step))

    # Ensure output directory exists
    setup_output_directory(config["output_dir"])

    # Execute the appropriate function based on mode
    if args.demo:
        # Run demo mode
        run_demo(config, use_parallel=args.parallel)

    elif args.compare_products:
        # Compare all products for the same init_date and fxx
        print(f"Comparing all products for {config['dates']['init_date']}, fxx={config['forecast']['fxx']}")
        compare_products(
            config["dates"]["init_date"],
            config["forecast"]["fxx"],
            config["forecast"]["domain"],
            config
        )

    elif args.valid_time:
        # Compare forecasts from different init times for the same valid time
        print(f"Comparing forecasts valid at {args.valid_time} from the past {args.lookback_days} days")
        create_valid_time_comparison(
            args.valid_time,
            lookback_days=args.lookback_days,
            products=[config["forecast"]["product"]],
            domains=[config["forecast"]["domain"]],
            config=config
        )

    elif args.process_range:
        # Process a range of forecast hours
        print(f"Processing forecast range {config['forecast']['fxx_range']} for {config['dates']['init_date']}")
        if args.parallel:
            process_forecast_range_parallel(
                config["dates"]["init_date"],
                product=config["forecast"]["product"],
                domain=config["forecast"]["domain"],
                config=config
            )
        else:
            process_forecast_range(
                config["dates"]["init_date"],
                product=config["forecast"]["product"],
                domain=config["forecast"]["domain"],
                config=config
            )

    elif args.init_date or any([args.fxx, args.product, args.domain, args.fxx_min, args.fxx_max]):
        # Process a single forecast with provided parameters
        print(f"Processing single forecast: {config['dates']['init_date']}, fxx={config['forecast']['fxx']}")
        process_single_forecast(
            config["dates"]["init_date"],
            config["forecast"]["fxx"],
            config["forecast"]["product"],
            config["forecast"]["domain"],
            config,
            save=True,
            show=True
        )

    else:
        # No arguments provided, run demo with current settings
        print("No arguments provided. Running default demo.")
        run_demo(config, use_parallel=args.parallel)