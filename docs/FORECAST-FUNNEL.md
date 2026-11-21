# Forecast funnel (NAM / GFS synoptic montage)

A **forecast funnel** is the classic top-down forecasting workflow — read the synoptic
scale first (the jet, the long waves), zoom to the regional flow and moisture, then finish
at the surface synoptic analysis. This tool renders that as one publication montage from a
single NAM analysis, matching the repo's WRF-figure aesthetic (Helvetica / minimalist /
fixed colour scales via `visualize/style.py`; fail-soft Natural-Earth overlays via
`visualize/basemap.py`).

- **Skill:** `/basin-forecast-funnel` (`.claude/skills/basin-forecast-funnel/SKILL.md`).
- **CLI:** `scripts/forecast_funnel.py --init-time <when>`.
- **SLURM (DTN):** `scripts/forecast_funnel.dtn.slurm`.
- **Engine:** `brc_tools/nwp/forecast_funnel.py` (data) + `brc_tools/visualize/funnel.py` (render).

## Panels

A 2×2 montage; every panel carries state borders, population-ranked city labels, rivers and
lakes:

| Panel | Domain | Level | Fill | Contours | Vectors |
|-------|--------|-------|------|----------|---------|
| 1a | CONUS | 250 hPa | wind speed (jet isotachs) | geopotential height | barbs |
| 1b | Western CONUS | 500 hPa | **absolute vorticity** | geopotential height | barbs |
| 1c | Utah + neighbours | 600 hPa | **specific humidity** | geopotential height + **temperature advection** (warm red / cold blue) | barbs; basin waypoints labelled |
| 1d | Western CONUS | surface | — | smoothed MSLP isobars | H/L centres + TFP frontal zones |

It is a model **analysis** (f00: NAM, or GFS after NAM's retirement), so the valid time
equals the init time.

## Source (auto-picked by init date)

`funnel_source_for(init_dt)` chooses the download path:

| Init date | Source | How |
|-----------|--------|-----|
| 2020-03 … 2026-11-03 | `herbie` | Herbie operational `nam` model (`product="awphys"`, AWS/NOMADS). Herbie-native (the repo's preferred route). `awphys` ships **RH** (not SPFH) on pressure levels, so specific humidity is derived from RH + T. |
| ≤ 2017-04 | `ncei` | Auth-free NCEI historical grib1 `namanl_218` via `wrf_staging.stage_nam_analysis`. Uses SPFH when present, else derives it from RH + T. |
| 2017-04 … 2020-03 | — | **Unwired** — raises with a clear message. No post-2017 NCEI grib2 template exists yet (see Follow-ups). Use a recent or pre-2017 init for testing. |
| after 2026-11-03 | `gfs` | **GFS 0.25°**, Herbie operational `gfs` model (`product="pgrb2.0p25"`), the successor JRL chose on 2026-11-21 (GH #81). NAM was retired after `nam.20261103` (NWS SCN 26-48). GFS is a regular lat-lon grid, so its winds are earth-relative as published; the fetch sorts it to the NAM layout (longitude −180…180, rows northward) so every gradient keeps its sign. Sea-level pressure is PRMSL. The grid is ~25 km, against NAM's 12 km, so the local panel is coarser. `--source herbie` for these dates still raises, naming the retirement. |

Override with `--source gfs|herbie|ncei` (`gfs` works for any date Herbie's GFS archive holds). Herbie's NAM archive on AWS (`noaa-nam-pds`) runs from
roughly 2020-02 to 2026-11-03; the last day's later cycles may be missing, which Herbie then
reports as file-not-found.

## Usage

```bash
# recent init — Herbie path (run on a DTN for internet)
sbatch scripts/forecast_funnel.dtn.slurm "2026-07-20 00Z"

# historical init — NCEI path
sbatch scripts/forecast_funnel.dtn.slurm "2013-01-31 00Z"

# quick local test on any network node (no SLURM)
python scripts/forecast_funnel.py --init-time "2026-07-20 00Z" \
    --output-dir /scratch/general/vast/$USER/forecast_funnel
```

The montage is written to
`/scratch/general/vast/$USER/forecast_funnel/forecast_funnel_<YYYYMMDD_HHMM>Z.png`.
Outputs and GRIB always route to scratch — the renderer hard-refuses a repo-internal path.

**Map overlays** need the Natural-Earth shapefiles (now including `populated_places` for the
city labels) staged once into the persistent cache: `sbatch scripts/fetch_basemap.dtn.slurm`
→ `$BRC_TOOLS_BASEMAP_DIR`. Overlays are fail-soft — an unstaged layer is silently omitted.

## Fronts are diagnostic

Panel 1d marks **Thermal-Front-Parameter (TFP)** baroclinic zones, coloured by 850 hPa
temperature advection (blue where cold, red where warm). TFP identifies frontal *zones*; it
does **not** truly type warm/cold/stationary fronts the way an analyst would. Treat the
frontal overlay as a first guess, not a hand analysis. On real 12 km data the raw TFP is
noisy, so `forecast_funnel.thermal_front_parameter` smooths the temperature field
(`smooth_sigma`) and **gates out weakly-baroclinic air** (`min_grad_per_100km`); tune those
two, plus `tfp_threshold` in `visualize/funnel.plot_synoptic_panel`, if the zones are still
busy or too sparse.

## Follow-ups (not yet built)

- **RRFS North America 13 km** as a finer successor (GH #81 chose GFS 0.25° first). It
  needs a rotated-lat-lon wind rotation, which `derived.rotate_winds_to_earth` refuses today.

- **Post-2017 NCEI grib2 NAM template** to close the 2017–2020 auto-pick gap
  (`nam_218_<date>_<hhmm>_000.grb2`, a new `[models.*]` block in `lookups.toml`).
