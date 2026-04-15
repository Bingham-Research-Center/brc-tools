# How to write a case study script

Case study scripts are the primary output of `brc_tools`. They fetch NWP
model data and/or station observations for a specific weather event and
produce publication-quality diagnostic figures.

## Anatomy of a case study script

Every case study follows a consistent structure:

```
1. Imports + configuration constants
2. Event selection (user-specified date or scan-and-select)
3. Data fetching (NWP + obs)
4. Figure functions (one per figure)
5. Main function with figure pipeline
```

## Two paths

### Path A: Known date

You already know the event date. Skip scanning, go straight to fetch.

```python
EVENT_DATE = "2025-02-22"
src = NWPSource("hrrr")
datasets = fetch_multi_init(src, EVENT_DATE, [12, 18], SFC_VARS, fhour_map)
```

See: `scripts/case_study_20250222.py`

### Path B: Scan-and-select

You know the phenomenon type (foehn, wind ramp, cold-pool erosion) but
not the date. Scan months of obs to find and rank candidates.

```python
from brc_tools.obs.scanner import scan_events, detect_wind_ramp

candidates = scan_events(
    stid="KVEL",
    variables=["wind_speed_10m", "wind_dir_10m"],
    months=(3, 4, 5),
    year=2025,
    criteria_fn=detect_wind_ramp,
    rank_key="wind_increase",
)
EVENT_DATE = candidates[0]["date"]
```

To write a custom criteria function:

```python
def detect_my_event(day_df: pl.DataFrame, date_val: datetime.date) -> dict | None:
    """Return a dict with at least the rank_key field, or None to skip."""
    # Filter to your time window
    # Apply meteorological criteria
    # Return scored result dict or None
    ...
```

See: `scripts/case_study_kvel_westerly.py`, `scripts/case_study_kvel_foehn.py`

## Step-by-step: writing from scratch

### 1. Define the event

Pick a date (or date range to scan), region, and phenomenon.

### 2. Choose init hours and forecast ranges

```python
INIT_HOURS = [12, 18]               # or [15, 16, 17] for close comparison
fhour_map = {12: range(0, 19),      # 12Z→06Z+1
             18: range(0, 13)}      # 18Z→06Z+1
```

### 3. Choose variables

Surface aliases (from `lookups.toml`):
- Temperature/moisture: `temp_2m`, `dewpoint_2m`, `rh_2m`
- Wind: `wind_u_10m`, `wind_v_10m` (fetch these; derive speed/dir post-hoc)
- Pressure: `mslp`
- Boundary layer: `pbl_height`
- Precipitation: `precip_1hr`, `snow_depth`
- Stability: `cape_surface`, `cin_surface`

Pressure-level aliases (pass `levels=[...]` to fetch):
- `temp_pl`, `wind_u_pl`, `wind_v_pl`, `height_pl`, `rh_pl`, `omega_pl`

### 4. Choose waypoints

Waypoint groups (from `lookups.toml`):
- `foehn_path` — 6 stations W→E: Daniels Summit → Vernal
- `us40_dense` — 14 stations along US-40 corridor
- `basin_full` — 6 core basin stations
- `basin_aq` — 5 air-quality-focused stations
- `basin_west`, `basin_east` — subsets

### 5. Write figure functions

Each figure in its own function. Use the visualisation library:

```python
def figure_wind_evolution(datasets, waypoints):
    fig = plot_planview_evolution(
        datasets[18], "wind_speed_10m",
        waypoints=waypoints, cmap="YlOrRd", vmin=0, vmax=20,
        wind_barbs=True, barb_skip=5,
        suptitle=f"HRRR 18Z | Wind Speed | {EVENT_DATE}",
    )
    annotate(fig, "HRRR | BRC Tools")
    fig.savefig(OUTDIR / "wind_evolution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
```

### 6. Wire up main

```python
run_figure_pipeline([
    ("Wind evolution", figure_wind_evolution, (datasets, waypoints)),
    ("Temp timeseries", figure_temp_ts, (wp_series, obs_df, waypoints)),
    ...
])
```

## Unit conventions

| Source | Temperature | Pressure | Wind speed |
|--------|------------|----------|------------|
| NWP (Herbie) | Kelvin | Pa | m/s |
| Obs (Synoptic) | Celsius | hPa | m/s |
| Display | Celsius | hPa | m/s or kt |

Conversions: `temp_K_to_C`, `pa_to_hpa`, or inline lambdas.

## Tips

- All times UTC (naive datetime). Never use pytz or timezone-aware objects.
- Polars for tabular data, xarray for gridded. Never mix.
- `add_wind_fields(ds)` must be called after `fetch()` to get wind_speed_10m.
- Figures go in `figures/{case_name}/` (gitignored).
- Use `--scan-only` flag for quick obs-scanning dry runs.
- Each figure function should be self-contained. `run_figure_pipeline` wraps
  each in try/except so one failure doesn't stop the rest.
