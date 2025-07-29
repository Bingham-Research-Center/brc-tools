# Script 2: NAM Midwest Cross-Section (Custom Styling - Revised)
import sys

import cmocean
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import metpy.calc as mpcalc
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from metpy.units import units
from metpy.interpolate import cross_section
from herbie import Herbie
from datetime import datetime
import warnings
import pint # Required for unit handling

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning)

# --- Configuration ---
date_args = {
    "year": 2025, "month": 1, "day": 31, "hour": 6, "minute": 0, "second": 0
}
analysis_date = datetime(**date_args)
model_name = 'nam'
# NAM product names can vary. 'conusnest.hiresf' is a common one.
# Check Herbie inventory if this fails for your chosen date.

# Gemini says this might also be "nam"?
product_name = 'conusnest.hiresf'
forecast_hour = 6
# Provo, UT
start_point = (40.30, -111.86)
# SE of Dinosaur NM, CO, co. line
# Rangely, CO
end_point = (40.08, -108.79)

# Variables to fetch (Temperature, Height on pressure levels, Surface Pressure)
# Using common NAM GRIB patterns - check inventory if needed
# TMP: Temperature, HGT: Geopotential Height, PRES: Pressure
search_pattern = r":(?:TMP|HGT):\d+ mb|:PRES:surface:"

# Plotting
plot_top_pressure = 650
plot_bottom_pressure = 900

theta_levels = np.arange(260, 311, 2)
cmap_style = cmocean.cm.thermal

### FUNCTIONS ###

def prepare_terrain_data(cross, sfc_pres_var_name):
    """
    Prepare terrain data using a surface pressure variable.

    Args:
        cross (xr.Dataset): The xarray dataset containing cross-section data.
        sfc_pres_var_name (str): The name of the surface pressure variable.

    Returns:
        xr.Dataset: The updated dataset including the terrain pressure DataArray.
    """
    print("Preparing terrain data...")
    terrain_pressure_hpa = None  # Initialize

    if sfc_pres_var_name and (sfc_pres_var_name in cross):
        print(f"Using surface pressure variable \\{sfc_pres_var_name}\\ for terrain.")
        sp_da = cross[sfc_pres_var_name]

        # Check/Assign units (NAM surface pressure is often Pascals)
        if 'units' not in sp_da.attrs or sp_da.metpy.units == units.dimensionless:
            print(f"Assigning units to surface pressure \\{sfc_pres_var_name}\\ (assuming Pa)...")
            sp_da = sp_da.metpy.quantify(units.pascal)
        else:
            print(f"Surface pressure variable \\{sfc_pres_var_name}\\ already has units: {sp_da.metpy.units}")

        # Convert to hPa for plotting consistency with y-axis
        terrain_pressure_hpa = sp_da.metpy.convert_units('hPa')

        # Add to dataset, ensuring coordinates are just the 'index' dim
        cross['terrain_pressure'] = xr.DataArray(
            terrain_pressure_hpa.data,  # Use .data to avoid coordinate conflicts
            coords={'index': cross['index']},  # Only assign the index coordinate
            dims=['index'],
            name='terrain_pressure',
            attrs={'units': 'hPa'}
        )
        print("Terrain pressure (from Surface Pressure) prepared in hPa.")
    else:
        print(f"Surface pressure variable \\{sfc_pres_var_name}\\ not found or not in cross section. Cannot create terrain data.")
        # Assign NaN array or handle appropriately in plotting code
        cross['terrain_pressure'] = xr.DataArray(
            [np.nan] * len(cross['index']),
            coords={'index': cross['index']},
            dims=['index'],
            name='terrain_pressure',
            attrs={'units': 'hPa'}
        )
    return cross

# --- Data Acquisition ---
print(f"Attempting to access {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")
H = Herbie(
    analysis_date,
    model=model_name,
    product=product_name,
    fxx=forecast_hour,
    save_dir='/Users/johnlawson/data/temp_python/xsection',
    verbose=False # Set to True for more Herbie download details
)

