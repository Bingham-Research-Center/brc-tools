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

## brc_tools.satellite.modis — MODIS context imagery

```python
from datetime import datetime, timezone

from brc_tools.satellite.modis import render_context

result = render_context(
    datetime(2013, 2, 2, 18, tzinfo=timezone.utc),
    (-111.8, 39.2, -108.2, 41.5),
    "/tmp/modis_uinta_20130202_near1800",
)
```

`discover_granules()` queries NASA CMR for daytime Terra/Aqua Level-1B swaths
covering the map center and selects the midpoint closest to the requested UTC time.
`fetch_gibs_image()` retrieves a georeferenced daily corrected-reflectance PNG.
`render_context()` orchestrates discovery, cached fetches, PNG/PDF rendering, and a
JSON provenance sidecar. See `MODIS-CONTEXT-RENDERER.md` for the CLI, cache, offline,
and interpretation contracts.

---

## brc_tools.hydro — Streamflow and snow-course records (token-free)

Cache-first clients for two providers without a quota contract; the restraint is one
request at a time, a pause between pages, raw pages written before parsing (with
`.meta.json` sidecars), and derived parquet trusted only while its sidecar lists the
same pages. Cache root: `BRC_HYDRO_CACHE`, else `~/.cache/brc-tools/hydro`.

### nwis — USGS Water Data OGC API (`api.waterdata.usgs.gov`, the successor of the
NWIS web services that close in February 2027)
- `monitoring_locations(bbox, site_type_code="ST")` → sites with altitude (m), HUC and
  drainage area (km2) converted from the API's feet and square miles.
- `daily(site_id, parameter_code="00060", statistic_id="00003", start, end)` → daily
  values with `value_m3s` for discharge; cursor paging, 5000 per page.
- `water_year_summary(df, months=(4,5,6,7))` → volume, centroid date, peak per water year.

### awdb — NRCS Air and Water Database REST (`wcc.sc.egov.usda.gov/awdbRestApi`)
- `stations(states, networks=("SNTL","SCAN"), bbox=None)` → one cached request per
  (state, network) with element lists narrowed to the six elements x DAILY (the API
  rejects an unnarrowed element listing). `shef_id` is the Synoptic station id,
  `data_time_zone` the station's data offset (-8 for SNOTEL).
- `station_elements(stations)` → the authoritative sensor-depth table (`heightDepth`
  inches below ground → `depth_cm`), which Synoptic's SNOTEL metadata lacks.
- `daily(triplet, elements, begin, end)` → WTEQ/PREC mm, SNWD cm, STO/TOBS degC, SMS %,
  with NRCS QC/QA flags.

## WRF & figure-engine modules (index)

One-line map of the WRF-era modules; each row's owning doc carries the detail.

