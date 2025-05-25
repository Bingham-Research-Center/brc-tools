# Demonstration script for using Herbie with the AQM model (Multi-Phase Parallel)
import os
import sys
import pathlib
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Use non-interactive backend for parallel plotting
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
# import cfgrib # Keep if used for specific engine calls
from herbie import Herbie # Assuming Herbie is installed in your environment
import multiprocessing
import time # To time the execution

# --- Configuration (Based on gemini_parallel-aqm.py) ---
try:
    project_root = pathlib.Path(__file__).parent
except NameError:
    project_root = pathlib.Path('../..').resolve()

# Base output directory, subdirs will be created per init time
FIG_OUTPUT_DIR = project_root / "figures"
os.makedirs(FIG_OUTPUT_DIR, exist_ok=True)

# Base directory for downloads (will have subdirs per date)
GRIB_FDIR_BASE = "/Users/johnlawson/data/"
os.makedirs(GRIB_FDIR_BASE, exist_ok=True)

print(f"Base output directory set to: {FIG_OUTPUT_DIR}")

# --- Font Setup (Based on gemini_parallel-aqm.py) ---
try:
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Helvetica', 'Arial', 'Fira Sans', 'Nimbus Sans']
    print("Font preferences set to: Helvetica, Arial, Fira Sans, Nimbus Sans (sans-serif fallback)")
except Exception as e:
    print(f"Warning: Could not set all font preferences. Matplotlib defaults may apply. Error: {e}")

# --- Helper Functions (Based on gemini_parallel-aqm.py) ---
def extract_first_hour(forecast_str):
    """Extract the first number from strings like '7-15 hour ave fcst' for sorting."""
    if not isinstance(forecast_str, str): return 999
    parts = forecast_str.split();
    if not parts: return 999
    hour_range = parts[0]
    if '-' in hour_range:
        try: return int(hour_range.split('-')[0])
        except (ValueError, IndexError): return 999
    return 999

# --- Core Functions (Setup, Plotting, Processing - Based on gemini_parallel-aqm.py) ---
def setup_herbie(base_herbie_params):
    """Initializes Herbie, downloads data if needed, and returns the Herbie object."""
    init_date_str = base_herbie_params.get('date', 'Unknown Date')
    print(f"--- [Setup] Attempting for Date: {init_date_str} (PID: {os.getpid()}) ---")
    try:
        save_dir = base_herbie_params.get('save_dir')
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)

        H = Herbie(**base_herbie_params)
        local_file = H.download()  # Download the full AQM file

        # Confirm the GRIB file path
        if local_file and pathlib.Path(local_file).exists():
            print(f"Full AQM file found: {local_file}")
            base_herbie_params['file_path'] = str(local_file)
            H = Herbie(**base_herbie_params)
        else:
            print(f"Warning: Full AQM file not found for {init_date_str}.")
            return None

        return H  # Return the configured Herbie object

    except Exception as e:
        print(f"\n>>> Critical Error during setup_herbie for {init_date_str} (PID: {os.getpid()}): {e}")
        return None

