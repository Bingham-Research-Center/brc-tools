#!/usr/bin/env python
# Simple AQM Model Explorer for Herbie
# Author: Seth Lyman
# Date: April 2025

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr

sys.path.append('/Users/johnlawson/PycharmProjects/Herbie/herbie/models/aqm.py')
from herbie import Herbie

# =======================================================================
# Configuration settings - Edit these parameters for your specific needs
# =======================================================================

# Basic settings
CONFIG = {
    # Date and time settings
    "init_date": "2025-01-31 12:00",   # Initial model run date/time
    "fxx": 14,                         # Forecast hour
    
    # Product settings
    "product": "ave_8hr_o3",           # Default product to download and visualize
    "domain": "CS",                    # Domain (CS=CONUS, AK=Alaska, HI=Hawaii)
    
    # Visualization settings
    "min_threshold_contour": 30,               # Min value to display (ppb)
    "min_threshold_fill": 50,               # Min value to display (ppb)
    "max_cap": 100,                    # Max value to display (ppb)
    "focus_on_utah": True,             # Whether to zoom in on Utah
    "dpi": 250,                        # Output image resolution
    "contour_spacing": 2,              # Spacing between contour lines (ppb)
    "colormap": "plasma_r",            # Colormap for filled contours
    
    # Output settings
    "output_dir": Path(__file__).parent / "aqm_figures",  # Output directory
    "save_figures": True,              # Whether to save figures
    "show_figures": True,              # Whether to show figures on screen
}

# =======================================================================
# Helper Functions
# =======================================================================

def setup_output_directory(output_dir):
    """Create output directory if it doesn't exist"""
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def utc_to_local(utc_hour, offset=-6):
    """Convert UTC time to local time (default Mountain Time)"""
    return (utc_hour + offset) % 24

def format_forecast_time(forecast_str):
    """Format forecast time string for display"""
    if 'hour ave fcst' in forecast_str:
        # Extract from patterns like "7-15 hour ave fcst"
        hour_parts = forecast_str.split('hour ave fcst')[0].strip().split()
        if hour_parts:
            forecast_range = hour_parts[-1]
            return forecast_range
    elif 'hour fcst' in forecast_str:
        # Extract from patterns like "12 hour fcst"
        hour_parts = forecast_str.split('hour fcst')[0].strip().split()
        if hour_parts:
            return hour_parts[-1]
    return forecast_str

def generate_filename(H, valid_time, config):
    """Generate standardized output filename for plots"""
    init_datetime = H.date

    # Determine product type
    if "o3" in H.product.lower():
        product_type = "o3"
    elif "pm25" in H.product.lower() or "pmtf" in H.product.lower():
        product_type = "pm25"
    else:
        product_type = "unknown"

    # Determine averaging period
    averaging = ""
    if "1hr" in H.product:
        averaging = "1h"
    elif "8hr" in H.product:
        averaging = "8h"

    # Determine if max or avg product
    if "max" in H.product:
        product_modifier = "_max"
    else:
        product_modifier = "_avg"

    # Check if bias-corrected
    bias_corrected = "_bc" if "_bc" in H.product else ""

    # Add Utah focus indicator
    domain_focus = "_utah" if config["focus_on_utah"] else ""

    filename = (
        f"aqm_{init_datetime:%Y%m%d%H}Z_"
        f"{valid_time:%Y%m%d%H}Z"
        f"{domain_focus}_{product_type}{averaging}{product_modifier}{bias_corrected}.png"
    )

    return config["output_dir"] / filename

# =======================================================================
# Core AQM Data Functions
# =======================================================================

def initialize_herbie(init_date, product, domain, fxx):
    """Initialize a Herbie object with AQM parameters"""
    
    # Convert string date to datetime if needed
    if isinstance(init_date, str) and ' ' in init_date:
        # This is pandas datetime format
        pass
    elif isinstance(init_date, str):
        # This is YYYYMMDDHH format
        init_date = datetime.strptime(init_date, "%Y%m%d%H")
    
    # For 8-hour averages, ensure fxx is greater than 7
    if "8hr" in product and fxx <= 7:
        print("Warning: For 8-hour averages, fxx should be > 7. Adjusting to 8.")
        fxx = 8
    
    herbie_params = {
        "date": init_date,
        "model": "aqm",
        "product": product,
        "domain": domain,
        "fxx": fxx,
    }
    
    return Herbie(**herbie_params)

