# Download model forecast data — walk-through

**What / why:** Pull gridded weather-model output (HRRR, GEFS, NAM) for a region,
then read forecast values at named locations. You'd run this to make maps, build
time series, or compare a forecast against what was observed.

> Downloading **for WRF** is different — that keeps raw GRIB on disk and lives in
> [wrf-staging.md](wrf-staging.md). This page is for analysis (data → xarray).

**Needs:** nothing required · `BRC_TOOLS_HERBIE_CACHE` optional (cache dir) · conda env `brc-tools`

## Fetch a region, then extract at waypoints

```python
from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import add_wind_fields

src = NWPSource("hrrr")                    # also "gefs", "rrfs"
ds = src.fetch(
    init_time="2025-02-22 12Z",
    forecast_hours=range(0, 13),           # fxx 0..12
    variables=["temp_2m", "wind_u_10m", "wind_v_10m", "mslp"],
    region="uinta_basin",
)
ds = add_wind_fields(ds)                    # adds wind_speed_10m, wind_dir_10m
nwp_df = src.extract_at_waypoints(ds, group="foehn_path")
```

**Produces:** `ds` is an xarray Dataset `(time, y, x)`; `nwp_df` is a Polars
DataFrame of per-waypoint time series.

## Line up a forecast with observations

```python
from brc_tools.nwp.alignment import align_obs_to_nwp

paired = align_obs_to_nwp(obs_df, nwp_df, variables=["temp_2m", "wind_speed_10m"])
# matches obs to the nearest forecast valid time; columns get _nwp / _obs suffixes
```

(`obs_df` comes from [obs.md](obs.md). Units are harmonized for you.)

**See also:** signatures → [`API-REFERENCE.md` → NWPSource / derived / alignment](../API-REFERENCE.md) · terms (init time, fxx) → [GLOSSARY.md](GLOSSARY.md)