def plot_ozone_forecast(ds, title, base_herbie_params, output_fpath,
                        focus_on_utah=True, min_threshold=50, max_cap=100):
    """Plots AQM ozone forecast using Cartopy. (Based on gemini_parallel-aqm.py)"""
    # print(f"Generating plot: {output_fpath.name} (PID: {os.getpid()})") # Reduced verbosity
    fig = plt.figure(figsize=(10, 8))
    try:
        map_proj = ccrs.Mercator(central_longitude=-95); data_proj = ccrs.PlateCarree()
        ax = plt.axes(projection=map_proj)
        if focus_on_utah: ax.set_extent([-112.15, -108.6, 40.0, 41.65], crs=data_proj)
        else: ax.set_extent([-125, -85, 32, 45], crs=data_proj)
        ax.add_feature(cfeature.LAND.with_scale('10m'), edgecolor='black', facecolor='#F0F0F0', zorder=0)
        ax.add_feature(cfeature.OCEAN.with_scale('10m'), edgecolor='black', facecolor='#D6EAF8', zorder=0)
        ax.add_feature(cfeature.LAKES.with_scale('10m'), edgecolor='black', facecolor='#D6EAF8', zorder=1)
        ax.add_feature(cfeature.STATES.with_scale('10m'), linewidth=0.5, edgecolor='dimgray', zorder=2)
        ax.add_feature(cfeature.BORDERS.with_scale('10m'), linewidth=0.7, edgecolor='black', zorder=3)
        if focus_on_utah:
            try:
                counties = cfeature.NaturalEarthFeature(category='cultural', name='admin_2_counties', scale='10m', facecolor='none')
                ax.add_feature(counties, edgecolor='darkgray', linewidth=0.3, zorder=3)
            except Exception as e: print(f"Note (PID {os.getpid()}): Could not load county boundaries. Error: {e}")
        ax.coastlines(resolution='10m', color='black', linewidth=0.8, zorder=4)
        try: ozone_data = ds["ozcon"].squeeze().copy(); lon = ds["longitude"]; lat = ds["latitude"]
        except KeyError: print(f"Error (PID {os.getpid()}): 'ozcon' not found for {title}."); plt.close(fig); return None, None
        except Exception as e: print(f"Error (PID {os.getpid()}) accessing data: {e}"); plt.close(fig); return None, None
        ozone_data_capped = ozone_data.where(ozone_data <= max_cap, max_cap)
        ozone_masked = ozone_data_capped.where(ozone_data_capped >= min_threshold)

        print(f"Original shape: {ozone_masked.shape}")

        cs_sp = 2; levels_fill = np.arange(min_threshold, max_cap + cs_sp, cs_sp)
        if len(levels_fill) > 1 and np.any(ozone_masked.notnull()):
            cs_fill = ax.contourf(lon, lat, ozone_masked, levels=levels_fill, transform=data_proj, cmap='plasma_r', extend='max', zorder=5, alpha=0.65)
            cbar = plt.colorbar(cs_fill, orientation='horizontal', pad=0.05, aspect=40, shrink=0.8)
            cbar.set_label(f'8-hr Avg Ozone (ppb) - Values < {min_threshold} ppb transparent')
        levels_lines = np.arange(30, max_cap + cs_sp, cs_sp*2)
        if len(levels_lines) > 0 and np.any(ozone_data_capped.notnull()):
            cs_lines = ax.contour(lon, lat, ozone_data_capped, levels=levels_lines, transform=data_proj, colors='black', linewidths=0.5, zorder=6)
            if hasattr(cs_lines, 'levels') and cs_lines.levels is not None and len(cs_lines.levels) > 0: plt.clabel(cs_lines, inline=True, fontsize=8, fmt='%d')
        init_datetime = pd.to_datetime(base_herbie_params["date"])
        try:
            end_valid_time = pd.to_datetime(ds.valid_time.values); start_valid_time = end_valid_time - pd.Timedelta(hours=8)
            utc_label = f"UTC Valid: {start_valid_time:%m-%d %H:%M} - {end_valid_time:%m-%d %H:%M}"; mt_label = "MT Valid: N/A"
            try:
                import pytz
                mt_start = pd.Timestamp(start_valid_time, tz='UTC').tz_convert('America/Denver'); mt_end = pd.Timestamp(end_valid_time, tz='UTC').tz_convert('America/Denver')
                mt_label = f"MT Valid:  {mt_start:%m-%d %H:%M %Z} - {mt_end:%m-%d %H:%M %Z}"
            except ImportError: mt_offset = -6; mt_start = start_valid_time + pd.Timedelta(hours=mt_offset); mt_end = end_valid_time + pd.Timedelta(hours=mt_offset); mt_label = f"MT Approx: {mt_start:%m-%d %H:%M} - {mt_end:%m-%d %H:%M}"
            except Exception as tz_e: print(f"Note (PID {os.getpid()}): MT conversion failed: {tz_e}")
            text_props = dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7)
            ax.text(0.01, 0.01, utc_label, transform=ax.transAxes, fontsize=9, ha='left', va='bottom', bbox=text_props, zorder=10)
            ax.text(0.01, 0.05, mt_label, transform=ax.transAxes, fontsize=9, ha='left', va='bottom', bbox=text_props, zorder=10)
        except Exception as e: print(f"Warning (PID {os.getpid()}): Could not add time labels: {e}")
        ax.set_title(title, fontsize=12, pad=15)
        fig.tight_layout(rect=[0, 0.08, 1, 0.93])
        plt.savefig(output_fpath, dpi=250, bbox_inches='tight')
        # print(f"Plot saved: {output_fpath} (PID: {os.getpid()})") # Reduced verbosity
    except Exception as plot_err:
        print(f"\n>>> Error (PID {os.getpid()}) during plotting for {output_fpath.name}: {plot_err}")
        import traceback; traceback.print_exc()
    finally: plt.close(fig)
    return fig, ax

