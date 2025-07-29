# Script 1: GFS East Coast Cross-Section (Baseline)

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import metpy.calc as mpcalc
from metpy.units import units
from metpy.interpolate import cross_section
from herbie import Herbie
from datetime import datetime
import warnings

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning) # Ignore numpy/xarray FutureWarnings

# --- Configuration ---
analysis_date = datetime(2024, 5, 1, 12) # Example Date (YYYY, M, D, H)
model_name = 'gfs'
product_name = 'pgrb2.0p25' # GFS 0.5 degree pressure GRIB2
forecast_hour = 6
start_point = (45.0, -80.0) # Approx. Ontario/Quebec border
end_point = (25.0, -75.0)  # Approx. Bahamas/Florida coast

# Variables to fetch (Temperature, Height on pressure levels, Surface Pressure)
# Use regex for flexibility
search_pattern = r":(?:TMP|HGT):\d+ mb|:PRES:surface:"

# --- Data Acquisition ---
print(f"Attempting to access {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")
try:
    H = Herbie(
        analysis_date,
        model=model_name,
        product=product_name,
        fxx=forecast_hour,
        save_dir='/Users/johnlawson/data/temp_python/xsection',
        verbose=False # Set to True for more Herbie download details
    )

    # Download and load data into xarray
    # Setting save_dir might be useful for caching if running repeatedly
    ds = H.xarray(search_pattern, verbose=False, save_dir='/Users/johnlawson/data/temp_python/xsection')
    print("Data loaded successfully.")
except Exception as e:
    print(f"ERROR: Could not retrieve or load data. Herbie/xarray error: {e}")
    exit()

# --- Data Preparation ---
# Parse CF conventions and assign units if needed (Herbie+cfgrib often handles this)
if all(isinstance(item, xr.Dataset) for item in ds):
    ds = xr.merge(ds)

ds = ds.metpy.parse_cf().squeeze()

# Select isobaric levels (example: 1000 hPa to 100 hPa)
ds_levels = ds.sel(isobaricInhPa=slice(1000, 100)) # Adjust level coord name if needed

# from metpy.units import units
import pint # Import pint

# --- Calculate Cross Section ---
print("Calculating cross-section...")
cross = cross_section(ds, start_point, end_point).set_coords(('latitude', 'longitude'))
print("Cross-section calculated.")
print("Cross section data structure:")
print(cross) # Add this to see variable names and coords

# --- Calculate Potential Temperature ---
print("Calculating potential temperature...")

# Define the variable names based on the output of print(cross)
temp_var_name = 't'             # Temperature variable name (seems correct)
pres_coord_name = 'isobaricInhPa' # Pressure coordinate name (seems correct)

# Get the DataArrays from the cross-section dataset
temp_da = cross[temp_var_name]
pres_coord = cross[pres_coord_name] # This is the 1D coordinate

# Check and assign units if missing (Keep this robust check)
if 'units' not in temp_da.attrs or temp_da.metpy.units == units.dimensionless:
    print(f"Assigning units to temperature variable '{temp_var_name}' (assuming Kelvin)...")
    temp_da = temp_da.metpy.quantify(units.kelvin) # GFS Temp is Kelvin
else:
    print(f"Temperature variable '{temp_var_name}' already has units: {temp_da.metpy.units}")

if 'units' not in pres_coord.attrs or pres_coord.metpy.units == units.dimensionless:
    print(f"Assigning units to pressure coordinate '{pres_coord_name}' (assuming hPa)...")
    pres_coord = pres_coord.metpy.quantify(units.hPa) # cfgrib usually puts hPa in coord name
else:
    print(f"Pressure coordinate '{pres_coord_name}' already has units: {pres_coord.metpy.units}")


# --- FIX: Create broadcasted 2D arrays for calculation ---
# This ensures both pressure and temperature have the same dimensions (isobaricInhPa, index)
pres_da_2d, temp_da_2d = xr.broadcast(pres_coord, temp_da)
print(f"Shape after broadcasting - Pressure: {pres_da_2d.shape}, Temperature: {temp_da_2d.shape}")

# --- Use the broadcasted arrays for the calculation ---
# Pass the underlying magnitude+units array to MetPy calc functions
pressure_for_calc = pres_da_2d.metpy.unit_array
temperature_for_calc = temp_da_2d.metpy.unit_array

potential_temp = mpcalc.potential_temperature(pressure_for_calc, temperature_for_calc)

# Add calculated potential temperature back to the cross dataset
# Important: Use the coordinates and dimensions from the broadcasted arrays
# used in the calculation to ensure the result aligns correctly.
cross['potential_temperature'] = xr.DataArray(
    potential_temp,
    coords=temp_da_2d.coords, # Use coords from broadcasted temp
    dims=temp_da_2d.dims,     # Use dims from broadcasted temp
    name='potential_temperature', # Good practice to name the DataArray
    attrs={'units': str(potential_temp.units)} # Store units as string attribute
)
print("Potential temperature calculated and added to dataset.")

