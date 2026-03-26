# AI Agent Quick Reference - brc-tools

**Current Task:** Minimal hourly HRRR road proof-of-concept
**Status:** Local code, tests, and one live dry-run working; upload still off by default
**Last Session:** 2026-03-26
**Working Branch:** `feat/hrrr-road-poc-minimal`

---

## Start Here
- Read `README.md` and the `Current Session Endpoint (2026-03-26)` section.
- Read `AGENTS.md` for working rules.
- Read `HRRR-MERGE-PLAN.md` before expanding the HRRR work.

---

## Current Endpoint

### Done
- Shared HRRR access layer added in `brc_tools/download/hrrr_access.py`.
- Shared HRRR config and route metadata added in `brc_tools/download/hrrr_config.py`.
- Hourly road CLI added in `brc_tools/download/get_road_forecast.py`.
- Smoke wrapper added in `scripts/run_road_forecast_smoke.sh`.
- Logic tests added in `tests/test_road_forecast_logic.py`.
- Packaging updated from `synoptic` to `SynopticPy`.
- HRRR path cleaned so importing the road CLI no longer pulls Synoptic code.

### Verified
- Dedicated env: `/home/johnrobertlawson/.conda/envs/brc-tools`
- Tests: `python -m pytest tests/test_road_forecast_logic.py`
- Live dry-run: one successful `--max-fxx 1` run writing JSON to `/tmp/brc-tools-road-smoke`

### Next Small Steps
1. Run a `6-12` hour dry-run.
2. Harden partial-hour handling and add tests.
3. Decide the v1 road upload bucket before enabling upload.
4. Keep aviation separate and start it only after road output is stable.

---

## Key Files
- `brc_tools/download/get_map_obs.py`: production observation pipeline
- `brc_tools/download/push_data.py`: shared upload helper used across repos
- `brc_tools/download/hrrr_access.py`: shared HRRR fetch and extraction helpers
- `brc_tools/download/hrrr_config.py`: HRRR query map and route metadata
- `brc_tools/download/get_road_forecast.py`: minimal hourly road forecast CLI
- `tests/test_road_forecast_logic.py`: first HRRR road unit tests
- `HRRR-MERGE-PLAN.md`: longer implementation plan and caveats

---

## Commands
```bash
/home/johnrobertlawson/.conda/envs/brc-tools/bin/python -m pytest tests/test_road_forecast_logic.py

BRC_TOOLS_HRRR_CACHE=/tmp/brc-tools-hrrr-cache \
/home/johnrobertlawson/.conda/envs/brc-tools/bin/python \
-m brc_tools.download.get_road_forecast \
--dry-run --max-fxx 1 --min-usable-hours 1 \
--data-dir /tmp/brc-tools-road-smoke
```

---

## Guardrails
- Keep `push_data.py` stable unless the same change is needed by both `brc-tools` and `clyfar`.
- Do not merge the old HRRR branches wholesale.
- Keep road and aviation as separate products.
- Hourly road MVP comes before 15-minute output, lagged ensemble work, or website integration.
- Use Miniforge/conda/mamba rather than ad hoc `pip`.

---

## Cross-Repo Pointers
- `../ubair-website`: upload routes and page-side consumers
- `../clyfar`: useful operational patterns for scheduled model download and smoke runs
- `docs/PIPELINE-ARCHITECTURE.md`: repo-local architecture notes
