# Rewritten Script: RRFS Southern Plains Cross-Section (Potential Temperature)
# Removed Herbie dependency, uses xarray/cfgrib and MetPy directly.

import os
import sys
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import metpy.calc as mpcalc
from metpy.units import units
from metpy.interpolate import cross_section
from datetime import datetime
import cartopy.crs as ccrs
import pandas as pd
import warnings
# from metpy.plots import LambertConformal
import pyproj
import pint # Required for unit handling by MetPy

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning)

# --- Configuration (Preserved from original script) ---
date_args = {
    "year": 2025, "month": 1, "day": 31, "hour": 0, "minute": 0, "second": 0
}
analysis_date = datetime(**date_args)

# Path to the GRIB file directory
grib_fdir = "/Users/johnlawson/data/temp_rrfs/"
model_name = 'rrfs'
product_name = 'natlev' # Assumed based on original filename construction
member_val = "control" # Assumed based on original script
forecast_hour = 12

# Cross-section start and end points
start_point = (31.0, -100.0) # Approx. West Texas [cite: 3]
end_point = (38.0, -97.0)   # Approx. Central Kansas [cite: 3]

# Plotting options
plot_min_pressure = 500

# --- Construct Local File Path (Adapted from original script) ---
# Example filename structure: rrfs.t{HH}z.{product}.f{FFF}.grib2
# Ensure product name matches the file naming convention
# The original construct_rrfs_url function seemed to build this:
date_str = analysis_date.strftime('%Y%m%d')
hour_str = analysis_date.strftime('%H')
# Construct the expected filename based on typical RRFS naming
local_fname_only = f"rrfs.t{hour_str}z.{product_name}.f{forecast_hour:03d}.grib2" #[cite: 6] adjusted format
local_fname = os.path.join(grib_fdir, local_fname_only)

# Output directory setup
date_str_compact = analysis_date.strftime('%Y%m%d%H')
output_dir = f"./xsection/{model_name}/{date_str_compact}"
os.makedirs(output_dir, exist_ok=True)
output_filename = f"{output_dir}/{model_name}_xsection_pot_temp_f{forecast_hour:03d}.png"


# --- Data Acquisition (Using xarray/cfgrib) ---
print(f"--- Script: {model_name.upper()} Potential Temperature Cross-Section (No Herbie) ---")
print(f"Attempting to load {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")
print(f"Using local file: {local_fname}")

ds = None
if os.path.exists(local_fname):
    # Open the dataset using xarray and cfgrib engine
    # Filter by typeOfLevel if necessary, similar to original attempt [cite: 8]
    ds = xr.open_dataset(
        local_fname,
        engine='cfgrib',
        backend_kwargs={
            'filter_by_keys': {'typeOfLevel': 'isobaricInhPa'}, # Adjust filter as needed for 'natlev'
            'errors': 'ignore' # Tolerate errors reading some messages if needed
        }
    )
    print(f"Dataset loaded successfully from {local_fname}")

    # Handle surface pressure separately if needed (might be in a different message type)
    try:
        ds_sfc = xr.open_dataset(
            local_fname,
            engine='cfgrib',
            backend_kwargs={
                    'filter_by_keys':{
                        'stepType': 'instant',
                        'typeOfLevel': 'surface'
                    },
                'errors': 'ignore'
                }
        )
        # Merge surface fields if they exist and are not already in ds
        for var in ds_sfc:
            if var not in ds:
                ds[var] = ds_sfc[var]
        print("Merged surface variables.")
        ds_sfc.close()
    except Exception as e_sfc:
        print(f"Warning: Could not load or merge surface variables separately: {e_sfc}")
