# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations (SynopticPy) and NWP model data (Herbie/HRRR) on CHPC;
pushes JSON to the BasinWX website. Python package: **`brc_tools`**
(underscore). Repo: **`brc-tools`** (hyphen).

## Current focus
- NWP integration is operational (HRRR, GEFS, RRFS via `brc_tools/nwp/`).
- Case study pipeline: natural language → Python script → diagnostic figures.
- Issue **#10** tracks HRRR/RRFS → BasinWX. Strategy: `docs/nwp/README.md`.
- HRRR 15-min sub-hourly and ensemble workflows = future extensions.
- Prioritised backlog: `WISHLIST-TASKS.md` (next: integration tests, then HRRR operational pipeline).

## Repo map
```
brc_tools/        installable package
  nwp/            NWPSource (HRRR/GEFS/RRFS via Herbie) + lookups.toml
                  + derived.py (theta-e, wind, gradients) + alignment.py
                  + case_study.py (shared helpers for case study scripts)
  obs/            ObsSource (SynopticPy wrapper, shared alias namespace)
                  + scanner.py (event detection: scan_events, detect_foehn, etc.)
  verify/         deterministic metrics (RMSE, bias, MAE, paired_scores)
  visualize/      planview.py (maps + obs overlay), timeseries.py
  download/       Synoptic obs (get_map_obs.py) + push_data.py uploader
                  + HRRR helpers (hrrr_access.py, get_road_forecast.py)
  aviation/       FlightAware helpers
  utils/          lookups (station IDs, variables) + helpers
  filter/ ml/     scaffolded; stubs
scripts/          case studies + operational scripts
in_progress/      experimental (do not edit except to extract code out)
docs/             project docs (pointers below)
reference/        external references (FlightAware spec)
tests/            pytest suite (scanner, derived, deterministic, road forecast)
figures/          generated output (gitignored)
```

## Primary workflow: natural language → case study

User describes a weather event in natural language → agent writes a
Python script using `brc_tools` → script fetches data and produces
publication-quality diagnostic figures.

**Working references** (read before writing a new case study):
- `scripts/case_study_20250222.py` — 23-figure cold-pool erosion / quasi-front
- `scripts/case_study_kvel_westerly.py` — synoptic wind event with obs scanning
- `scripts/case_study_kvel_foehn.py` — mesoscale foehn with scan-and-select pattern
- `scripts/snow_depth_april_range.py` — obs-only multi-year climatology (no NWP); SynopticPy Metadata for station discovery by bbox + variable

**Pattern:**
1. Scan obs to identify/rank candidate event dates (`scan_events`)
2. Fetch HRRR surface + optional pressure-level data (`NWPSource.fetch`)
3. Compute derived fields (`add_wind_fields`, `add_theta_e`, `hourly_tendency`)
4. Plot planview evolution maps + station time series
5. Run verification (`paired_scores`) if comparing NWP to obs
6. Save figures to `figures/<case_study_name>/` (gitignored)

## Quick-start recipe
```python
from brc_tools.nwp import NWPSource
from brc_tools.nwp.source import load_lookups
from brc_tools.nwp.derived import add_wind_fields, add_theta_e
from brc_tools.visualize.planview import plot_planview_evolution
from brc_tools.visualize.timeseries import plot_station_timeseries
from brc_tools.verify.deterministic import paired_scores

src = NWPSource("hrrr")
ds = src.fetch(init_time="YYYY-MM-DD HHZ", forecast_hours=range(0,13),
               variables=["temp_2m","dewpoint_2m","wind_u_10m","wind_v_10m","mslp"],
               region="uinta_basin")
ds = add_wind_fields(ds); ds = add_theta_e(ds)
wp = {n: load_lookups()["waypoints"][n]
      for n in load_lookups()["waypoint_groups"]["us40_dense"]}
fig = plot_planview_evolution(ds, "theta_e_2m", waypoints=wp, cmap="RdYlBu_r")
```
- Obs: `ObsSource().timeseries(waypoint_group="us40_dense", start=..., end=..., variables=[...])`.
- Station discovery (not supported by ObsSource): `synoptic.services.Metadata(bbox=..., vars=...)` directly.
- Verification: `paired_scores(nwp_df, obs_df, ["temp_2m","wind_speed_10m"])`.
- Event scanning: `scan_events(stid="KVEL", variables=[...], months=(3,4,5), year=2025, criteria_fn=detect_wind_ramp, rank_key="wind_increase")`.

