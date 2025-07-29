# Script 4: RRFS Southern Plains Cross-Section (Potential Temperature - Revised Again)
import os
import sys
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import metpy
import metpy.calc as mpcalc
from metpy.units import units
from metpy.interpolate import cross_section
from herbie import Herbie
from datetime import datetime, timedelta # Import timedelta
import warnings
import pint # Required for unit handling

from o3_mini_high_rrfs import download_rrfs_file, construct_rrfs_url

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module='metpy')
warnings.filterwarnings("ignore", category=FutureWarning)

# --- Configuration ---
# analysis_date = datetime.utcnow() - timedelta(days=1) # Yesterday
# analysis_date = analysis_date.replace(hour=12, minute=0, second=0, microsecond=0) # 12Z
date_args = {
    "year": 2025, "month": 1, "day": 31, "hour": 0, "minute": 0, "second": 0
}
analysis_date = datetime(**date_args)

use_local = 1
grib_fdir = "/Users/johnlawson/data/temp_rrfs/"
model_name = 'rrfs'
product_name = 'natlev'
member_val = "control"
forecast_hour = 12

start_point = (31.0, -100.0) # Approx. West Texas
end_point = (38.0, -97.0)   # Approx. Central Kansas
plot_min_pressure = 500

# --- FIX: Adjust search pattern if needed based on product ---
# If using 'a' or 'prslev', 'isobaricInhPa' is likely correct.
# If forced to use 'nat', this pattern would need changing.
search_pattern = r":(?:TMP|HGT|UGRD|VGRD|PRES):isobaricInhPa|:PRES:surface:"

date_str_compact = analysis_date.strftime('%Y%m%d%H')
output_dir = f"./xsection/{model_name}/{date_str_compact}"
os.makedirs(output_dir, exist_ok=True)
output_filename = f"{output_dir}/{model_name}_xsection_pot_temp_f{forecast_hour:03d}.png"


# --- Data Acquisition ---
print(f"--- Script 4: {model_name.upper()} Potential Temperature Cross-Section ---")
print(f"Attempting to access {model_name.upper()} data for {analysis_date} F{forecast_hour:03d}...")

# Define the local file path and parameters
herbie_params = {
    'date': analysis_date,
    'model': model_name,
    'product': product_name,
    'fxx': forecast_hour,
    'member': member_val,
    'domain': 'conus',
    'save_dir': grib_fdir,
    'verbose': False,
}

_, local_fname = construct_rrfs_url(
    analysis_date.strftime('%Y%m%d'),
    analysis_date.strftime('%H'),
    forecast_hour,
    product_name,
)
local_fname = os.path.join(herbie_params['save_dir'],
                # "rrfs.t00z.natlev.f012.grib2"
                local_fname,
                )
# Create the Herbie instance
H = Herbie(**herbie_params)

# Make the save_dir if it doesn't exist
if not os.path.exists(H.save_dir): os.makedirs(H.save_dir)

if use_local and os.path.exists(local_fname):
    # Define the local file path and parameters
    local_fname = os.path.join(grib_fdir, local_fname)

    # Delete the cached index if available
    # try:
    #     del H.index_as_dataframe
    # except AttributeError:
    #     pass

    # Try to load the dataset from the local file
    print(f"Attempting to load dataset from {local_fname}...")
    try:
        # ds = H.xarray(local_fname)
        # Open the dataset with a filter for typeOfLevel to avoid duplicate 'heightAboveGround'
        ds = xr.open_dataset(
            local_fname,
            engine='cfgrib',
            backend_kwargs={
                'filter_by_keys': {'typeOfLevel': 'heightAboveGround'}
            }
        )

        # Once the dataset is loaded, assign the CRS using kwargs only. Avoid mixing with an attribute dictionary.
        ds = ds.metpy.assign_crs(
            grid_mapping_name="lambert_conformal_conic",
            latitude_of_projection_origin=38.5,
            longitude_of_central_meridian=262.5,
            standard_parallel=(38.5, 38.5),
            earth_radius=6371229.0
        )
    # except ValueError as e:
        # if "No index file was found" in str(e):
        #     print("Index file missing")#; downloading full file...")
        #     try:
        #         del H.index_as_dataframe
        #         print("Deleted index file.")
        #     except AttributeError:
        #         print("No index file to delete.")
        #     # create index by loading again
        #     del H
        #     H = Herbie(**herbie_params)
        #     ds = H.xarray(local_fname)
        #     print(f"Dataset loaded successfully from {local_fname}.")
        # print("No index file to delete.")
    # except ValueError as e:
    except:
        H = Herbie(**herbie_params)
        # del H.index_as_dataframe
        ds = H.xarray(local_fname)
        print(f"Dataset loaded successfully another way from {local_fname}.")

