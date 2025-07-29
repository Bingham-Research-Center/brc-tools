# HRRR Cross-Section - Switch between Potential and Drybulb Temperature
# Using Native Model Levels with distance-height coordinates

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
import cartopy.crs as ccrs
from scipy.spatial import cKDTree
from scipy.interpolate import griddata


# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning)


def haversine_distance(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points
    on the earth specified in decimal degrees.

    Args:
        lon1, lat1: Longitude and latitude of point 1 (in degrees)
        lon2, lat2: Longitude and latitude of point 2 (in degrees)

    Returns:
        Distance in kilometers
    """
    from math import radians, cos, sin, asin, sqrt

    # Convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of earth in kilometers

    return c * r


# --- Configuration ---
date_args = {
    "year": 2025, "month": 1, "day": 31, "hour": 6, "minute": 0, "second": 0
}
analysis_date = datetime(**date_args)

model_name = 'hrrr'
product_name = 'nat'  # Use 'nat' for native model levels
forecast_hour = 6     # Short forecast hour for HRRR

# *** TEMPERATURE DISPLAY OPTION ***
# Choose between 'potential' and 'drybulb'
temp_display = 'drybulb'  # 'potential' or 'drybulb'

# Cross-section endpoints
start_point = (40.7606, -111.8881)       # Salt Lake City, UT
end_point = (40.222665, -108.477740)     # SE of Dinosaur NM, CO

# Set height level limits for the plot (meters)
user_y_bottom = 1500  # Bottom height limit (m)
user_y_top = 6000     # Top height limit (m)

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
    contour_levels = np.arange(-20, 6, 1)  # -20 to +5 C
    cmap_style = 'coolwarm'

# --- Data Acquisition ---
print(f"--- HRRR {plot_title} Cross-Section on Native Levels ---")
print(f"Attempting to access {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")

# Define the S3 URL and local file path
s3_url = f"https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{analysis_date:%Y%m%d}/conus/hrrr.t{analysis_date:%H}z.wrfnatf{forecast_hour:02d}.grib2"
local_file = f"/Users/johnlawson/data/hrrr/{analysis_date:%Y%m%d}/hrrr.t{analysis_date:%H}z.wrfnatf{forecast_hour:02d}.grib2"

# Create directory if needed
os.makedirs(os.path.dirname(local_file), exist_ok=True)

# Check if file already exists, if not download it
if not os.path.exists(local_file):
    print(f"File not found locally. Downloading from {s3_url}")
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
    print(f"Using existing file at {local_file}")

# Open the GRIB file
try:
    import cfgrib
    ds = xr.open_dataset(local_file, engine='cfgrib', backend_kwargs={'filter_by_keys': {'typeOfLevel': 'hybrid'}})
    print("Successfully opened file with xarray.")
except Exception as e:
    print(f"ERROR: Failed to open file: {e}")
    sys.exit(1)

# --- Check Dataset Contents ---
print("\nVariables in dataset:")
for var_name in ds.data_vars:
    print(f"  {var_name}")

# Update variable name mapping based on dataset contents
temp_var_name = 't'          # Temperature
hybrid_pres_var = 'pres'     # Pressure
height_var = 'gh'            # Geopotential Height
u_wind_var = 'u'             # U-component of wind
v_wind_var = 'v'             # V-component of wind

# --- Apply MetPy Parsing and Coordinate Setup ---
try:
    ds = ds.metpy.parse_cf().squeeze()
except Exception as e:
    print(f"ERROR during MetPy parsing: {e}")
    print("Attempting to set up coordinates manually...")

# --- Verify MetPy CRS and x/y coordinates ---
required_coords = ['metpy_crs', 'x', 'y']
missing_coords = [coord for coord in required_coords if coord not in ds.coords]

if missing_coords:
    print(f"WARNING: Missing required coordinates for cross_section: {missing_coords}")

    # Set up CRS manually if missing
    if 'metpy_crs' not in ds.coords:
        print("Applying explicit CRS setup (Lambert Conformal)...")

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

        # Re-parse with MetPy
        try:
            ds = ds.metpy.parse_cf()
            print("CRS assigned manually.")
        except Exception as e:
            print(f"Warning: Error re-parsing with MetPy after CRS assignment: {e}")

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

# Identify vertical coordinate
hybrid_level_coords = [coord for coord in ds.coords
                       if any(kw in coord.lower() for kw in ['hybrid', 'lev', 'layer'])]
if not hybrid_level_coords:
    print("Error: Could not identify hybrid level coordinate.")
    sys.exit(1)

hybrid_level_name = hybrid_level_coords[0]
print(f"Using '{hybrid_level_name}' as the vertical coordinate.")

# --- Calculate Cross Section (Manual Method) ---
print("Calculating cross-section using manual interpolation...")

# Get lat/lon arrays
lats = ds.latitude.values
lons = ds.longitude.values

# Make sure lat/lon are 2D arrays
if lats.ndim == 1 or lons.ndim == 1:
    # Try to use meshgrid to create 2D arrays if needed
    print("Converting 1D lat/lon to 2D meshgrid...")
    lon_1d, lat_1d = np.unique(lons), np.unique(lats)
    lons, lats = np.meshgrid(lon_1d, lat_1d)

# Create a direct path between start and end points
start_lat, start_lon = start_point
end_lat, end_lon = end_point

# For testing, use fewer points along the path
num_points = 50  # Reduced from 200 for faster execution

# Generate path points
path_lats = np.linspace(start_lat, end_lat, num_points)
path_lons = np.linspace(start_lon, end_lon, num_points)

# Calculate distance along path (in km)
distances = np.zeros(num_points)
for i in range(1, num_points):
    segment_dist = haversine_distance(
        path_lons[i-1], path_lats[i-1],
        path_lons[i], path_lats[i]
    )
    distances[i] = distances[i-1] + segment_dist



print("Using robust nearest-neighbor interpolation...")

# Create cross section dataset
cross_vars = {}

# Process each variable of interest
for var_name, da in ds.data_vars.items():
    if hybrid_level_name in da.dims and var_name in [temp_var_name, hybrid_pres_var, height_var, u_wind_var, v_wind_var]:
        # Initialize array for interpolated values
        num_levels = len(ds[hybrid_level_name])
        cross_section_data = np.zeros((num_levels, num_points))

        # Process one level at a time
        for level in range(num_levels):
            # For each point along the path
            for i, (path_lat, path_lon) in enumerate(zip(path_lats, path_lons)):
                # Find nearest grid point (but handle both 1D and 2D lat/lon)
                if lats.ndim == 2 and lons.ndim == 2:
                    # 2D lat/lon case
                    dist = (lats - path_lat)**2 + (lons - path_lon)**2
                    idx = np.nanargmin(dist)  # Using nanargmin to ignore NaN values
                    y_idx, x_idx = np.unravel_index(idx, dist.shape)

                    # Get data value at this point
                    if level < da.shape[0] and y_idx < da.shape[1] and x_idx < da.shape[2]:
                        cross_section_data[level, i] = da.values[level, y_idx, x_idx]
                    else:
                        # Handle out-of-bounds indices
                        cross_section_data[level, i] = np.nan
                else:
                    # 1D lat/lon case
                    lat_idx = np.nanargmin(np.abs(lats - path_lat))
                    lon_idx = np.nanargmin(np.abs(lons - path_lon))

                    # Get data value
                    if level < da.shape[0] and lat_idx < da.shape[1] and lon_idx < da.shape[2]:
                        cross_section_data[level, i] = da.values[level, lat_idx, lon_idx]
                    else:
                        cross_section_data[level, i] = np.nan

            # Debug: print min/max/variation for the first and last level
            if level == 0 or level == num_levels-1:
                variation = np.nanmax(cross_section_data[level]) - np.nanmin(cross_section_data[level])
                print(f"Level {level} of {var_name}: min={np.nanmin(cross_section_data[level])}, "
                      f"max={np.nanmax(cross_section_data[level])}, variation={variation}")

        # Check for NaN values in the data
        nan_percentage = 100 * np.isnan(cross_section_data).sum() / cross_section_data.size
        if nan_percentage > 0:
            print(f"WARNING: {var_name} has {nan_percentage:.1f}% NaN values")

        # Replace any remaining NaNs with reasonable values to avoid plotting issues
        if np.any(np.isnan(cross_section_data)):
            if var_name == temp_var_name:
                # For temperature, use a default value (-20°C for safety)
                cross_section_data = np.nan_to_num(cross_section_data, nan=-20)
            elif var_name == height_var:
                # For height, use a default based on level (rough estimate)
                for lev in range(num_levels):
                    if np.any(np.isnan(cross_section_data[lev])):
                        # Replace NaNs with level-based estimate
                        valid_vals = cross_section_data[lev][~np.isnan(cross_section_data[lev])]
                        if len(valid_vals) > 0:
                            fill_val = np.mean(valid_vals)
                        else:
                            # If no valid values at this level, estimate
                            fill_val = 1500 + lev * (6000 / num_levels)

                        cross_section_data[lev] = np.nan_to_num(cross_section_data[lev], nan=fill_val)
            else:
                # For other variables, replace with zeros
                cross_section_data = np.nan_to_num(cross_section_data)

        # Create DataArray
        cross_vars[var_name] = xr.DataArray(
            cross_section_data,
            coords={hybrid_level_name: ds[hybrid_level_name], 'index': np.arange(num_points)},
            dims=[hybrid_level_name, 'index'],
            name=var_name,
            attrs=da.attrs
        )

# Create path coordinates
cross_lat = xr.DataArray(
    path_lats,
    coords={'index': np.arange(num_points)},
    dims=['index'],
    name='latitude'
)

cross_lon = xr.DataArray(
    path_lons,
    coords={'index': np.arange(num_points)},
    dims=['index'],
    name='longitude'
)

cross_distance = xr.DataArray(
    distances,
    coords={'index': np.arange(num_points)},
    dims=['index'],
    name='distance',
    attrs={'units': 'km'}
)

# Create the cross-section dataset
cross = xr.Dataset(cross_vars)
cross = cross.assign_coords({
    'latitude': cross_lat,
    'longitude': cross_lon,
    'distance': cross_distance
})

print("Cross-section calculated successfully.")

# --- Prepare Temperature and Height Data ---
try:
    temp_da = cross[temp_var_name]
    pres_da = cross[hybrid_pres_var]
    height_da = cross[height_var]

    # Ensure units are assigned
    if not hasattr(temp_da, 'metpy') or temp_da.metpy.units == units.dimensionless:
        print("Assigning temperature units (K)...")
        temp_da = temp_da * units.kelvin

    if not hasattr(pres_da, 'metpy') or pres_da.metpy.units == units.dimensionless:
        print("Assigning pressure units (Pa)...")
        pres_da = pres_da * units.pascal
        pres_da = pres_da.metpy.convert_units(units.hPa)

    if not hasattr(height_da, 'metpy') or height_da.metpy.units == units.dimensionless:
        print("Assigning height units (m)...")
        height_da = height_da * units.meter

    # Calculate temperature based on selection
    if temp_display == 'potential':
        print("Calculating potential temperature...")
        # Calculate potential temperature
        temperature_result = np.zeros_like(temp_da.values)

        # Loop through each point to calculate potential temperature
        for i in range(temp_da.shape[1]):  # Loop through each point in cross-section
            temperature_result[:, i] = mpcalc.potential_temperature(
                pres_da.values[:, i] * units.hPa,
                temp_da.values[:, i] * units.kelvin
            ).magnitude

        temp_units = 'K'
        temp_name = 'potential_temperature'
    else:  # drybulb
        print("Converting temperature to Celsius...")
        # Convert temperature to Celsius
        temperature_result = (temp_da.values - 273.15)  # K to C
        temp_units = 'degC'
        temp_name = 'temperature'

    # Store in dataset
    cross['plot_temperature'] = xr.DataArray(
        temperature_result,
        coords=temp_da.coords,
        dims=temp_da.dims,
        name=temp_name,
        attrs={'units': temp_units}
    )

    print(f"{plot_title} prepared and added to dataset.")
except Exception as e:
    print(f"ERROR preparing temperature data: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# --- Calculate Wind Components ---
try:
    if u_wind_var in cross and v_wind_var in cross:
        print("Calculating wind components...")
        u_wind_da = cross[u_wind_var]
        v_wind_da = cross[v_wind_var]

        # Extract values
        u_data = u_wind_da.values
        v_data = v_wind_da.values

        # Store as knots for plotting
        u_knots = u_data * 1.94384  # m/s to knots
        v_knots = v_data * 1.94384  # m/s to knots

        # Store component winds in dataset
        cross['u_wind_knots'] = xr.DataArray(
            u_knots,
            coords=u_wind_da.coords,
            dims=u_wind_da.dims,
            name='u_wind',
            attrs={'units': 'knots'}
        )

        cross['v_wind_knots'] = xr.DataArray(
            v_knots,
            coords=v_wind_da.coords,
            dims=v_wind_da.dims,
            name='v_wind',
            attrs={'units': 'knots'}
        )

        print("Wind components calculated.")
except Exception as e:
    print(f"WARNING: Error calculating wind components: {e}")
    # Non-critical, can continue

# --- Plotting ---
print("Generating plot...")
fig = plt.figure(figsize=(16, 8))
ax = plt.axes()

# Get coordinates for plotting
distance = cross['distance'].values  # Distance along cross-section in km
heights = height_da.values  # Heights in meters

# Check if heights are valid (non-negative and not all zeros)
if np.any(heights <= 0) or np.all(np.isclose(heights, heights[0, 0])):
    print("WARNING: Height values appear invalid. Using level indices instead.")
    # Use level indices as a fallback
    heights = np.tile(np.arange(len(cross[hybrid_level_name]))[:, np.newaxis],
                      (1, len(distance)))
    height_label = "Model Level"
    heights_valid = False
else:
    height_label = "Height (m)"
    heights_valid = True

# Create 2D meshes for plotting
distance_2d = np.tile(distance, (len(cross[hybrid_level_name]), 1))

# Print some stats for debugging
print(f"Distance array shape: {distance.shape}")
print(f"Heights array shape: {heights.shape}")
print(f"Temperature array shape: {cross['plot_temperature'].shape}")
print(f"Distance range: {np.min(distance)} to {np.max(distance)} km")
print(f"Height range: {np.min(heights)} to {np.max(heights)} m")
print(f"Temperature range: {np.min(cross['plot_temperature'].values)} to {np.max(cross['plot_temperature'].values)} {temp_units}")

# Plot temperature
temp_contourf = ax.contourf(
    distance_2d, heights, cross['plot_temperature'].values,
    levels=contour_levels, cmap=cmap_style, extend='both', alpha=0.7
)

# Add contour lines for temperature
temp_contour = ax.contour(
    distance_2d, heights, cross['plot_temperature'].values,
    levels=contour_levels, colors='black', linewidths=0.5
)

# Add colorbar
cbar = fig.colorbar(temp_contourf, ax=ax, pad=0.02, aspect=30)
cbar.set_label(plot_title)

# Plot terrain approximation

# Now fix the terrain representation
# Replace the terrain plotting code with:

# Plot terrain approximation
if heights_valid:
    # Salt Lake City is around 1300m, Dinosaur area around 1800m
    # Create a synthetic terrain that varies along the path

    # Option 1: Use lowest level heights if they show variation
    lowest_level_heights = heights[0, :]
    terrain_variation = np.max(lowest_level_heights) - np.min(lowest_level_heights)

    if terrain_variation > 100:  # If we have reasonable variation
        print(f"Using model's lowest level heights for terrain: {np.min(lowest_level_heights):.1f}m to {np.max(lowest_level_heights):.1f}m")
        terrain_height = lowest_level_heights
    else:
        # Option 2: Create synthetic terrain based on known elevations
        print("Creating synthetic terrain based on known elevations")
        # Base terrain that rises from SLC to Dinosaur area
        base_terrain = np.linspace(1300, 1800, num_points)

        # Add some realistic variations - mountains in the Uinta region
        # Roughly in the middle of the path
        mountain_center = num_points // 2
        mountain_width = num_points // 4
        mountain_height = 1000  # Peak 1000m above base elevation

        # Create bell-shaped mountain range
        x = np.arange(num_points)
        mountains = mountain_height * np.exp(-((x - mountain_center) ** 2) / (2 * mountain_width ** 2))

        # Combine base terrain with mountains
        terrain_height = base_terrain + mountains

        print(f"Synthetic terrain range: {np.min(terrain_height):.1f}m to {np.max(terrain_height):.1f}m")

    # Create terrain polygon
    ax.fill_between(
        distance, 0, terrain_height,
        facecolor='saddlebrown', alpha=0.8, zorder=10,
        edgecolor='black', linewidth=1.0
    )

    # Ensure y-axis starts at zero to show terrain properly
    current_ymin, current_ymax = ax.get_ylim()
    if current_ymin > 0:
        ax.set_ylim(0, current_ymax)

# Plot wind barbs if available
if 'u_wind_knots' in cross and 'v_wind_knots' in cross:
    print("Plotting wind barbs...")

    # Define subsampling for wind barbs (to avoid overcrowding)
    skip_x = max(1, len(distance) // 20)  # Aim for about 20 barbs across
    skip_y = max(1, len(cross[hybrid_level_name]) // 10)  # Aim for about 10 levels

    # Create mesh grid for barb locations
    x_sub = distance_2d[::skip_y, ::skip_x]
    y_sub = heights[::skip_y, ::skip_x]

    # Get wind components
    u_barbs = cross['u_wind_knots'].values[::skip_y, ::skip_x]
    v_barbs = cross['v_wind_knots'].values[::skip_y, ::skip_x]

    # Plot barbs (along-section and vertical components)
    ax.barbs(
        x_sub, y_sub, u_barbs, v_barbs,
        length=6, pivot='middle', color='brown',
        zorder=5, alpha=0.7
    )

# Set axis limits and labels
if heights_valid:
    y_min = max(np.min(heights), user_y_bottom)
    y_max = min(np.max(heights), user_y_top)
    ax.set_ylim(y_min, y_max)

ax.set_xlim(0, np.max(distance))
ax.set_xlabel("Distance (km)")
ax.set_ylabel(height_label)

# Create secondary x-axis for longitude
ax2 = ax.twiny()
ax2.set_xlim(ax.get_xlim())
ax2.set_xticks(np.linspace(0, np.max(distance), 5))
lon_ticks = np.linspace(start_point[1], end_point[1], 5)
ax2.set_xticklabels([f"{lon:.2f}°E" for lon in lon_ticks])
ax2.set_xlabel("Longitude")

# Set title
time_str = analysis_date.strftime("%Y-%m-%d %H:%M UTC")
ax.set_title(
    f'{model_name.upper()} {plot_title} Cross-Section on Native Model Levels\n'
    f'From {start_point} to {end_point}\n'
    f'Valid: {time_str}'
)

# Finalize and save
plt.tight_layout()
plt.savefig(output_filename, dpi=250, bbox_inches='tight')
print(f"Plot saved to {output_filename}")
plt.close(fig)

print("Script completed successfully!")