else:
    print(f"GRIB file not found at {local_fname}")
    print("Attempting to download the file...")

    # Extract date and hour components from analysis_date
    date_str = analysis_date.strftime('%Y%m%d')
    hour_str = analysis_date.strftime('%H')

    try:
        # Import the download function from o3_mini_high_rrfs
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from o3_mini_high_rrfs import download_rrfs_file

        # Download the file to the specified directory
        downloaded_file = download_rrfs_file(
            date=date_str,
            run_hour=hour_str,
            forecast_hour=forecast_hour,
            coord_mode=product_name,
            output_dir=grib_fdir
        )

        # Check if download was successful
        if downloaded_file and os.path.exists(downloaded_file):
            print(f"Successfully downloaded file to {downloaded_file}")
            local_fname = downloaded_file

            # Now load the dataset (reuse the code from above)
            ds = xr.open_dataset(
                local_fname,
                engine='cfgrib',
                backend_kwargs={
                    'filter_by_keys': {'typeOfLevel': 'isobaricInhPa'},
                    'errors': 'ignore'
                }
            )
            print(f"Dataset loaded successfully from {local_fname}")

            # Handle surface pressure separately if needed
            try:
                ds_sfc = xr.open_dataset(
                    local_fname,
                    engine='cfgrib',
                    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'surface'}, 'errors': 'ignore'}
                )
                # Merge surface fields if they exist
                for var in ds_sfc:
                    if var not in ds:
                        ds[var] = ds_sfc[var]
                print("Merged surface variables.")
                ds_sfc.close()
            except Exception as e_sfc:
                print(f"Warning: Could not load or merge surface variables separately: {e_sfc}")
        else:
            print(f"ERROR: Failed to download RRFS file for {analysis_date} F{forecast_hour:03d}")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: Download attempt failed: {e}")
        print("This script requires the GRIB file to be present locally or downloadable.")
        sys.exit(1)


# --- MetPy Parsing and Coordinate Setup ---
print("Parsing CF conventions and setting up coordinates...")
try:
    # Parse CF conventions and squeeze unnecessary dimensions
    ds = ds.metpy.parse_cf().squeeze()
except Exception as e:
    print(f"ERROR during MetPy parsing (parse_cf/squeeze): {e}")
    print("Dataset structure before error:")
    print(ds) # Print ds structure before the error
    sys.exit(1)

# Replace the CRS assignment section with this improved version
print("Setting up coordinate reference system...")
if 'metpy_crs' not in ds.coords:
    print("Attempting to assign CRS...")
    print("Setting up coordinate reference system...")
    # Create a Lambert Conformal projection using cartopy
    rrfs_crs = ccrs.LambertConformal(
        central_longitude=-97.5,
        central_latitude=38.5,
        standard_parallels=(38.5,)
    )

    # Replace the problematic CRS setup with this simplified approach
    print("Setting up for cross-section...")

    # We know the dataset has 2D latitude and longitude coordinates
    if 'latitude' in ds.coords and 'longitude' in ds.coords:
        print("Found lat/lon coordinates, preparing cross-section...")

        # Get the start and end points
        start_lat, start_lon = start_point
        end_lat, end_lon = end_point

        print(f"Creating cross-section from ({start_lat}, {start_lon}) to ({end_lat}, {end_lon})")

        # Create a direct implementation of cross-section without requiring MetPy's full functionality
        # First, we'll define a straight line between start and end points with evenly spaced steps
        steps = 200
        lats = np.linspace(start_lat, end_lat, steps)
        lons = np.linspace(start_lon, end_lon, steps)

        # Create a pandas DataFrame to store the cross-section data
        import pandas as pd
        cross_df = pd.DataFrame({
            'latitude': lats,
            'longitude': lons,
            'index': np.arange(steps)
        })

        # Create a list to store interpolated data
        cross_data = []

        # For each pressure level, interpolate the data along the cross-section
        for level in ds['isobaricInhPa'].values:
            level_data = ds.sel(isobaricInhPa=level)

            # Create interpolated arrays for each variable at this level
            level_dict = {'isobaricInhPa': level, 'index': np.arange(steps)}

            # Interpolate each variable to the cross-section points
            for var_name in ['t', 'q', 'u', 'v', 'gh']:
                if var_name in level_data:
                    # Use scipy's griddata for 2D interpolation
                    from scipy.interpolate import griddata

                    # Extract variable data and coordinates
                    var_data = level_data[var_name].values
                    lats_grid = level_data['latitude'].values
                    lons_grid = level_data['longitude'].values

                    # Prepare points for interpolation
                    points = np.column_stack((lats_grid.ravel(), lons_grid.ravel()))
                    values = var_data.ravel()

                    # Points to interpolate to
                    xi = np.column_stack((lats, lons))

                    # Interpolate
                    try:
                        interp_data = griddata(points, values, xi, method='linear')
                        level_dict[var_name] = interp_data
                    except Exception as e:
                        print(f"Warning: Could not interpolate {var_name} at level {level}: {e}")

            # Add this level's data to the cross-section
            cross_data.append(level_dict)

        # Convert to xarray Dataset
        cross_ds_list = []
        for level_dict in cross_data:
            level_value = level_dict.pop('isobaricInhPa')
            indices = level_dict.pop('index')

            # Create a dataset for this level
            level_ds = xr.Dataset(
                {var_name: (['index'], values) for var_name, values in level_dict.items()},
                coords={
                    'index': indices,
                    'isobaricInhPa': level_value,
                    'latitude': ('index', lats),
                    'longitude': ('index', lons)
                }
            )
            cross_ds_list.append(level_ds)

        # Combine all levels into a single dataset
        cross = xr.concat(cross_ds_list, dim='isobaricInhPa')

        # Now calculate potential temperature if 't' is available
        if 't' in cross:
            print("Calculating potential temperature...")
            # Convert to units and calculate
            temperature = cross['t'].values * units.kelvin  # Assuming temperature is in K
            pressure = cross['isobaricInhPa'].values * units.hPa

            # Create a meshgrid of pressure for each point along the cross-section
            pressure_grid = np.tile(pressure[:, np.newaxis], (1, steps))

            # Calculate potential temperature
            theta = mpcalc.potential_temperature(pressure_grid * units.hPa, temperature * units.kelvin)

            # Add to dataset
            cross['potential_temperature'] = xr.DataArray(
                theta.magnitude,
                dims=['isobaricInhPa', 'index'],
                coords={
                    'isobaricInhPa': cross['isobaricInhPa'],
                    'index': cross['index'],
                    'latitude': cross['latitude'],
                    'longitude': cross['longitude']
                },
                attrs={'units': 'K'}
            )

            print("Potential temperature calculation successful")
        else:
            print("ERROR: Temperature ('t') not available for potential temperature calculation")

        print("Cross-section created successfully")
    else:
        print("ERROR: latitude and longitude coordinates not found in dataset")

