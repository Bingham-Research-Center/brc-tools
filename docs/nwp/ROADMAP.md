# NWP/Synoptic helper roadmap

## Status (as of 2026-04-15)
**Phases 0–4 complete.** Phase 5 partially done. Phase 6 in progress.
Tracked in GitHub issue #10.

### What was built
- **NWPSource** (`brc_tools/nwp/source.py`): HRRR/GEFS/RRFS fetch via Herbie, parallel downloads, canonical alias namespace, waypoint extraction (PR #16).
- **ObsSource** (`brc_tools/obs/source.py`): SynopticPy wrapper sharing the alias namespace.
- **Event scanner** (`brc_tools/obs/scanner.py`): Generic `scan_events` loop with `detect_wind_ramp` and `detect_foehn` criteria functions.
- **Derived fields** (`brc_tools/nwp/derived.py`): Wind speed/dir, theta-e, potential temperature, tendencies, gradients.
- **Alignment** (`brc_tools/nwp/alignment.py`): Model/obs temporal join, unit harmonisation.
- **Verification** (`brc_tools/verify/deterministic.py`): RMSE, bias, MAE, correlation, `paired_scores`.
- **Visualisation**: `planview.py` (maps + obs overlay), `timeseries.py` (multi-station panels).
- **Case study helpers** (`brc_tools/nwp/case_study.py`): Shared config, multi-init fetch, figure pipeline.
- **lookups.toml**: 30+ variable aliases, 14 waypoints, 5 regions, 7 waypoint groups, 3 model configs.
- **Three case studies**: Feb 2025 quasi-front (23 figs), KVEL westerly, KVEL foehn.
- **Test suite**: 45 tests (scanner, derived, deterministic, road forecast).

### What remains
- Phase 5: HRRR sub-hourly (15-min), lagged ensemble workflows (GEFS config exists).
- Phase 6: Comprehensive integration tests, API reference docs, deployment docs.

## Problem
- Add reusable Python helper functions that CLI agents and scripts can call to assemble Herbie-based model downloads and Synoptic observation pulls without having to rediscover product names, inventory strings, caching rules, or GRIB2 decode quirks each time.
- The initial scientific target is a Uinta Basin case-study workflow: combine HRRR-family guidance with historical Synoptic observations to test the springtime eastward-moving warm-front / cold-pool-erosion hypothesis from Duchesne to Vernal.

## Current state
- Packaged observation support already exists in `brc_tools/download/`:
  - `download_funcs.py` has thin helpers for Synoptic metadata/time series and JSON filename generation.
  - `get_map_obs.py` is a production script that downloads, shapes, saves, and uploads latest observations.
- Packaged model support does **not** yet exist:
  - Herbie usage is concentrated in `in_progress/aqm/*.py` and multiple notebooks for AQM, HRRR, RRFS, GFS, and NAM.
  - Those prototypes show useful patterns (inventory inspection, `H.download()`, `H.xarray()`, direct `cfgrib` fallbacks), but they are notebook/script-oriented rather than reusable library functions.
- Repo/docs already acknowledge this gap:
  - `WISHLIST-TASKS.md` calls for moving AQM code out of `in_progress/` and documenting conda/venv compatibility.
  - `docs/PIPELINE-ARCHITECTURE.md` treats a Herbie-backed model pipeline as planned rather than implemented.
- Environment/dependency picture is only partially settled:
  - `pyproject.toml` includes `herbie-data`, `synoptic`, and `python-dotenv`.
  - Experimental code uses `cfgrib`, but `cfgrib`/`eccodes` are not pinned in the package metadata.
  - `docs/CHPC-REFERENCE.md` documents Miniforge-based conda environments (`brc-tools`, `clyfar-nov2025`) and a shared Herbie cache location.
- Testing is effectively absent right now (`tests/` has no meaningful coverage).

## Proposed approach
1. Create a dedicated helper layer for NWP access instead of burying model logic inside website upload scripts or leaving it in notebooks.
2. Promote only the stable Herbie patterns from `in_progress/` into small, typed, composable library functions.
3. Extend the existing observation helper layer so historical Synoptic data retrieval and model/obs alignment use the same conventions (UTC-first, reusable station/variable mappings, agent-friendly return shapes).
4. Keep phase 1 focused on the shortest path to a trustworthy analysis workflow, then widen the same interface to HRRR-adjacent and ensemble products.

## Recommended package shape
- New subpackage: `brc_tools/nwp/`
  - Reason: these helpers will do more than "download" (inventory lookup, cache handling, subsetting, decode/open, point extraction), so a dedicated NWP namespace is clearer than continuing to overload `brc_tools/download/`.
- Observation helper expansion in `brc_tools/download/` (or a small `synoptic_helpers.py` inside it), because observation fetching already lives there.

## Phase plan

### Phase 0: environment and dependency audit
- Verify whether the documented `brc-tools` or `clyfar-nov2025` conda environments are sufficient for:
  - `herbie`
  - `synoptic`
  - `cfgrib`
  - `eccodes` / related GRIB backends
- Decide whether to:
  - keep using the existing `brc-tools` env and document extra installs, or
  - create/document a dedicated NWP-ready conda environment spec.
- Capture the supported backend strategy for GRIB2 decoding so helper functions know when to use `Herbie.xarray()` directly versus an explicit `cfgrib` path.

### Phase 1: define stable helper interfaces
- Create a minimal, agent-friendly API in `brc_tools/nwp/` around these concepts:
  - model request construction
  - inventory inspection/search
  - GRIB download/caching
  - dataset opening
  - valid-time/lead-time resolution
- Keep signatures simple enough that a CLI agent can call them without deep Herbie knowledge.
- Favor explicit inputs over magic globals; use environment/config only for cache or optional defaults.

### Phase 2: implement HRRR-first helpers
- Add HRRR-oriented wrappers as the initial supported model family:
  - standard hourly HRRR surface products
  - pressure-level products
  - a path for the 15-minute/subhourly HRRR variant if included in phase 1 scope
- Convert notebook logic for search strings and field selection into reusable functions instead of hard-coded notebook cells.
- Return both machine-friendly metadata and opened datasets/paths so agents can chain operations.

### Phase 3: strengthen Synoptic historical-observation helpers
- Expand beyond the current thin wrappers to support:
  - historical time series pulls with cleaner input validation
  - metadata lookup for station cohorts
  - consistent UTC handling
  - normalization into a predictable dataframe/table shape for later joins with model output
- Reuse existing lookups in `brc_tools/utils/lookups.py` where possible instead of duplicating station/variable lists.

### Phase 4: build model/obs alignment utilities for case studies
- Add helper functions that make the warm-front hypothesis test practical:
  - station-sequence definitions for Duchesne -> Myton -> Roosevelt -> Vernal
  - extraction of point or small-area model time series from HRRR
  - alignment of model valid times with Synoptic observations
  - derived metrics/proxies such as wind shifts, temperature jumps, pressure tendencies, and front-passage timing
- Keep this layer analysis-oriented and separate from raw download helpers.

### Phase 5: extend the same interface to adjacent products
- Once HRRR-first helpers are stable, extend via the same request/open/search patterns to:
  - HRRR 15-minute output
  - RRFS experimental products
  - ensemble inputs relevant to Clyfar/GEFS workflows
- Defer lagged-ensemble and exponential-decay probability helpers until the base single-run workflow is trustworthy and tested.

### Phase 6: tests, examples, and documentation
- Add unit tests for:
  - request/time parsing
  - inventory record matching
  - cache/path behavior
  - observation normalization and alignment logic
- Add a small number of integration/smoke checks for live services only where appropriate and clearly marked.
- Document:
  - recommended environment setup for NWP work
  - example helper calls for agents
  - one end-to-end warm-front case-study example

## Key design decisions to carry into implementation
- **Start narrow, then generalize.** HRRR + Synoptic is the fastest path to the scientific use case; RRFS/subhourly/ensembles should plug into the same interface later.
- **Separate raw access from analysis logic.** Request/download/open helpers should stay independent from warm-front metrics and verification utilities.
- **Preserve UTC internally.** Existing docs already prefer UTC-first handling, which matters for model/obs joins.
- **Prefer composable helpers over one giant pipeline.** The user goal is natural-language-driven analysis, so functions should be easy to mix and match from agents.
- **Document the decode backend explicitly.** GRIB2 pain points are a core risk, so backend assumptions should be part of the API contract, not hidden behavior.

## Likely files to change when implementation begins
- `brc_tools/nwp/__init__.py` (new)
- `brc_tools/nwp/*.py` (new helper modules)
- `brc_tools/download/download_funcs.py` and/or a new Synoptic helper module
- `brc_tools/utils/lookups.py` if station-group utilities need expansion
- `tests/` for new unit/integration coverage
- `docs/ENVIRONMENT-SETUP.md` and possibly a new NWP-focused usage doc if environment/backend setup needs clarification

## Risks / unknowns
- The biggest uncertainty is whether the existing conda environments already include a reliable GRIB2 decode stack.
- Some of the most useful current examples are notebooks, so extraction work may involve untangling prototype assumptions and hard-coded paths.
- The final helper API should avoid coupling too tightly to one model family while still keeping phase 1 small enough to finish cleanly.

## Confirmed phase 1 scope
- Phase 1 will target **HRRR hourly + Synoptic historical observations first**.
- HRRR 15-minute output, RRFS, and broader ensemble workflows remain explicit phase 2+ extensions once the base interface is stable.
