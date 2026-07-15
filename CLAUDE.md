# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations (SynopticPy) and NWP model data (Herbie) on CHPC; pushes
JSON to the BasinWX website. Package: **`brc_tools`** (underscore).
Repo: **`brc-tools`** (hyphen).

## Current focus
- **pelican2013 manuscript support** (final-draft push lives in `latex-jrl-mjd-mdpiair-2026`): figure engine + X8 deficit-transport diagnostics merged; the study's evidence packet pins an exact brc-tools SHA — treat `wrf_figures.py`/`wrf_output.py`/`visualize/*` as frozen unless the study repo asks.
- HRRR/RRFS → BasinWX operational ingest (GH #10). Strategy/status: `docs/nwp/ROADMAP.md`.
- Case-study pipeline (natural language → script → figures): `docs/CASE-STUDY-GUIDE.md`.
- **WRF-input staging**: stage GRIB → scratch as `manifest_<case>.json` + `contract_<case>.json` for `brc-wrf` (brc-tools owns staging/download + `visualize/grid.py`; WPS/`real.exe`/`wrf.exe`/run-Slurm stay in `brc-wrf`). NAM-only & GFS proven/merged; RAP blocked pre-`real.exe` (no layered soil); GEFS+NAM two-stream unproven. Cold-start SSOT: `docs/WRF-STAGING-STATE-PLAYBOOK.md`.
- Next up: NWPSource / ObsSource integration tests. Backlog: `WISHLIST-TASKS.md`.

## Repo map
```
brc_tools/        installable package
  nwp/            NWPSource (Herbie), lookups.toml, derived, alignment, case_study, wrf_staging (WRF/WPS GRIB)
  obs/            ObsSource (SynopticPy wrapper), scanner (event detection)
  verify/         deterministic metrics (paired_scores, RMSE/bias/MAE)
  visualize/      planview + timeseries panels; grid.py (field/section plots — brc-wrf seam); figure-engine modules (surface/section/upperair/profile/domains/heatdeficit/deficitflux/basemap/style)
  download/       Synoptic obs script, push_data uploader, HRRR helpers
  api/            external API clients: FlightAware, FR24, Perplexity, Mistral (shared _auth); soundings (IGRA2/Wyoming RAOB) + aqs (EPA AQS AirData bulk), both auth-free
  satellite/      MODIS context imagery (NASA CMR timing + GIBS corrected reflectance, cached, provenance sidecars)
  utils/          lookups, small helpers
scripts/          operational scripts + case studies
docs/             canonical project docs (see Doc map below)
  walkthroughs/   plain-language per-tool guides + glossary
tests/            pytest suite
figures/          generated output (gitignored)
```

## Doc map (single source of truth per topic — load a doc only when its topic is in play)
- `README.md` / `docs/walkthroughs/` — human onboarding + per-tool guides & glossary (new-hire entry)
- `docs/README.md` — index of `docs/` (mirrors this map)
- `docs/API-REFERENCE.md` / `docs/API-CLIENTS.md` — module reference / external API-client helpers
- `docs/CASE-STUDY-GUIDE.md` — how to write a case-study script
- `docs/CHPC-REFERENCE.md` — CHPC account, partitions, salloc, cron (incl. HRRR upload)
- `docs/WEBSITE-INTEGRATION.md` — BasinWX upload contract (endpoint, auth, dataTypes, schemas, fan-out)
- `docs/ENVIRONMENT-SETUP.md` — conda/venv setup · `docs/CROSS-REPO-SYNC.md` — sibling-repo sync protocol
- `docs/MODIS-CONTEXT-RENDERER.md` — portable NASA CMR/GIBS MODIS timing, rendering, cache, and provenance workflow
- `docs/nwp/ROADMAP.md` — HRRR/RRFS strategy · `docs/nwp/NWP-SOURCE-MATRIX.md` — per-source download matrix
- `docs/WRF-STAGING-STATE-PLAYBOOK.md` — **WRF-staging cold-start SSOT**; detail in `docs/WRF-INPUT-STAGING.md`; two-stream draft `docs/WRF-GEFS-NAM-FIELD-MAP.md` (parked)
- `docs/WRF-FIGURE-ENGINE.md` — dataset-agnostic figure engine (`brc_tools/nwp/wrf_figures.py` + `scripts/wrf_figures.py --config <case.toml>`). Per-study case TOMLs + the run/figure inventory live in the active study repo; SSOT index → `../latex-jrl-mjd-mdpiair-2026/verification/figures/archive-inventory.md`
- `WISHLIST-TASKS.md` — prioritised backlog

When editing a topic, edit its canonical doc above; do not duplicate into CLAUDE.md.

## Key data-flow anchor (load-bearing — verify before changing)
`brc_tools.download.push_data.send_json_to_server(server_address, fpath, file_data, API_KEY)`
POSTs `multipart/form-data` to `{server_address}/api/upload/{file_data}`
with headers `x-api-key` (32-char hex from `DATA_UPLOAD_API_KEY`) and
`x-client-hostname` (must end `.chpc.utah.edu`). Server URL resolves
`BASINWX_API_URLS` (env, comma-sep for fan-out) → `~/.config/ubair-website/website_urls`
→ `website_url` (legacy). Health: `/api/health`.
**`clyfar` imports this function** — do not change its signature without
a cross-repo PR. Operational deployment lives in `docs/CHPC-REFERENCE.md`.

A second cross-repo seam: `brc_tools.visualize.grid` (`plot_grid_field`,
`plot_vertical_section`) is imported by `brc-wrf`'s `wrf_quicklook.py` — signatures
load-bearing. The publication figure engine built on it (`wrf_figures.py` over
`wrf_output.py` + `visualize/*`) is documented in `docs/WRF-FIGURE-ENGINE.md` (Doc map).

## Conventions
- **UTC internally, always.** `datetime.timezone.utc`, never pytz. (Servers sit in different local zones — UTC is the portable invariant; convert to Mountain only at display.)
- **No path crosses machines.** CHPC and the website hub (Linode/Akamai) share **no filesystem**; `/uufs`, `/scratch`, `~` are CHPC-local. The cross-machine seam is the **HTTP URL contract** (`BASINWX_API_URLS` / `~/.config/ubair-website/website_url`), never a shared path; in-repo references use **relative** paths. **Cold-start check:** an absolute path handed to the *other* server is a bug.
- **Runtime outputs stay out of the repo checkout.** Route generated JSON, caches, GRIB, logs, temp/lock files **outside** `~/gits/brc-tools/`: `/scratch/general/vast/$USER/...` (large reproducible data), `~/.cache/brc-tools/...` or env-driven (per-user caches), `tempfile.gettempdir()` (temp/locks). No repo-local runtime defaults (`~/gits/brc-tools/data/...`) or user-absolute examples (`/uufs/.../u0737349/...`) unless it's an intentional committed fixture/schema.
- **Polars** preferred over pandas for new code.
- **American English** in code identifiers (British prose is fine).
- **Imports**: stdlib → third-party → local.
- **JSON filenames**: `generate_json_fpath()` → `{prefix}_{YYYYMMDD_HHMM}Z.json`.
- **API calls**: wrap in try/except; log and continue; retry with backoff at boundaries only.
- **NWP code** lives in `brc_tools/nwp/`, not `brc_tools/download/`.
- **Heavy jobs run on SLURM, not login nodes.** Involved processing (WRF figure batches, multi-file analysis, staging) runs as CHPC SLURM jobs — ship a `scripts/*.slurm` wrapper (see `stage_inputs.dtn.slurm`; account `lawson-np`) and call the env python directly since the login env doesn't carry. Study-specific figure wrappers live in the active study repo (e.g. `../latex-jrl-mjd-mdpiair-2026/verification/slurm/pelican_figures.slurm` → the generic `scripts/wrf_figures.py`). Details: `docs/CHPC-REFERENCE.md`.
- **Don't reinvent NWP downloads — check Herbie first.** Brian Blaylock's Herbie ([herbie.readthedocs.io](https://herbie.readthedocs.io)) ships hardened, on-rails model templates (`herbie/models/*.py`) for most NOAA/NCEI sources — prefer them over hand-rolled fetches. Record each source's Herbie-native-vs-direct decision in `docs/nwp/NWP-SOURCE-MATRIX.md` (enforced by `tests/test_source_matrix.py`). A hand-rolled GET is the exception and must justify why Herbie doesn't fit (today: `nam_analysis`/`rap_analysis`/`gfs_analysis`, which Herbie can't retrieve for 2013).
- **Units**: NWP temps in K, MSLP in Pa, wind in m/s. Obs already in C / Pa / m/s (Synoptic returns Pa for pressure; units are per-alias in `lookups.toml` `synoptic_units`). Convert at the boundary (e.g. Pa→hPa) only for display.
- **Lookups** (`brc_tools/nwp/lookups.toml`) is the source of truth for models, regions, waypoints, waypoint groups, variable aliases. Read it; don't duplicate its contents into docs.
- **Navigate, don't dredge.** Ingest high-value tokens, not whole trees. Never blind-`cat`/read entire figure, GRIB, or `run_*` output dirs (the WRF archive is ~30 GB of near-duplicate PNGs) — `ls | wc -l` or glob first, then read the one file you need; load a doc/TOML only when its topic is in play (see Doc map). For WRF run/figure locations + completeness, read the SSOT index `../latex-jrl-mjd-mdpiair-2026/verification/figures/archive-inventory.md`, not the archive tree.

## Environment variables
| Var | Purpose | Required? |
|-----|---------|-----------|
| `DATA_UPLOAD_API_KEY` | BasinWX upload auth | for uploads |
| `BASINWX_API_URLS` | BasinWX upload URL(s), comma-sep fan-out; overrides `~/.config/ubair-website/website_url(s)` | optional |
| `SYNOPTIC_TOKEN` | Synoptic obs (also via `~/.config/SynopticPy/config.toml`) | for obs |
| `FLIGHTAWARE_API_KEY` | FlightAware AeroAPI (`api/` clients) | aviation only |
| `PERPLEXITY_API_KEY` | Perplexity client + `.mcp.json` MCP server | optional |
| `MISTRAL_API_KEY` | Mistral client + `.mcp.json` MCP server | optional |
| `BRC_TOOLS_HERBIE_CACHE` / `BRC_TOOLS_HRRR_CACHE` | NWP / HRRR GRIB cache dir override | optional |
| `BRC_TOOLS_BASEMAP_DIR` | persistent Natural-Earth cache for figure map overlays (else `CARTOPY_DATA_DIR` → scratch); stage once via `scripts/fetch_basemap.dtn.slurm` | optional |
| `BRC_TOOLS_MODIS_CACHE` | host-local NASA CMR metadata and GIBS corrected-reflectance PNG cache; supports offline rerendering | optional |
| `BRC_TOOLS_AQS_CACHE` | EPA AQS AirData bulk-file cache (default `~/.cache/brc-tools/aqs`) with provenance sidecars | optional |
| `BRC_TOOLS_LOCK_DIR` / `BRC_TOOLS_HTTP_IPV4_ONLY` | parallel-download lock dir / force IPv4 (CHPC DTN IPv6 workaround) | optional |

All `api/` clients resolve keys via `brc_tools.api._auth.load_api_key(VAR)` — **env var
only** today (the helper also accepts an optional `~/.config/<svc>/api_key` fallback, but
no client wires it yet); `FR24_API_KEY` is reserved for the skeleton FlightRadar24 client.

## Testing
```
pytest tests/
```
Use a conda env with the deps (herbie, polars, pandas, matplotlib, cfgrib, requests).
Preferred: the dedicated **`brc-tools-2026`** env (`mamba env create -f environment.yml`;
herbie 2026.3.0 — validated, 180 passed / 2 skipped); the shared `clyfar-nov2025` also works. Fresh
setup → `docs/ENVIRONMENT-SETUP.md`. Not bare `python`.

## Related repos
- `ubair-website` — Node.js receiver for uploads (data contract).
- `clyfar` — ozone forecast; imports `brc_tools.download.push_data`.
- `brc-wrf` — WRF runs; consumes brc-tools staging (`manifest`/`contract` sidecars) + imports `brc_tools.visualize.grid`.
- `latex-jrl-mjd-mdpiair-2026` — **active** pelican2013 WRF study + manuscript; owns the case TOMLs (`verification/config/figures/`) + run/figure inventory (SSOT for run/figure locations), consumes the brc-tools figure engine.
- `wrf-nudge-ozone-air2026` — frozen/read-only predecessor of the above; case TOMLs were copied byte-for-byte into the active repo. Do not use.
- `brc-knowledge` — canonical CHPC infra + validated Slurm run scripts (referenced, not imported).
- `preprint-clyfar-v0p9` — LaTeX manuscript.

Governed by `.github/CODEOWNERS`; PRs require review from
@johnrobertlawson. Personal preferences go in `CLAUDE.local.md`
(gitignored).
