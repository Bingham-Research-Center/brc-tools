# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations (SynopticPy) and NWP model data (Herbie) on CHPC; pushes
JSON to the BasinWX website. Package: **`brc_tools`** (underscore).
Repo: **`brc-tools`** (hyphen).

## Current focus
- HRRR/RRFS → BasinWX operational ingest (GH issue #10). Strategy and status: `docs/nwp/ROADMAP.md`.
- Case-study pipeline (natural language → script → figures). Pattern: `docs/CASE-STUDY-GUIDE.md`.
- **WRF-input staging**: stage GRIB → scratch as a `manifest_<case>.json` + `contract_<case>.json` handshake that `brc-wrf` consumes for WPS/WRF. brc-tools owns staging/manifests/contracts/NWP-download + the reusable `visualize/grid.py` quicklook helpers; WPS/`real.exe`/`wrf.exe`/run-Slurm stay in `brc-wrf`. NAM-only proven & merged; GEFS+NAM two-stream optional/unproven; RAP source requested by brc-wrf, not yet added. State → `docs/WRF-STAGING-STATE-PLAYBOOK.md`; cross-repo entry → `../brc-wrf/brc-docs/BRC-TOOLS-LINK-HANDOFF.md` (full WRF doc set in Doc map below).
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
- `docs/WRF-INPUT-STAGING.md` — WRF/WPS GRIB staging: status, microtasks, CHPC DTN + SLURM
- `docs/WRF-STAGING-STATE-PLAYBOOK.md` — terse WRF staging state and reading packet
- `docs/WRF-GEFS-NAM-FIELD-MAP.md` — DRAFT GEFS/NAM two-stream field-map (NOT proven)
- `docs/HANDOFF-TO-BRC-WRF.md` — paste-prompt to hand the WRF run side to a brc-wrf session
- `docs/HANDOFF-TO-BRC-WRF-HYGIENE.md` — cross-repo wiring + AGENTS-caretaker handoff to brc-wrf
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
- **Units**: NWP temps in K, MSLP in Pa, wind in m/s. Obs already in C / Pa / m/s (Synoptic returns Pa — `lookups.toml` `synoptic_units`). Convert at the boundary.
- **Lookups** (`brc_tools/nwp/lookups.toml`) is the source of truth for models, regions, waypoints, waypoint groups, variable aliases. Read it; don't duplicate its contents into docs.

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

All `api/` clients resolve keys via `brc_tools.api._auth.load_api_key(VAR)` — env var
first, then optional `~/.config/<svc>/api_key`; `FR24_API_KEY` is reserved for the
skeleton FlightRadar24 client.

## Testing
```
pytest tests/
```
Local Python work: use a conda env that carries the deps (herbie, polars, pandas,
matplotlib, requests). On this CHPC checkout `clyfar-nov2025` already has them;
fresh setup → `docs/ENVIRONMENT-SETUP.md`. Not bare `python`.

## Related repos
- `ubair-website` — Node.js receiver for uploads (data contract).
- `clyfar` — ozone forecast; imports `brc_tools.download.push_data`.
- `brc-wrf` — WRF runs; consumes brc-tools staging (`manifest`/`contract` sidecars) + imports `brc_tools.visualize.grid`.
- `brc-knowledge` — canonical CHPC infra + validated Slurm run scripts (referenced, not imported).
- `preprint-clyfar-v0p9` — LaTeX manuscript.

Governed by `.github/CODEOWNERS`; PRs require review from
@johnrobertlawson. Personal preferences go in `CLAUDE.local.md`
(gitignored).