def get_available_forecasts(H):
    """Get all available forecast time periods in the file"""
    inventory_df = H.inventory()
    
    if inventory_df.empty:
        print("No inventory data available")
        return []
    
    return inventory_df["forecast_time"].unique()

def find_best_forecast_for_fxx(H, target_fxx):
    """Find the appropriate forecast for the given lead time"""
    try:
        forecasts = get_available_forecasts(H)
        if not forecasts:
            print("No forecasts available")
            return None
    except Exception as e:
        print(f"Error accessing forecasts: {e}")
        return None

    print(f"Available forecasts: {forecasts}")

    # Determine expected format based on product type
    is_avg = "max" not in H.product

    # Construct likely forecast strings
    target_formats = []

    if "8hr" in H.product:
        # For 8-hour products, center around target_fxx
        start_hr = max(0, target_fxx - 4)
        end_hr = start_hr + 8

        if is_avg:
            target_formats.append(f"{start_hr}-{end_hr} hour ave fcst")
        target_formats.append(f"{start_hr}-{end_hr} hour fcst")

    elif "1hr" in H.product:
        if is_avg:
            target_formats.append(f"{target_fxx-1}-{target_fxx} hour ave fcst")
        target_formats.append(f"{target_fxx} hour fcst")

    else:
        # Generic case
        target_formats.append(f"{target_fxx} hour fcst")

    # Try each target format
    for fmt in target_formats:
        if fmt in forecasts:
            print(f"Using forecast: {fmt}")
            return fmt

    # If not found, find closest match based on middle of range
    closest = None
    min_diff = float('inf')

    for forecast in forecasts:
        try:
            time_part = forecast.split("hour")[0].strip()

            if '-' in time_part:
                start, end = map(int, time_part.split('-'))
                mid = (start + end) / 2
            else:
                mid = float(time_part)

            diff = abs(mid - target_fxx)

            if diff < min_diff:
                min_diff = diff
                closest = forecast
        except (ValueError, IndexError):
            continue

    if closest:
        print(f"Using closest available: {closest}")
        return closest

    # Last resort
    print(f"No suitable match found. Using first available: {forecasts[0]}")
    return forecasts[0]

def load_aqm_dataset(H, forecast_hour_range=None):
    """Load an AQM dataset with minimal complexity"""
    try:
        # Convert path to string to avoid PosixPath errors
        file_path = str(H.grib) if hasattr(H, 'grib') else None

        if not file_path:
            print("No file path available")
            return None

        # Try direct loading with xarray
        try:
            # For max products, we need to specify a filter_by_keys to handle properly
            if "max" in H.product:
                ds = xr.open_dataset(
                    file_path,
                    engine='cfgrib',
                    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'surface'}}
                )
            else:
                ds = xr.open_dataset(file_path, engine='cfgrib')

            print(f"Loaded file directly")
            return ds
        except Exception as e:
            print(f"Direct loading failed: {e}")

            # Try with different filter options for max products
            if "max" in H.product:
                try:
                    # Different filter approach for max products
                    ds = xr.open_dataset(
                        file_path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {'stepType': 'max'}}
                    )
                    print(f"Loaded max product with stepType filter")
                    return ds
                except Exception as e2:
                    print(f"Max product loading failed: {e2}")

            # Last resort: Try Herbie's method with explicit file path
            try:
                ds = H.xarray(":", file_path=file_path)
                return ds
            except Exception as e3:
                print(f"Herbie xarray method failed: {e3}")
                return None
    except Exception as e:
        print(f"Failed to load: {e}")
        return None

# =======================================================================
# Visualization Functions
# =======================================================================