# --- Verify Coordinates for Cross Section ---
required_coords = ['metpy_crs', 'x', 'y']
missing_coords = [coord for coord in required_coords if coord not in ds.coords]
if missing_coords:
    print(f"ERROR: Missing required coordinates for cross_section after checks: {missing_coords}")
    print("Dataset Coordinates:", ds.coords)
    sys.exit(1)
else:
    print("Required coordinates ('metpy_crs', 'x', 'y') are present.")


# Replace the variable identification section with this more flexible approach
print("Identifying variables for cross-section...")

# First check what vertical levels are available
print(f"Available pressure levels: {ds['isobaricInhPa'].values}")
num_pressure_levels = len(ds['isobaricInhPa'])
print(f"Number of pressure levels: {num_pressure_levels}")

# Since we have 3D variables but temperature is only 2D, we need to adjust our approach
# Let's see if we can use one of the 3D variables for the cross-section
print("Checking if we can create a cross-section using available 3D fields...")

# Identify any 3D variable to use for creating the cross-section structure
crosssection_var = None
for var_name in ['gh', 'q', 'r', 'absv', 'u', 'v']:
    if var_name in ds and 'isobaricInhPa' in ds[var_name].dims:
        crosssection_var = var_name
        print(f"Will use '{crosssection_var}' to create cross-section structure.")
        break

if not crosssection_var:
    print("ERROR: No suitable 3D variable found for cross-section. Cannot proceed.")
    sys.exit(1)

# Check whether we'll be able to use temperature directly
if 't' in ds and len(ds['t'].dims) == 2:
    print("Temperature ('t') is available as a 2D field.")
    use_temperature_directly = True
else:
    print("Temperature ('t') not available in expected format.")
    use_temperature_directly = False

# Check if potential temperature is already available
if 'pt' in ds:
    print("Potential temperature ('pt') is directly available in the dataset.")
    use_pt_directly = True
else:
    use_pt_directly = False

# Check for other needed variables
level_coord_name = 'isobaricInhPa'  # We know this is the vertical coordinate from diagnostics
if use_temperature_directly:
    temp_var_name = 't'
    print(f"Using temperature variable: '{temp_var_name}'")
else:
    # If temperature isn't available, try to find a suitable replacement
    temp_var_name = None
    print("Will need to derive temperature from other fields.")

