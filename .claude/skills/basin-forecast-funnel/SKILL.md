---
name: basin-forecast-funnel
description: Render a NAM "forecast funnel" montage (250 hPa jet -> 500 hPa flow -> 600 hPa moisture/LLJ -> surface synoptic analysis) for a given analysis init time on CHPC. Use when asked to make a forecast funnel / synoptic overview figure from NAM.
---

# Basin forecast funnel

Drives `scripts/forecast_funnel.py --init-time <when>` (brc-tools) to download a single
NAM analysis and render the four-panel **forecast funnel** as one publication montage
(shared Helvetica look via `visualize/style.py`; state borders, rivers, lakes, and
population-ranked city labels via the fail-soft `visualize/basemap.py` overlays):

- **1a** CONUS, 250 hPa — jet isotachs (fill) + heights + barbs
- **1b** Western CONUS, 500 hPa — absolute-vorticity fill + heights + barbs
- **1c** Utah + neighbours, 600 hPa — specific-humidity fill + heights + temperature advection (warm/cold air) + barbs; basin waypoints labelled
- **1d** Western CONUS surface — smoothed MSLP isobars + auto H/L centres + diagnostic (TFP) frontal zones

Engine: `brc_tools.nwp.forecast_funnel` (data) + `brc_tools.visualize.funnel` (render).
Details + caveats: `docs/FORECAST-FUNNEL.md`.

## Steps
1. **Pick the analysis init time** (ask the user): `'YYYY-MM-DD HHZ'` or `YYYYMMDDHH`,
   UTC. The NAM source is **auto-picked by date**:
   - recent (>= 2020-03) → Herbie operational NAM (AWS/NOMADS);
   - pre-2017 (<= 2017-04) → NCEI historical grib1 `namanl_218`;
   - the 2017–2020 window is **unwired** and errors out — use a recent or pre-2017 init
     for testing (see `docs/FORECAST-FUNNEL.md` for the post-2017 grib2 follow-up).
   Override with `--source herbie|ncei` if you must.
2. **Stage map overlays once (if not already cached):** city labels need the Natural-Earth
   `populated_places` layer alongside the existing ones — `sbatch scripts/fetch_basemap.dtn.slurm`
   into the persistent `$BRC_TOOLS_BASEMAP_DIR`. Overlays are fail-soft: an unstaged layer
   is silently omitted, never a crash.
3. **Submit on a DTN (never a login node):** downloads need internet, which only DTNs have —
   `sbatch scripts/forecast_funnel.dtn.slurm "<init time>"` (or
   `sbatch --export=ALL,INIT="<init time>" scripts/forecast_funnel.dtn.slurm`). The job
   forces IPv4 (CHPC DTN IPv6 workaround), caches GRIB + matplotlib on scratch, points
   `BRC_TOOLS_BASEMAP_DIR` at the persistent overlay cache, and runs download + plot together.
4. **Verify output:** the montage lands at
   `/scratch/general/vast/$USER/forecast_funnel/forecast_funnel_<YYYYMMDD_HHMM>Z.png`;
   the job log (`/scratch/general/vast/$USER/forecast_funnel_<jobid>.out`) prints the path,
   the chosen source, and the panel count. Spot-check that all four panels populated.

## Notes
- **Outputs + GRIB route to scratch, never the repo** (`--output-dir` overrides; the renderer
  hard-refuses a repo-internal path). Default `/scratch/general/vast/$USER/forecast_funnel`.
- Levels default to `250,500,600` hPa (`--levels`); it is a NAM **analysis** (f00), so the
  valid time equals the init time.
- **Fronts are diagnostic, not analyst-typed.** Panel 1d marks Thermal-Front-Parameter
  baroclinic zones (blue where 850 hPa advection is cold, red where warm); treat them as a
  first-guess overlay, not a hand analysis.
- Uses the `brc-tools-2026` env python (herbie 2026.3.0) directly, since the login env does
  not carry into batch jobs.
- Quick local test without SLURM (on any network node): `python scripts/forecast_funnel.py
  --init-time "<when>" --output-dir /scratch/general/vast/$USER/forecast_funnel`.
