# Demonstration script for using Herbie with the AQM model
import os
import sys
import pytz
import pathlib
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import cfgrib
from herbie import Herbie # Assuming Herbie is installed in your environment

# --- Configuration ---

# Get the project root directory (assuming script is in a subdirectory)
# Adjust number of parents if script location differs
try:
    # Assumes script is run as a file
    project_root = pathlib.Path(__file__).parent
except NameError:
    # Fallback for interactive environments (like Jupyter)
    project_root = pathlib.Path('../aqm').resolve()

# Create output directory relative to the project root
OUTPUT_DIR = project_root / "test_figs"
os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"Output directory set to: {OUTPUT_DIR}")

# --- Font Setup ---
# Set font preferences globally
# Ensure these fonts are available on your system for Matplotlib to find
try:
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Helvetica', 'Arial', 'Fira Sans', 'Nimbus Sans']
    print("Font preferences set to: Helvetica, Arial, Fira Sans, Nimbus Sans (sans-serif fallback)")
except Exception as e:
    print(f"Warning: Could not set all font preferences. Matplotlib defaults may apply. Error: {e}")


# --- Helper Functions ---

def extract_first_hour(forecast_str):
    """Extract the first number from strings like '7-15 hour ave fcst' for sorting."""
    if not isinstance(forecast_str, str):
        return 999 # Handle non-string cases
    parts = forecast_str.split()
    if not parts:
        return 999

    hour_range = parts[0]
    if '-' in hour_range:
        try:
            first_hour = int(hour_range.split('-')[0])
            return first_hour
        except (ValueError, IndexError):
            return 999
    return 999

# --- Core Functions ---

def setup_herbie(base_herbie_params):
    """Initializes Herbie, downloads data if needed, and returns the Herbie object."""
    print(f"\n--- Setting up Herbie for Date: {base_herbie_params.get('date', 'Not specified')} ---")
    H = Herbie(**base_herbie_params)
    print(f"Model: {H.model.upper()}")
    print(f"Product: {H.product} ({H.product_description})")
    print(f"Initialization Time: {H.date}")
    print(f"Source URL: {H.grib_source}")
    print(f"Local GRIB file path (initially): {H.grib}")

    # Attempt to download the GRIB2 file. Herbie handles existing files.
    # `download()` returns the local path or None if it fails/already exists but path unknown.
    local_file = H.download() # Let Herbie manage finding/downloading

    if H.grib: # Check if Herbie has a path to the grib file after download attempt
        print(f"Confirmed local GRIB file: {H.grib}")
        # Optional: Re-initialize Herbie explicitly with the confirmed path
        # H = Herbie(**base_herbie_params, file_path=str(H.grib))
    elif local_file: # If download returned a path but H.grib wasn't updated
        print(f"Downloaded to/found at: {local_file}")
        H = Herbie(**base_herbie_params, file_path=str(local_file)) # Ensure H uses the specific file
    else:
        # This case might occur if download fails and file wasn't found initially
        print("Warning: Could not confirm local GRIB file path after download attempt.")
        return None
    return H


