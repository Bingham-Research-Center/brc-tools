# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations and NWP model data on CHPC and pushes JSON to the BasinWX
website (companion repo: `ubair-website`). Used as a library by the
`clyfar` ozone forecast model. Python package name is **`brc_tools`**
(underscore), repo name is **`brc-tools`** (hyphen).

## Current focus
- HRRR/RRFS ingest → BasinWX (GitHub issue **#10**).
- Strategy and read order: **`docs/nwp/README.md`**.
- Reusable HRRR prototypes live on branch `feat/hrrr-road-poc-minimal`,
  not on `main`. New NWP code goes in a new `brc_tools/nwp/` subpackage,
  not in `brc_tools/download/`.
- Phase 1 scope: HRRR hourly + Synoptic historical observations.
  RRFS, sub-hourly HRRR, and ensembles are explicit Phase 2+ extensions.

## Repo map
```
brc_tools/        installable package
  nwp/            NWPSource (HRRR/GEFS/RRFS via Herbie) + lookups.toml
  obs/            ObsSource (SynopticPy wrapper, shared alias namespace)
  download/       Synoptic obs (get_map_obs.py) + push_data.py uploader
                  + HRRR helpers (hrrr_access.py, get_road_forecast.py)
  aviation/       FlightAware helpers
  utils/          lookups (station IDs, variables) + helpers
  filter/ verify/ visualize/ ml/   scaffolded; mostly stubs
in_progress/      experimental HRRR/RRFS/AQM scripts + notebooks
docs/             canonical project docs (see below)
reference/        external references (FlightAware spec, setup Q&A)
tests/            road forecast logic tests (3 passing)
scripts/          case study + operational helpers
```

## Canonical docs (do not duplicate them here)
- `docs/CHPC-REFERENCE.md` — CHPC account, partitions, salloc, cron.
- `docs/ENVIRONMENT-SETUP.md` — venv/conda setup for new team members.
- `docs/PIPELINE-ARCHITECTURE.md` — fetch → process → push pattern.
- `docs/CROSS-REPO-SYNC.md` — protocol for the four sibling repos.
- `docs/nwp/` — HRRR/RRFS roadmap, branch notes (current focus).
- `WISHLIST-TASKS.md` — prioritised backlog (kept at root by convention).
- `README.md` — human-facing entry point.

## Key data-flow anchor (load-bearing — verify before changing)
`brc_tools.download.push_data.send_json_to_server(server_address, fpath, file_data, API_KEY)`
POSTs `multipart/form-data` to `{server_address}/api/upload/{file_data}`
with headers `x-api-key` (32-char hex) and `x-client-hostname` (must end
`.chpc.utah.edu`). A health check hits `{server_address}/api/health`
first. Server URL is read from `~/.config/ubair-website/website_url` and
the API key from the `DATA_UPLOAD_API_KEY` environment variable
(`load_config()`). **`clyfar` imports this function** for forecast
upload — do not change its signature without a coordinated cross-repo PR.

## Environment variables
- `DATA_UPLOAD_API_KEY` — required for uploads (32-char hex).
- `SYNOPTIC_API_TOKEN` — required for Synoptic downloads.
- `FLIGHTAWARE_API_KEY` — optional, aviation only.

See `.env.example` for the full list.

## Conventions
- **UTC internally, always.** Use `datetime.timezone.utc`, not pytz.
- **Polars preferred over pandas** for new code (`.select()`, `.filter()`,
  `.with_columns()`).
- **American English in code** (the `visualise → visualize` rename is
  done). British English in free-form comments is fine.
- **Import order:** stdlib, third-party, local.
- **JSON filenames:** use `generate_json_fpath()` →
  `{prefix}_{YYYYMMDD_HHMM}Z.json`.
- **Error handling:** wrap API calls in try/except; log and continue;
  retry network requests with backoff.
- **New NWP code → `brc_tools/nwp/`**, not `brc_tools/download/`. See
  `docs/nwp/ROADMAP.md`.
- **Do not edit `in_progress/`** except to extract code out of it.

## Testing commands
```
ruff check .
mypy brc_tools/
pytest tests/
```

## Related repos
- `ubair-website` — Node.js site that receives the uploads (data contract).
- `clyfar` — ozone forecast model; imports `brc_tools.download.push_data`.
- `preprint-clyfar-v0p9` — LaTeX manuscript; methodology source of truth.

## Things deliberately NOT in this file
- CHPC salloc / cron templates → `docs/CHPC-REFERENCE.md`
- Python env install steps → `docs/ENVIRONMENT-SETUP.md`
- Pipeline / data-flow design → `docs/PIPELINE-ARCHITECTURE.md`
- HRRR branch read order → `docs/nwp/HRRR-BRANCH-NOTES.md`
- HRRR phased plan → `docs/nwp/ROADMAP.md`
- Backlog → `WISHLIST-TASKS.md`

## Ownership
This `CLAUDE.md` is the **shared project context** — facts every teammate
and every Claude Code session should agree on. It is governed by
`.github/CODEOWNERS` and any PR touching it requires review from
@johnrobertlawson, so the file does not silently drift between teammates'
local sessions.

For **personal** preferences (machine-specific paths, in-progress notes,
"explain Polars in extra detail to me", etc.), create `CLAUDE.local.md`
at the repo root. It is gitignored, never committed, and Claude Code
reads it automatically alongside this file. Each teammate has their own;
they never collide. Sync your `CLAUDE.local.md` across your own machines
via a private dotfiles repo, not through this repo.