def process_forecast(H, fxx, base_herbie_params, FIG_OUTPUT_DIR):
    """Fetches data via H.xarray and plots it. (Based on gemini_parallel-aqm.py)"""
    current_pid = os.getpid()
    if H is None or H.grib is None: print(f"Error (PID {current_pid}): Herbie object invalid for f{fxx:02d}."); return None
    start_hr = fxx - 8
    if start_hr < 0: print(f"Warning (PID {current_pid}): fxx={fxx} too early. Skipping."); return None
    forecast_search_str = f":{start_hr}-{fxx} hour ave fcst:"
    result_status = None
    try:
        ds = H.xarray(forecast_search_str,
                            # backend_kwargs=dict(
                            # engine="cfgrib"),
                            verbose=False)
        if ds is None: return None
        if "ozcon" not in ds: print(f"Error (PID {current_pid}): 'ozcon' not found for f{fxx:02d}. Vars: {list(ds.data_vars)}"); return None
        init_datetime = H.date
        # Convert nanoseconds to hours for easier handling
        hours = ds.step.values.astype('timedelta64[h]').astype(int)
        # fxx = 8 means 0-8 average period up to fxx=72
        ds = ds.isel(step=list(hours).index(fxx)) #.squeeze()

        try:
            end_valid_time = pd.to_datetime(ds.valid_time.values) if 'valid_time' in ds.coords else init_datetime + pd.Timedelta(hours=fxx)
            start_valid_time = end_valid_time - pd.Timedelta(hours=8)
        except Exception as time_calc_e: print(f"Warning (PID {current_pid}): Time calc failed: {time_calc_e}"); end_valid_time = init_datetime + pd.Timedelta(hours=fxx); start_valid_time = init_datetime + pd.Timedelta(hours=start_hr)

        # Ensure end_valid_time is a single Timestamp
        if isinstance(end_valid_time, pd.DatetimeIndex):
            end_valid_time = end_valid_time[0]  # Select the first element
        elif isinstance(end_valid_time, np.ndarray):
            end_valid_time = pd.Timestamp(end_valid_time[0])  # Convert to Timestamp if it's an array

        # Format the datetime strings
        init_time_str = f"{init_datetime:%Y%m%d_%H%M}"
        valid_end_time_str = f"{end_valid_time:%Y%m%d_%H%M}"

        output_fname = f"aqm_{init_time_str}Z_f{fxx:03d}_valid_{valid_end_time_str}Z_utah_o3_8h.png"
        output_fpath = FIG_OUTPUT_DIR / output_fname
        title = None
        # title = (f"AQM 8-hr Avg Ozone ({H.product_description.upper()})\n"
        #          f"Init: {init_datetime:%Y-%m-%d %H:%M}Z, Fhr End: F{fxx:03d}\n"
        #          f"Valid: {start_valid_time:%Y-%m-%d %H:%M}Z - {end_valid_time:%Y-%m-%d %H:%M}Z")
        _, _ = plot_ozone_forecast(ds, title, base_herbie_params, output_fpath, focus_on_utah=False)
        if output_fpath.exists(): result_status = str(output_fpath)
        else: print(f"Plot file {output_fpath.name} not created (PID: {current_pid})."); result_status = f"Failed Plotting f{fxx:02d}"
    except ValueError as ve: print(f"--> ValueError (PID {current_pid}) accessing '{forecast_search_str}': {ve}"); result_status = f"Failed Access f{fxx:02d}"
    except Exception as e: print(f"\n>>> Unexpected Error (PID {current_pid}) processing f{fxx:02d}: {e}"); import traceback; traceback.print_exc(); result_status = f"Failed Error f{fxx:02d}"
    return result_status