# --- Calculate Wind Components (Add check for variable existence) ---
u_wind_var = 'u' # Check if 'u' exists in print(cross)
v_wind_var = 'v' # Check if 'v' exists in print(cross)

if u_wind_var in cross and v_wind_var in cross:
    print("Calculating wind components...")
    u_wind_da = cross[u_wind_var]
    v_wind_da = cross[v_wind_var]

    # Add unit checks for u/v winds (assuming m/s from GFS)
    if 'units' not in u_wind_da.attrs or u_wind_da.metpy.units == units.dimensionless:
        print(f"Assigning units to U-wind variable '{u_wind_var}' (assuming m/s)...")
        u_wind_da = u_wind_da.metpy.quantify(units('m/s'))
    if 'units' not in v_wind_da.attrs or v_wind_da.metpy.units == units.dimensionless:
        print(f"Assigning units to V-wind variable '{v_wind_var}' (assuming m/s)...")
        v_wind_da = v_wind_da.metpy.quantify(units('m/s'))

    # Convert to knots for plotting/calculation if needed
    u_wind_knots = u_wind_da.metpy.convert_units('knots')
    v_wind_knots = v_wind_da.metpy.convert_units('knots')

    # Ensure winds are 2D (they should be if interpolated like temperature)
    if u_wind_knots.dims != temp_da_2d.dims:
        print("Warning: Wind dimensions do not match temperature dimensions. Broadcasting might be needed.")
        # Add broadcasting logic if necessary, e.g.,
        # _, u_wind_knots = xr.broadcast(pres_coord, u_wind_knots) # Example if winds were 1D
        # _, v_wind_knots = xr.broadcast(pres_coord, v_wind_knots)

    # Calculate tangential/normal components
    tangential_wind, normal_wind = mpcalc.cross_section_components(u_wind_knots, v_wind_knots)

    # Add results back to the dataset
    cross['tangential_wind'] = xr.DataArray(tangential_wind, coords=u_wind_knots.coords, dims=u_wind_knots.dims, name='tangential_wind', attrs={'units': 'knots'})
    cross['normal_wind'] = xr.DataArray(normal_wind, coords=v_wind_knots.coords, dims=v_wind_knots.dims, name='normal_wind', attrs={'units': 'knots'})
    print("Wind components calculated.")
else:
    print(f"Wind variables '{u_wind_var}' or '{v_wind_var}' not found in cross dataset. Skipping component calculation.")


# --- Prepare Terrain Data (Using Surface Pressure 'sp') ---
print("Preparing terrain data...")
terrain_var_sp = 'sp' # Surface Pressure variable name from print(cross)
terrain_pressure_hpa = None # Initialize

if terrain_var_sp in cross:
    print(f"Using surface pressure variable '{terrain_var_sp}' for terrain.")
    sp_da = cross[terrain_var_sp]

    # Check/Assign units (GFS surface pressure is often Pascals)
    if 'units' not in sp_da.attrs or sp_da.metpy.units == units.dimensionless:
        print(f"Assigning units to surface pressure '{terrain_var_sp}' (assuming Pa)...")
        sp_da = sp_da.metpy.quantify(units.pascal)
    else:
        print(f"Surface pressure variable '{terrain_var_sp}' already has units: {sp_da.metpy.units}")

    # Convert to hPa for plotting consistency with y-axis
    terrain_pressure_hpa = sp_da.metpy.convert_units('hPa')

    # Add to dataset, ensuring coordinates are just the 'index' dim
    cross['terrain_pressure'] = xr.DataArray(
        terrain_pressure_hpa.data, # Use .data to avoid coordinate conflicts
        coords={'index': cross['index']}, # Only assign the index coordinate
        dims=['index'],
        name='terrain_pressure',
        attrs={'units': 'hPa'}
    )
    print("Terrain pressure (from Surface Pressure 'sp') prepared in hPa.")
else:
    print(f"Surface pressure variable '{terrain_var_sp}' not found. Cannot create terrain data.")
    # Assign None or handle appropriately in plotting code
    cross['terrain_pressure'] = xr.DataArray([np.nan]*len(cross['index']), coords={'index': cross['index']}, dims=['index'], name='terrain_pressure', attrs={'units': 'hPa'})

# --- Plotting ---
print("Generating plot...")
fig = plt.figure(figsize=(12, 8)) # Or your adjusted figsize
ax = plt.axes()