def plot_ozone_forecast(ds, title, base_herbie_params, output_fpath,
                        focus_on_utah=True, min_threshold=50, max_cap=100):
    """
    Plots AQM ozone forecast using Cartopy.

    Parameters are the same as before. Requires Cartopy installed.
    """
    print(f"Generating plot: {output_fpath.name}")
    fig = plt.figure(figsize=(10, 8))

    # Ensure necessary CRS and features are available
    map_proj = ccrs.Mercator(central_longitude=-95)
    data_proj = ccrs.PlateCarree()
    ax = plt.axes(projection=map_proj)

    # Set map extent
    if focus_on_utah:
        # Utah-focused extent: [west, east, south, north]
        ax.set_extent([-112.15, -108.6, 40.0, 41.65], crs=data_proj)
        print("Focusing map extent on Utah.")
    else:
        # North America extent
        ax.set_extent([-130, -65, 25, 50], crs=data_proj)
        print("Using default North America map extent.")

    # Add map features with controlled zorder
    ax.add_feature(cfeature.LAND.with_scale('10m'), edgecolor='black', facecolor='#F0F0F0', zorder=0) # Light grey land
    ax.add_feature(cfeature.OCEAN.with_scale('10m'), edgecolor='black', facecolor='#D6EAF8', zorder=0) # Light blue ocean
    ax.add_feature(cfeature.LAKES.with_scale('10m'), edgecolor='black', facecolor='#D6EAF8', zorder=1) # Light blue lakes
    ax.add_feature(cfeature.STATES.with_scale('10m'), linewidth=0.5, edgecolor='dimgray', zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale('10m'), linewidth=0.7, edgecolor='black', zorder=3)

    if focus_on_utah:
        # Add county boundaries if focusing on Utah
        counties = cfeature.NaturalEarthFeature(
            category='cultural', name='admin_2_counties', scale='10m', facecolor='none'
        )
        ax.add_feature(counties, edgecolor='darkgray', linewidth=0.3, zorder=3)
        print("Added county boundaries.")

    ax.coastlines(resolution='10m', color='black', linewidth=0.8, zorder=4)

    # --- Data Processing and Plotting ---
    try:
        ozone_data = ds["ozcon"].squeeze().copy() # Ensure 'ozcon' variable exists
        lon = ds["longitude"]
        lat = ds["latitude"]
        print(f"Ozone data range (before capping/masking): {ozone_data.min().item():.2f} - {ozone_data.max().item():.2f} ppb")
    except KeyError:
        print(f"Error: 'ozcon' variable not found in the dataset for title: '{title}'. Cannot plot.")
        plt.close(fig)
        return None, None
    except Exception as e:
        print(f"Error accessing data (ozcon/latitude/longitude) from dataset: {e}")
        plt.close(fig)
        return None, None

    ozone_data_capped = ozone_data.where(ozone_data <= max_cap, max_cap) # Cap high values first
    ozone_masked = ozone_data_capped.where(ozone_data_capped >= min_threshold) # Mask low values

    # Plot filled contours (masked data)
    cs_sp = 2 # Contour spacing
    levels_fill = np.arange(min_threshold, max_cap + cs_sp, cs_sp)

    if len(levels_fill) > 1 and np.any(ozone_masked.notnull()):
        print(f"Plotting filled contours from {min_threshold} to {max_cap} ppb.")
        cs_fill = ax.contourf(
            lon, lat, ozone_masked,
            levels=levels_fill, transform=data_proj,
            cmap='plasma_r', extend='max', zorder=5, alpha=0.65 # Slightly adjusted alpha
        )
        # Add horizontal colorbar at the bottom
        cbar = plt.colorbar(cs_fill, orientation='horizontal', pad=0.05, aspect=40, shrink=0.8)
        cbar.set_label(f'8-hr Avg Ozone (ppb) - Values < {min_threshold} ppb transparent')
    else:
        print(f"Note: No data to plot with filled contours between {min_threshold} and {max_cap} ppb.")

    # Plot contour lines (using capped data for consistency)
    levels_lines = np.arange(30, max_cap + cs_sp, cs_sp*2) # Wider spacing for lines
    print("Plotting contour lines.")
    cs_lines = ax.contour(
        lon, lat, ozone_data_capped,
        levels=levels_lines, transform=data_proj,
        colors='black', linewidths=0.5, zorder=6
    )
    # Add contour labels only if lines were plotted
    if hasattr(cs_lines, 'levels') and cs_lines.levels is not None and len(cs_lines.levels) > 0:
        plt.clabel(cs_lines, inline=True, fontsize=8, fmt='%d')

    # --- Add Time Information ---
    init_datetime = pd.to_datetime(base_herbie_params["date"])
    # Extract valid time from dataset, assume it's the end of the 8hr period
    end_valid_time = pd.to_datetime(ds.valid_time.values)
    start_valid_time = end_valid_time - pd.Timedelta(hours=8)

    utc_label = f"UTC Valid: {start_valid_time:%m-%d %H:%M} - {end_valid_time:%m-%d %H:%M}"

    # Calculate Mountain Time (attempt precise conversion, fallback offset)
    mt_label = "MT Valid: N/A" # Initialised

    mt_start = pd.Timestamp(start_valid_time, tz='UTC').tz_convert('America/Denver')
    mt_end = pd.Timestamp(end_valid_time, tz='UTC').tz_convert('America/Denver')
    mt_label = f"MT Valid:  {mt_start:%m-%d %H:%M %Z} - {mt_end:%m-%d %H:%M %Z}"
    mt_offset = -6 # Assume standard time for simplicity - change to dynamic?
    mt_start = start_valid_time + pd.Timedelta(hours=mt_offset)
    mt_end = end_valid_time + pd.Timedelta(hours=mt_offset)
    mt_label = f"MT Approx: {mt_start:%m-%d %H:%M} - {mt_end:%m-%d %H:%M}"

    # Add time info to plot with background for readability
    text_props = dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7)
    ax.text(0.01, 0.01, utc_label, transform=ax.transAxes, fontsize=9, ha='left', va='bottom', bbox=text_props, zorder=10)
    ax.text(0.01, 0.05, mt_label, transform=ax.transAxes, fontsize=9, ha='left', va='bottom', bbox=text_props, zorder=10)

    # Set title and adjust layout
    ax.set_title(title, fontsize=12, pad=15) # Add padding to title
    fig.tight_layout(rect=[0, 0.08, 1, 0.93]) # Adjust rect to make space for colorbar/text

    # Save and close
    plt.savefig(output_fpath, dpi=250, bbox_inches='tight')
    print(f"Plot saved successfully: {output_fpath}")

    plt.close(fig) # Ensure figure is closed even if errors occurred

    return fig, ax # Return fig/ax mainly for potential interactive use, not strictly needed


