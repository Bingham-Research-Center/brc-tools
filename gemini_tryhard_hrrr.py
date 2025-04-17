# Script 3: HRRR West Coast Cross-Section (Potential Temperature - Revised Again)

import sys
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import metpy.calc as mpcalc
from metpy.units import units
from metpy.interpolate import cross_section
from herbie import Herbie
from datetime import datetime, timedelta # Import timedelta
import warnings
import pint # Required for unit handling
import os # For creating directories

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning)

# --- Configuration ---
date_args = {
    "year": 2025, "month": 1, "day": 31, "hour": 6, "minute": 0, "second": 0
}
analysis_date = datetime(**date_args)

model_name = 'hrrr'
product_name = 'prs' # Standard HRRR product on pressure levels
forecast_hour = 6    # Short forecast hour for HRRR

# SLC
start_point = (40.7606, -111.8881) # Salt Lake City, UT
# SE of Dinosaur NM, CO, co. line
end_point = (40.222665, -108.477740)

# Define plot top pressure (set manually or use data min)
# plot_min_pressure = 200 # Example: Plot up to 200 hPa
plot_min_pressure = None # Set to None to use data minimum (at least 100 hPa)

# Variables to fetch (Temperature, Height, Winds on pressure levels, Surface Pressure)
# --- FIX: Corrected search pattern for pressure levels ---
# Look for variables on levels specified in millibars (e.g., :500 mb:)
search_pattern = r":(?:TMP|HGT|UGRD|VGRD):\d+ mb|:PRES:surface:"

# Define output directory
date_str_compact = analysis_date.strftime('%Y%m%d%H')
output_dir = f"./xsection/{model_name}/{date_str_compact}"
os.makedirs(output_dir, exist_ok=True)
output_filename = f"{output_dir}/{model_name}_xsection_pot_temp_f{forecast_hour:03d}.png"


# --- Data Acquisition ---
print(f"--- Script 3: {model_name.upper()} Potential Temperature Cross-Section ---")
print(f"Attempting to access {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")
# Optional: Check inventory first if debugging
# H_check = Herbie(analysis_date, model=model_name, product=product_name, fxx=forecast_hour)
# print("Inventory Check (Temperature on Pressure Levels):")
# print(H_check.inventory(search=r":TMP:\d+ mb"))
# print("Inventory Check (Surface Pressure):")
# print(H_check.inventory(search=r":PRES:surface:"))
# del H_check # Clean up check object

H = Herbie(
    analysis_date,
    model=model_name,
    product=product_name,
    fxx=forecast_hour,
    save_dir='/Users/johnlawson/data/temp_python/xsection', # Adjust as needed
    verbose=False # Set to True for more Herbie download details
)

# Download and load data into xarray
try:
    # Use the corrected search pattern here
    ds_raw = H.xarray(search_pattern, verbose=False, remove_grib=False) # Keep grib for inspection
except Exception as e:
    print(f"ERROR: Failed to download or access data via Herbie: {e}")
    print("Check model/date/product availability and Herbie setup.")
    sys.exit(1)

# --- Handle list output from H.xarray ---
if isinstance(ds_raw, list):
    print("Herbie returned a list of datasets, attempting merge...")
    if ds_raw and all(isinstance(item, xr.Dataset) for item in ds_raw):
        ds = xr.merge(ds_raw, compat='override', join='outer')
        print("Datasets merged successfully.")
    elif not ds_raw:
        print("Error: Herbie returned an empty list. Check search pattern and data availability.")
        sys.exit(1)
    else:
        print("Error: Not all items in the Herbie list were xarray Datasets.")
        sys.exit(1)
elif isinstance(ds_raw, xr.Dataset):
    ds = ds_raw # Already a dataset
else:
    print(f"Error: Unexpected data type returned by H.xarray: {type(ds_raw)}")
    sys.exit(1)

print("Data loaded successfully.")

# --- MetPy Parsing and Coordinate Setup ---
print("Parsing CF conventions and setting up coordinates...")
try:
    ds = ds.metpy.parse_cf().squeeze()
