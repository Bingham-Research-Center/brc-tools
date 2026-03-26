# Repository Guidelines
Date updated: 2026-03-26

This repo holds shared utilities used across BRC projects.

## First Load
- Read `README.md` first, especially `Current Session Endpoint (2026-03-26)`.
- If touching HRRR work, read `HRRR-MERGE-PLAN.md`.
- If you need a quick machine-readable hand-off, read `AGENT-INDEX.md`.
- Work inside the `brc_tools/` package unless the task is explicitly about docs or packaging.

## Current State
- Production observation upload already exists in `brc_tools/download/get_map_obs.py`.
- Dev-only HRRR road proof-of-concept now exists in:
  - `brc_tools/download/hrrr_access.py`
  - `brc_tools/download/hrrr_config.py`
  - `brc_tools/download/get_road_forecast.py`
  - `scripts/run_road_forecast_smoke.sh`
  - `tests/test_road_forecast_logic.py`
- Verified on `2026-03-26`:
  - dedicated Miniforge env at `/home/johnrobertlawson/.conda/envs/brc-tools`
  - `pytest` passes for the new road logic tests
  - a live `--max-fxx 1` HRRR dry-run succeeds and writes local JSON
- Road and aviation must stay separate products.
- Hourly road MVP comes before 15-minute data, lagged ensemble work, or website-side integration.

## Cross-repo Pointers
- Control plane for tasking and execution reports: `../ceidwad`
- Clyfar domain logic and verification context: `../clyfar`
- BasinWx website upload routes and page consumers: `../ubair-website`
- Clyfar manuscript repo: `../preprint-clyfar-v0p9`
- Durable reference material: `../brc-knowledge`

## Working Rules
- Do not treat this repo as the source of truth for project-specific science logic.
- Use it for shared helpers, reusable data/verification utilities, and common tooling.
- Keep `push_data.py` stable unless both this repo and `clyfar` need the same uploader change.
- Do not pull Synoptic imports into the HRRR-only path.
- Default to Miniforge/conda/mamba, not ad hoc `pip`.
- For HRRR work, write local JSON first and only upload when explicitly requested.
- Prefer small hardening steps over broad merges from the historical HRRR PR branches.
- Use relative paths only.

## Next Small Steps
1. Run a `6-12` hour road dry-run and inspect missing-hour behaviour.
2. Decide the v1 road upload bucket name before enabling upload by default.
3. Add tests around partial HRRR hour availability.
4. Start aviation only after the road payload shape is stable.