| module | what it is | owning doc |
|---|---|---|
| `nwp.wrf_staging` | GRIB → scratch staging (manifest/contract sidecars) for brc-wrf | WRF-STAGING-STATE-PLAYBOOK.md |
| `nwp.wrf_section` | wrfout → plan/arbitrary-transect adapter (native eta) | WRF-WINDS.md |
| `nwp.wrf_derived` | fog/visibility/cloud/surface-energy/stability/TKE diagnostics WRF never writes | WRF-WINDS.md |
| `nwp.wrf_tracers` | passive `tr17_*` air-mass source attribution | WRF-WINDS.md |
| `nwp.wrf_deficit_reference` | fixed / sunset-profile reference for the heat deficit, two-datum error bar, per-catchment budget terms, the `theta_ref_*.json` sidecar | DEFICIT-REFERENCE.md |
| `nwp.gates` | reader for the lookups.toml `[gates.*]` table (rim / floor / port flux planes) | TERRAIN-D8.md |
| `terrain.dem` / `terrain.d8` / `terrain.catchments` / `terrain.gates` / `terrain.validate` | 3DEP mosaics, D8 routing, basin floors and rim crossings, perpendicular gate lines, NWIS/WBD/NHD checks (optional extra `terrain`) | TERRAIN-D8.md |
| `terrain.depressions` / `terrain.throat` / `terrain.profiles` | closed-depression inventory, the sill between two basins, volume against stage; minimum-cut throat area and clearance width; long profiles and reach-averaged valley sections | TERRAIN-THROATS.md |
| `terrain.wrfgrid` / `terrain.conditioning` / `terrain.skyview` | a WRF `geo_em` on a `Grid`, `HGT_M` against its source (crater detector), WPS tile coverage; slope limiting and channel breaching; sky-view factor | TERRAIN-THROATS.md |
| `drainage.cooling` / `drainage.slopeflow` / `drainage.hydraulics` / `drainage.cascade` | idealised theory on that geometry: clear-night surface energy balance, Prandtl and bulk slope flow, Froude numbers and pool tilt, reduced-gravity throat capacity (critical, drowned, friction-limited), fill-and-spill of linked basins. numpy only | DRAINAGE-THEORY.md |
| `flow.mountainwave` / `flow.layer` / `flow.leewaves` / `flow.seiche` / `flow.pool` / `flow.volume` | idealised stratified flow over that geometry: linear 3-D waves (with constant-height `planes`) and layered lee waves, one-layer hydraulics, trapped-wave criteria, free and forced pool seiches and their currents, the soft-boundary pool; `volume` composes them into theta and wind per cell. numpy (scipy for seiches) | FLOW-THEORY.md |
| `nwp.wrf_write` | the inverse of `wrf_output`: writes idealised fields as wrfout (T, PHB, staggered U/V/W, COSALPHA/SINALPHA) that WRF readers and brc-voxel-viz take unchanged; each file is marked as theory | FLOW-THEORY.md |
| `drainage.sinks` | `tomllib`-only reader for the lookups.toml `[sinks.*]` table (basins, exits, throats), waypoints and regions -- usable where `brc_tools.nwp` cannot be imported | DRAINAGE-THEORY.md |
| `nwp.wrf_trajectories` | offline forward/backward kinematic trajectories from any WRF stream carrying `U, V, W, PH, PHB`, integrated in model-index space | WRF-TRAJECTORIES.md |
| `obs.profiles` / `satellite.goes` / `utils.solar` | stations read as theta-against-height profiles, heat deficit and drainage metrics; GOES ABI L2 listing, download and parallax-corrected resampling (`requests`, no S3 client); sun position, sunrise/sunset and one-night-long night windows | EVENT-DIAGNOSTICS.md |
| `nwp.wrf_convective` | auxhist stream + convective diagnostics | WRF-CONVECTIVE.md |
| `nwp.convective_env` | MetPy parcel/shear/SRH environment | WRF-CONVECTIVE.md |
| `nwp.wrf_tslist` | `.TS` traces + level profiles | WRF-CONVECTIVE.md |
| `nwp.wrf_engine` | shared TOML/time plumbing + FigureLedger for the engines | WRF-WINDS.md |
| `nwp.wrf_output` / `nwp.wrf_figures` | publication figure engine (pelican2013 — frozen) | WRF-FIGURE-ENGINE.md |
| `nwp.forecast_funnel` | NAM synoptic-montage data | FORECAST-FUNNEL.md |
| `visualize.grid` | field/section plots — **brc-wrf import seam** | WRF-FIGURE-ENGINE.md |
| `visualize.wrf_curtain` | native-eta curtains (ASL or terrain-flattened) | WRF-WINDS.md |
| `visualize.tracer_origin` | tracer curtains/spectra/origin maps | WRF-WINDS.md |
| `visualize.timeheight` | tslist time–height sections | WRF-WINDS.md |
| `visualize.coldpool3d` / `visualize.profile` / `visualize.hodograph` | 3-D isentrope views / θ+humidity+wind profiles / hodographs | WRF-WINDS.md, WRF-CONVECTIVE.md |
| `radar.iem` / `radar.nexrad` | observed Level-III (IEM RIDGE) / Level-II (MetPy) + 4/3-Earth beam geometry | WRF-CONVECTIVE.md |

## Configuration: lookups.toml

Central registry at `brc_tools/nwp/lookups.toml`. Defines:

- **[models]**: hrrr, gefs, rrfs — Herbie model name, init cadence, products, grid methods
- **[regions]**: Named bounding boxes (sw/ne lat-lon)
- **[waypoints]**: Named locations with lat, lon, elevation_m, reference_stid
- **[waypoint_groups]**: Named collections of waypoints
- **[aliases]**: Canonical variable mappings — search strings per model, units, Synoptic equivalents
- **[defaults]**: Cache settings, retry counts, validation flags