# Try to identify wind variables
u_wind_var = next((var for var in ['u', 'UGRD'] if var in ds and level_coord_name in ds[var].dims), None)
v_wind_var = next((var for var in ['v', 'VGRD'] if var in ds and level_coord_name in ds[var].dims), None)
if u_wind_var: print(f"Identified U-wind variable: '{u_wind_var}'")
else: print("U-wind variable not available with pressure levels.")
if v_wind_var: print(f"Identified V-wind variable: '{v_wind_var}'")
else: print("V-wind variable not available with pressure levels.")

# Surface pressure for terrain
sfc_pres_var_name = next((var for var in ['sp', 'PRES_surface', 'PRES_P0_L1', 'mslet']
                          if var in ds), None)
if sfc_pres_var_name:
    print(f"Identified surface pressure variable: '{sfc_pres_var_name}'")
else:
    print("Surface pressure variable not identified.")

# --- Calculate Cross Section ---
print("Calculating cross-section...")
# Create cross section using the identified 3D variable
# Update parameters based on the current MetPy cross_section function signature
# Check the function signature to understand available parameters
print(f"Cross-section function info: {cross_section.__doc__.splitlines()[0]}")

# Create cross section using basic parameters only
cross = cross_section(
    ds,
    start_point,
    end_point,
    steps=200
).set_coords(('latitude', 'longitude'))

print("Cross-section calculated successfully.")

# If temperature is 2D surface field, add it to cross-section
if use_temperature_directly and len(ds['t'].dims) == 2:
    print("Adding 2D temperature to cross-section...")
    temp_cross = cross_section(ds, start_point, end_point, steps=200)
    cross['surface_temperature'] = temp_cross['t']

# If potential temperature is directly available
if use_pt_directly:
    print("Adding potential temperature to cross-section...")
    if len(ds['pt'].dims) == 2:
        pt_cross = cross_section(ds, start_point, end_point, steps=200)
        cross['surface_potential_temperature'] = pt_cross['pt']
    else:
        cross['potential_temperature'] = cross['pt']

print("Cross-section structure:")
print(cross)

# --- Calculate Potential Temperature ---
print("Calculating/processing potential temperature...")

try:
    # If we have 3D fields with pressure levels
    if level_coord_name in cross and crosssection_var in cross:
        if use_pt_directly and 'potential_temperature' in cross:
            print("Using provided potential temperature field.")
            # Nothing more to do - already have it
        elif temp_var_name in cross and level_coord_name in cross[temp_var_name].coords:
            print("Calculating potential temperature from 3D temperature.")
            # Get temperature and pressure data from the cross-section
            temperature = cross[temp_var_name].metpy.quantify()
            pressure = cross[level_coord_name].metpy.quantify()

            # Compute potential temperature
            theta = mpcalc.potential_temperature(pressure, temperature)

            # Add calculated theta to the cross-section dataset
            cross['potential_temperature'] = xr.DataArray(
                theta.magnitude,
                coords=temperature.coords,
                dims=temperature.dims,
                name='potential_temperature',
                attrs={'units': str(theta.units)}
            )
        else:
            print("Cannot calculate 3D potential temperature - missing required variables.")

    # Check if we should use surface temperature/potential temperature
    if 'surface_temperature' in cross:
        print("Using surface temperature for potential temperature calculation.")
        # For surface temperature, we need surface pressure
        if sfc_pres_var_name in cross:
            t_surface = cross['surface_temperature'].metpy.quantify()
            p_surface = cross[sfc_pres_var_name].metpy.quantify()

            # Calculate surface potential temperature
            theta_surface = mpcalc.potential_temperature(p_surface, t_surface)

            cross['surface_potential_temperature'] = xr.DataArray(
                theta_surface.magnitude,
                coords=t_surface.coords,
                dims=t_surface.dims,
                name='surface_potential_temperature',
                attrs={'units': str(theta_surface.units)}
            )
        elif 'surface_potential_temperature' in cross:
            print("Using provided surface potential temperature.")
        else:
            print("Cannot calculate surface potential temperature - missing surface pressure.")

    # If we have neither 3D nor surface potential temperature, set a flag for plotting
    if 'potential_temperature' not in cross and 'surface_potential_temperature' not in cross:
        print("WARNING: No potential temperature data available for plotting!")

except Exception as e:
    print(f"ERROR processing potential temperature: {e}")
    import traceback
    traceback.print_exc()

# --- Plotting ---
# Adjust plotting code to handle either 3D cross-section or just surface fields
print("Generating plot...")
fig = plt.figure(figsize=(16, 9))
ax = plt.axes()

