# WRF Staging State Playbook

Short print-oriented explanation for John/JRL and Michael. This file describes
what `brc-tools` owns in the WRF workflow, what is already proven, and what
should happen next. **This is the single cold-start source of truth for the WRF
lane** — start here; the detail/proof lives in `docs/WRF-INPUT-STAGING.md`.

## Cold-start handoff (for the next Claude Code session)

**You are in `brc-tools`. GFS analysis is now a supported, staged, verified, and
WRF-consumed second forcing source for the Pelican hot-swap lane. `brc-wrf`
already ran WPS (`Vtable.GFS`) -> metgrid -> `real.exe` -> `wrf.exe`, archived
the run, and rendered paired NAM/GFS quicklooks.**

State (2026-06-30):
- **NAM baseline complete:** `brc-wrf` has the successful
  `pelican2013_nam_3_1_333m_75lev` 3/1/0.333 km, 75-level, six-hour run.
- **RAP staged + verified, but blocked in WRF:** the RAP bundle under
  `/scratch/general/vast/$USER/wrf_inputs/pelican2013_rap_3_1_333m_75lev/`
  has 7 hourly RAP-130 GRIB files and a valid contract, but two WPS-only
  `brc-wrf` proofs blocked before `real.exe`: hybrid RAP lacked a real-ready
  3D atmosphere, and pressure RAP lacked layered soil temperature/moisture.
- **ERA5 blocked locally:** no `era5` WRF-staging source exists here,
  `brc-tools-2026` lacks `cdsapi`/`ecmwfapi`, and CDS credentials were not
  configured. `brc-wrf` has a plausible WPS-side `Vtable.ECMWF`, but staging is
  not ready.
