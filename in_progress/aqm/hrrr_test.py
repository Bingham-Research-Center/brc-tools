import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import xarray as xr
from datetime import datetime
import metpy.calc as mpcalc
from metpy.units import units
from herbie import Herbie
import metpy.plots as mpplots
from scipy.ndimage import gaussian_filter

# Set the forecast date and time
init_date = datetime(2025, 1, 31, 12)  # 31 Jan 2025 12Z
valid_date = datetime(2025, 1, 31, 18)  # 31 Jan 2025 18Z
forecast_hour = (valid_date - init_date).total_seconds() / 3600

# Initialize Herbie for HRRR data
h = Herbie(
    date=init_date,
    model="hrrr",
    product="prs",  # Pressure levels for vertical cross-section
    fxx=int(forecast_hour)
)

datasets = h.xarray("(?:SNOD|SNOWC|TMP|HGT|PRES|HGTSFC)")
ds = xr.merge(datasets)

# Define the cross-section line (Heber City to Dinosaur, Colorado)
start_point = (-111.413, 40.507)  # Heber City
end_point = (-109.017, 40.243)    # Dinosaur, Colorado

# Create a set of points along the line
num_points = 100
lons = np.linspace(start_point[0], end_point[0], num_points)
lats = np.linspace(start_point[1], end_point[1], num_points)

# Extract data along the cross-section
pressure_levels = ds.lev.values
temp_cross = np.zeros((len(pressure_levels), num_points))
height_cross = np.zeros((len(pressure_levels), num_points))
terrain_height = np.zeros(num_points)

# Interpolate data to the cross-section line
for i, (lon, lat) in enumerate(zip(lons, lats)):
    # Find the nearest grid points
    lon_idx = np.abs(ds.longitude - lon).argmin()
    lat_idx = np.abs(ds.latitude - lat).argmin()

    # Extract temperature and height profiles
    temp_cross[:, i] = ds.TMP.isel(time=0).sel(lev=pressure_levels)[:, lat_idx, lon_idx].values
    height_cross[:, i] = ds.HGT.isel(time=0).sel(lev=pressure_levels)[:, lat_idx, lon_idx].values

    # Extract terrain height
    terrain_height[i] = ds.HGTSFC.isel(time=0)[lat_idx, lon_idx].values

# Convert temperature to potential temperature
potential_temp = np.zeros_like(temp_cross)
for i in range(num_points):
    for j, pressure in enumerate(pressure_levels):
        temp = temp_cross[j, i] * units.kelvin
        press = pressure * units.hectopascal
        potential_temp[j, i] = mpcalc.potential_temperature(press, temp).magnitude

# Create the cross-section plot
fig, ax = plt.subplots(figsize=(12, 8))

# Create a meshgrid for plotting
x = np.arange(num_points)
y = height_cross

# Plot potential temperature contours
levels = np.arange(270, 330, 2)
cs = ax.contour(x, y, potential_temp, levels=levels, colors='k', linewidths=0.8)
ax.clabel(cs, fmt='%d', inline=True, fontsize=8)

# Fill contours for potential temperature
cf = ax.contourf(x, y, potential_temp, levels=levels, cmap='RdBu_r', alpha=0.7)
cbar = plt.colorbar(cf, ax=ax, orientation='vertical', pad=0.05, shrink=0.8)
cbar.set_label('Potential Temperature (K)')

# Plot terrain
ax.fill_between(x, 0, terrain_height, facecolor='saddlebrown', alpha=0.8)

# Set axis labels and title
ax.set_title(f'W-E Cross-Section of Potential Temperature\nHeber City to Dinosaur, CO\nValid: {valid_date.strftime("%Y-%m-%d %HZ")}')
ax.set_xlabel('Distance (km)')
ax.set_ylabel('Height (m)')

# Calculate distance in km for x-axis
distance = np.zeros(num_points)
for i in range(1, num_points):
    dx = 111.32 * np.cos(np.deg2rad(lats[i])) * (lons[i] - lons[i-1])
    dy = 110.57 * (lats[i] - lats[i-1])
    distance[i] = distance[i-1] + np.sqrt(dx**2 + dy**2)

# Create a secondary x-axis with distance in km
ax2 = ax.twiny()
ax2.set_xlim(ax.get_xlim())
ax2.set_xticks(np.linspace(0, num_points-1, 6))
ax2.set_xticklabels([f'{d:.0f}' for d in np.linspace(0, distance[-1], 6)])
ax2.set_xlabel('Distance (km)')

# Add city markers
city_positions = [0, num_points-1]  # Heber City and Dinosaur
city_names = ['Heber City', 'Dinosaur']
for pos, name in zip(city_positions, city_names):
    ax.annotate(name, xy=(pos, terrain_height[pos] + 100), ha='center', fontsize=10)
    ax.plot([pos, pos], [terrain_height[pos], terrain_height[pos] + 50], 'k-')

# Set y-axis limits to focus on the lower atmosphere
ax.set_ylim(1500, 6000)  # Adjust based on terrain height

plt.tight_layout()
plt.savefig('potential_temperature_cross_section.png', dpi=300)
plt.show()