## Module reference (for agent script construction)

### Data acquisition
| Module | Entry point | Returns | Purpose |
|--------|------------|---------|---------|
| `brc_tools.nwp` | `NWPSource(model)` | class | Fetch NWP gridded data |
| `brc_tools.obs` | `ObsSource()` | class | Fetch station observations |
| `brc_tools.obs.scanner` | `scan_events(...)` | `list[dict]` | Scan obs for event candidates |

### NWPSource methods
| Method | Returns | Key parameters |
|--------|---------|----------------|
| `.fetch(init_time, forecast_hours, variables, region=)` | `xr.Dataset` | variables from lookups.toml aliases |
| `.extract_at_waypoints(ds, group=)` | `pl.DataFrame` | waypoint group from lookups.toml |
| `.latest_init()` | `datetime` | most recent available init |

### ObsSource methods
| Method | Returns | Key parameters |
|--------|---------|----------------|
| `.timeseries(stids=, waypoint_group=, start=, end=, variables=)` | `pl.DataFrame` | one of stids/waypoint_group required |

### Derived fields (`brc_tools.nwp.derived`)
| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `add_wind_fields(ds)` | Dataset with wind_u_10m, wind_v_10m | adds wind_speed_10m, wind_dir_10m | call after fetch |
| `add_theta_e(ds)` | Dataset with temp_2m, dewpoint_2m | adds theta_e_2m | uses mslp if present |
| `hourly_tendency(ds, var)` | Dataset | adds `{var}_tendency` | forward difference |
| `horizontal_gradient_magnitude(field)` | DataArray | DataArray | frontal detection |

### Visualisation (`brc_tools.visualize`)
| Function | Returns | Purpose |
|----------|---------|---------|
| `plot_planview(ds, var, ...)` | Figure | Single map panel |
| `plot_planview_evolution(ds, var, ...)` | Figure | Multi-panel time evolution |
| `plot_station_timeseries(nwp_series, var, ...)` | Figure | Multi-station waypoint panels |
| `plot_verification_timeseries(nwp_df, obs_df, var, wp)` | Axes | NWP vs obs at one station |

### Verification (`brc_tools.verify.deterministic`)
| Function | Returns | Purpose |
|----------|---------|---------|
| `paired_scores(nwp_df, obs_df, vars)` | `pl.DataFrame` | Per-station RMSE, bias, MAE, corr |

### Event scanning (`brc_tools.obs.scanner`)
| Function | Returns | Purpose |
|----------|---------|---------|
| `scan_events(stid, variables, months, year, criteria_fn)` | `list[dict]` | Generic obs scan loop |
| `detect_wind_ramp(day_df, date)` | `dict` or None | Wind ramp criteria |
| `detect_foehn(day_df, date)` | `dict` or None | Foehn: warm + dry + wind |
| `print_candidate_table(candidates)` | None | Formatted table output |

### Case study helpers (`brc_tools.nwp.case_study`)
| Function | Returns | Purpose |
|----------|---------|---------|
| `load_waypoints(group)` | `dict` | Waypoint metadata from lookups.toml |
| `fetch_multi_init(src, date, init_hours, vars, fhour_map)` | `dict[int, Dataset]` | Multi-init fetch loop |
| `extract_all_waypoints(src, datasets, group)` | `dict[int, DataFrame]` | Waypoint extraction loop |
| `fetch_obs(waypoint_group=, stids=, event_date=, variables=)` | `DataFrame` or None | Obs fetch with error handling |
| `run_figure_pipeline(figures)` | None | Per-figure try/except runner |
| `annotate(fig, text)` | None | Attribution text |

### Available lookups (`brc_tools/nwp/lookups.toml`)
- **Models**: hrrr, gefs, rrfs
- **Regions**: uinta_basin, uinta_basin_wide, utah, conus
- **Waypoint groups**: `foehn_path` (6 stn W→E), `us40_dense` (14 stn), `basin_full`, `basin_aq`, `basin_west`, `basin_east`
- **Surface aliases**: temp_2m, dewpoint_2m, wind_u_10m, wind_v_10m, wind_speed_10m (derived), wind_dir_10m (derived), mslp, pbl_height, rh_2m, precip_1hr, snow_depth, visibility, cape_surface, cin_surface, wind_gust_10m, cloud_cover_total
- **Pressure-level aliases** (pass `levels=[...]`): temp_pl, wind_u_pl, wind_v_pl, height_pl, rh_pl, omega_pl