def process_forecast(H, fxx, base_herbie_params, output_dir):
    """
    Fetches data for a specific forecast hour (fxx), plots it, and saves the file.

    Parameters:
    -----------
    H : Herbie object
        Initialized Herbie object pointing to the data file.
    fxx : int
        The forecast hour *end* time for the 8-hour average.
    base_herbie_params : dict
        Original parameters, used for metadata and time calculations.
    output_dir : pathlib.Path
        Directory to save the output plot.
    """
    if H is None or H.grib is None:
        print(f"Error: Herbie object is not valid or has no GRIB file path. Skipping f{fxx:02d}.")
        return None, None

    print(f"\n--- Processing Forecast Hour f{fxx:02d} ---")

    # Determine the forecast search string needed for Herbie's xarray accessor
    start_hr = fxx - 8
    if start_hr < 0:
        print(f"Warning: fxx={fxx} is too early for an 8-hour average product (start hour < 0). Skipping.")
        return None, None

    # Standard format for AQM 8hr ozone average forecast time identifier
    forecast_search_str = f":{start_hr}-{fxx} hour ave fcst:"
    print(f"Searching for GRIB message matching: '{forecast_search_str}'")

    try:
        # Get the dataset for this specific forecast time using xarray via Herbie
        # Requires cfgrib engine installed: pip install cfgrib
        ds = H.xarray(forecast_search_str, backend_kwargs={'engine':"cfgrib"},
                                    verbose=False)

        if ds is None:
            print(f"No dataset returned by Herbie/xarray for search string '{forecast_search_str}'. Skipping.")
            return None, None
        if "ozcon" not in ds:
            print(f"Error: Variable 'ozcon' not found in the retrieved dataset for f{fxx:02d}. Skipping.")
            print(f"Available variables: {list(ds.data_vars)}")
            return None, None
        if "valid_time" not in ds.coords:
            print(f"Warning: 'valid_time' coordinate not found in dataset for f{fxx:02d}.")
            # Attempt to proceed but time labeling might fail

        print(f"Successfully retrieved dataset for f{fxx:02d}.")
        if 'valid_time' in ds.coords:
            print(f"  Dataset valid time: {ds.valid_time.values}")

        # --- Prepare for Plotting ---
        init_datetime = H.date # Herbie object stores the init datetime

        # Calculate valid start/end times (best effort)
        try:
            end_valid_time = pd.to_datetime(ds.valid_time.values) if 'valid_time' in ds.coords else init_datetime + pd.Timedelta(hours=fxx)
            start_valid_time = end_valid_time - pd.Timedelta(hours=8)
        except Exception as time_calc_e:
            print(f"Warning: Could not accurately determine start/end valid times: {time_calc_e}")
            # Fallback using fxx and init_datetime directly
            end_valid_time = init_datetime + pd.Timedelta(hours=fxx)
            start_valid_time = init_datetime + pd.Timedelta(hours=start_hr)


        # Format times for filename and title
        init_time_str = f"{init_datetime:%Y%m%d_%H%M}"
        valid_end_time_str = f"{end_valid_time:%Y%m%d_%H%M}" # Use end time for identifying file

        # Construct filename
        output_fname = f"aqm_{init_time_str}Z_f{fxx:03d}_valid_{valid_end_time_str}Z_utah_o3_8h.png" # Use f008 format
        output_fpath = output_dir / output_fname

        # Create a comprehensive title for the plot
        title = (f"AQM 8-hr Avg Ozone ({H.product_description.upper()})\n"
                 f"Init: {init_datetime:%Y-%m-%d %H:%M}Z, Forecast Hour Ending: F{fxx:03d}\n"
                 f"Valid Approx: {start_valid_time:%Y-%m-%d %H:%M}Z - {end_valid_time:%Y-%m-%d %H:%M}Z")

        # --- Plot the data ---
        # This function now handles its own errors internally
        _, _ = plot_ozone_forecast(ds, title, base_herbie_params, output_fpath, focus_on_utah=True)

        return ds, output_fpath # Return dataset and path even if plotting had issues

    except ValueError as ve:
        # Handle error if Herbie/xarray couldn't find the forecast string
        print(f"--> Error accessing forecast '{forecast_search_str}': {ve}")

    except AttributeError as ae:
        # Handle cases where dataset might be missing expected components
        print(f"--> Attribute error processing f{fxx:02d} (likely issue with data loading/structure): {ae}")
        return None, None

    except Exception as e:
        # Catch-all for other unexpected errors during processing
        print(f"\n>>> An unexpected error occurred processing f{fxx:02d}: {e}")
        import traceback
        traceback.print_exc() # Print full traceback
        return None, None