- **GFS analysis SUPPORTED + STAGED + VERIFIED + CONSUMED (2026-06-30):** added
  `[models.gfs_analysis]` (NCEI grid-004 0.5° GRIB2, auth-free direct GET — same
  lane as NAM/RAP) + `stage_gfs_analysis()` + matrix row + tests. Field adequacy
  CONFIRMED from the live `.inv` (4-layer soil T/moisture, land-sea mask, skin
  temp, snow/ice, 26-level atmosphere — the soil + real-ready 3D atmosphere RAP
  lacked). Staged + `verify_manifest` 2/2 OK to
  `/scratch/general/vast/$USER/wrf_inputs/pelican2013_gfs_3_1_333m_75lev/`
  (12Z+18Z, `wps_fg_name=["GFS"]`, `interval_seconds=21600` — an exact structural
  mirror of the NAM baseline). `brc-wrf` consumed the contract in job `13753673`;
  WPS, `real.exe`, `wrf.exe`, and archive completed, with
  `NUM_METGRID_SOIL_LEVELS = 4`. Paired NAM/GFS quicklooks completed in job
  `13755401`. Chosen over NCAR-RDA FNL (auth-gated; 0.5° GFS is finer than 2013
  FNL's 1°). NCEI product:
  https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast
- **Environment guardrail:** every brc-tools Python, Herbie, WRF
  source-planning, staging, manifest-verification, or pytest command must use
  `conda run -n brc-tools-2026 ...` or
  `/uufs/chpc.utah.edu/common/home/u0737349/software/pkg/miniforge3/envs/brc-tools-2026/bin/python`.
  Do not rely on inherited shells; Codex has inherited `clyfar-nov2025` in this
  lane.

Current stop point:
1. Default next work is in `brc-wrf`: review the completed NAM/GFS paired
   quicklooks and write the science-review packet. Do not redo GFS source
   support.
2. Optional new-source work belongs here only if John explicitly asks for FNL,
   corrected RAP, or ERA5/CDS support.
3. Cross-repo handoff:
   `../brc-wrf/brc-docs/BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md`.

Optional brc-tools fast-follow (only if `brc-wrf` wants finer LBCs): grid-4 ships
`_003`/`_006` offsets, so 3-hourly boundaries (`interval_seconds=10800`) are
available from the 12Z+18Z cycles with a small stager change (forecast-offset
enumeration; the analysis filename template currently hardcodes `_000`).

Read for full context:
- `docs/WRF-INPUT-STAGING.md` - NAM-only end-to-end proof detail.
- `docs/nwp/NWP-SOURCE-MATRIX.md` - per-source Herbie-vs-direct decisions and
  Herbie currency.
- `../brc-wrf/brc-docs/BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md` - active
  cross-repo handoff and paste prompts.
- `../brc-wrf/brc-docs/BRC-WRF-PELICAN-RAP-FEASIBILITY.md` - RAP Vtable
  candidates and field gaps, only if RAP is explicitly revived.
- Caretaker: when a brc-tools path moves, re-check that
  `../brc-tools` <-> `../brc-wrf` doc links still resolve. `brc-wrf` consumes
  the contract sidecar, not `staged_files`.

Stop points (still `brc-wrf`/human-owned): WPS, `real.exe`, `wrf.exe`, `sbatch`,
NetCDF-heavy reads, archive inventories, and quicklooks. brc-tools staging for the
GFS hot-swap is done (John-authorized 2026-06-30); any *further new-source*
downloads/staging still warrant a heads-up first.

Remaining brc-tools backlog (not blocking brc-wrf): `WISHLIST-TASKS.md` → "Session closeout" section.

Maintenance check after WRF-lane doc edits:

```bash
conda run -n brc-tools-2026 python scripts/check_wrf_doc_freshness.py
```

## One-Sentence State

`brc-tools` can stage WRF-ready GRIB inputs (NAM, RAP, and now GFS analysis; GEFS
reforecast partial), verify their integrity, and hand `brc-wrf` a manifest/contract
boundary; the NAM-only single-stream path is proven through WPS, `real.exe`, and
`wrf.exe`, and GFS analysis is staged, verified, and consumed by the completed
Pelican GFS WRF-side run plus paired NAM/GFS quicklooks.

## What This Repo Owns

| Owns | Plain language |
| --- | --- |
| NWP source access | Herbie/NCEI/S3-facing data discovery and downloads. |
| WRF input staging | Put GRIB files under `/scratch/general/vast/$USER/wrf_inputs/<case>/`. |
| Manifest verification | Prove every staged file still exists and matches size/hash. |
| Case contract | Tell `brc-wrf` the WPS-relevant facts: sources, cadence, `fg_name`, and `interval_seconds`. |
| Input quicklooks | Sanity maps of staged source data before WPS/WRF consumes it. |

This repo does not run WPS, `real.exe`, `wrf.exe`, or Slurm WRF integrations.
Those belong in `brc-wrf`, using CHPC settings from `brc-knowledge`.

## What Is Proven

| Item | Status |
| --- | --- |
| NAM analysis staging | Proven and used in the successful Jan-2013 WRF proof. |
| GFS analysis staging | Supported (`gfs_analysis`) + staged + `verify_manifest` 2/2 OK for `pelican2013_gfs_3_1_333m_75lev` (12Z+18Z); field-complete per the `.inv`; consumed by the completed `brc-wrf` GFS WRF-side run. |
| Manifest verification | Proven: the existing proof manifest verifies `28/28 OK`. |
| Contract sidecar | Implemented for fresh stages; old proof scratch predates this sidecar. |
| Lead-time subsetting | Implemented for GEFS reforecast to reduce unnecessary download volume. |
| GEFSv12 reforecast download | Partial staged files proven; full WPS two-stream path not proven. |
| DTN posture | Full transfer work should run on `notchpeak-dtn`, not login nodes. |

## What `brc-wrf` Has Proven With These Inputs

| Stage | Result |
| --- | --- |
| WPS with NAM only | Produced 14 `met_em` files for d01/d02, 6-hour cadence. |
| WPS with GFS analysis | Produced `num_metgrid_levels = 27` and `NUM_METGRID_SOIL_LEVELS = 4` for the Pelican 3-domain run. |
| `real.exe` | Reached `SUCCESS COMPLETE REAL_EM INIT`. |
| `wrf.exe` | Reached `SUCCESS COMPLETE WRF`. |
| Archive | Produced a durable `lawson-group6` run directory. |
| Visual QA | `brc-wrf` rendered paired NAM/GFS standardized quicklooks, 30 PNGs per forcing. |

## Where We Should Go Next

| Order | Next move | Stop point |
| --- | --- | --- |
| 1 | ✅ Done — `feat/wrf-input-staging` merged to `main` (PR #22 NAM-only, PR #23 hygiene batch). | `main` now contains the proven staging boundary. |
| 2 | Keep NAM-only as the baseline proof. | Do not rename it as GEFS+NAM. |
| 3 | ✅ Done — `gfs_analysis` source support added; GFS grid-4 staged + verified for `pelican2013_gfs_3_1_333m_75lev` (branch `nwp/gfs-analysis-source`). | Contract handed to `brc-wrf` via `BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md`. |
| 4 | ✅ Done — `brc-wrf` ran WPS `Vtable.GFS` -> metgrid -> `real.exe` -> `wrf.exe`; confirmed `NUM_METGRID_SOIL_LEVELS = 4`. | Review paired NAM/GFS quicklooks before approving more source work. |
| 5 | Keep every full-stage or full-run step behind CHPC ownership boundaries. | DTN for downloads, `brc-wrf` for WPS/WRF, `brc-knowledge` for Slurm truth. |

## Reading Packet

Read these with the matching `brc-wrf` packet:

1. `docs/WRF-INPUT-STAGING.md`
2. `docs/WRF-STAGING-STATE-PLAYBOOK.md`
3. `../brc-wrf/brc-docs/BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md`
4. `../brc-wrf/brc-docs/BRC-WRF-STATE-PLAYBOOK.md`
5. `../brc-wrf/brc-docs/BRC-WRF-FIRST-CASE.md`
6. `../brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md` sections 1-3 and Q1
7. `../brc-knowledge/scholarium/reference-base/resources/wrf-on-chpc-quickstart.md` sections 2, 3, and 8

For a new developer, the key idea is simple: `brc-tools` makes the input pile
clean and auditable; `brc-wrf` proves WRF can consume it.
