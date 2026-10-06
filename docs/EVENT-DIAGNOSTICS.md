# Reading a night from stations, a satellite and the sun

Three small modules that turn what already exists for a past night -- mesonet reports,
GOES land-surface temperature, the clock -- into the numbers a cold-pool or drainage case
study needs. They were written for ub-wx `drainage-canyons-gigawatts` (26-28 January 2025)
and hold nothing about that case: every place, window and threshold is a caller argument.

| Module | Needs | Does |
|---|---|---|
| `brc_tools.obs.profiles` | numpy | stations read as a profile: theta against height, heat deficit, tilt; drainage wind at a station |
| `brc_tools.satellite.goes` | numpy, `requests`, `netCDF4` | list, download and resample GOES ABI Level-2 fields, with parallax |
| `brc_tools.utils.solar` | stdlib | sun position, sunrise and sunset, nights that are one night long |

Tests: `tests/test_obs_profiles.py`, `tests/test_satellite_goes.py`,
`tests/test_utils_solar.py` (31 tests, no network; a synthetic ABI file is written to
`tmp_path`). Run them in the `brc-tools-2026` env.

## 1. `obs.profiles` -- stations as a sounding

A basin ringed by stations at different heights is a poor man's sounding. The module holds
the pieces between a Synoptic time series and that picture. Arrays in, arrays or small
frozen dataclasses out; nothing touches the network.

### Potential temperature without a pressure sensor

Few mesonet stations report pressure, and a 1 % pressure error is 0.8 K in theta -- as large
as the signal. So theta is never computed from a standard atmosphere:

```python
from brc_tools.obs import profiles as op

fit = op.fit_pressure_height(z_m, pressure_hpa)        # ln p = a + b z over the stations that report it
theta = op.potential_temperature(temp_c, op.pressure_at(z_m_all, fit))
```

`fit_pressure_height` drops reports more than 3 % from the standard atmosphere (altimeter
settings and sea-level pressures filed as station pressure) and returns the scale height
and the rms of the fit. Every theta in one profile then shares one pressure-height
relation, so differences between neighbours are not sensor offsets. In the January case
41-43 stations gave a scale height of 7.7-7.8 km with an rms of 5 hPa; a 5 hPa error in the
fitted pressure is 0.5 K in theta, common to every station to first order.

Two traps the module documents rather than hides: **Synoptic elevations are in feet**
(`feet_to_m`), and a station inventory's elevation can be wrong by kilometres -- take the
height from a DEM at the station's coordinates.

### The profile, and how strong the pool is

| Function | Returns |
|---|---|
| `pseudo_profile(z, value, bin_m=100)` | median, quartiles and count per height bin |
| `two_layer_fit(z, theta)` | `TwoLayerFit`: the height where the stratification changes, both gradients |
| `heat_deficit(z, theta, z_ref_m=...)` | `HeatDeficit`: J m-2 missing below `z_ref_m`, and the same as a pressure head (Pa) |
| `theta_plane_fit(z, x_km, y_km, theta)` | `ThetaPlane`: stratification and the horizontal theta gradient at fixed height |
| `nightly_cooling(times, temp_c, sunset=, sunrise=)` | sunset temperature, minimum, the fall between them |

**Heat deficit** (Whiteman et al. 1999) is the measure to prefer:
`H = c_p * integral(rho * (theta(z_ref) - theta(z)) dz)`. It needs no pool top. `head_pa` is
the same deficit as a hydrostatic pressure excess at the bottom of the column, which is the
number to set against a synoptic pressure difference across the basin.

What the January case taught about each:

* `two_layer_fit` assumes a pool with a lid. The Uinta Basin on those nights was
  continuously stratified over a kilometre; the fitted "top" jumped between 1500 m and
  2900 m from one snapshot to the next. Use it only where a kink is visible in the plot.
* A pseudo-profile is the air **at the ground** at each height. Rim stations sit in their
  own surface inversions (5 K colder than the free air at their height at sunrise), so a
  deficit referred to a rim-level station median is a lower bound on the deficit against
  the free air, and it moves when the set of rim stations changes. Report which stations.
* By day the rim stations warm in the sun and the reference rises: a station-based deficit
  peaks in mid-morning for that reason alone.
* `theta_plane_fit` separates the stratification from a tilt of the isentropes, but where
  the floor itself slopes, height and position are correlated among the stations. Bootstrap
  over stations for the interval, and compare the isentrope slope with the ground's.