# Download and load data into xarray
ds_raw = H.xarray(search_pattern, verbose=False, remove_grib=False)

# --- FIX: Handle list output from H.xarray ---
if isinstance(ds_raw, list):
    print("Herbie returned a list of datasets, attempting merge...")
    # Ensure all items are datasets before merging
    if all(isinstance(item, xr.Dataset) for item in ds_raw):
        ds = xr.merge(ds_raw)
        print("Datasets merged successfully.")
    else:
        print("Error: Not all items in the list were xarray Datasets.")
        exit()
elif isinstance(ds_raw, xr.Dataset):
    ds = ds_raw # Already a dataset
else:
    print(f"Error: Unexpected data type returned by H.xarray: {type(ds_raw)}")
    exit()

print("Data loaded successfully.")

# --- MetPy Parsing and Coordinate Setup ---
print("Parsing CF conventions and setting up coordinates...")
# Ensure parse_cf is called on the final dataset
# Squeeze might not be needed if dimensions are correct, but generally safe
ds = ds.metpy.parse_cf().squeeze()

# *** Coordinate Verification and Fixing ***
print("\n--- Dataset structure after parse_cf ---")
# print(ds) # Keep this commented unless debugging deep issues
print("--- Coordinates after parse_cf ---")
print(ds.coords)

required_coords = ['metpy_crs', 'x', 'y'] # Need projection grid coords
missing_coords = [coord for coord in required_coords if coord not in ds.coords]

if missing_coords:
    print(f"WARNING: Missing required coordinates for cross_section: {missing_coords}")
    # Attempt to assign CRS if missing (NAM is Lambert Conformal)
    if 'metpy_crs' not in ds.coords:
        print("Attempting to assign standard NAM CRS (Lambert Conformal)...")
        # These parameters are typical for NAM CONUS, verify if needed
        # (Check GRIB file metadata or official NAM docs if unsure)
        nam_crs_params = {
            "grid_mapping_name": "lambert_conformal_conic",
            "latitude_of_projection_origin": 25.0,
            "longitude_of_central_meridian": 265.0, # 265.0 == -95.0 W
            "standard_parallel": (25.0, 25.0),
            "earth_radius": 6371229.0,
        }
        try:
            ds = ds.metpy.assign_crs(nam_crs_params, write_coords=True)
            print("Assigned CRS. Re-checking coordinates...")
            print(ds.coords)
        except Exception as e:
            print(f"ERROR assigning CRS: {e}. Cannot proceed.")
            sys.exit(1)


    # If x/y are missing but lat/lon exist, assign x/y based on CRS
    # Note: parse_cf should ideally find x/y if they are dimension coords
    if ('x' not in ds.coords or 'y' not in ds.coords) and 'metpy_crs' in ds.coords:
        if 'latitude' in ds.coords and 'longitude' in ds.coords:
            print("Attempting to assign y/x dimension coordinates from lat/lon...")
            try:
                ds = ds.metpy.assign_y_x()
                print("Assigned y/x. Coordinates:")
                print(ds.coords)
            except Exception as e:
                print(f"ERROR assigning y/x coordinates: {e}. Cannot proceed.")
                sys.exit(1)

        else:
            print("ERROR: Cannot assign y/x without latitude/longitude coordinates.")
            sys.exit(1)

    # Final check
    missing_coords = [coord for coord in required_coords if coord not in ds.coords]
    if missing_coords:
        print(f"ERROR: Still missing required coordinates after attempting fixes: {missing_coords}")
        sys.exit(1)
    else:
        print("Required coordinates ('metpy_crs', 'x', 'y') seem to be present.")