def plot_aqm_forecast(ds, title, init_datetime, config):
    """Plot AQM ozone/PM2.5 forecast"""
    # Extract configuration
    focus_on_utah = config["focus_on_utah"]
    min_threshold_contour = config["min_threshold_contour"]
    min_threshold_fill = config["min_threshold_fill"]
    max_cap = config["max_cap"]
    contour_spacing = config["contour_spacing"]
    colormap = config["colormap"]

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

    # Add map features
    ax.add_feature(cfeature.LAND, edgecolor='black', facecolor='lightgray', zorder=0)
    ax.add_feature(cfeature.OCEAN, edgecolor='black', facecolor='lightblue', zorder=0)
    ax.add_feature(cfeature.LAKES, edgecolor='black', facecolor='lightblue', zorder=1)
    ax.add_feature(cfeature.STATES, linewidth=0.5, edgecolor='gray', zorder=2)
    ax.add_feature(cfeature.BORDERS, linewidth=0.7, zorder=3)

    # Add Utah counties if focusing on Utah
    if focus_on_utah:
        # Add county boundaries
        counties = cfeature.NaturalEarthFeature(
            category='cultural',
            name='admin_2_counties',
            scale='10m',
            facecolor='none'
        )
        ax.add_feature(counties, edgecolor='gray', linewidth=0.3, zorder=3)

    ax.coastlines(resolution='10m', zorder=5)

    # Get available data variables
    data_vars = list(ds.data_vars)
    print(f"Available data variables: {data_vars}")

    # First, try to determine from search attributes
    if "o3" in ds.attrs.get("search", ""):
        data_var = "ozcon"
        var_label = "Ozone (ppb)"
    elif "pm25" in ds.attrs.get("search", ""):
        data_var = "pmtf"
        var_label = "PM2.5 (μg/m³)"
    # Then check if standard variable names exist in the dataset
    elif "ozcon" in data_vars:
        data_var = "ozcon"
        var_label = "Ozone (ppb)"
    elif "pmtf" in data_vars:
        data_var = "pmtf"
        var_label = "PM2.5 (μg/m³)"
    # Finally, use the first non-coordinate data variable
    elif data_vars:
        for var in data_vars:
            if var not in ds.coords:
                data_var = var
                var_label = var
                break

    # Process data - apply threshold and cap
    plot_data = ds[data_var]

    # Handle 3D data - take the first step if 3D
    if plot_data.ndim > 2:
        print(f"Found {plot_data.ndim}D data, reducing to 2D for plotting")
        # Check if there's a time dimension
        if 'time' in plot_data.dims:
            plot_data = plot_data.isel(time=0)
        # If there's a step dimension
        elif 'step' in plot_data.dims:
            plot_data = plot_data.isel(step=0)
        # Default to first dim if others aren't recognized
        else:
            plot_data = plot_data.isel({plot_data.dims[0]: 0})

    # Ensure we have a 2D array
    plot_data = plot_data.squeeze()

    if plot_data.ndim != 2:
        print(f"ERROR: Could not reduce to 2D. Dimensions: {plot_data.dims}")
        return fig, ax

    # Create separate data for contours and filled contours
    # For contours (lines)
    contour_data = plot_data.copy()
    contour_data = contour_data.where(contour_data <= max_cap, max_cap)

    # For filled contours
    fill_data = plot_data.copy()
    fill_data = fill_data.where(fill_data <= max_cap, max_cap)
    fill_data = fill_data.where(fill_data >= min_threshold_fill)

    # Plot filled contours only for values above threshold
    cs_fill = ax.contourf(
        ds.longitude,
        ds.latitude,
        fill_data,
        levels=np.arange(min_threshold_fill, max_cap+contour_spacing, contour_spacing),
        transform=ccrs.PlateCarree(),
        cmap=colormap,
        extend='max',
        zorder=6,
        alpha=0.5,
    )

    # Plot contour lines for all values
    cs_lines = ax.contour(
        ds.longitude,
        ds.latitude,
        contour_data,
        levels=np.arange(min_threshold_contour, max_cap+contour_spacing, contour_spacing),
        transform=ccrs.PlateCarree(),
        colors='black',
        linewidths=0.5,
        zorder=7
    )

    # Add contour labels
    plt.clabel(cs_lines, inline=True, fontsize=8, fmt='%d')

    # Add horizontal colorbar at the bottom
    cbar = plt.colorbar(cs_fill, orientation='horizontal', pad=0.05, aspect=40, shrink=0.8)
    cbar.set_label(f'{var_label} - Filled values ≥ {min_threshold_fill}, Lines ≥ {min_threshold_contour}')

    # Set title and layout
    plt.title(title, fontsize=12)
    plt.tight_layout()

    return fig, ax

