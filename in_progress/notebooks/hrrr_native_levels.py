# HRRR Cross-Section - Switch between Potential and Drybulb Temperature

import os
import requests
import sys
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import metpy.calc as mpcalc
from metpy.units import units
from metpy.interpolate import cross_section
from herbie import Herbie
from datetime import datetime
import warnings
import pint

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning)

# --- Configuration ---
date_args = {
    "year": 2025, "month": 1, "day": 31, "hour": 6, "minute": 0, "second": 0
}
analysis_date = datetime(**date_args)

model_name = 'hrrr'
product_name = 'nat'  # Use 'wrfnat' for native model levels
forecast_hour = 6        # Short forecast hour for HRRR

# *** TEMPERATURE DISPLAY OPTION ***
# Choose between 'potential' and 'drybulb'
temp_display = 'drybulb'  # 'potential' or 'drybulb'

# SLC
start_point = (40.7606, -111.8881)  # Salt Lake City, UT
# SE of Dinosaur NM, CO, co. line
end_point = (40.222665, -108.477740)

# Set pressure level limits for the plot
user_y_bottom = 875  # Bottom pressure limit (hPa)
user_y_top = 650     # Top pressure limit (hPa)

# Define output directory
date_str_compact = analysis_date.strftime('%Y%m%d%H')
output_dir = f"./xsection/{model_name}/{date_str_compact}"
os.makedirs(output_dir, exist_ok=True)

# Set filename and plot title based on chosen temperature type
if temp_display == 'potential':
    output_filename = f"{output_dir}/{model_name}_xsection_pot_temp_native_f{forecast_hour:03d}.png"
    plot_title = "Potential Temperature (K)"
    contour_levels = np.arange(270, 321, 1)  # Levels for potential temperature
    cmap_style = 'viridis'
else:  # drybulb
    output_filename = f"{output_dir}/{model_name}_xsection_drybulb_temp_native_f{forecast_hour:03d}.png"
    plot_title = "Temperature (°C)"
    contour_levels = np.arange(-20, 6, 1)  # -20 to +5 C as requested
    cmap_style = 'coolwarm'

# --- Data Acquisition ---
print(f"--- HRRR {plot_title} Cross-Section on Native Levels ---")
print(f"Attempting to access {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")

# Create the Herbie instance with the correct product (wrfnat)
H = Herbie(
    analysis_date,
    model=model_name,
    product=product_name,
    fxx=forecast_hour,
    save_dir='/Users/johnlawson/data/',
    verbose=False
)

# From the inventory, we know exactly what fields to request on hybrid levels
# We specifically want TMP, PRES, HGT, UGRD, VGRD on hybrid levels, and PRES on surface
variables_to_get = [
    "TMP:hybrid",    # Temperature on hybrid levels
    "PRES:hybrid",   # Pressure on hybrid levels
    "HGT:hybrid",    # Geopotential Height on hybrid levels
    "UGRD:hybrid",   # U-component of wind on hybrid levels
    "VGRD:hybrid",   # V-component of wind on hybrid levels
    "PRES:surface"   # Surface pressure
]

# Tell me everything about the Herbie object
print("Herbie object info:")
print(H)
print("Herbie inventory:")
print(H.inventory)
print(H.grib)

# Define the S3 URL and local file path
s3_url = f"https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{analysis_date:%Y%m%d}/conus/hrrr.t{analysis_date:%H}z.wrfnatf{forecast_hour:02d}.grib2"
local_file = f"/Users/johnlawson/data/hrrr/{analysis_date:%Y%m%d}/hrrr.t{analysis_date:%H}z.wrfnatf{forecast_hour:02d}.grib2"

# Create directory if needed
os.makedirs(os.path.dirname(local_file), exist_ok=True)

