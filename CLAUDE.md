# CLAUDE.md — Agent context for brc-tools

Shared Python utilities for the Bingham Research Center. Pulls weather
observations (SynopticPy) and NWP model data (Herbie) on CHPC; pushes
JSON to the BasinWX website. Package: **`brc_tools`** (underscore).
Repo: **`brc-tools`** (hyphen).

## Current focus
- **pelican2013 manuscript support** (final-draft push lives in `latex-jrl-mjd-mdpiair-2026`): figure engine + X8 deficit-transport diagnostics merged; the study's evidence packet pins an exact brc-tools SHA — treat `wrf_figures.py`/`wrf_output.py`/`visualize/*` as frozen unless the study repo asks.
- HRRR/RRFS → BasinWX operational ingest (GH #10). Strategy/status: `docs/nwp/ROADMAP.md`.
- Case-study pipeline (natural language → script → figures): `docs/CASE-STUDY-GUIDE.md`.
- **WRF-input staging**: GRIB → scratch manifests/contracts for `brc-wrf`. Status, division of labour, cold-start SSOT: `docs/WRF-STAGING-STATE-PLAYBOOK.md`.
- Next up: NWPSource / ObsSource integration tests. Backlog: `WISHLIST-TASKS.md`.

## Repo map
```
brc_tools/        installable package
  nwp/            NWPSource (Herbie), lookups.toml, staging/alignment/derived, and the WRF adapters + diagnostics (wrf_*, convective_env, forecast_funnel) — module-by-module: docs/API-REFERENCE.md
  obs/            ObsSource (SynopticPy wrapper), scanner (event detection)
  verify/         deterministic metrics (paired_scores, RMSE/bias/MAE)
  visualize/      planview/timeseries panels; grid.py (brc-wrf seam); figure-engine, WRF-curtain, tracer-origin and time-height modules — see docs/API-REFERENCE.md
  download/       Synoptic obs script, push_data uploader, HRRR helpers
  api/            external API clients: FlightAware, FR24, Perplexity, Mistral (shared _auth); soundings (IGRA2/Wyoming RAOB) + aqs (EPA AQS AirData bulk), both auth-free
  radar/          4/3-Earth beam geometry + observed radar: iem.py (Level-III from Iowa State RIDGE — the route that works for historical cases) and nexrad.py (Level-II via MetPy). Observations, not NWP — sibling of satellite/
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
- `docs/WRF-STAGING-STATE-PLAYBOOK.md` — **WRF-staging cold-start SSOT**, summary + full detail in one doc; two-stream draft `docs/WRF-GEFS-NAM-FIELD-MAP.md` (parked)
- `docs/WRF-FIGURE-ENGINE.md` — dataset-agnostic figure engine (`brc_tools/nwp/wrf_figures.py` + `scripts/wrf_figures.py --config <case.toml>`). Per-study case TOMLs + the run/figure inventory live in the active study repo; SSOT index → `../latex-jrl-mjd-mdpiair-2026/verification/figures/archive-inventory.md`
- `docs/WRF-WINDS.md` — the winds engine (`scripts/wrf_winds.py --config <case.toml>`; `/wrf-basin-winds` skill): five `--figure` families (`topdown`, `section`, `profile`, `view3d`, `tracers`) plus the separate tslist time–height engine `scripts/wrf_timeheight.py` — the family that answers *when*. **SSOT for `w_exag` and section fill/sign conventions** — defer to it, never restate. Per-case TOMLs live in the repo owning the case.
- `docs/WRF-CONVECTIVE.md` — the convective engine (`scripts/wrf_convective.py --config <case.toml>`; `/wrf-convective` skill), third engine distinct from both above: reflectivity **sampled on a real WSR-88D's beam surfaces** with the observed IEM Level-III scan beside it, a derived `meso` family, MetPy parcel/shear/hodograph products, `auxhist` + `tslist` access. Observed-radar transport: `docs/nwp/NWP-SOURCE-MATRIX.md`.
- `docs/FORECAST-FUNNEL.md` — NAM "forecast funnel" synoptic montage (`brc_tools/nwp/forecast_funnel.py` + `brc_tools/visualize/funnel.py` + `scripts/forecast_funnel.py`); `/basin-forecast-funnel` skill. NAM source auto-picks by init date (Herbie recent / NCEI pre-2017).
- `docs/VISUAL-SUITE-SOP.md` — **how to produce a suite of WRF visuals, and the ways it goes wrong.** Engine-agnostic procedure (pick engine by question → smoke-test EVERY family at one time → narrow with `--figure`/`--domain`/`--start`/`--end` → DTN → check `.err` → promote keepers), plus the errors already found and fixed and the gaps still open. Read before a first sweep on a new case.
- `WISHLIST-TASKS.md` — prioritised backlog

When editing a topic, edit its canonical doc above; do not duplicate into CLAUDE.md.

## Key data-flow anchor (load-bearing — verify before changing)
`brc_tools.download.push_data.send_json_to_server(server_address, fpath, file_data, API_KEY)`
POSTs `multipart/form-data` to `{server_address}/api/upload/{file_data}`
with headers `x-api-key` (32–128-char hex from `DATA_UPLOAD_API_KEY`) and
`x-client-hostname` (must end `.chpc.utah.edu`). Server URL resolves
`BASINWX_API_URLS` (env, comma-sep for fan-out) → `~/.config/ubair-website/website_urls`
→ `website_url` (legacy). Health: `/api/health`.
**`clyfar` imports this function** — do not change its signature without
a cross-repo PR. Operational deployment lives in `docs/CHPC-REFERENCE.md`.

A second cross-repo seam: `brc_tools.visualize.grid` (`plot_grid_field`,
`plot_vertical_section`, `terrain_contour_levels`) is imported by `brc-wrf`'s
`wrf_quicklook.py` — signatures load-bearing. That script also shells out to
`scripts/stage_wrf_inputs.py` to verify a manifest, so its CLI is part of the seam too. The publication figure engine built on it (`wrf_figures.py` over
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
- **Heavy jobs run on SLURM, not login nodes.** Ship a `scripts/*.slurm` wrapper (see `stage_inputs.dtn.slurm`; account `lawson-np`) and call the env python directly — the login env doesn't carry. Details + study-repo wrappers: `docs/CHPC-REFERENCE.md`.
- **Don't reinvent NWP downloads — check Herbie first.** Record each source's Herbie-native-vs-direct decision in `docs/nwp/NWP-SOURCE-MATRIX.md` (enforced by `tests/test_source_matrix.py`); a hand-rolled GET is the exception and must justify why Herbie doesn't fit.
- **Units**: NWP temps in K, MSLP in Pa, wind in m/s. Obs already in C / Pa / m/s (Synoptic returns Pa for pressure; units are per-alias in `lookups.toml` `synoptic_units`). Convert at the boundary (e.g. Pa→hPa) only for display.
- **Lookups** (`brc_tools/nwp/lookups.toml`) is the source of truth for models, regions, waypoints, waypoint groups, variable aliases. Grep it — at 40 KB it is never worth reading whole — and don't duplicate its contents into docs.
- **Navigate, don't dredge.** Ingest high-value tokens, not whole trees. Never blind-`cat`/read entire figure, GRIB, or `run_*` output dirs (the WRF archive is ~30 GB of near-duplicate PNGs) — `ls | wc -l` or glob first, then read the one file you need; load a doc/TOML only when its topic is in play (see Doc map). For WRF run/figure locations + completeness, read the SSOT index `../latex-jrl-mjd-mdpiair-2026/verification/figures/archive-inventory.md`, not the archive tree.
- **A figure states the quantity, not just the variable** — `pcolormesh` for data
  (never `contourf`), titles lead `WRF`/`OBSERVED`, a section fill names which wind
  it draws, and colour limits live in `visualize/style.py`, never in a renderer.
  Full house rules: `docs/VISUAL-SUITE-SOP.md`.
- **Figures use the Helvetica-first font stack and land outside the checkout** (default group6 `brc-tools-output`, override `BRC_TOOLS_OUTPUT_DIR`). Stack + rationale in `docs/VISUAL-SUITE-SOP.md` (House style); reference impl `scripts/basin_floor_ozone_snow.py`.

## Environment variables
| Var | Purpose | Required? |
|-----|---------|-----------|
| `DATA_UPLOAD_API_KEY` | BasinWX upload auth | for uploads |
| `BASINWX_API_URLS` | BasinWX upload URL(s), comma-sep fan-out; overrides `~/.config/ubair-website/website_url(s)` | optional |
| `SYNOPTIC_TOKEN` | Synoptic obs (also via `~/.config/SynopticPy/config.toml`) | for obs |
| `FLIGHTAWARE_API_KEY` | FlightAware AeroAPI (`api/` clients) | aviation only |
| `PERPLEXITY_API_KEY` | Perplexity client + `.mcp.json` MCP server | optional |
| `MISTRAL_API_KEY` | Mistral client + `.mcp.json` MCP server | optional |
| `BRC_TOOLS_{HERBIE,HRRR,MODIS,AQS}_CACHE`, `BRC_TOOLS_BASEMAP_DIR`, `BRC_TOOLS_LOCK_DIR`, `BRC_TOOLS_HTTP_IPV4_ONLY` | cache/lock-dir overrides + CHPC IPv4 workaround; defaults live in each module (basemap staged once via `scripts/fetch_basemap.dtn.slurm`) | optional |

All `api/` clients resolve keys via `brc_tools.api._auth.load_api_key(VAR)` — **env var
only** today (the helper also accepts an optional `~/.config/<svc>/api_key` fallback, but
no client wires it yet); `FR24_API_KEY` is reserved for the skeleton FlightRadar24 client.

## Testing
```
pytest tests/
cd /tmp && python -c "import brc_tools, brc_tools.visualize.grid"   # editable install present?
```
Use the dedicated **`brc-tools-2026`** env — fresh setup and the CHPC pip flags
(`--no-build-isolation --no-user`) are in `docs/ENVIRONMENT-SETUP.md`. Not bare `python`.
**Verify the import from OUTSIDE the checkout** — a cwd-inside-the-repo test passes even
with no editable install; the failure only surfaces later in `brc-wrf`/`clyfar`.

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