# Define potential temperature contour levels (adjust as needed)
pres_coord_name = 'isobaricInhPa' # Make sure this is correct
theta_levels = np.arange(270, 400, 3) # Example levels

# Define plot coordinates
x_coords = cross['longitude'] # Use longitude for a meaningful x-axis
y_coords = cross[pres_coord_name] # Pressure levels coordinate

# --- Plot Potential Temperature Contours ---
print("Plotting Potential Temperature...")
cs = ax.contour(x_coords, y_coords, cross['potential_temperature'],
                levels=theta_levels, colors='black', linewidths=1.0)
ax.clabel(cs, cs.levels[1::2], inline=True, fontsize=10, fmt='%iK') # Add labels

# --- Plot Terrain ---
terrain_pressure_plot = cross.get('terrain_pressure', None) # Use.get for safety
y_bottom_pressure = cross[pres_coord_name].max().item() # Max pressure (~1000 hPa), float
y_top_pressure = cross[pres_coord_name].min().item()   # Min plot pressure (~100 hPa), float

# Check if terrain data is valid before plotting
if terrain_pressure_plot is not None and not terrain_pressure_plot.isnull().all():
    print("Plotting terrain...")

    # --- FIX: Explicitly get the magnitude from the Pint array ---
    # Access the underlying data (which is a Pint Quantity array)
    terrain_pint_array = terrain_pressure_plot.data
    # Get the unitless numerical magnitude from the Pint array
    terrain_magnitudes = terrain_pint_array.magnitude

    # Now compare the unitless magnitude array with the unitless float
    where_condition = terrain_magnitudes >= y_top_pressure

    ax.fill_between(
        x_coords.data,                  # Use.data for x-coordinates
        terrain_magnitudes,             # Use the unitless magnitudes for y-values
        y_bottom_pressure,              # Base level for fill (e.g., 1000 hPa)
        where=where_condition,          # Use the purely numerical comparison result
        facecolor='grey',               # Changed color slightly for visibility
        interpolate=True,
        zorder=2                        # Ensure terrain is behind contours
    )
else:
    print("WARNING: Terrain data is missing or invalid. Terrain not plotted.")

# --- Plot Wind Barbs (Optional, if calculated) ---
if 'tangential_wind' in cross and 'normal_wind' in cross:
    print("Plotting wind barbs...")
    # Subsample barbs to avoid clutter
    # Adjust barb_slice_x and barb_slice_y as needed for density
    barb_slice_x = slice(None, None, 5) # Every 5th point horizontally
    barb_slice_y = slice(None, None, 3) # Every 3rd level vertically

    # Get coordinates for barbs - ensure they match the sliced data
    x_barbs = x_coords[barb_slice_x]
    y_barbs = y_coords[barb_slice_y]
    # Important: Need to broadcast y_barbs to match shape of wind data after slicing
    # OR index wind data carefully
    u_barbs = cross['tangential_wind'][barb_slice_y, barb_slice_x]
    v_barbs = cross['normal_wind'][barb_slice_y, barb_slice_x]

    # Broadcast y_barbs to match the shape of u_barbs/v_barbs
    yy_barbs, _ = xr.broadcast(y_barbs, u_barbs) # Broadcast y against u

    ax.barbs(x_barbs.data, yy_barbs.data, # Use broadcasted y
             u_barbs.data, v_barbs.data,
             length=7, pivot='middle')


# --- Configure Axes ---

# More useful for near-surface
plot_min_pressure = 600 # 100 hPa otherwise, typically, for synoptic

print("Configuring axes...")
ax.set_yscale('log') # Use symlog or log scale for pressure
# ax.set_yscale('symlog') # Use symlog or log scale for pressure
ax.set_yticks(np.arange(1000, plot_min_pressure, -100))
ax.set_yticklabels([str(int(p)) for p in np.arange(1000, plot_min_pressure, -100)]) # Format labels as integer strings
ax.set_ylim(y_bottom_pressure, plot_min_pressure) # Set limits from max pressure down to min pressure
# ax.set_ylim(y_bottom_pressure, y_top_pressure) # Set limits from max pressure down to min pressure
# ax.invert_yaxis() # Don't invert if using symlog/log and setting ylim(max, min)

ax.set_xlabel(f"Longitude ({cross['longitude'].min().item():.1f}°E to {cross['longitude'].max().item():.1f}°E)")
ax.set_ylabel(f"Pressure ({y_coords.attrs.get('units', 'hPa')})")
ax.set_title('GFS Potential Temperature Cross-Section\n'
             f'Start: {start_point} | End: {end_point}\n'
             f'Valid: {cross["valid_time"].dt.strftime("%Y-%m-%d %H:%M UTC").item()}')

plt.grid(True, linestyle='--', alpha=0.5)
plt.show()
print("Plot generation complete.")