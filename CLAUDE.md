# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations (SynopticPy) and NWP model data (Herbie) on CHPC; pushes
JSON to the BasinWX website. Package: **`brc_tools`** (underscore).
Repo: **`brc-tools`** (hyphen).

## Current focus
- HRRR/RRFS → BasinWX operational ingest (GH issue #10). Strategy and status: `docs/nwp/ROADMAP.md`.
- Case-study pipeline (natural language → script → figures). Pattern: `docs/CASE-STUDY-GUIDE.md`.
- **WRF-input staging** (branch `feat/wrf-input-staging`): stage GRIB (GEFS reforecast + NAM analysis) to scratch for WRF/WPS. **End-to-end validated** (NAM-only single-stream → WPS → `real.exe` → `wrf.exe` `SUCCESS COMPLETE WRF`, Jan-2013 Basin); merge gate met, GEFS two-stream still optional. Handoff + microtasks + CHPC/SLURM: `docs/WRF-INPUT-STAGING.md`.
- Next up: NWPSource / ObsSource integration tests. Backlog: `WISHLIST-TASKS.md`.

## Repo map
```
brc_tools/        installable package
  nwp/            NWPSource (Herbie), lookups.toml, derived, alignment, case_study, wrf_staging (WRF/WPS GRIB)
  obs/            ObsSource (SynopticPy wrapper), scanner (event detection)
  verify/         deterministic metrics (paired_scores, RMSE/bias/MAE)
  visualize/      planview maps, timeseries panels
  download/       Synoptic obs script, push_data uploader, HRRR helpers
  aviation/       FlightAware spec-fetch helpers (being retired into api/)
  utils/          lookups, small helpers
scripts/          operational scripts + case studies
docs/             canonical project docs (see Doc map below)
tests/            pytest suite
figures/          generated output (gitignored)
```

## Doc map (single source of truth per topic)
- `README.md` — install + minimal quick usage (human onboarding)
- `docs/API-REFERENCE.md` — full module / function reference
- `docs/CASE-STUDY-GUIDE.md` — how to write a case-study script (pattern, conventions)
- `docs/CHPC-REFERENCE.md` — CHPC account, partitions, salloc, cron (incl. HRRR upload)
- `docs/ENVIRONMENT-SETUP.md` — conda / venv setup
- `docs/CROSS-REPO-SYNC.md` — sync protocol with clyfar / ubair-website / preprint
- `docs/nwp/ROADMAP.md` — HRRR/RRFS strategy and phase tracker
- `docs/WRF-INPUT-STAGING.md` — WRF/WPS GRIB staging: status, microtasks, CHPC DTN + SLURM
- `WISHLIST-TASKS.md` — prioritised backlog

When introducing or editing a topic, find its canonical home above and
edit there; do not duplicate into CLAUDE.md.

## Key data-flow anchor (load-bearing — verify before changing)
`brc_tools.download.push_data.send_json_to_server(server_address, fpath, file_data, API_KEY)`
POSTs `multipart/form-data` to `{server_address}/api/upload/{file_data}`
with headers `x-api-key` (32-char hex from `DATA_UPLOAD_API_KEY`) and
`x-client-hostname` (must end `.chpc.utah.edu`). Server URL from
`~/.config/ubair-website/website_url`. Health: `/api/health`.
**`clyfar` imports this function** — do not change its signature without
a cross-repo PR. Operational deployment lives in `docs/CHPC-REFERENCE.md`.

## Conventions
- **UTC internally, always.** `datetime.timezone.utc`, never pytz.
- **Polars** preferred over pandas for new code.
- **American English** in code identifiers (British prose is fine).
- **Imports**: stdlib → third-party → local.
- **JSON filenames**: `generate_json_fpath()` → `{prefix}_{YYYYMMDD_HHMM}Z.json`.
- **API calls**: wrap in try/except; log and continue; retry with backoff at boundaries only.
- **NWP code** lives in `brc_tools/nwp/`, not `brc_tools/download/`.
- **Units**: NWP temps in K, MSLP in Pa, wind in m/s. Obs already in C / hPa / m/s. Convert at the boundary.
- **Lookups** (`brc_tools/nwp/lookups.toml`) is the source of truth for models, regions, waypoints, waypoint groups, variable aliases. Read it; don't duplicate its contents into docs.

## Environment variables
| Var | Purpose | Required? |
|-----|---------|-----------|
| `DATA_UPLOAD_API_KEY` | BasinWX upload auth | for uploads |
| `SYNOPTIC_TOKEN` | Synoptic obs (also via `~/.config/SynopticPy/config.toml`) | for obs |
| `FLIGHTAWARE_API_KEY` | FlightAware AeroAPI | aviation only |
| `BRC_TOOLS_HERBIE_CACHE` | NWP GRIB cache dir override | optional |
| `BRC_TOOLS_LOCK_DIR` | Parallel-download lock dir | optional |

## Testing
```
pytest tests/
```
Local Python work: use the `brc-tools` conda env, not bare `python`.

## Related repos
- `ubair-website` — Node.js receiver for uploads (data contract).
- `clyfar` — ozone forecast; imports `brc_tools.download.push_data`.
- `preprint-clyfar-v0p9` — LaTeX manuscript.

Governed by `.github/CODEOWNERS`; PRs require review from
@johnrobertlawson. Personal preferences go in `CLAUDE.local.md`
(gitignored).
