# API Reference — brc_tools

## brc_tools.nwp — NWP model data

### NWPSource

```python
from brc_tools.nwp import NWPSource

src = NWPSource("hrrr")               # also: "gefs", "rrfs"
src = NWPSource("gefs", member="p01")  # ensemble member
```

#### .fetch(init_time, forecast_hours, variables, *, region=, bbox=, levels=, product=, max_workers=6) → xr.Dataset

Fetch gridded NWP data via Herbie. Downloads are parallelised across forecast hours.

- **init_time**: `"YYYY-MM-DD HHZ"` or tz-naive UTC datetime
- **forecast_hours**: `range(0, 13)` or `[0, 3, 6, 9, 12]`
- **variables**: canonical alias names from `lookups.toml` (e.g. `["temp_2m", "mslp"]`)
- **region**: named region from `lookups.toml` (e.g. `"uinta_basin"`)
- **levels**: pressure levels for `_pl` aliases (e.g. `[850, 700, 500]`)

Returns `xr.Dataset` with dims `(time, y, x)` and canonical variable names.

**Note:** Derived aliases like `wind_speed_10m` are not fetched — call `add_wind_fields(ds)` after.

#### .extract_at_waypoints(ds, *, group=, waypoints=) → pl.DataFrame

Extract nearest-point time series at named waypoints.

- **group**: waypoint group name (e.g. `"foehn_path"`)
- Returns DataFrame with columns: `waypoint`, `valid_time`, plus data variables

#### .latest_init(now=) → datetime.datetime

Most recent init time likely to have data available.

### load_lookups() → dict

Load the `lookups.toml` configuration registry. Cached after first call.

---

## brc_tools.nwp.derived — Derived meteorological fields

```python
from brc_tools.nwp.derived import add_wind_fields, add_theta_e, hourly_tendency
```

| Function | Input | Adds to dataset | Notes |
|----------|-------|-----------------|-------|
| `add_wind_fields(ds)` | wind_u_10m, wind_v_10m | wind_speed_10m, wind_dir_10m | |
| `add_theta_e(ds)` | temp_2m, dewpoint_2m | theta_e_2m | uses mslp if present |
| `hourly_tendency(ds, var)` | any variable | `{var}_tendency` | forward difference |
| `horizontal_gradient_magnitude(field, dx_m=3000)` | DataArray | DataArray | 2D gradient |

Unit conversions: `temp_K_to_C`, `temp_C_to_K`, `pa_to_hpa`, `hpa_to_pa`.

Wind: `wind_speed(u, v)`, `wind_direction(u, v)`, `wind_components(speed, dir)`.

Thermodynamics: `potential_temperature`, `saturation_vapor_pressure`, `mixing_ratio`, `theta_e`, `relative_humidity`.

---

## brc_tools.nwp.alignment — Model/obs alignment

```python
from brc_tools.nwp.alignment import harmonize_units, align_obs_to_nwp
```

#### harmonize_units(nwp_df, obs_df, variables, *, target="obs") → (DataFrame, DataFrame)

Convert NWP and obs DataFrames to matching unit systems using the conversion table in `lookups.toml`.

#### align_obs_to_nwp(obs_df, nwp_df, *, variables=, tolerance_minutes=30, strategy="nearest", harmonize=True) → DataFrame

Temporal asof-join matching obs to NWP valid times. Returns DataFrame with `{var}_nwp` and `{var}_obs` columns.

---

## brc_tools.obs — Station observations

### ObsSource

```python
from brc_tools.obs import ObsSource

obs = ObsSource()
df = obs.timeseries(
    waypoint_group="foehn_path",
    start="2025-02-22 12Z",
    end="2025-02-23 06Z",
    variables=["temp_2m", "wind_speed_10m", "mslp"],
)
```

#### .timeseries(*, stids=, waypoint_group=, waypoints=, start, end, variables) → pl.DataFrame