else:
    init_date = analysis_date.strftime('%Y%m%d')
    run_hour = analysis_date.strftime('%H')
    forecast_hour = forecast_hour

    # Call the download function with the specified parameters.
    downloaded_file = download_rrfs_file(init_date, run_hour, forecast_hour, product_name, output_dir=grib_fdir)

    if downloaded_file:
        print(f"File successfully downloaded: {downloaded_file}")
        try:
            ds = H.xarray(local_fname)
        except:
            H = Herbie(**herbie_params)
            ds = H.xarray(local_fname)
            print(f"Dataset loaded successfully from {local_fname}.")
    else:
        print("Download failed.")

print("Data loaded successfully.")

# --- MetPy Parsing and Coordinate Setup ---
print("Parsing CF conventions and setting up coordinates...")
try:
    ds = ds.metpy.parse_cf().squeeze()
except Exception as e:
    print(f"ERROR during MetPy parsing (parse_cf/squeeze): {e}")
    print("Dataset structure before error:")
    # print(ds_raw)
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
        print("Attempting to assign standard RRFS/HRRR CRS (Lambert Conformal)...")
        # RRFS often uses the same projection as HRRR CONUS
        rrfs_crs_params = {
            "grid_mapping_name": "lambert_conformal_conic",
            "latitude_of_projection_origin": 38.5,
            "longitude_of_central_meridian": 262.5, # -97.5 W
            "standard_parallel": (38.5, 38.5),
            "earth_radius": 6371229.0, # Use NCEP definition
        }
        try:
            ds = ds.metpy.assign_crs(rrfs_crs_params, write_coords=True)
            print("Assigned CRS. Re-checking coordinates...")
            print(ds.coords)
        except Exception as e:
            print(f"ERROR assigning CRS: {e}. Cannot proceed.")
            sys.exit(1)

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

    missing_coords = [coord for coord in required_coords if coord not in ds.coords]
    if missing_coords:
        print(f"ERROR: Still missing required coordinates after attempting fixes: {missing_coords}")
        sys.exit(1)
    else:
        print("Required coordinates ('metpy_crs', 'x', 'y') seem to be present.")

# --- Identify Variable Names ---
print("Identifying variable names...")

# Identify the pressure level coordinate, or fallback to 'heightAboveGround'
level_coord_name = next((coord for coord in ds.coords if 'isobaric' in coord.lower()), None)
if level_coord_name is None:
    if 'heightAboveGround' in ds.coords:
        level_coord_name = 'heightAboveGround'
        print("Using 'heightAboveGround' as the level coordinate.")
    else:
        raise KeyError(f"Could not identify pressure level coordinate in ds.coords: {list(ds.coords)}")
print(f"Identified pressure coordinate: '{level_coord_name}'")

print("Available data variables:")
print(list(ds.data_vars))

# Identify the temperature variable.
# If the data variable 'unknown' is present then use it as a fallback.
if 'unknown' in ds.data_vars:
    temp_var_name = 'unknown'
    print("Using 'unknown' as temperature variable.")
else:
    temp_var_name = next(
        (var for var, da in ds.data_vars.items()
         if (da.attrs.get('standard_name') == 'air_temperature' or var.startswith('TMP'))
         and level_coord_name in da.coords),
        None
    )
    if temp_var_name is None:
        raise KeyError(f"Could not identify temperature variable with coordinate '{level_coord_name}'. Available: {list(ds.data_vars)}")
print(f"Identified temperature variable: '{temp_var_name}'")

u_wind_var = next((var for var, da in ds.data_vars.items() if (da.attrs.get('standard_name') == 'eastward_wind' or var.startswith('UGRD')) and level_coord_name in da.coords), None)
v_wind_var = next((var for var, da in ds.data_vars.items() if (da.attrs.get('standard_name') == 'northward_wind' or var.startswith('VGRD')) and level_coord_name in da.coords), None)
if u_wind_var: print(f"Identified U-wind variable: '{u_wind_var}'")
else: print("Warning: U-wind variable not identified.")
if v_wind_var: print(f"Identified V-wind variable: '{v_wind_var}'")
else: print("Warning: V-wind variable not identified.")

sfc_pres_var_name = next((var for var, da in ds.data_vars.items() if da.attrs.get('standard_name') == 'surface_air_pressure' or var.startswith('PRES_surface') or var.startswith('PRES_P0_L1')), None)
if sfc_pres_var_name: print(f"Identified surface pressure variable: '{sfc_pres_var_name}'")
else: print("Warning: Could not identify surface pressure variable for terrain.")