# Determine what we're plotting
plot_3d = 'potential_temperature' in cross and level_coord_name in cross
plot_surface = 'surface_potential_temperature' in cross
plot_mode = 'full_cross_section' if plot_3d else 'surface_only'

print(f"Plot mode: {plot_mode}")

if plot_3d:
    # --- 3D Cross-section plotting (similar to original) ---
    print("Plotting 3D potential temperature cross-section...")

    y_coords = cross[level_coord_name].metpy.quantify()
    x_coords = cross['longitude'].metpy.quantify()

    y_bottom_pressure_mag = y_coords.max().item()
    y_top_pressure_val = float(plot_min_pressure) if plot_min_pressure else max(100.0, y_coords.min().item())

    # Create meshgrid for contour plotting
    x_plot = x_coords.data
    y_plot = y_coords.data
    if x_plot.ndim == 1 and y_plot.ndim == 1:
        xx, yy = np.meshgrid(x_plot, y_plot)
        # Now plot the contours
        theta_levels = np.arange(260, 370, 3)
        theta_data = cross['potential_temperature'].data

        cf = ax.contourf(xx, yy, theta_data,
                       levels=theta_levels, cmap='cividis', extend='both')

        # Configure axis
        ax.set_yscale('log')
        ax.set_ylim(y_bottom_pressure_mag, y_top_pressure_val)
        ax.set_ylabel(f"Pressure (hPa)")

        # Add colorbar
        cbar = fig.colorbar(cf, ax=ax, pad=0.02, aspect=30)
        cbar.set_label(f"Potential Temperature (K)")

        # Add terrain if available
        if 'terrain_pressure' in cross:
            terrain_data = cross['terrain_pressure'].data
            ax.fill_between(x_plot, terrain_data, y_bottom_pressure_mag,
                           where=terrain_data >= y_top_pressure_val,
                           facecolor='darkgoldenrod', alpha=0.7)

        # Add wind barbs if available
        if 'tangential_wind' in cross and 'normal_wind' in cross:
            # (wind barb plotting code remains the same)
            pass

elif plot_surface:
    # --- Surface-only plotting ---
    print("Plotting surface potential temperature...")

    # For surface plot, we use horizontal distance as x-axis
    x_coords = cross['index'].metpy.magnitude  # Use cross-section distance

    # Plot surface potential temperature
    theta_surface = cross['surface_potential_temperature'].metpy.magnitude
    ax.plot(x_coords, theta_surface, 'r-', linewidth=2)

    # Add labels
    ax.set_xlabel("Distance along cross-section (index)")
    ax.set_ylabel("Potential Temperature (K)")

    # Add terrain profile if available
    if 'orog' in cross:
        # Terrain height on secondary y-axis
        ax2 = ax.twinx()
        terrain = cross['orog'].metpy.magnitude
        ax2.fill_between(x_coords, 0, terrain, color='darkgoldenrod', alpha=0.7)
        ax2.set_ylabel("Terrain Height (m)")

else:
    # No potential temperature data available
    print("ERROR: No suitable data for plotting!")
    ax.text(0.5, 0.5, "No potential temperature data available",
            ha='center', va='center', fontsize=16, transform=ax.transAxes)

# --- Labels and Title ---
model_name_upper = model_name.upper()
try:
    valid_time_str = cross["valid_time"].dt.strftime("%Y-%m-%d %H:%M UTC").item()
except:
    valid_time_str = str(analysis_date + pd.Timedelta(hours=forecast_hour))

ax.set_title(
    f'{model_name_upper} {"Potential Temperature Cross-Section" if plot_3d else "Surface Potential Temperature"}\n'
    f'From ({start_point[0]}N, {start_point[1]}E) to ({end_point[0]}N, {end_point[1]}E)\n'
    f'Valid: {valid_time_str}'
)
ax.grid(True, linestyle=':', alpha=0.5)

# --- Final Steps ---
plt.tight_layout()

# Save figure
try:
    output_suffix = "_surface" if not plot_3d else ""
    output_filename_adj = output_filename.replace(".png", f"{output_suffix}.png")
    plt.savefig(output_filename_adj, dpi=150, bbox_inches='tight')
    print(f"Plot saved to {output_filename_adj}")
except Exception as e:
    print(f"ERROR saving plot: {e}")

plt.show()
plt.close(fig)

print("Script finished.")