# --- Worker Functions for Multiprocessing ---

def worker_setup_herbie(params_for_init_time):
    """
    Worker function to call setup_herbie for a single initialization time.
    Takes a dictionary of parameters for that specific time.
    Returns a tuple: (params_used, grib_file_path_or_None)
    """
    current_pid = os.getpid()
    init_date = params_for_init_time.get('date', 'Unknown Date')
    # print(f"Download Worker (PID: {current_pid}) started for: {init_date}") # Reduce verbosity
    try:
        H = setup_herbie(params_for_init_time) # Call the original setup
        if H and H.grib:
            print(f"Download SUCCESS (PID: {current_pid}) for: {init_date} -> {H.grib}")
            return params_for_init_time, str(H.grib)
        else:
            print(f"Download FAILED (PID: {current_pid}) for: {init_date}")
            return params_for_init_time, None
    except Exception as e:
        print(f"\n>>> Error in worker_setup_herbie (PID {current_pid}) for {init_date}: {e}")
        # import traceback; traceback.print_exc() # Optional full trace
        return params_for_init_time, None

def worker_process_forecast(args):
    """
    Worker function for plotting/processing a single fxx from a specific GRIB file.
    (Based on gemini_parallel-aqm.py worker)
    """
    fxx, base_params, out_dir, grib_file_path = args
    current_pid = os.getpid()
    # print(f"Plot Worker (PID: {current_pid}) started for f{fxx:02d} from {pathlib.Path(grib_file_path).name}") # Reduce verbosity
    if not grib_file_path or not pathlib.Path(grib_file_path).exists():
        print(f"Error (PID {current_pid}): Invalid GRIB path '{grib_file_path}' for f{fxx:02d}.")
        return f"Failed Plot f{fxx:02d} - Bad Path"
    try:
        worker_base_params = base_params.copy()
        worker_base_params['file_path'] = str(grib_file_path)
        worker_base_params.pop('save_dir', None) # Ensure save_dir isn't reused
        H_worker = Herbie(**worker_base_params)
        # Call the original process_forecast which does xarray access AND plotting
        result = process_forecast(H_worker, fxx, base_params, out_dir)
        # print(f"Plot Worker (PID: {current_pid}) finished for f{fxx:02d}") # Reduce verbosity
        return result
    except Exception as e:
        print(f"\n>>> Error in worker_process_forecast (PID {current_pid}) for f{fxx:02d}: {e}")
        import traceback; traceback.print_exc()
        return f"Failed Worker f{fxx:02d}"