# --- FIX: Dynamically find coordinate and variable names ---
# Find pressure coordinate (common names: isobaric, isobaricX, plev, level)
level_coord_name = next((coord for coord in ds.coords
                         if 'isobaric' in coord.lower() or 'plev' in coord.lower() or 'level' in coord.lower()), None)
if level_coord_name is None:
    print(f"ERROR: Could not identify pressure level coordinate in ds.coords: {list(ds.coords)}")
    exit()
else:
    print(f"Identified pressure coordinate: '{level_coord_name}'")

# Find temperature variable on pressure levels
temp_var_name = next((var for var in ds.data_vars
                      if ('TMP' in var or 't' == var.lower()) and level_coord_name in ds[var].coords), None)
if temp_var_name is None:
    print(f"ERROR: Could not identify temperature variable with coordinate '{level_coord_name}'. Available vars: {list(ds.data_vars)}")
    exit()
else:
    print(f"Identified temperature variable: '{temp_var_name}'")

# Find surface pressure variable (common names: PRES_surface, sp, PSFC)
sfc_pres_var_name = next((var for var in ds.data_vars
                          if 'PRES_surface' in var or 'sp' == var.lower() or 'psfc' == var.lower()), None)
if sfc_pres_var_name:
    print(f"Identified surface pressure variable: '{sfc_pres_var_name}'")
else:
    print("Warning: Could not identify surface pressure variable for terrain.")


# --- Calculate Cross Section ---
print("Calculating cross-section...")
try:
    cross = cross_section(ds, start_point, end_point).set_coords(('latitude', 'longitude'))
    print("Cross-section calculated.")
    # print("Cross section data structure:") # Uncomment to inspect 'cross'
    # print(cross)
except Exception as e:
    print(f"ERROR during cross_section calculation: {e}")
    print("Ensure input data 'ds' has required coordinates (lat, lon, pressure level).")
    exit()


# --- Calculate Potential Temperature ---
print("Calculating potential temperature...")

# Get the DataArrays from the cross-section dataset
temp_da = cross[temp_var_name]
pres_coord = cross[level_coord_name] # This is the 1D coordinate

# --- FIX: Check and assign units ---
if 'units' not in temp_da.attrs or temp_da.metpy.units == units.dimensionless:
    print(f"Assigning units to temperature variable '{temp_var_name}' (assuming Kelvin)...")
    temp_da = temp_da.metpy.quantify(units.kelvin) # NAM Temp is Kelvin
else:
    print(f"Temperature variable '{temp_var_name}' already has units: {temp_da.metpy.units}")

if 'units' not in pres_coord.attrs or pres_coord.metpy.units == units.dimensionless:
    print(f"Assigning units to pressure coordinate '{level_coord_name}' (assuming hPa)...")
    # cfgrib usually converts Pa levels to hPa coordinates named isobaricInhPa etc.
    pres_coord = pres_coord.metpy.quantify(units.hPa)
else:
    print(f"Pressure coordinate '{level_coord_name}' already has units: {pres_coord.metpy.units}")

# --- FIX: Create broadcasted 2D arrays for calculation ---
pres_da_2d, temp_da_2d = xr.broadcast(pres_coord, temp_da)
print(f"Shape after broadcasting - Pressure: {pres_da_2d.shape}, Temperature: {temp_da_2d.shape}")

# Use the broadcasted arrays for the calculation
pressure_for_calc = pres_da_2d.metpy.unit_array
temperature_for_calc = temp_da_2d.metpy.unit_array

potential_temp = mpcalc.potential_temperature(pressure_for_calc, temperature_for_calc)

# Add calculated potential temperature back to the cross dataset
cross['potential_temperature'] = xr.DataArray(
    potential_temp,
    coords=temp_da_2d.coords,
    dims=temp_da_2d.dims,
    name='potential_temperature',
    attrs={'units': str(potential_temp.units)}
)
print("Potential temperature calculated and added to dataset.")


# --- Prepare Terrain Data (Using Surface Pressure) ---
cross = prepare_terrain_data(cross, sfc_pres_var_name)

