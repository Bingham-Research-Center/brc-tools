# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations (SynopticPy) and NWP model data (Herbie) on CHPC; pushes
JSON to the BasinWX website. Package: **`brc_tools`** (underscore).
Repo: **`brc-tools`** (hyphen).

## Current focus
- HRRR/RRFS → BasinWX operational ingest (GH issue #10). Strategy and status: `docs/nwp/ROADMAP.md`.
- Case-study pipeline (natural language → script → figures). Pattern: `docs/CASE-STUDY-GUIDE.md`.
- **WRF-input staging**: stage GRIB → scratch as a `manifest_<case>.json` + `contract_<case>.json` handshake that `brc-wrf` consumes for WPS/WRF. brc-tools owns staging/manifests/contracts/NWP-download + the reusable `visualize/grid.py` quicklook helpers; WPS/`real.exe`/`wrf.exe`/run-Slurm stay in `brc-wrf`. NAM-only proven & merged (baseline `pelican2013_nam`); RAP staged but **blocked before `real.exe`** (no layered soil); **`gfs_analysis` added + staged+verified** (`pelican2013_gfs`, #33) as the 2nd IC/LBC forcing — brc-wrf consumes the GFS contract next (WPS `Vtable.GFS` → metgrid/real/wrf); GEFS+NAM two-stream optional/unproven. **Cold-start entry → `docs/WRF-STAGING-STATE-PLAYBOOK.md`** (single source of truth for this lane); proof detail → `docs/WRF-INPUT-STAGING.md`; cross-repo → `../brc-wrf/brc-docs/BRC-TOOLS-LINK-HANDOFF.md`.
- Next up: NWPSource / ObsSource integration tests. Backlog: `WISHLIST-TASKS.md`.

## Repo map
```
brc_tools/        installable package
  nwp/            NWPSource (Herbie), lookups.toml, derived, alignment, case_study, wrf_staging (WRF/WPS GRIB)
  obs/            ObsSource (SynopticPy wrapper), scanner (event detection)
  verify/         deterministic metrics (paired_scores, RMSE/bias/MAE)
  visualize/      planview maps, timeseries panels, grid.py (reusable field/section plots; consumed by brc-wrf)
  download/       Synoptic obs script, push_data uploader, HRRR helpers
  api/            external API clients: FlightAware, FR24, Perplexity, Mistral (shared _auth)
  utils/          lookups, small helpers
scripts/          operational scripts + case studies
docs/             canonical project docs (see Doc map below)
  walkthroughs/   plain-language per-tool guides + glossary
tests/            pytest suite
figures/          generated output (gitignored)
```

## Doc map (single source of truth per topic)
- `README.md` — install + minimal quick usage (human onboarding)
- `docs/walkthroughs/` — plain-language per-tool walk-throughs + shared glossary (new-hire entry point)
- `docs/README.md` — index of the `docs/` directory (mirrors this map)
- `docs/API-REFERENCE.md` — full module / function reference
- `docs/API-CLIENTS.md` — external API-client helpers (e.g. FlightAware/AeroAPI)
- `docs/CASE-STUDY-GUIDE.md` — how to write a case-study script (pattern, conventions)
- `docs/CHPC-REFERENCE.md` — CHPC account, partitions, salloc, cron (incl. HRRR upload)
- `docs/WEBSITE-INTEGRATION.md` — BasinWX upload contract (endpoint, auth, dataTypes, schemas, fan-out)
- `docs/ENVIRONMENT-SETUP.md` — conda / venv setup
- `docs/CROSS-REPO-SYNC.md` — sync protocol with clyfar / ubair-website / preprint
- `docs/nwp/ROADMAP.md` — HRRR/RRFS strategy and phase tracker
- `docs/nwp/NWP-SOURCE-MATRIX.md` — per-source download matrix (Herbie vs direct), idiosyncrasies, Herbie currency
- `docs/WRF-INPUT-STAGING.md` — WRF/WPS GRIB staging: status, microtasks, CHPC DTN + SLURM
- `docs/WRF-STAGING-STATE-PLAYBOOK.md` — **WRF-lane cold-start source of truth** (state + next-session handoff)
- `docs/WRF-GEFS-NAM-FIELD-MAP.md` — DRAFT GEFS/NAM two-stream field-map (parked, NOT proven)
- `WISHLIST-TASKS.md` — prioritised backlog

When introducing or editing a topic, find its canonical home above and
edit there; do not duplicate into CLAUDE.md.

## Key data-flow anchor (load-bearing — verify before changing)
`brc_tools.download.push_data.send_json_to_server(server_address, fpath, file_data, API_KEY)`
POSTs `multipart/form-data` to `{server_address}/api/upload/{file_data}`
with headers `x-api-key` (32-char hex from `DATA_UPLOAD_API_KEY`) and
`x-client-hostname` (must end `.chpc.utah.edu`). Server URL resolves
`BASINWX_API_URLS` (env, comma-sep for fan-out) → `~/.config/ubair-website/website_urls`
→ `website_url` (legacy). Health: `/api/health`.
**`clyfar` imports this function** — do not change its signature without
a cross-repo PR. Operational deployment lives in `docs/CHPC-REFERENCE.md`.

A second cross-repo interface: `brc_tools.visualize.grid` (`plot_grid_field`,
`plot_vertical_section`) is imported by `brc-wrf`'s `wrf_quicklook.py` — treat its
public signatures as load-bearing too.

## Conventions
- **UTC internally, always.** `datetime.timezone.utc`, never pytz. (Servers sit in different local zones — UTC is the portable invariant; convert to Mountain only at display.)
- **No path crosses machines.** CHPC and the Linode/Akamai website hub share **no filesystem**; absolute paths (`/uufs`, `/scratch`, `~`) are machine-local (CHPC-only here). The cross-machine seam is the **HTTP URL contract** (`BASINWX_API_URLS` / `~/.config/ubair-website/website_url`), never a shared path; in-repo doc/code references use **relative** paths. Same discipline as UTC: commit the portable invariant (UTC / URL / relative), never the machine-specific form. **Cold-start check:** if a doc or script hands an absolute path to the *other* server, that's a bug.
- **Runtime outputs stay out of the repo checkout.** New code/docs should route generated JSON, caches, GRIB, logs, temp files, and locks to machine-appropriate locations **outside** `~/gits/brc-tools/`: use `/scratch/general/vast/$USER/...` for large reproducible data, `~/.cache/brc-tools/...` or env-driven paths for per-user caches, and `tempfile.gettempdir()` / `/tmp` for short-lived temp/lock files. Do **not** introduce repo-local runtime defaults like `~/gits/brc-tools/data/...` or user-specific absolute examples like `/uufs/chpc.utah.edu/common/home/u0737349/...` unless the file is an intentional committed fixture/schema/example.
- **Polars** preferred over pandas for new code.
- **American English** in code identifiers (British prose is fine).
- **Imports**: stdlib → third-party → local.
- **JSON filenames**: `generate_json_fpath()` → `{prefix}_{YYYYMMDD_HHMM}Z.json`.
- **API calls**: wrap in try/except; log and continue; retry with backoff at boundaries only.
- **NWP code** lives in `brc_tools/nwp/`, not `brc_tools/download/`.
- **Don't reinvent NWP downloads — check Herbie first.** Brian Blaylock's Herbie ([herbie.readthedocs.io](https://herbie.readthedocs.io)) ships hardened, on-rails model templates (`herbie/models/*.py`) for most NOAA/NCEI sources — prefer them over hand-rolled fetches. Record each source's Herbie-native-vs-direct decision in `docs/nwp/NWP-SOURCE-MATRIX.md` (enforced by `tests/test_source_matrix.py`). A hand-rolled GET is the exception and must justify why Herbie doesn't fit (today: `nam_analysis`/`rap_analysis`/`gfs_analysis`, which Herbie can't retrieve for 2013).
- **Units**: NWP temps in K, MSLP in Pa, wind in m/s. Obs already in C / Pa / m/s (Synoptic returns Pa for pressure; units are per-alias in `lookups.toml` `synoptic_units`). Convert at the boundary (e.g. Pa→hPa) only for display.
- **Lookups** (`brc_tools/nwp/lookups.toml`) is the source of truth for models, regions, waypoints, waypoint groups, variable aliases. Read it; don't duplicate its contents into docs.
- **Visualizations use Helvetica, and never write into the repo.** Every figure sets a Helvetica-first sans-serif stack — `["Helvetica", "Nimbus Sans", "Arial", "Liberation Sans", "DejaVu Sans"]` (Helvetica is proprietary and absent on CHPC, so **Nimbus Sans**, its URW metric-clone, renders it identically). Generated images must land **outside** the checkout: default to CHPC group storage `/uufs/.../lawson-group6/jrlawson/brc-tools-output` (override `BRC_TOOLS_OUTPUT_DIR`), never `figures/` in the repo. Reference impl: `scripts/basin_floor_ozone_snow.py` (`_apply_style`, `DEFAULT_OUTPUT_ROOT`).

## Environment variables
| Var | Purpose | Required? |
|-----|---------|-----------|
| `DATA_UPLOAD_API_KEY` | BasinWX upload auth | for uploads |
| `BASINWX_API_URLS` | BasinWX upload URL(s), comma-sep fan-out; overrides `~/.config/ubair-website/website_url(s)` | optional |
| `SYNOPTIC_TOKEN` | Synoptic obs (also via `~/.config/SynopticPy/config.toml`) | for obs |
| `FLIGHTAWARE_API_KEY` | FlightAware AeroAPI (`api/` clients) | aviation only |
| `PERPLEXITY_API_KEY` | Perplexity client + `.mcp.json` MCP server | optional |
| `MISTRAL_API_KEY` | Mistral client + `.mcp.json` MCP server | optional |
| `BRC_TOOLS_HERBIE_CACHE` | NWP GRIB cache dir override | optional |
| `BRC_TOOLS_HRRR_CACHE` | HRRR GRIB cache dir override | optional |
| `BRC_TOOLS_LOCK_DIR` | Parallel-download lock dir | optional |
| `BRC_TOOLS_HTTP_IPV4_ONLY` | Force IPv4 (CHPC DTN IPv6-hang workaround) | optional |

All `api/` clients resolve keys via `brc_tools.api._auth.load_api_key(VAR)` — **env var
only** today (the helper also accepts an optional `~/.config/<svc>/api_key` fallback, but
no client wires it yet); `FR24_API_KEY` is reserved for the skeleton FlightRadar24 client.

## Testing
```
pytest tests/
```
Use a conda env with the deps (herbie, polars, pandas, matplotlib, cfgrib, requests).
Preferred: the dedicated **`brc-tools-2026`** env (`mamba env create -f environment.yml`;
herbie 2026.3.0 — validated, 110 passed); the shared `clyfar-nov2025` also works. Fresh
setup → `docs/ENVIRONMENT-SETUP.md`. Not bare `python`.

## Related repos
- `ubair-website` — Node.js receiver for uploads (data contract).
- `clyfar` — ozone forecast; imports `brc_tools.download.push_data`.
- `brc-wrf` — WRF runs; consumes brc-tools staging (`manifest`/`contract` sidecars) + imports `brc_tools.visualize.grid`.
- `brc-knowledge` — canonical CHPC infra + validated Slurm run scripts (referenced, not imported).
- `preprint-clyfar-v0p9` — LaTeX manuscript.

Governed by `.github/CODEOWNERS`; PRs require review from
@johnrobertlawson. Personal preferences go in `CLAUDE.local.md`
(gitignored).