### Drainage wind at a station

```python
sector = op.sector_from_azimuth(channel_runs_toward_deg, half_width=40)   # down-valley wind comes FROM the reciprocal
night = op.drainage_metrics(times, speed, direction, sector, sunset=ss, sunrise=sr)
steady = op.wind_constancy(speed_night, direction_night)
```

`drainage_metrics` gives the share of the night in the sector, the onset (minutes after
sunset; negative in a shaded canyon), the duration, the mean down-axis component, the calm
fraction and a surge count (`count_surges`). `wind_constancy` gives the vector-mean
direction and the ratio of vector to scalar speed, which needs **no sector at all**: a
drainage current is a constancy near 1 from a direction the terrain explains.

Choose the sector from the terrain, not by eye. In January a station 40 m above the creek
on a bench had been given its neighbour's canyon sector; it scored 18 % "down-canyon"
against 53 % on the axis the DEM gave it, and the report built on the wrong number.

## 2. `satellite.goes` -- ABI Level-2 on a lat/lon grid

No credentials and no s3 client: the public buckets answer plain HTTPS.

```python
from datetime import datetime
from brc_tools.satellite import goes

files = goes.list_abi("ABI-L2-LSTC", datetime(2025, 1, 27, 0), datetime(2025, 1, 27, 14), bucket="noaa-goes18")
hourly = goes.nearest_files(files, [datetime(2025, 1, 27, h) for h in range(0, 15)])
paths = goes.fetch_abi(list(hourly.values()), "scratch/goes")              # a download: run it on a DTN
field = goes.sample_on_latlon(paths[0], (-111.8, -107.4, 39.05, 41.9), res_deg=0.02,
                              height_m=terrain_on_the_target_grid, max_quality=1)
```

`sample_on_latlon` computes the scan angles at which the satellite sees every target point
(`scan_angles`, the GOES-R PUG fixed-grid navigation on the file's own ellipsoid) and takes
the nearest pixel. `height_m` lifts each point to its terrain first: the **parallax
correction**, 3-4 km over 2-3 km terrain at the 55-60 degree zenith angles of the interior
West. `max_quality` screens on the product's `DQF` (for LST: 0 high, 1 medium, 2 low, 3 no
retrieval; `None` keeps everything). The result is a `LatLonField` with rows north to south.

Caveats that belong to the product:

* LST is a **skin** temperature and a clear-sky product. On the two January nights it ran
  2.3 K colder than 2 m air on average; night minima correlated 0.8 with stations on the
  open floor and 0.1 on the forested north rim. Use it for pattern and for sides with no
  stations, not for a canyon.
* The pixel is 2 km at nadir and 3-4 km here. A reservoir 2 km wide is a mixed pixel.
* A missing retrieval is the product's cloud flag. At night it can also be fog in the
  bottom of a pool, or a cold surface mistaken for cloud.
* `DQF` is stored **unsigned** with a fill value; widen it before filling (the reader does,
  and the test writes an unsigned flag to keep it so).

## 3. `utils.solar` -- nights that are one night long

```python
from datetime import date
from brc_tools.utils.solar import nights, sun_times, solar_position

for label, sunset_utc, sunrise_utc in nights(date(2025, 1, 26), date(2025, 1, 27), 40.455, -109.53):
    ...
```

`nights` pairs each sunset with the **first sunrise after it**, labelled by the local date
of the sunset (`utc_offset_h`, MST by default). Pairing by UTC calendar day instead gives
38-hour nights wherever local sunset falls after 00 UTC -- January and September in Utah --
and that once put night shading a day early on a figure and inflated every night mean
behind it. Both regressions are tests. Dates or datetimes are accepted; a datetime is read
as its calendar day.

## 4. Where the case-specific half lives

ub-wx `experiments/drainage-canyons-gigawatts/analysis/iter5/event_*.py` is the worked
example: which stations stand where (read from the reference rasters at each station's
coordinates), the valley axis from the DEM, HRRR analyses beside the stations, GOES by rim
side. Nothing there defines a place; waypoints and sinks come from `lookups.toml`.

## References

Whiteman, C. D., X. Bian and S. Zhong, 1999: Wintertime evolution of the temperature
inversion in the Colorado Plateau Basin. *J. Appl. Meteor.*, **38**, 1103-1117.

GOES-R Series Product Definition and Users' Guide, Volume 3 (Level 1b), section 5.1.2.8:
navigation of image data on the fixed grid.