def run_forecast_sequence(base_herbie_params, fxx_values, output_dir):
    """
    Sets up Herbie once, then processes and plots a sequence of forecast hours (fxx).

    Parameters:
    -----------
    base_herbie_params : dict
        Core Herbie parameters (date, model, product, domain). 'fxx' is ignored here.
    fxx_values : list or range
        A sequence of forecast hours (end hour of 8-hr average) to process.
    output_dir : pathlib.Path
        Directory to save the output plots.
    """
    print("--- Starting Forecast Sequence ---")
    print(f"Base Parameters: {base_herbie_params}")
    print(f"Forecast Hours (fxx) to process: {list(fxx_values)}")
    print(f"Output Directory: {output_dir}")
    print("-" * 30)

    # Setup Herbie and download data once for the base run date/time
    H = setup_herbie(base_herbie_params)

    if H is None:
        print("\nHerbie setup failed. Cannot process forecast sequence. Exiting.")
        return # Exit if Herbie couldn't be initialized

    # Process each requested forecast hour using the single Herbie object
    results = {}
    processed_count = 0
    plot_success_count = 0

    for fxx in fxx_values:
        # Basic validation for 8hr average product
        if not isinstance(fxx, int) or fxx < 8:
            print(f"\nSkipping invalid fxx={fxx} (must be integer >= 8 for 8-hour average ending at fxx)")
            continue

        # Process this forecast hour
        # Pass the single Herbie object (H) that points to the downloaded file
        ds, output_file_path = process_forecast(H, fxx, base_herbie_params, output_dir)

        # Record results
        if ds is not None: # Data was successfully retrieved
            processed_count += 1
            if output_file_path and output_file_path.exists(): # Check if plot file was created
                results[fxx] = output_file_path
                plot_success_count += 1
                print(f"  Successfully processed and plotted f{fxx:02d}.")
            elif output_file_path:
                results[fxx] = f"Processed (Plot Failed: {output_file_path.name})"
                print(f"  Successfully processed data for f{fxx:02d}, but plot generation failed or file not found.")
            else:
                results[fxx] = "Processed (Plotting Skipped or Failed)"
                print(f"  Successfully processed data for f{fxx:02d}, but plotting was skipped or failed.")
        else:
            # process_forecast returned None for ds, indicating failure
            results[fxx] = "Failed"
            print(f"  Failed to process data for f{fxx:02d}.")


    print("\n--- Processing Sequence Complete ---")
    total_requested = len(list(fxx_values))
    print(f"Requested FXX values: {total_requested}")
    print(f"Successfully processed data for: {processed_count}/{total_requested}")
    print(f"Successfully generated plots for: {plot_success_count}/{processed_count}")
    print(f"Plots saved in: {output_dir}")
    # print("\nDetailed Results:")
    # for fxx, status in results.items():
    #     print(f"  f{fxx:02d}: {status}")
    print("-" * 30)


# --- Main Execution Block ---

if __name__ == "__main__":

    # === User Configuration ===
    date_args = {
        "year": 2025, "month": 1, "day": 31, "hour": 12, "minute": 0, "second": 0
    }
    # Format this date for Herbie init
    date_str = (f"{date_args['year']}-{date_args['month']:02d}-"
                f"{date_args['day']:02d} {date_args['hour']:02d}"
                f":{date_args['minute']:02d}")

    grib_fdir = "/Users/johnlawson/data/temp_aqm/"

    # 1. Define the base parameters for the model run
    base_run_params = {
        "date": date_str,
        # "date": "2025-01-31 12:00",
        "model": "aqm",
        "product": "ave_8hr_o3",   # 8-hour average ozone
        "domain": "CS",            # CONUS domain for AQM
        # 'fxx' is handled by the loop, not needed here.
        # Optional: Specify local save directory for Herbie downloads
        "save_dir": pathlib.Path(grib_fdir),

    }

    # 2. Define the sequence of forecast hours (fxx) to process
    #    fxx represents the *end* hour of the 8-hour averaging period.
    #    Example: 0-8hr avg -> fxx=8; 1-9hr avg -> fxx=9; ...; 23-31hr avg -> fxx=31
    forecast_hours_sequence = range(8, 25, 1)
    # forecast_hours_sequence = [8, 12, 16, 20, 24, 28, 31]
    # forecast_hours_sequence = [15,]

    # =======================

    # Create the main output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Execute the forecast sequence
    run_forecast_sequence(
        base_herbie_params=base_run_params,
        fxx_values=forecast_hours_sequence,
        output_dir=OUTPUT_DIR
    )

    print("\nScript finished.")