Fetch station time series via SynopticPy. Provide one of `stids`, `waypoint_group`, or `waypoints`.

Returns DataFrame with columns: `stid`, `valid_time` (tz-naive UTC), plus one per alias. `waypoint` column added when using waypoint_group/waypoints.

---

## brc_tools.obs.scanner — Event detection

```python
from brc_tools.obs.scanner import scan_events, detect_wind_ramp, detect_foehn
```

#### scan_events(stid, variables, months, year, criteria_fn, *, rank_key="score") → list[dict]

Generic scan loop: queries ObsSource month-by-month, partitions into daily windows, evaluates each day with `criteria_fn`.

#### detect_wind_ramp(day_df, date, **kwargs) → dict | None

Detect sustained late-day westerly wind ramp. Key thresholds (all configurable):
- `min_peak_speed_ms=8.0`, `min_increase_ms=5.0`, `min_consec_westerly=3`

#### detect_foehn(day_df, date, **kwargs) → dict | None

Detect foehn event (warming + drying + wind ramp). Includes anti-front check.
- `min_temp_increase_C=2.0`, `min_dewpt_decrease_C=2.0`, `max_post_peak_drop_C=6.0`

---

## brc_tools.verify.deterministic — Forecast verification

```python
from brc_tools.verify.deterministic import paired_scores, bias, mae, rmse, correlation
```

#### paired_scores(nwp_df, obs_df, variables, tolerance_minutes=30) → pl.DataFrame

Join NWP waypoint series with obs, compute per-station/variable metrics. Returns DataFrame with columns: `waypoint`, `variable`, `n_obs`, `bias`, `mae`, `rmse`, `correlation`.

Scalar functions: `bias(obs, fcst)`, `mae(obs, fcst)`, `rmse(obs, fcst)`, `correlation(obs, fcst)`.

---

## brc_tools.visualize — Plotting

```python
from brc_tools.visualize import plot_planview, plot_planview_evolution
from brc_tools.visualize import plot_station_timeseries, plot_verification_timeseries
```

#### plot_planview(ds, variable, *, time_idx=, valid_time=, ax=, waypoints=, cmap=, vmin=, vmax=, wind_barbs=, obs_overlay=, ...) → Axes

Single-panel plan-view map with Cartopy. Supports wind barbs, waypoint markers, MSLP contour overlay, obs scatter overlay.

#### plot_planview_evolution(ds, variable, *, ncols=3, waypoints=, cmap=, wind_barbs=, contour_var=, suptitle=, ...) → Figure

Multi-panel time evolution (one panel per forecast hour).

#### plot_station_timeseries(nwp_series, variable, *, obs_df=, waypoint_names=, secondary_variable=, run_styles=, ...) → Figure

Multi-station subplot grid with multi-run overlay and optional obs scatter.

#### plot_verification_timeseries(nwp_df, obs_df, variable, waypoint, *, ax=, show_error=, ...) → Axes

NWP vs obs comparison at a single station with error shading.

---

## brc_tools.nwp.case_study — Shared case study helpers

```python
from brc_tools.nwp.case_study import (
    load_waypoints, next_day, fetch_multi_init,
    extract_all_waypoints, fetch_obs, run_figure_pipeline, annotate,
)
```

See `CASE-STUDY-GUIDE.md` for usage patterns.

---

## Configuration: lookups.toml

Central registry at `brc_tools/nwp/lookups.toml`. Defines:

- **[models]**: hrrr, gefs, rrfs — Herbie model name, init cadence, products, grid methods
- **[regions]**: Named bounding boxes (sw/ne lat-lon)
- **[waypoints]**: Named locations with lat, lon, elevation_m, reference_stid
- **[waypoint_groups]**: Named collections of waypoints
- **[aliases]**: Canonical variable mappings — search strings per model, units, Synoptic equivalents
- **[defaults]**: Cache settings, retry counts, validation flags