## Case study construction pattern

When asked to analyse a weather event, construct a script following this template:

1. **Configuration block**: OUTDIR, EVENT_DATE, INIT_HOURS, SFC_VARS, WP_GROUP, OBS_VARS
2. **Event selection**: Either user-specified date or `scan_events()` to find candidates
3. **Data fetch**: `fetch_multi_init()` for each init hour (adds wind + theta-e by default)
4. **Waypoint extraction**: `extract_all_waypoints()` for point time series
5. **Obs fetch**: `fetch_obs()` for waypoint group and/or single station
6. **Figure functions**: Each figure in its own `def`, returning fig. Use `run_figure_pipeline()`.
7. **Main**: Parse args (`--scan-only`, `--date`), run phases sequentially, save to `figures/{case_name}/`

Key conventions:
- All times in UTC (naive datetime, no timezone)
- Polars DataFrames for tabular data, xarray Datasets for gridded
- NWP temps in Kelvin; obs temps in Celsius; use `unit_transform=lambda x: x-273.15`
- MSLP in Pa from NWP; use `pa_to_hpa()` or `lambda x: x/100.0`
- Wind speed in m/s; use `KT_FACTOR = 1.94384` for knots
- Figures saved as PNG at DPI=150 to `figures/{case_name}/`

## Key data-flow anchor (load-bearing — verify before changing)
`brc_tools.download.push_data.send_json_to_server(server_address, fpath, file_data, API_KEY)`
POSTs `multipart/form-data` to `{server_address}/api/upload/{file_data}`
with headers `x-api-key` (32-char hex) and `x-client-hostname` (must end
`.chpc.utah.edu`). Health check: `{server_address}/api/health`.
Server URL from `~/.config/ubair-website/website_url`; API key from
`DATA_UPLOAD_API_KEY` env var. **`clyfar` imports this function** — do not
change its signature without a cross-repo PR.

## Environment variables
- `DATA_UPLOAD_API_KEY` — required for uploads (32-char hex).
- `SYNOPTIC_TOKEN` — required for Synoptic obs (SynopticPy >=2024.0.0).
  Also via `~/.config/SynopticPy/config.toml`.
- `FLIGHTAWARE_API_KEY` — optional, aviation only.
- `BRC_TOOLS_HERBIE_CACHE` — optional, NWP GRIB cache dir.
- `BRC_TOOLS_LOCK_DIR` — optional, parallel-download lock dir (default: tempdir).

## Conventions
- **UTC internally, always.** `datetime.timezone.utc`, not pytz.
- **Polars preferred** over pandas for new code.
- **American English** in code. British in prose is fine.
- **Import order:** stdlib → third-party → local.
- **JSON filenames:** `generate_json_fpath()` → `{prefix}_{YYYYMMDD_HHMM}Z.json`.
- Wrap API calls in try/except; log and continue; retry with backoff.
- New NWP code → `brc_tools/nwp/`, not `brc_tools/download/`.

## Testing
```
pytest tests/
```

## Docs (detail lives here, not in this file)
- `docs/CHPC-REFERENCE.md` — CHPC account, partitions, salloc, cron
- `docs/ENVIRONMENT-SETUP.md` — venv/conda setup
- `docs/PIPELINE-ARCHITECTURE.md` — fetch → process → push
- `docs/CROSS-REPO-SYNC.md` — protocol for four sibling repos
- `docs/nwp/` — HRRR/RRFS roadmap and branch notes
- `docs/CASE-STUDY-GUIDE.md` — how to write a case study
- `docs/API-REFERENCE.md` — full API reference
- `WISHLIST-TASKS.md` — backlog

## Related repos
- `ubair-website` — Node.js site receiving uploads (data contract)
- `clyfar` — ozone forecast model; imports `brc_tools.download.push_data`
- `preprint-clyfar-v0p9` — LaTeX manuscript

Governed by `.github/CODEOWNERS`; PRs require review from @johnrobertlawson.
Personal preferences go in `CLAUDE.local.md` (gitignored).