except Exception as e:
    print(f"ERROR during MetPy parsing (parse_cf/squeeze): {e}")
    print("Dataset structure before error:")
    print(ds_raw)
    sys.exit(1)


# *** Coordinate Verification and Fixing ***
print("\n--- Dataset structure after parse_cf ---")
# print(ds)
print("--- Coordinates after parse_cf ---")
print(ds.coords)

required_coords = ['metpy_crs', 'x', 'y']
missing_coords = [coord for coord in required_coords if coord not in ds.coords]

if missing_coords:
    print(f"WARNING: Missing required coordinates for cross_section: {missing_coords}")
    if 'metpy_crs' not in ds.coords:
        print("Attempting to assign standard HRRR CRS (Lambert Conformal)...")
        hrrr_crs_params = {
            "grid_mapping_name": "lambert_conformal_conic", "latitude_of_projection_origin": 38.5,
            "longitude_of_central_meridian": 262.5, "standard_parallel": (38.5, 38.5),
            "earth_radius": 6371229.0,
        }
        try:
            ds = ds.metpy.assign_crs(hrrr_crs_params, write_coords=True)
            print("Assigned CRS. Re-checking coordinates...")
            print(ds.coords)
        except Exception as e: print(f"ERROR assigning CRS: {e}. Cannot proceed."); sys.exit(1)

    if ('x' not in ds.coords or 'y' not in ds.coords) and 'metpy_crs' in ds.coords:
        if 'latitude' in ds.coords and 'longitude' in ds.coords:
            print("Attempting to assign y/x dimension coordinates from lat/lon...")
            try:
                ds = ds.metpy.assign_y_x()
                print("Assigned y/x. Coordinates:")
                print(ds.coords)
            except Exception as e: print(f"ERROR assigning y/x coordinates: {e}. Cannot proceed."); sys.exit(1)
        else: print("ERROR: Cannot assign y/x without latitude/longitude coordinates."); sys.exit(1)

    missing_coords = [coord for coord in required_coords if coord not in ds.coords]
    if missing_coords: print(f"ERROR: Still missing required coordinates after attempting fixes: {missing_coords}"); sys.exit(1)
    else: print("Required coordinates ('metpy_crs', 'x', 'y') seem to be present.")


# --- Identify Variable Names ---
print("Identifying variable names...")
# Find pressure coordinate (This should now exist if data was loaded correctly)
level_coord_name = next((coord for coord in ds.coords if 'isobaric' in coord.lower()), None)
if level_coord_name is None: raise KeyError(f"Could not identify pressure level coordinate in ds.coords: {list(ds.coords)}. Check Herbie search pattern and GRIB contents.")
print(f"Identified pressure coordinate: '{level_coord_name}'")

# Find temperature variable
temp_var_name = next((var for var, da in ds.data_vars.items() if (da.attrs.get('standard_name') == 'air_temperature' or var.startswith('TMP')) and level_coord_name in da.coords), None)
if temp_var_name is None: raise KeyError(f"Could not identify temperature variable with coordinate '{level_coord_name}'. Available: {list(ds.data_vars)}")
print(f"Identified temperature variable: '{temp_var_name}'")

# Find wind variables
u_wind_var = next((var for var, da in ds.data_vars.items() if (da.attrs.get('standard_name') == 'eastward_wind' or var.startswith('UGRD')) and level_coord_name in da.coords), None)
v_wind_var = next((var for var, da in ds.data_vars.items() if (da.attrs.get('standard_name') == 'northward_wind' or var.startswith('VGRD')) and level_coord_name in da.coords), None)
if u_wind_var: print(f"Identified U-wind variable: '{u_wind_var}'")
else: print("Warning: U-wind variable not identified.")
if v_wind_var: print(f"Identified V-wind variable: '{v_wind_var}'")
else: print("Warning: V-wind variable not identified.")

# Find surface pressure variable
sfc_pres_var_name = next((var for var, da in ds.data_vars.items() if da.attrs.get('standard_name') == 'surface_air_pressure' or var.startswith('PRES_surface') or var.startswith('PRES_P0_L1')), None)
if sfc_pres_var_name: print(f"Identified surface pressure variable: '{sfc_pres_var_name}'")
else: print("Warning: Could not identify surface pressure variable for terrain.")


