# WRF Staging State Playbook

Short print-oriented explanation for John/JRL and Michael. This file describes
what `brc-tools` owns in the WRF workflow, what is already proven, and what
should happen next.

## One-Sentence State

`brc-tools` can stage WRF-ready GRIB inputs for the Jan-2013 Basin case, verify
their integrity, and hand `brc-wrf` a manifest/contract boundary; the NAM-only
single-stream path is proven through WPS, `real.exe`, and `wrf.exe`.

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
| Manifest verification | Proven: the existing proof manifest verifies `28/28 OK`. |
| Contract sidecar | Implemented for fresh stages; old proof scratch predates this sidecar. |
| Lead-time subsetting | Implemented for GEFS reforecast to reduce unnecessary download volume. |
| GEFSv12 reforecast download | Partial staged files proven; full WPS two-stream path not proven. |
| DTN posture | Full transfer work should run on `notchpeak-dtn`, not login nodes. |

## What `brc-wrf` Has Proven With These Inputs

| Stage | Result |
| --- | --- |
| WPS with NAM only | Produced 14 `met_em` files for d01/d02, 6-hour cadence. |
| `real.exe` | Reached `SUCCESS COMPLETE REAL_EM INIT`. |
| `wrf.exe` | Reached `SUCCESS COMPLETE WRF`. |
| Archive | Produced a durable `lawson-group6` run directory. |
| Visual QA | `brc-wrf` can now render no-run quicklooks from existing artifacts. |

## Where We Should Go Next

| Order | Next move | Stop point |
| --- | --- | --- |
| 1 | ✅ Done — `feat/wrf-input-staging` merged to `main` (PR #22 NAM-only, PR #23 hygiene batch). | `main` now contains the proven staging boundary. |
| 2 | Keep NAM-only as the baseline proof. | Do not rename it as GEFS+NAM. |
| 3 | Decide whether GEFS+NAM is needed for the next science question. | If yes, design the WPS two-stream proof with `brc-wrf`; if no, improve NAM repeatability. |
| 4 | If GEFS+NAM is pursued, run a no-download design pass first. | Confirm Vtable, source split, and expected missing fields before WPS. |
| 5 | Keep every full-stage or full-run step behind CHPC ownership boundaries. | DTN for downloads, `brc-wrf` for WPS/WRF, `brc-knowledge` for Slurm truth. |

## Reading Packet

Read these with the matching `brc-wrf` packet:

1. `docs/WRF-INPUT-STAGING.md`
2. `docs/WRF-STAGING-STATE-PLAYBOOK.md`
3. `../brc-wrf/brc-docs/BRC-TOOLS-LINK-HANDOFF.md`
4. `../brc-wrf/brc-docs/BRC-WRF-STATE-PLAYBOOK.md`
5. `../brc-wrf/brc-docs/BRC-WRF-FIRST-CASE.md`
6. `../brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md` sections 1-3 and Q1
7. `../brc-knowledge/scholarium/reference-base/resources/wrf-on-chpc-quickstart.md` sections 2, 3, and 8

For a new developer, the key idea is simple: `brc-tools` makes the input pile
clean and auditable; `brc-wrf` proves WRF can consume it.