### Preserved observation acquisition (research workers)

`ObsSource.metadata`, `ObsSource.networks`, and `ObsSource.fetch_timeseries` accept
`archive=Path`, `budget=Budget`, and Synoptic provider parameters. They return a
`SynopticResult` containing the preserved payload, parsed frame, receipt and receipt
path. The research time-series frame is long: sensor identity, original units,
raw value, QC and sensor metadata stay attached. Existing `timeseries()` remains
unchanged, including its historical pivot/alias behavior; it is not the research
archive interface.

`brc_tools.obs.research.fetch(..., max_station_hours=5000, parse=True)` bounds one
time-series request (the pilot's 5000 by default, Synoptic's 100,000 at most) and,
with `parse=False`, returns the receipt and path without decoding the payload -- a
five-water-year hourly station is a few hundred thousand cells, which the one-dict-
per-cell long frame would not survive on a small host. `request_key` and `receipt_of`
expose the archive's request index.
`brc_tools.obs.research.result(receipt)` replays without network or credentials.

`brc_tools.obs.coverage` reads an archive back: `build_index(archive)` writes
`coverage/windows.parquet` (one row per request x station: window and variables asked)
and `coverage/index.parquet` (one row per station x sensor x UTC day: values and QC
flags returned), incrementally and one object at a time. `plan_requests(stations,
start_wy, end_wy, vars_for=...)` lists the water-year blocks not yet spanned by an
archived window that asked for those variables; an empty answer is a legitimate answer
and is not re-asked. `coverage_report` fills a station x water-year x variable grid.

`brc_tools.obs.daily.build_daily(archive, out_dir, day_basis=("utc", "mst"))` is the
time-zone boundary: per station parquet tables of daily n/mean/min/max per sensor, QC-
flagged values dropped under a named policy and counted, the payload's unit kept verbatim
beside an SI conversion through `obs.units.convert`, `mst` meaning fixed UTC-7. Part
files per archived object make it resumable; overlapping windows keep the later request.
Generic metadata conversion returns SI elevations while retaining original metadata.
`brc_tools.obs.units.convert` uses declared units and returns explicit unsupported
unit status. It never guesses pressure units from values.

`brc_tools.obs.budget.Budget` is for a dedicated, single-threaded subprocess. Its
transport context wraps the libraries' existing Requests transport, including
SynopticPy's import-time token check. It carries a named **tier**: `pilot` (default;
at most eight requests per provider and batch) or `historical` (at most 60 per batch
and 300 per rolling 24 h, counted across every batch in the ledger). Both keep one
request in flight, 30 seconds after each completed request, 10/60 second connect/read
timeouts, and no retries or automatic redirects. `headroom()` reports what is left in
the batch and the window without taking the lock; `acknowledge_empty_probe(reason)`
clears a stop caused only by a *no data* answer (HTTP 200, RESPONSE_CODE 2, no quota
wording), the case of a probe into history the token does not cover. Request outcomes,
including crashes and rejected responses, are persistent. Authorization, quota,
HTTP errors and payload errors stop acquisition. A reviewed redirect can be
acknowledged explicitly without resetting counts; this cannot clear other failures.
The local lock does not coordinate jobs on another host or account-wide usage.

Canonical archives retain scientific content without rounding, share compressed
content-addressed station metadata, remove only the documented response timing
fields, redact credentials and verify object/receipt hashes on replay. They are
not original wire bytes. Archive and ledger roots are supplied by the caller.

`brc_tools.api.soundings.archive.station_archive(..., year=2026)` caches a NOAA
current-year ZIP once; `extract(receipt,start,end)` uses Siphon's parser offline,
returns all decoded columns and SI winds, and separates a missing launch from a
parse/request failure. Original ZIP bytes preserve fields and precision not carried
by Siphon's normalized frame. The caller verifies the published current-year file
before requesting it; this interface does not probe alternate years/providers.

References checked 2026-11-10:
[Synoptic limits](https://docs.synopticdata.com/services/api-performance-and-limits),
[Synoptic errors](https://docs.synopticdata.com/services/errors),
[NOAA IGRA](https://www.ncei.noaa.gov/products/weather-balloon/integrated-global-radiosonde-archive).