# --- Calculate Cross Section ---
print("Calculating cross-section...")
try:
    # High number of steps for RRFS resolution
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
    # Ensure the temperature variable has a valid unit.
    if ds[temp_var_name].attrs.get("units", None) in [None, "unknown"]:
        ds[temp_var_name].attrs["units"] = "K"

    # Use a valid pressure field. If a pressure variable exists, convert it.
    if "pressure" in ds.data_vars:
        pressure = ds["pressure"].metpy.convert_units("hPa")
    else:
        # Approximate pressure using the level coordinate (assumed to be height in meters)
        # using a conversion factor of 0.12 hPa per meter.
        pressure = (1000 * units.hPa) - (ds[level_coord_name].metpy.unit_array * 0.12 * (units.hPa/units.m))

    # Convert temperature to a unit-wrapped array.
    temperature = ds[temp_var_name].metpy.unit_array

    # Compute potential temperature with a reference pressure of 1000 hPa.
    theta = mpcalc.potential_temperature(pressure, temperature, 1000 * units.hPa)

    # Squeeze extra dimensions to ensure a 2D field.
    theta = np.squeeze(theta)
    if theta.ndim != 2:
        raise ValueError(f"Computed theta has shape {theta.shape}; expected a 2D field.")

    ds["potential_temperature"] = (("y", "x"), theta)
    print("Potential temperature calculated.")
except Exception as e:
    print(f"ERROR calculating potential temperature: {e}")


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
    except Exception as e:
        print(f"ERROR calculating wind components: {e}")
else:
    print("Wind variables missing or not found in cross section. Skipping component calculation.")


# --- Prepare Terrain Data (Using Surface Pressure) ---
print("Preparing terrain data...")
terrain_pressure_hpa = None
if sfc_pres_var_name and sfc_pres_var_name in cross:
    print(f"Using surface pressure variable '{sfc_pres_var_name}' for terrain.")
    try:
        sp_da = cross[sfc_pres_var_name]
        if sp_da.metpy.units == units.dimensionless: sp_da = sp_da.metpy.quantify(units.pascal) # Assume Pa for surface pressure

        terrain_pressure_hpa = sp_da.metpy.convert_units('hPa')
        cross['terrain_pressure'] = xr.DataArray(
            terrain_pressure_hpa.data, coords={'index': cross['index']}, dims=['index'],
            name='terrain_pressure', attrs={'units': 'hPa'}
        )
        print("Terrain pressure prepared in hPa.")
    except Exception as e:
        print(f"ERROR preparing terrain pressure from '{sfc_pres_var_name}': {e}")
        cross['terrain_pressure'] = None
else:
    print(f"Surface pressure variable '{sfc_pres_var_name}' not found or not in cross section. Cannot create terrain data.")
    cross['terrain_pressure'] = None


# --- Plotting ---
print("Generating plot...")
fig = plt.figure(figsize=(16, 9))
ax = plt.axes()

x_coords = cross['longitude']
y_coords = cross[level_coord_name]

# Use try-except for magnitude access during plotting
try:
    y_bottom_pressure_mag = y_coords.max().metpy.magnitude
    y_top_pressure_val = plot_min_pressure if plot_min_pressure else max(100.0, y_coords.min().metpy.magnitude)
    x_coords_mag = x_coords.metpy.magnitude
    y_coords_mag = y_coords.metpy.magnitude
except AttributeError:
    print("Warning: Using.data for plot coordinates/limits due to missing units/accessor.")
    y_bottom_pressure_mag = y_coords.max().item()
    y_top_pressure_val = plot_min_pressure if plot_min_pressure else max(100.0, y_coords.min().item())
    x_coords_mag = x_coords.data
    y_coords_mag = y_coords.data


# --- Plot Potential Temperature (Filled Contours) ---
if cross.get('potential_temperature') is not None:
    print("Plotting Potential Temperature...")
    theta_levels = np.arange(260, 370, 3)
    cmap_style = 'cividis'
    try:
        pot_temp_mag = cross['potential_temperature'].metpy.magnitude
        theta_contourf = ax.contourf(
            x_coords_mag, y_coords_mag, pot_temp_mag,
            levels=theta_levels, cmap=cmap_style, extend='both'
        )
        cbar = fig.colorbar(theta_contourf, ax=ax, pad=0.02, aspect=30)
        cbar.set_label(f"Potential Temperature ({cross['potential_temperature'].attrs.get('units', 'K')})")
    except AttributeError:
        print("Warning: Plotting potential temperature using.data due to missing units/accessor.")
        theta_contourf = ax.contourf(
            x_coords_mag, y_coords_mag, cross['potential_temperature'].data,
            levels=theta_levels, cmap=cmap_style, extend='both'
        )
        cbar = fig.colorbar(theta_contourf, ax=ax, pad=0.02, aspect=30)
        cbar.set_label(f"Potential Temperature (Units Unknown)")