# --- Calculate Cross Section ---
print("Calculating cross-section...")
try:
    cross = cross_section(ds, start_point, end_point, steps=200).set_coords(('latitude', 'longitude'))
    print("Cross-section calculated.")
except Exception as e:
    print(f"ERROR during cross_section calculation: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


# --- Calculate Potential Temperature ---
print("Calculating potential temperature...")
try:
    temp_da = cross[temp_var_name]
    pres_coord = cross[level_coord_name]

    if temp_da.metpy.units == units.dimensionless: temp_da = temp_da.metpy.quantify(units.kelvin)
    if pres_coord.metpy.units == units.dimensionless: pres_coord = pres_coord.metpy.quantify(units.hPa)

    pres_da_2d, temp_da_2d = xr.broadcast(pres_coord, temp_da)
    pressure_for_calc = pres_da_2d.metpy.unit_array
    temperature_for_calc = temp_da_2d.metpy.unit_array
    potential_temp = mpcalc.potential_temperature(pressure_for_calc, temperature_for_calc)

    cross['potential_temperature'] = xr.DataArray(
        potential_temp, coords=temp_da_2d.coords, dims=temp_da_2d.dims,
        name='potential_temperature', attrs={'units': str(potential_temp.units)}
    )
    print("Potential temperature calculated and added to dataset.")
except Exception as e:
    print(f"ERROR calculating potential temperature: {e}")
    cross['potential_temperature'] = None


# --- Calculate Wind Components (Optional) ---
if u_wind_var and v_wind_var and u_wind_var in cross and v_wind_var in cross:
    print("Calculating wind components...")
    try:
        u_wind_da = cross[u_wind_var]
        v_wind_da = cross[v_wind_var]

        if u_wind_da.metpy.units == units.dimensionless: u_wind_da = u_wind_da.metpy.quantify(units('m/s'))
        if v_wind_da.metpy.units == units.dimensionless: v_wind_da = v_wind_da.metpy.quantify(units('m/s'))

        u_wind_knots = u_wind_da.metpy.convert_units('knots')
        v_wind_knots = v_wind_da.metpy.convert_units('knots')
        tangential_wind, normal_wind = mpcalc.cross_section_components(u_wind_knots, v_wind_knots)

        cross['tangential_wind'] = xr.DataArray(tangential_wind, coords=u_wind_knots.coords, dims=u_wind_knots.dims, name='tangential_wind', attrs={'units': 'knots'})
        cross['normal_wind'] = xr.DataArray(normal_wind, coords=v_wind_knots.coords, dims=v_wind_knots.dims, name='normal_wind', attrs={'units': 'knots'})
        print("Wind components calculated.")
    except Exception as e: print(f"ERROR calculating wind components: {e}")
else: print("Wind variables missing or not found in cross section. Skipping component calculation.")


# --- Prepare Terrain Data (Using Surface Pressure) ---
print("Preparing terrain data...")
terrain_pressure_hpa = None
if sfc_pres_var_name and sfc_pres_var_name in cross:
    print(f"Using surface pressure variable '{sfc_pres_var_name}' for terrain.")
    try:
        sp_da = cross[sfc_pres_var_name]
        if sp_da.metpy.units == units.dimensionless: sp_da = sp_da.metpy.quantify(units.pascal)
        terrain_pressure_hpa = sp_da.metpy.convert_units('hPa')
        cross['terrain_pressure'] = xr.DataArray(
            terrain_pressure_hpa.data, coords={'index': cross['index']}, dims=['index'],
            name='terrain_pressure', attrs={'units': 'hPa'}
        )
        print("Terrain pressure prepared in hPa.")
    except Exception as e: print(f"ERROR preparing terrain pressure from '{sfc_pres_var_name}': {e}"); cross['terrain_pressure'] = None
else: print(f"Surface pressure variable '{sfc_pres_var_name}' not found or not in cross section. Cannot create terrain data."); cross['terrain_pressure'] = None


# --- Plotting ---
print("Generating plot...")
fig = plt.figure(figsize=(16, 8))
ax = plt.axes()
x_coords = cross['longitude']
y_coords = cross[level_coord_name]
y_bottom_pressure = y_coords.max().item()
y_top_pressure = plot_min_pressure if plot_min_pressure else max(100.0, y_coords.min().item())

# Plot Potential Temperature
if cross.get('potential_temperature') is not None:
    print("Plotting Potential Temperature...")
    # theta_levels = np.arange(270, 360, 2)
    theta_levels = np.arange(270, 321, 1)
    cmap_style = 'viridis'
    theta_contourf = ax.contourf(
        x_coords, y_coords, cross['potential_temperature'],
        levels=theta_levels, cmap=cmap_style, extend='both',
        alpha=0.7, zorder=1)
    theta_contour = ax.contour(
        x_coords, y_coords, cross['potential_temperature'],
        levels=theta_levels, colors='black', linewidths=0.5,
        zorder=2)
    cbar = fig.colorbar(theta_contourf, ax=ax, pad=0.02, aspect=30)
    cbar.set_label(f"Potential Temperature ({cross['potential_temperature'].attrs.get('units', 'K')})")
else: print("Potential temperature data not available for plotting.")

# --- Plot Terrain ---
terrain_pressure_plot = cross.get('terrain_pressure', None) # DataArray, units=hPa

# Get numerical limits for plotting and comparison using .metpy.magnitude
# Use try-except in case coordinate doesn't have units/accessor yet
try:
    y_bottom_pressure_mag = cross[level_coord_name].max().metpy.magnitude
    y_top_pressure_val = plot_min_pressure if plot_min_pressure else max(100.0, cross[level_coord_name].min().metpy.magnitude)
except AttributeError: # Fallback if .metpy accessor failed earlier
    print("Warning: Using .item() for pressure limits, units might be inconsistent.")
    y_bottom_pressure_mag = cross[level_coord_name].max().item()
    y_top_pressure_val = plot_min_pressure if plot_min_pressure else max(100.0, cross[level_coord_name].min().item())


if terrain_pressure_plot is not None and not terrain_pressure_plot.isnull().all():
    print("Plotting terrain...")
    # --- FIX: Use .metpy.magnitude to get unitless NumPy array ---
    try:
        terrain_magnitudes = terrain_pressure_plot.metpy.magnitude # Get unitless NumPy array
    except AttributeError:
        print("Warning: Could not get terrain magnitude via .metpy accessor, using .data.")
        # Fallback, but might still cause issues if .data returns Pint array
        terrain_magnitudes = terrain_pressure_plot.data


    # --- Perform comparison with unitless numbers ---
    where_condition = terrain_magnitudes >= y_top_pressure_val # Compare numpy array >= float

    # --- Pass unitless data to fill_between ---
    ax.fill_between(
        x_coords.metpy.magnitude,   # Use magnitude for x-coords (longitude)
        terrain_magnitudes,         # Use unitless magnitudes for terrain y-values
        y_bottom_pressure_mag,      # Use unitless base level for fill
        where=where_condition,
        facecolor='saddlebrown', alpha=1.0,
        interpolate=True,
        zorder=10,
    )
else:
    print("WARNING: Terrain data missing or invalid. Terrain not plotted.")

# --- Optional: Plot Wind Barbs (Also use.magnitude) ---
if 'tangential_wind' in cross and 'normal_wind' in cross:
    print("Plotting wind barbs...")
    try:
        # --- Define Subsampling Slices ---
        # Subsample heavily for HRRR resolution to avoid clutter
        barb_slice_x = slice(None, None, 12) # Every 15th point horizontally
        barb_slice_y = slice(None, None, 2)  # Every 5th level vertically

        # --- Apply Slices to Coordinates and Data ---
        # Get the full coordinate arrays first
        x_coords_full = cross['longitude']
        y_coords_full = cross[level_coord_name] # Use the identified pressure coord name

        # Apply slicing to get subsets for barbs
        x_barbs = x_coords_full[barb_slice_x]
        y_barbs_1d = y_coords_full[barb_slice_y] # This will be 1D (pressure levels)

        # Apply slicing to the 2D wind component DataArrays
        u_barbs_da = cross['tangential_wind'][barb_slice_y, barb_slice_x]
        v_barbs_da = cross['normal_wind'][barb_slice_y, barb_slice_x]

        # --- Check if Slicing Resulted in Data ---
        if u_barbs_da.size > 0 and v_barbs_da.size > 0:
            # --- Broadcast 1D y-coordinate to match 2D wind data shape ---
            # We need a y-coordinate value for each barb position
            yy_barbs_da, xx_barbs_da = xr.broadcast(y_barbs_1d, x_barbs) # Broadcast both x and y to ensure alignment

            # --- Plot using.metpy.magnitude ---
            # Pass the unitless numerical magnitudes to ax.barbs
            ax.barbs(
                xx_barbs_da.metpy.magnitude,    # X coordinates (broadcasted)
                yy_barbs_da.metpy.magnitude,    # Y coordinates (broadcasted)
                u_barbs_da.metpy.magnitude,     # U component (tangential) magnitude
                v_barbs_da.metpy.magnitude,     # V component (normal) magnitude
                length=6,                       # Length of barb shafts
                pivot='middle',                 # Anchor point of the barb
                color='brown',                  # Barb color
                zorder=5,                      # Z-order for layering
                alpha=0.7                       # Transparency
            )
        else:
            print("Warning: Subsampling for wind barbs resulted in empty data. Skipping barb plotting.")

    except AttributeError as ae:
        # Handle cases where.metpy.magnitude might fail (e.g., if units weren't assigned)
        print(f"ERROR plotting wind barbs (AttributeError, likely missing units/magnitude): {ae}")
        print("Attempting plot with.data (may fail if units persist)...")
        # Fallback attempt (less robust)
        try:
            if u_barbs_da.size > 0 and v_barbs_da.size > 0:
                yy_barbs_da, xx_barbs_da = xr.broadcast(y_barbs_1d, x_barbs)
                ax.barbs(xx_barbs_da.data, yy_barbs_da.data, u_barbs_da.data, v_barbs_da.data,
                         length=6, pivot='middle', color='black', alpha=0.6)
        except Exception as fallback_e:
            print(f"Fallback wind barb plotting failed: {fallback_e}")

    except Exception as e:
        print(f"ERROR plotting wind barbs: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for unexpected errors

else:
    print("Tangential or normal wind data not found in 'cross' dataset. Skipping wind barb plotting.")


# --- Axis Configuration (Use magnitudes for limits) ---
print("Configuring axes...")
ax.set_yscale('log')
user_y_bottom = 875
user_y_top = 650
ax.set_ylim(user_y_bottom, user_y_top)
# ax.set_ylim(y_bottom_pressure_mag, y_top_pressure_val) # Use unitless magnitudes

# ... (rest of y-tick setup, labels, title) ...
# Make sure labels don't explicitly assume units if using magnitudes
ax.set_xlabel(f"Longitude (°E)")
ax.set_ylabel(f"Pressure (hPa)") # Keep label generic if units stripped for plotting
ax.set_title(
    f'{model_name.upper()} Potential Temperature (K) Cross-Section\n'
    f'From {start_point} to {end_point}\n'
    f'Valid: {cross["valid_time"].dt.strftime("%Y-%m-%d %H:%M UTC").item()}'
)

# Turn off grid
ax.grid(False)
# ax.grid(True, linestyle='--', alpha=0.4)

# Create y-axis ticks that read like "600", "650", "700", etc.
y_ticks = np.arange(user_y_bottom, user_y_top + 1, 50)
ax.set_yticks(y_ticks)
ax.set_yticklabels([f'{int(tick)}' for tick in y_ticks])


plt.tight_layout()
plt.show()
# Save figure
plt.savefig(output_filename, dpi=250, bbox_inches='tight')
print(f"Plot saved to {output_filename}")
plt.close(fig) # Close figure to free memory

print("Script finished.")