# --- New Orchestration Function for Multi-Phase Parallel Execution ---
def run_multi_forecast_parallel(list_of_base_params, fxx_values_common, output_base_dir):
    """
    Handles multiple initialization times:
    1. Downloads GRIB files in parallel.
    2. Prepares tasks for plotting.
    3. Processes/plots all forecast hours for all downloaded files in parallel.
    """
    total_start_time = time.time()
    print("--- Starting Multi-Forecast Parallel Workflow ---")
    print(f"Processing {len(list_of_base_params)} initialization time(s).")
    print(f"Common FXX values: {list(fxx_values_common)}")
    print(f"Base Output Directory: {output_base_dir}")

    # --- Phase 1: Parallel Download ---
    print("\n--- Phase 1: Parallel Downloads ---")
    download_start_time = time.time()
    download_results = []

    try: # Default N-1 cores for download
        cpu_count = os.cpu_count(); num_dl_workers = max(1, cpu_count - 1) if cpu_count else 1
    except NotImplementedError: num_dl_workers = 1
    print(f"Using {num_dl_workers} worker processes for downloads.")

    if num_dl_workers > 0 and len(list_of_base_params) > 0 :
        try:
            with multiprocessing.Pool(processes=num_dl_workers) as pool:
                download_results = pool.map(worker_setup_herbie, list_of_base_params)
        except Exception as pool_err: print(f"\n>>> Error during download pool: {pool_err}"); import traceback; traceback.print_exc()
    else: print("Skipping parallel download.")

    download_end_time = time.time()
    print(f"--- Download Phase Complete ({download_end_time - download_start_time:.2f} seconds) ---")

    # --- Phase 2: Serial Preparation for Plotting ---
    print("\n--- Phase 2: Preparing Plotting Tasks & Ensuring Indices ---")
    # Filter successful downloads
    successful_downloads = [(params, grib_path) for params, grib_path in download_results if grib_path]
    if not successful_downloads: print("No GRIB files downloaded. Cannot plot."); return
    print(f"\nSuccessfully obtained {len(successful_downloads)} GRIB file(s).")

    # *** NEW: Serial loop to generate .idx files ***
    precheck_idx = False # Set to True to force index creation/check
    if precheck_idx:
        print("Generating GRIB index (.idx) files sequentially...")
        indexed_files = [] # Store paths of files that were successfully indexed
        for base_params, grib_file_path in successful_downloads:
            print(f"  Indexing: {grib_file_path}...")
            try:
                # Create temporary Herbie object pointing to the specific downloaded file
                # h_idx = Herbie(file_path=grib_file_path, **{k: v for k, v in base_params.items() if k != 'save_dir'})

                base_params['file_path']=str(grib_file_path)

                h_idx = Herbie(**{k: v for k, v in base_params.items() if k != 'save_dir'})
                # Calling inventory() typically forces index creation/check
                _ = h_idx.inventory(verbose=False)
                idx_path = pathlib.Path(f"{grib_file_path}.idx") # Construct expected path
                if idx_path.exists():
                    print(f"  Index OK: {idx_path.name}")
                    indexed_files.append((base_params, grib_file_path)) # Keep if index confirmed
                else:
                    print(f"  Warning: Index file not found after H.inventory() for {grib_file_path}")
                del h_idx # Clean up object

            except Exception as idx_err:
                print(f"  Error creating index for {grib_file_path}: {idx_err}")
                print(f"  Skipping plotting tasks for this file.")

        if not indexed_files:
            print("No GRIB files were successfully indexed. Cannot proceed to plotting.")
            return

        print("Index generation complete.")

    print("\n--- Phase 2: Preparing Plotting Tasks ---")
    plotting_task_args = []
    for base_params, grib_file_path in successful_downloads:
        init_time_obj = pd.to_datetime(base_params['date'])
        init_time_subdir_name = f"{init_time_obj:%Y%m%d_%H%M}Z"
        plot_FIG_OUTPUT_DIR_for_init = output_base_dir / init_time_subdir_name
        os.makedirs(plot_FIG_OUTPUT_DIR_for_init, exist_ok=True)
        for fxx in fxx_values_common:
            if isinstance(fxx, int) and fxx >= 8:
                plotting_task_args.append((fxx, base_params, plot_FIG_OUTPUT_DIR_for_init, grib_file_path))
            else: print(f"Skipping invalid fxx={fxx} for init time {base_params['date']}")
    if not plotting_task_args: print("No valid plotting tasks generated."); return
    print(f"Prepared {len(plotting_task_args)} total plotting tasks.")

    # --- Phase 3: Parallel Plotting ---
    print("\n--- Phase 3: Parallel Plotting/Processing ---")
    plotting_start_time = time.time()
    plotting_results = []
    try: # Default N-1 cores for plotting
        cpu_count = os.cpu_count(); num_plot_workers = max(1, cpu_count - 1) if cpu_count else 1
    except NotImplementedError: num_plot_workers = 1
    print(f"Using {num_plot_workers} worker processes for plotting.")

    if num_plot_workers > 0 :
        try:
            with multiprocessing.Pool(processes=num_plot_workers) as pool:
                plotting_results = pool.map(worker_process_forecast, plotting_task_args)
        except Exception as pool_err: print(f"\n>>> Error during plotting pool: {pool_err}"); import traceback; traceback.print_exc()
    else: print("Skipping parallel plotting.")

    plotting_end_time = time.time()
    print(f"\n--- Plotting Phase Complete ({plotting_end_time - plotting_start_time:.2f} seconds) ---")

    # Report final results
    total_end_time = time.time(); print("\n--- Multi-Forecast Workflow Complete ---"); print(f"Total execution time: {total_end_time - total_start_time:.2f} seconds")
    success_count = 0; failures = [];
    for result in plotting_results:
        try:
            if isinstance(result, str) and pathlib.Path(result).is_file(): success_count += 1
            else: failures.append(result)
        except (TypeError, ValueError): failures.append(result)
    total_tasks = len(plotting_task_args); print(f"Attempted plotting tasks: {total_tasks}"); print(f"Successfully generated plots: {success_count}/{total_tasks}")
    if failures: print(f"Failures ({len(failures)}):"); [print(f"  - {f}") for f in failures[:10]];
    if len(failures) > 10: print(f"  ... and {len(failures)-10} more.")
    print(f"Plots saved in subdirectories under: {output_base_dir}"); print("-" * 30)