# --- Plotting ---
print("Generating plot...")
fig = plt.figure(figsize=(12, 8))
ax = plt.axes()

# Define plot coordinates
x_coords = cross['longitude'] # Use longitude for x-axis
y_coords = cross[level_coord_name] # Pressure levels coordinate

# Define potential temperature contour levels and colormap

# --- Plot Potential Temperature using filled contours (contourf) ---
print("Plotting Potential Temperature (filled contours)...")
theta_contourf = ax.contourf(
    x_coords, y_coords, cross['potential_temperature'],
    levels=theta_levels, cmap=cmap_style, extend='both',
    alpha=0.5,
)

theta_contour = ax.contour(
    x_coords, y_coords, cross['potential_temperature'],
    levels=theta_levels, colors='black', linewidths=0.5,
)

# Add a colorbar
cbar = fig.colorbar(theta_contourf, ax=ax, pad=0.02, aspect=30)
cbar.set_label(f"Potential Temperature ({cross['potential_temperature'].attrs.get('units', 'K')})")

# Optional: Overlay line contours for emphasis
# theta_contour = ax.contour(
#     x_coords, y_coords, cross['potential_temperature'],
#     levels=theta_levels[::5], colors='white', linewidths=0.5, alpha=0.7
# )


# --- Plot Terrain ---
terrain_pressure_plot = cross.get('terrain_pressure', None)
y_bottom_pressure = y_coords.max().item() # Max pressure (~1000 hPa), float
y_top_pressure = y_coords.min().item()   # Min plot pressure (~100 hPa), float

if terrain_pressure_plot is not None and not terrain_pressure_plot.isnull().all():
    print("Plotting terrain...")

    # --- FIX: Explicitly get magnitude for comparison and plotting ---
    terrain_pint_array = terrain_pressure_plot.data
    terrain_magnitudes = terrain_pint_array.magnitude
    where_condition = terrain_magnitudes >= y_top_pressure # Compare unitless array >= float

    ax.fill_between(
        x_coords.data,                  # Use.data for x-coordinates
        terrain_magnitudes,             # Use unitless magnitudes for y-values
        y_bottom_pressure,              # Base level for fill
        where=where_condition,
        facecolor='darkgrey',           # Darker grey from original Script 2
        interpolate=True,
        zorder=5                        # Ensure terrain is behind contours
    )
else:
    print("WARNING: Terrain data is missing or invalid. Terrain not plotted.")


# --- Axis Configuration ---
print("Configuring axes...")