# =======================================================================
# Main Function to Process AQM Data
# =======================================================================

def process_aqm_data(config):
    """Process and visualize AQM data based on configuration"""
    # Setup output directory
    setup_output_directory(config["output_dir"])

    # Initialize Herbie
    H = initialize_herbie(
        config["init_date"],
        config["product"],
        config["domain"],
        config["fxx"]
    )

    print(f"\nProcessing AQM data:")
    print(f"Model: {H.model.upper()}")
    print(f"Product: {H.product}")
    print(f"Initial time: {H.date}")
    print(f"Forecast hour: {H.fxx}")

    # Download data
    if H.grib is None:
        print(f"No data found for {H.date} - product {H.product}")
        return None, None

    print(f"Source: {H.grib_source}")
    local_file = H.download()
    print(f"Downloaded to: {local_file}")

    print(H.inventory())

    # Find appropriate forecast range
    forecast_range = find_best_forecast_for_fxx(H, H.fxx)

    # Load dataset
    ds = load_aqm_dataset(H, forecast_range)
    if ds is None:
        print(f"Failed to load dataset")
        return None, None

    # Calculate valid time from forecast range
    init_datetime = H.date
    valid_time = init_datetime + timedelta(hours=H.fxx)

    # Create title with proper product description
    # Determine pollutant type (O3 or PM2.5)
    if "o3" in H.product.lower():
        pollutant = "Ozone"
    elif "pm25" in H.product.lower():
        pollutant = "PM2.5"
    else:
        pollutant = H.product.upper().replace('_', ' ')

    # Determine if maximum or average
    is_max = "max" in H.product.lower()
    stat_type = "Maximum" if is_max else "Average"

    # Determine time period (1-hr, 8-hr)
    if "1hr" in H.product:
        time_period = "1-Hour"
    elif "8hr" in H.product:
        time_period = "8-Hour"
    # elif "24hr" in H.product:
    #     time_period = "24-Hour"
    else:
        time_period = ""

    # Check if bias-corrected
    bias_corrected = "Bias-Corrected " if "_bc" in H.product else ""

    # Construct title
    title = (f"AQM {bias_corrected}{stat_type} {time_period} {pollutant}\n"
             f"Init: {init_datetime:%Y-%m-%d %HZ}, Valid: {valid_time:%Y-%m-%d %HZ}")

    # Plot the data
    fig, ax = plot_aqm_forecast(ds, title, init_datetime, config)

    # Save the plot if requested
    if config["save_figures"]:
        output_path = generate_filename(H, valid_time, config)
        plt.savefig(output_path, dpi=config["dpi"])
        print(f"Plot saved as {output_path}")

    # Show the plot if requested
    if config["show_figures"]:
        plt.show()
    else:
        plt.close(fig)

    return ds, fig

def process_multiple_products(init_date, fxx, domain="CS", products=None, config=None):
    """Process multiple AQM products for the same initialization time and lead time"""
    if config is None:
        config = CONFIG.copy()

    if products is None:
        products = [
            "ave_1hr_o3", "ave_1hr_o3_bc",
            "ave_8hr_o3", "ave_8hr_o3_bc",
            "max_1hr_o3", "max_1hr_o3_bc",
            "max_8hr_o3", "max_8hr_o3_bc"
        ]

    results = {}

    # Update config with provided parameters
    config["init_date"] = init_date
    config["fxx"] = fxx
    config["domain"] = domain

    # Process each product
    for product in products:
        print(f"\n===== Processing {product} =====")
        config_copy = config.copy()
        config_copy["product"] = product

        try:
            ds, fig = process_aqm_data(config_copy)
            results[product] = {"dataset": ds, "figure": fig}
        except Exception as e:
            print(f"Error processing {product}: {e}")
            results[product] = {"dataset": None, "figure": None}

    return results

# =======================================================================
# Main Execution
# =======================================================================

if __name__ == "__main__":
    # Process a single forecast with current configuration
    # ds, fig = process_aqm_data(CONFIG)

    init_date = CONFIG["init_date"]
    fxx = CONFIG["fxx"]

    print(f"Processing all products for init_date={init_date}, fxx={fxx}")
    results = process_multiple_products(init_date, fxx)