else:
    print("Potential temperature data not available for plotting.")


# --- Plot Terrain ---
terrain_pressure_plot = cross.get('terrain_pressure', None)
if terrain_pressure_plot is not None and not terrain_pressure_plot.isnull().all():
    print("Plotting terrain...")
    try:
        terrain_magnitudes = terrain_pressure_plot.metpy.magnitude
        where_condition = terrain_magnitudes >= y_top_pressure_val
        ax.fill_between(
            x_coords_mag, terrain_magnitudes, y_bottom_pressure_mag,
            where=where_condition, facecolor='darkgoldenrod', alpha=0.7,
            interpolate=True, zorder=5
        )
    except AttributeError:
        print("Warning: Plotting terrain using.data due to missing units/accessor.")
        terrain_magnitudes = terrain_pressure_plot.data
        where_condition = terrain_magnitudes >= y_top_pressure_val
        ax.fill_between(
            x_coords_mag, terrain_magnitudes, y_bottom_pressure_mag,
            where=where_condition, facecolor='darkgoldenrod', alpha=0.7,
            interpolate=True, zorder=5
        )
else:
    print("WARNING: Terrain data missing or invalid. Terrain not plotted.")


# --- Optional: Plot Wind Barbs ---
if 'tangential_wind' in cross and 'normal_wind' in cross:
    print("Plotting wind barbs...")
    barb_slice_x = slice(None, None, 15)
    barb_slice_y = slice(None, None, 5)

    x_barbs = x_coords[barb_slice_x]
    y_barbs_1d = y_coords[barb_slice_y]
    u_barbs = cross['tangential_wind'][barb_slice_y, barb_slice_x]
    v_barbs = cross['normal_wind'][barb_slice_y, barb_slice_x]

    if u_barbs.size > 0:
        try:
            yy_barbs, xx_barbs_bc = xr.broadcast(y_barbs_1d, x_barbs) # Broadcast both
            ax.barbs(xx_barbs_bc.metpy.magnitude, yy_barbs.metpy.magnitude,
                     u_barbs.metpy.magnitude, v_barbs.metpy.magnitude,
                     length=6, pivot='middle', color='white', alpha=0.7)
        except AttributeError:
            print("Warning: Plotting barbs using.data due to missing units/accessor.")
            yy_barbs, xx_barbs_bc = xr.broadcast(y_barbs_1d, x_barbs)
            ax.barbs(xx_barbs_bc.data, yy_barbs.data,
                     u_barbs.data, v_barbs.data,
                     length=6, pivot='middle', color='white', alpha=0.7)
        except Exception as e:
            print(f"ERROR plotting wind barbs: {e}")


# --- Axis Configuration ---
print("Configuring axes...")
ax.set_yscale('log')
ax.set_ylim(y_bottom_pressure_mag, y_top_pressure_val)

yticks_major = 10**np.arange(np.ceil(np.log10(y_top_pressure_val)), np.floor(np.log10(y_bottom_pressure_mag))+0.1, 1)
yticks_manual = np.arange(int(y_bottom_pressure_mag // 100 * 100), int(y_top_pressure_val), -100)
yticks_list = np.unique(np.concatenate(([y_top_pressure_val, y_bottom_pressure_mag], yticks_major, yticks_manual)))
yticks_list = yticks_list[(yticks_list >= y_top_pressure_val) & (yticks_list <= y_bottom_pressure_mag)]
ax.set_yticks(sorted(list(yticks_list)))
ax.set_yticklabels([f"{int(p)}" for p in sorted(list(yticks_list))])
ax.minorticks_off()


# --- Labels and Title ---
ax.set_xlabel(f"Longitude (°E)")
ax.set_ylabel(f"Pressure (hPa)")
ax.set_title(
    f'{model_name.upper()} Potential Temperature (K) Cross-Section\n'
    f'From {start_point} to {end_point}\n'
    f'Valid: {cross["valid_time"].dt.strftime("%Y-%m-%d %H:%M UTC").item()}'
)
ax.grid(True, linestyle=':', alpha=0.5)

plt.tight_layout()
plt.show() # Show the plot interactively
# Save figure
plt.savefig(output_filename, dpi=150, bbox_inches='tight')
print(f"Plot saved to {output_filename}")
plt.close(fig)



print("Script finished.")