ax.set_yscale('log') # Use log scale for pressure
ax.set_ylim(plot_bottom_pressure, plot_top_pressure) # Set limits from max pressure down to min pressure
# Define y-ticks (adjust range based on NAM levels if needed)
yticks = np.arange(int(plot_bottom_pressure // 100 * 100), plot_top_pressure, -100)
ax.set_yticks(yticks)
ax.set_yticklabels([str(int(p)) for p in yticks])

# string for approximate or exact horizontal grid spacing
# can we get this from the xarray dataset?
deltax = abs(x_coords.max().item() - x_coords.min().item()) / len(x_coords)
deltax_str = f"{int(deltax)}" if deltax.is_integer() else f"{deltax:.1f}"

# --- Labels and Title ---
ax.set_xlabel(f"Longitude ({x_coords.min().item():.1f}°E to {x_coords.max().item():.1f}°E)")
ax.set_ylabel(f"Pressure ({y_coords.attrs.get('units', 'hPa')})")
ax.set_title(
    f'{model_name.upper()} Potential Temperature (K): {deltax_str}-km grid spacing\n'
    f'From {start_point} to {end_point}\n'
    f'Valid: {cross["valid_time"].dt.strftime("%Y-%m-%d %H:%M UTC").item()}' # Use UTC
)
ax.grid(True, linestyle='--', alpha=0.3) # Grid style from original Script 2

plt.tight_layout()
plt.show()

# Plot a new image
# It will be a top-down view of Utah, showing a maroon line
# of the path of this cross section through the map of Utah.
# This helps to contextualise the cross section.
# The left point on the cross section above is the westernmost point in the
# cross-section transect and nominally point "A".

fig = plt.figure(figsize=(10, 8))
map_proj = ccrs.Mercator(central_longitude=-95)
data_proj = ccrs.PlateCarree()
ax = plt.axes(projection=map_proj)
ax.set_extent([-112.3, -108.5, 40.0, 41.5], crs=data_proj)
ax.add_feature(cfeature.LAND.with_scale('10m'), edgecolor='black', facecolor='#F0F0F0', zorder=0)
ax.add_feature(cfeature.OCEAN.with_scale('10m'), edgecolor='black', facecolor='#D6EAF8', zorder=0)
ax.add_feature(cfeature.LAKES.with_scale('10m'), edgecolor='black', facecolor='#D6EAF8', zorder=1)
ax.add_feature(cfeature.STATES.with_scale('10m'), linewidth=0.5, edgecolor='dimgray', zorder=2)
ax.add_feature(cfeature.BORDERS.with_scale('10m'), linewidth=0.7, edgecolor='black', zorder=3)
counties = cfeature.NaturalEarthFeature(category='cultural', name='admin_2_counties', scale='10m', facecolor='none')
ax.add_feature(counties, edgecolor='darkgray', linewidth=0.3, zorder=3)
ax.coastlines(resolution='10m', color='black', linewidth=0.8, zorder=4)

# Plot the cross-section path
# Convert start and end points to the map projection
start_point_proj = map_proj.transform_point(start_point[1], start_point[0], src_crs=data_proj)
end_point_proj = map_proj.transform_point(end_point[1], end_point[0], src_crs=data_proj)
# Plot the path
ax.plot(
    [start_point_proj[0], end_point_proj[0]],
    [start_point_proj[1], end_point_proj[1]],
    color='maroon', linewidth=2, zorder=5,
    label='Cross Section Path'
)

# Use surface pressure and the height variable to plot terrain for the Utah area
# This is in the original ds dataset, not the cross-section
# Use the same function that computed terrain across cross-section but for whole domain of Utah
terrain = ds['surface_pressure'].metpy.convert_units('hPa').squeeze()


# Plot this
ax.contourf(
    ds['longitude'], ds['latitude'],
    terrain, levels=np.arange(0, 1000, 10),
    cmap='Greens', alpha=0.5, zorder=6
)
# Add contour lines for terrain
terrain_contours = ax.contour(
    ds['longitude'], ds['latitude'],
    terrain, levels=np.arange(0, 1000, 50),
    colors='darkgreen', linewidths=0.5, zorder=7
)
# Add labels to the contour lines
ax.clabel(terrain_contours, inline=True, fontsize=8, fmt='%d', colors='black')
# Add latitude/longitude lines, very thin and dotted
ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
# Add a scale bar
ax.add_feature(cfeature.SCALE, scale=0.1, color='black', zorder=8)
# Add a North arrow
ax.text(0.05, 0.95, 'N', transform=ax.transAxes, fontsize=12, color='black', ha='center', va='center', rotation=0)

# Add a colorbar for the terrain
cbar = fig.colorbar(terrain_contours, ax=ax, pad=0.02, aspect=30)
cbar.set_label(f"Terrain Pressure ({terrain.attrs.get('units', 'hPa')})")


# Add a legend
ax.legend(loc='upper right', fontsize=10, frameon=False)
# Add a title

title = "NAM Cross Section Path"
ax.set_title(title, fontsize=12, pad=15)
fig.tight_layout()
# plt.savefig(output_fpath, dpi=250, bbox_inches='tight')
fig.show()
plt.close()

print("Script finished.")