# --- Main Execution Block (Adapted for Multi-Phase Parallel) ---
if __name__ == "__main__":

    # === User Configuration ===

    # 1. Define MULTIPLE initialization dates/times to process
    #    These will be downloaded in parallel.
    init_dates_to_run = [
        "2025-04-21 12:00",
        "2025-04-21 06:00",
    ]

    # 2. Common model parameters (date will be overridden)
    model = "aqm"
    product = "ave_8hr_o3"
    domain = "CS"

    # 3. Create the list of parameter dictionaries for the download workers
    list_of_base_params = []
    for date_str in init_dates_to_run:
        specific_save_dir = pathlib.Path(GRIB_FDIR_BASE)
        list_of_base_params.append({
            "date": date_str, "model": model, "product": product, "domain": domain,
            "save_dir": specific_save_dir,
        })

    # 4. Define the COMMON sequence of forecast hours (fxx) for plotting
    #    This sequence will be applied to EACH successfully downloaded file.
    # forecast_hours_sequence = range(8, 33, 1)
    forecast_hours_sequence = range(9, 19, 3)

    # 5. Define the BASE output directory for plots (subdirs created per init time)
    plot_output_base_dir = FIG_OUTPUT_DIR # Using the global dir defined earlier

    # === End User Configuration ===

    os.makedirs(plot_output_base_dir, exist_ok=True)

    # --- Run the Multi-Phase Parallel Workflow ---
    run_multi_forecast_parallel(
        list_of_base_params=list_of_base_params,
        fxx_values_common=forecast_hours_sequence,
        output_base_dir=plot_output_base_dir,

    )

    print("\nScript finished.")