# Check if file already exists
if not os.path.exists(local_file):
    # Download the file
    print(f"File not found locally. Downloading from {s3_url} to {local_file}")
    response = requests.get(s3_url, stream=True)
    if response.status_code == 200:
        with open(local_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
        print("Download successful")
    else:
        print(f"Download failed with status code {response.status_code}")
        sys.exit(1)
else:
    print(f"File already exists at {local_file}. Using local copy.")


# Fallback: Try opening with xarray directly if Herbie fails
print("Attempting to open GRIB file directly with xarray...")
try:
    import cfgrib
    ds = xr.open_dataset(local_file, engine='cfgrib', backend_kwargs={'filter_by_keys': {'typeOfLevel': 'hybrid'}})
    print("Successfully opened file directly with xarray.")
except Exception as direct_error:
    print(f"ERROR: Failed to open file directly: {direct_error}")
    print("Check file integrity and format.")
    sys.exit(1)

print("Data loaded successfully.")

# --- Inspect Dataset Structure ---
print("\n--- Dataset Structure ---")
print("Variables:")
for var_name, var in ds.data_vars.items():
    print(f"  {var_name}: {var.dims}")

print("\nCoordinates:")
for coord_name, coord in ds.coords.items():
    print(f"  {coord_name}: {coord.dims if hasattr(coord, 'dims') else 'scalar'}")

# --- MetPy Parsing and Coordinate Setup ---
print("Parsing CF conventions and setting up coordinates...")
try:
    ds = ds.metpy.parse_cf().squeeze()
except Exception as e:
    print(f"ERROR during MetPy parsing (parse_cf/squeeze): {e}")
    print("Dataset structure before error:")
    print(ds)
    sys.exit(1)

# --- Identify Hybrid Level Coordinate ---
# Based on the inventory, the hybrid levels are numbered 1, 2, 3, etc.
hybrid_level_coords = [coord for coord in ds.coords
                       if any(kw in coord.lower() for kw in ['hybrid', 'lev', 'layer'])]

if not hybrid_level_coords:
    print("No hybrid level coordinate found. Looking for possible vertical dimension...")
    # Look for dimensions in temperature variable
    temp_vars = [v for v in ds.data_vars if 'TMP' in v]
    if temp_vars:
        temp_var = temp_vars[0]
        dims_to_check = [dim for dim in ds[temp_var].dims if dim not in ['x', 'y', 'time']]
        print(f"Possible vertical dimensions in temperature: {dims_to_check}")
        if dims_to_check:
            hybrid_level_coords = dims_to_check

if not hybrid_level_coords:
    print("ERROR: Could not identify hybrid level coordinate.")
    sys.exit(1)

hybrid_level_name = hybrid_level_coords[0]
print(f"Using '{hybrid_level_name}' as the vertical coordinate.")




# Update variable name mapping based on what's actually in the file
temp_var_name = 't'  # Instead of looking for 'TMP'
hybrid_pres_var = 'pres'  # Instead of looking for 'PRES'
u_wind_var = 'u'  # Instead of looking for 'UGRD'
v_wind_var = 'v'  # Instead of looking for 'VGRD'
height_var = 'gh'  # Instead of looking for 'HGT'



# --- Verify MetPy CRS and x/y coordinates ---
required_coords = ['metpy_crs', 'x', 'y']
missing_coords = [coord for coord in required_coords if coord not in ds.coords]

if missing_coords:
    print(f"WARNING: Missing required coordinates for cross_section: {missing_coords}")
    if 'metpy_crs' not in ds.coords:
        print("Attempting to assign standard HRRR CRS (Lambert Conformal)...")


        # Replace your CRS assignment code with this more explicit approach
        print("Applying explicit CRS setup...")
        try:
            # Create projection definition manually
            grid_mapping_dict = {
                'grid_mapping_name': 'lambert_conformal_conic',
                'latitude_of_projection_origin': 38.5,
                'longitude_of_central_meridian': 262.5,
                'standard_parallel': [38.5, 38.5],
                'earth_radius': 6371229.0
            }

            # Create the projection coordinate variable explicitly
            ds = ds.assign_coords(crs=1)
            ds['crs'] = xr.DataArray(0, attrs=grid_mapping_dict)

            # Assign the grid mapping to each data variable
            for var in ds.data_vars:
                ds[var].attrs['grid_mapping'] = 'crs'

            # Now try to assign CRS through MetPy
            ds = ds.metpy.parse_cf()
            print("Successfully assigned CRS manually.")
        except Exception as e:
            print(f"ERROR manually assigning CRS: {e}")
            sys.exit(1)

        # Ensure x and y coordinates are set up properly
        if 'x' not in ds.coords or 'y' not in ds.coords:
            print("Setting up x and y coordinates explicitly...")
            # Create coordinates based on the dimensions of the data
            y_size, x_size = ds[temp_var_name].shape[1:]
            ds = ds.assign_coords(
                x=np.arange(x_size),
                y=np.arange(y_size)
            )
            print("Assigned x and y coordinates.")

# --- Identify Variable Names ---
print("Identifying variable names...")

# For surface pressure, you might need to open the file again without filtering
sfc_pres_var_name = None
if not any(var.startswith('sp') or var == 'ps' for var in ds.data_vars):
    print("Surface pressure not found. Attempting to load it separately...")
    try:
        ds_surface = xr.open_dataset(local_file, engine='cfgrib',
                                     backend_kwargs={'filter_by_keys':
                                    {'typeOfLevel': 'surface', 'stepType': 'instant'}})
        # Find surface pressure variable
        sfc_pres_vars = [var for var in ds_surface.data_vars
                         if var.startswith('sp') or var == 'ps' or var == 'pres']
        if sfc_pres_vars:
            sfc_pres_var_name = sfc_pres_vars[0]
            ds[sfc_pres_var_name] = ds_surface[sfc_pres_var_name]
            print(f"Added surface pressure variable '{sfc_pres_var_name}' to dataset.")
        else:
            print("Surface pressure variable not found in surface level data.")
    except Exception as e:
        print(f"Failed to load surface data: {e}")
else:
    # Check if there's any surface pressure in the dataset already
    potential_sfc_vars = [var for var in ds.data_vars if 'surface' in str(ds[var].attrs.get('long_name', '')).lower()]
    if potential_sfc_vars:
        sfc_pres_var_name = potential_sfc_vars[0]
        print(f"Found surface pressure variable: '{sfc_pres_var_name}'")

# --- Calculate Cross Section ---
# Try alternative cross-section approach if the standard method fails
try:
    print("Attempting cross-section with standard method...")
    cross = cross_section(ds, start_point, end_point, steps=200).set_coords(('latitude', 'longitude'))
    print("Cross-section calculated.")
except Exception as e:
    print(f"ERROR during standard cross_section calculation: {e}")
    print("Attempting alternative cross-section approach...")

    try:
        # Get lat/lon arrays
        lats = ds.latitude.values
        lons = ds.longitude.values

        # Create a direct path between start and end points
        start_lat, start_lon = start_point
        end_lat, end_lon = end_point

        # Generate path points
        path_lats = np.linspace(start_lat, end_lat, 200)
        path_lons = np.linspace(start_lon, end_lon, 200)

        # Find nearest grid points to path
        path_indices = []
        for path_lat, path_lon in zip(path_lats, path_lons):
            # Find nearest grid point
            dist = (lats - path_lat)**2 + (lons - path_lon)**2
            y_idx, x_idx = np.unravel_index(np.argmin(dist), dist.shape)
            path_indices.append((y_idx, x_idx))

        # Create cross section dataset
        cross_vars = {}
        for var_name, da in ds.data_vars.items():
            if hybrid_level_name in da.dims:
                # Extract values along the path
                cross_section_data = np.array([da.values[:, y, x] for y, x in path_indices]).T

                # Create DataArray
                cross_vars[var_name] = xr.DataArray(
                    cross_section_data,
                    coords={
                        hybrid_level_name: ds[hybrid_level_name],
                        'index': np.arange(len(path_indices))
                    },
                    dims=[hybrid_level_name, 'index'],
                    name=var_name,
                    attrs=da.attrs
                )

        # Create path coordinates
        cross_lat = xr.DataArray(
            path_lats,
            coords={'index': np.arange(len(path_indices))},
            dims=['index'],
            name='latitude'
        )

        cross_lon = xr.DataArray(
            path_lons,
            coords={'index': np.arange(len(path_indices))},
            dims=['index'],
            name='longitude'
        )

        # Create the cross-section dataset
        cross = xr.Dataset(cross_vars)
        cross = cross.assign_coords({
            'latitude': cross_lat,
            'longitude': cross_lon
        })

        print("Alternative cross-section calculated.")
    except Exception as e2:
        print(f"ERROR during alternative cross_section calculation: {e2}")
        sys.exit(1)

# --- Prepare Temperature for Plotting ---
print(f"Preparing {plot_title} for plotting...")
try:
    temp_da = cross[temp_var_name]
    pres_da = cross[hybrid_pres_var]

    # Ensure units are assigned
    if temp_da.metpy.units == units.dimensionless:
        temp_da = temp_da.metpy.quantify(units.kelvin)
    if pres_da.metpy.units == units.dimensionless:
        pres_da = pres_da.metpy.quantify(units.pascal)
        pres_da = pres_da.metpy.convert_units(units.hPa)

    if temp_display == 'potential':
        # Calculate potential temperature
        pres_da_2d, temp_da_2d = xr.broadcast(pres_da, temp_da)
        pressure_for_calc = pres_da_2d.metpy.unit_array
        temperature_for_calc = temp_da_2d.metpy.unit_array

        temperature_result = mpcalc.potential_temperature(pressure_for_calc, temperature_for_calc)
        temp_units = str(temperature_result.units)
        temp_name = 'potential_temperature'
    else:  # drybulb
        # Convert temperature to Celsius
        temperature_result = temp_da.metpy.convert_units('degC').metpy.unit_array
        temp_units = 'degC'
        temp_name = 'temperature'

    # Store in dataset
    cross['plot_temperature'] = xr.DataArray(
        temperature_result, coords=temp_da.coords, dims=temp_da.dims,
        name=temp_name, attrs={'units': temp_units}
    )
    print(f"{plot_title} prepared and added to dataset.")
except Exception as e:
    print(f"ERROR preparing temperature: {e}")
    import traceback
    traceback.print_exc()
    cross['plot_temperature'] = None
    sys.exit(1)

# --- Calculate Wind Components (Optional) ---
if u_wind_var and v_wind_var and u_wind_var in cross and v_wind_var in cross:
    print("Calculating wind components...")
    try:
        u_wind_da = cross[u_wind_var]
        v_wind_da = cross[v_wind_var]

        if u_wind_da.metpy.units == units.dimensionless:
            u_wind_da = u_wind_da.metpy.quantify(units('m/s'))
        if v_wind_da.metpy.units == units.dimensionless:
            v_wind_da = v_wind_da.metpy.quantify(units('m/s'))

        u_wind_knots = u_wind_da.metpy.convert_units('knots')
        v_wind_knots = v_wind_da.metpy.convert_units('knots')
        tangential_wind, normal_wind = mpcalc.cross_section_components(u_wind_knots, v_wind_knots)

        cross['tangential_wind'] = xr.DataArray(
            tangential_wind, coords=u_wind_knots.coords, dims=u_wind_knots.dims,
            name='tangential_wind', attrs={'units': 'knots'}
        )
        cross['normal_wind'] = xr.DataArray(
            normal_wind, coords=v_wind_knots.coords, dims=v_wind_knots.dims,
            name='normal_wind', attrs={'units': 'knots'}
        )
        print("Wind components calculated.")
    except Exception as e:
        print(f"ERROR calculating wind components: {e}")
        import traceback
        traceback.print_exc()
else:
    print("Wind variables missing or not found in cross section. Skipping component calculation.")

# --- Prepare Terrain Data (Using Surface Pressure) ---
print("Preparing terrain data...")
if sfc_pres_var_name and sfc_pres_var_name in cross:
    print(f"Using surface pressure variable '{sfc_pres_var_name}' for terrain.")
    try:
        sp_da = cross[sfc_pres_var_name]
        if sp_da.metpy.units == units.dimensionless:
            sp_da = sp_da.metpy.quantify(units.pascal)

        terrain_pressure = sp_da.metpy.convert_units('hPa')

        # Store in the cross-section dataset
        cross['terrain_pressure'] = xr.DataArray(
            terrain_pressure.data, coords={'index': cross['index']},
            dims=['index'], name='terrain_pressure', attrs={'units': 'hPa'}
        )
        print("Terrain pressure prepared in hPa.")
    except Exception as e:
        print(f"ERROR preparing terrain pressure from '{sfc_pres_var_name}': {e}")
        import traceback
        traceback.print_exc()
        cross['terrain_pressure'] = None
else:
    print(f"Surface pressure variable not found in cross section.")
    cross['terrain_pressure'] = None

# --- Plotting ---
print("Generating plot...")
fig = plt.figure(figsize=(16, 8))
ax = plt.axes()

# For hybrid levels, we need to handle the dimensionality differently
x_coords = cross['longitude'].values
hybrid_data = cross[hybrid_pres_var]

# Check if pressure data is valid
if np.isnan(hybrid_data).all():
    print("WARNING: Pressure data contains all NaN values. Using level numbers instead.")
    # Use level numbers instead of actual pressure values
    num_levels = len(cross[hybrid_level_name])
    y_coords_vals = np.arange(1, num_levels + 1)
    y_levels_2d = np.tile(y_coords_vals[:, np.newaxis], (1, len(x_coords)))
    # Now plot indices instead of pressure
    ax.set_ylabel("Model Level (higher = closer to ground)")
    is_pressure = False
else:
    try:
        print("Using actual pressure values for vertical coordinate.")
        # Convert pressure to hPa for plotting
        if hasattr(hybrid_data, 'metpy') and hasattr(hybrid_data.metpy, 'convert_units'):
            hybrid_data = hybrid_data.metpy.convert_units('hPa')

        # Get 2D mesh for plotting
        y_levels_2d = hybrid_data.values
        is_pressure = True
        ax.set_ylabel("Pressure (hPa)")

        # Check if we have valid pressure data
        if np.isnan(y_levels_2d).all():
            raise ValueError("All pressure values are NaN")
    except Exception as e:
        print(f"Error preparing pressure data: {e}")
        print("Falling back to using level indices instead.")
        # Fall back to using level indices
        num_levels = len(cross[hybrid_level_name])
        y_coords_vals = np.arange(1, num_levels + 1)
        y_levels_2d = np.tile(y_coords_vals[:, np.newaxis], (1, len(x_coords)))
        ax.set_ylabel("Model Level")
        is_pressure = False

# For X dimension, create a 2D mesh of longitude values
x_levels_2d = np.tile(x_coords, (len(cross[hybrid_level_name]), 1))

# Check data dimensions
print(f"X dimensions: {x_levels_2d.shape}")
print(f"Y dimensions: {y_levels_2d.shape}")
print(f"Temperature dimensions: {cross['plot_temperature'].shape}")

# Plot Selected Temperature
if cross.get('plot_temperature') is not None:
    print(f"Plotting {plot_title}...")

    # Use 2D meshes for coordinates
    temp_contourf = ax.contourf(
        x_levels_2d, y_levels_2d, cross['plot_temperature'].values,
        levels=contour_levels, cmap=cmap_style, extend='both',
        alpha=0.7, zorder=1
    )
    temp_contour = ax.contour(
        x_levels_2d, y_levels_2d, cross['plot_temperature'].values,
        levels=contour_levels, colors='black', linewidths=0.5,
        zorder=2
    )
    cbar = fig.colorbar(temp_contourf, ax=ax, pad=0.02, aspect=30)
    cbar.set_label(plot_title)
else:
    print("Temperature data not available for plotting.")
    sys.exit(1)

# --- Plot Terrain (if available) ---
terrain_pressure_plot = cross.get('terrain_pressure', None)

if terrain_pressure_plot is not None and not terrain_pressure_plot.isnull().all():
    print("Plotting terrain...")
    try:
        # Extract terrain values
        try:
            terrain_pressure_vals = terrain_pressure_plot.metpy.magnitude
        except AttributeError:
            terrain_pressure_vals = terrain_pressure_plot.values

        # Use bottom row of the 2D mesh for x coordinates
        terrain_x = x_coords

        # Plot terrain
        if is_pressure:
            # For pressure coordinates, larger values are at the bottom
            terrain_max = np.nanmax(y_levels_2d) * 1.05
            ax.fill_between(
                terrain_x,
                terrain_pressure_vals,
                terrain_max,
                facecolor='saddlebrown',
                alpha=1.0,
                zorder=10
            )
        else:
            # For level indices, larger values are at the top
            terrain_y = np.ones_like(terrain_x) * np.nanmax(y_levels_2d)
            ax.fill_between(
                terrain_x,
                0,  # Bottom of plot
                1,  # Small height
                facecolor='saddlebrown',
                alpha=1.0,
                transform=ax.get_xaxis_transform(),  # This plots in axes coordinates
                zorder=10
            )
    except Exception as e:
        print(f"ERROR plotting terrain: {e}")
        import traceback
        traceback.print_exc()
else:
    print("WARNING: Terrain data missing or invalid. Terrain not plotted.")

# --- Optional: Plot Wind Barbs ---
if 'tangential_wind' in cross and 'normal_wind' in cross:
    print("Plotting wind barbs...")
    try:
        # Define Subsampling Slices
        skip_x = max(1, len(x_coords) // 20)  # Aim for about 20 barbs across
        skip_y = max(1, len(cross[hybrid_level_name]) // 10)  # Aim for about 10 levels

        # Create subsampled meshgrid
        x_sub = x_levels_2d[::skip_y, ::skip_x]
        y_sub = y_levels_2d[::skip_y, ::skip_x]

        # Get wind components
        u_barbs = cross['tangential_wind'].values[::skip_y, ::skip_x]
        v_barbs = cross['normal_wind'].values[::skip_y, ::skip_x]

        # Plot barbs
        ax.barbs(
            x_sub, y_sub, u_barbs, v_barbs,
            length=6, pivot='middle', color='brown',
            zorder=5, alpha=0.7
        )
    except Exception as e:
        print(f"ERROR plotting wind barbs: {e}")
        import traceback
        traceback.print_exc()
else:
    print("Wind data not found in dataset. Skipping wind barb plotting.")

# --- Axis Configuration ---
print("Configuring axes...")

if is_pressure:
    # Use log scale for pressure axis and invert (higher pressure at bottom)
    ax.set_yscale('log')

    # Determine pressure limits from data
    valid_pressures = y_levels_2d[~np.isnan(y_levels_2d)]
    if len(valid_pressures) > 0:
        y_min = np.nanmin(valid_pressures) * 0.95
        y_max = np.nanmax(valid_pressures) * 1.05

        # Override with user preferences if provided
        if 'user_y_bottom' in locals() and 'user_y_top' in locals():
            y_max = user_y_bottom  # Bottom limit (higher pressure)
            y_min = user_y_top     # Top limit (lower pressure)

        print(f"Setting y-axis limits: {y_min} to {y_max} hPa")
        ax.set_ylim(y_max, y_min)  # Inverted for pressure

        # Set up pressure ticks
        if y_max - y_min > 300:
            # Wider range, use standard pressure levels
            y_ticks = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100]
        else:
            # Narrower range, use finer intervals
            y_ticks = np.arange(np.ceil(y_min/50)*50, np.floor(y_max/50)*50 + 1, 50)

        y_ticks = y_ticks[(y_ticks >= y_min) & (y_ticks <= y_max)]
        ax.set_yticks(y_ticks)
        ax.set_yticklabels([f'{int(tick)}' for tick in y_ticks])
    else:
        print("WARNING: No valid pressure values found. Using default y-axis settings.")
else:
    # For level indices, higher values usually mean lower in atmosphere (closer to ground)
    y_min = np.nanmin(y_levels_2d)
    y_max = np.nanmax(y_levels_2d)
    ax.set_ylim(y_max, y_min)  # Typically inverted for model levels

    # Set ticks to be integer level values
    level_range = int(y_max - y_min)
    if level_range > 20:
        # If many levels, show fewer ticks
        y_ticks = np.linspace(y_min, y_max, 10).astype(int)
    else:
        # Show all levels if there aren't too many
        y_ticks = np.arange(int(y_min), int(y_max) + 1)

    ax.set_yticks(y_ticks)
    ax.set_yticklabels([f'{int(tick)}' for tick in y_ticks])

# Set labels and title
ax.set_xlabel("Longitude (°E)")

# Fix the time formatting for the title
# Handle zero-dimensional array properly
try:
    if hasattr(cross["time"], 'dt'):
        # For datetime64 objects with dt accessor
        if cross["time"].values.ndim == 0:
            # For 0-dimensional arrays, use item() instead of indexing
            time_str = cross["time"].dt.strftime("%Y-%m-%d %H:%M UTC").item()
        else:
            # For array-like time values, use index
            time_str = cross["time"].dt.strftime("%Y-%m-%d %H:%M UTC").values[0]
    else:
        # Fallback to using the analysis_date
        time_str = analysis_date.strftime("%Y-%m-%d %H:%M UTC")
except Exception as e:
    print(f"Error formatting time: {e}")
    # Use the input date as fallback
    time_str = analysis_date.strftime("%Y-%m-%d %H:%M UTC")

ax.set_title(
    f'{model_name.upper()} {plot_title} Cross-Section on Native Model Levels\n'
    f'From {start_point} to {end_point}\n'
    f'Valid: {time_str}'
)

plt.tight_layout()
plt.show()
plt.savefig(output_filename, dpi=250, bbox_inches='tight')
print(f"Plot saved to {output_filename}")
plt.close(fig)

print("Script completed successfully!")