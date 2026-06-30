# WRF Staging State Playbook

Short print-oriented explanation for John/JRL and Michael. This file describes
what `brc-tools` owns in the WRF workflow, what is already proven, and what
should happen next. **This is the single cold-start source of truth for the WRF
lane** — start here; the detail/proof lives in `docs/WRF-INPUT-STAGING.md`.

## Cold-start handoff (for the next Claude Code session)

**You are in `brc-tools`. The RAP forcing experiment's brc-tools half is DONE — the next
move is in `brc-wrf`.**

State (2026-06-29):
- **RAP staged + verified on scratch:** `/scratch/general/vast/$USER/wrf_inputs/pelican2013_rap_3_1_333m_75lev/`
  holds 7 hourly RAP-130 GRIB (2013-02-02 12–18Z, ~85 MB), `manifest_*.json` (`verify_manifest` 7/7 OK),
  and `contract_*.json` (`wps_fg_name:["RAP"]`, `interval_seconds:3600`, hourly).
- **`rap_analysis` source merged to `main`** (offline plan/contract/tests + source-generic whole-file
  staging); the NCEI path is live-preflight-confirmed. Env: **`brc-tools-2026`** (herbie 2026.3.0;
  `mamba env create -f environment.yml`).
- **Session PRs merged:** #25 (docs + `docs/nwp/NWP-SOURCE-MATRIX.md` + Herbie guard), #26 (RAP), #27 (env).

Next move — **switch to `brc-wrf`** and consume the contract:
1. Point the brc-wrf case at the contract/manifest above; choose the WPS **Vtable.RAP** (candidates in the
   memo — none generic) and run ungrib → metgrid → real → wrf.
2. ⚠️ **Open risk — verify first:** RAP field-adequacy is UNPROVEN (land-sea mask / soil / snow / skin-temp /
   SST). If RAP alone is short at metgrid, add a NAM filler stream (the parked GEFS+NAM two-stream pattern).

If you instead need a **different NWP model** for ICs/LBCs: the pattern is now small — add `[models.<src>]`
to `lookups.toml` (mirror `nam_analysis`/`rap_analysis`); a whole-file analysis source rides the existing
generic path (zero new code); then `--plan` → one live preflight → one DTN stage → add a source-matrix row
(the `tests/test_source_matrix.py` guard enforces it).

Read for full context:
- `docs/WRF-INPUT-STAGING.md` — NAM-only end-to-end proof detail.
- `docs/nwp/NWP-SOURCE-MATRIX.md` — per-source Herbie-vs-direct decisions + Herbie currency.
- `../brc-wrf/brc-docs/BRC-WRF-PELICAN-RAP-FEASIBILITY.md` — RAP Vtable candidates + field gaps.
- `../brc-wrf/brc-docs/BRC-TOOLS-LINK-HANDOFF.md` — brc-wrf's side of the seam.
- Caretaker: when a brc-tools path moves, re-check that `../brc-tools`↔`../brc-wrf` doc links still resolve
  (a manual pass — keep it true). brc-wrf consumes the **contract sidecar**, not `staged_files`.

brc-wrf session paste-prompt (start a Claude Code session in `~/gits/brc-wrf`):
- **Read:** `brc-docs/BRC-WRF-STATE-PLAYBOOK.md`, `brc-docs/BRC-WRF-PELICAN-RAP-FEASIBILITY.md`, `../brc-tools/docs/WRF-INPUT-STAGING.md`.
- **Login-safe:** `git status --short`; `python brc-cases/wrf_case.py validate <case>.yaml`.
- **Off-login (approved compute/DTN):** `python ../brc-tools/scripts/stage_wrf_inputs.py --verify-manifest /scratch/general/vast/$USER/wrf_inputs/pelican2013_rap_3_1_333m_75lev/manifest_pelican2013_rap_3_1_333m_75lev.json`; point the case `contract_path` at the RAP `contract_*.json`; then `wrf_case.py validate <case>.yaml --strict-files`.
- **Stop points:** no `sbatch`/WPS/`real.exe`/`wrf.exe` without explicit human approval; absolute `/scratch` paths are CHPC-local — never hand one to another machine.

Remaining brc-tools backlog (not blocking brc-wrf): `WISHLIST-TASKS.md` → "Session closeout" section.

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
