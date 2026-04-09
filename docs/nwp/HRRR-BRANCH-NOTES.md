# HRRR branch notes (handoff from Copilot exploration)

> Snapshot from a 2026-04-06 Copilot session that surveyed unmerged HRRR
> branches. Preserved as historical context for the HRRR/RRFS ingest work
> tracked in issue #10. See `./ROADMAP.md` for the forward-looking plan.

## TL;DR

The most useful branch for your goals is **`feat/hrrr-road-poc-minimal`** in `brc-tools`.

Why:
- it already splits HRRR work into a small reusable access layer
- it includes a compact query/config module
- it has first tests
- it already encodes a **US-40 sequence including Duchesne -> Myton -> Roosevelt -> Vernal**, which overlaps strongly with your warm-front / basin-erosion idea

The most useful `ubair-website` branch is **`origin/feat/rwis-surface-snow-decisions`**, but mainly as a **consumer-side logic reference** for RWIS, surface status, visibility, precipitation, and confidence rules. It is **not** the place where the HRRR fetch layer lives.

## Best branches to mine

| Branch | Repo | Value | Caveat |
| --- | --- | --- | --- |
| `feat/hrrr-road-poc-minimal` | `brc-tools` | **Best starting point** for reusable HRRR helpers | not merged on current `main` |
| `origin/chore/hrrr-road-ops-docs` | `brc-tools` | best spec for website contract, cron, and upload route | mostly docs/ops, not core Python logic |
| `origin/feat/hrrr-road-forecast-core` | `brc-tools` | earlier full road-forecast implementation | largely superseded by the minimal branch |
| `origin/recovery/brc-tools-hrrr-direct-main-2026-03-02` | `brc-tools` | historical recovery point for the older HRRR road work | treat as ancestry/reference, not as merge target |
| `origin/feat/rwis-surface-snow-decisions` | `ubair-website` | good RWIS/surface-status reasoning and UI implications | **no actual HRRR forecast endpoint implementation found** |

## Recommended read order

Use `git show <branch>:<path>` rather than switching branches or opening giant diffs.

| Priority | Read this | Why it matters | Token/use caveat |
| --- | --- | --- | --- |
| 1 | `git show feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_access.py` | cleanest reusable HRRR fetch/cache/open layer | **Read the whole file**; high value, compact |
| 2 | `git show feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_config.py` | query map, variables metadata, route/waypoint structure | **Read the whole file**; very high value |
| 3 | `git show feat/hrrr-road-poc-minimal:brc_tools/download/get_road_forecast.py` | shows how the access layer is turned into a JSON payload and CLI | read **top ~260 lines first**; that gets most of the logic |
| 4 | `git show feat/hrrr-road-poc-minimal:tests/test_road_forecast_logic.py` | fastest way to understand intended units, payload shape, and edge assumptions | **Read the whole file**; tiny and useful |
| 5 | `git show feat/hrrr-road-poc-minimal:HRRR-MERGE-PLAN.md` | good strategic notes on what to reuse and what not to merge wholesale | **Do not load whole file first**; skim headings and phase-1 sections only |
| 6 | `git show origin/chore/hrrr-road-ops-docs:docs/HRRR-ROAD-FORECAST-SPEC.md` | best statement of the intended website payload and endpoint contract | read sections on **overview, upload endpoint, retrieval endpoint, JSON schema** |
| 7 | `git show origin/chore/hrrr-road-ops-docs:scripts/run_road_forecast.sh` | tiny wrapper showing env/cron convention | **Read whole file** |
| 8 | `git show origin/feat/rwis-surface-snow-decisions:server/snowDetectionService.js` | useful RWIS confidence logic for surface state and precip interpretation | **Do not load whole file**; target RWIS-related sections only |
| 9 | `git show origin/feat/rwis-surface-snow-decisions:server/roadWeatherService.js` | useful road-condition heuristics from RWIS + weather inputs | **Do not load whole file**; target the decision blocks only |
| 10 | `git show origin/feat/rwis-surface-snow-decisions:public/js/roads/ConditionCards.js` | useful only if you care about downstream display semantics | optional; UI-level, not helper-layer critical |

## Most useful concrete findings

### 1. There is already a decent prototype of a reusable HRRR helper layer

From `feat/hrrr-road-poc-minimal`:
- `brc_tools/download/hrrr_access.py`
  - has `ensure_cache_dir()`
  - has `setup_herbie()`
  - has `get_latest_hrrr_init()`
  - has `fetch_hour_dataset()` / `fetch_hourly_datasets()`
  - handles basic cache validation and retry/purge logic

This is the strongest existing pattern for the helper-library idea you want.

### 2. The existing config already contains a corridor/station-sequence pattern you can repurpose

From `feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_config.py`:
- `ROAD_FORECAST_QUERY_MAP` is a practical example of mapping internal aliases to Herbie search strings
- `ROAD_CORRIDORS["us40"]` already contains:
  - Daniels Summit
  - Strawberry
  - Fruitland
  - Starvation
  - **Duchesne**
  - **Myton**
  - **Roosevelt**
  - **Vernal (Asphalt Ridge)**
  - Dinosaur

That means the branch already expresses a geographic sequence very close to your Uinta Basin analysis target. Even if you do not keep the road-product framing, the pattern is directly reusable for a generic **waypoint/station cohort** helper.

### 3. The minimal branch is more useful than the older HRRR branch cluster

`origin/feat/hrrr-road-forecast-core` and `origin/recovery/brc-tools-hrrr-direct-main-2026-03-02` are still useful references, but the minimal branch is better because it:
- isolates HRRR work more cleanly
- adds tests
- is explicit about not merging the old branches wholesale
- keeps the fetch path smaller and easier to generalize

### 4. The website contract was at least designed, even if not implemented

From `origin/chore/hrrr-road-ops-docs:docs/HRRR-ROAD-FORECAST-SPEC.md`:
- intended upload route: `POST /api/upload/road-forecast`
- intended retrieval route: `GET /api/road-weather/forecast`
- intended payload shape includes:
  - `model`
  - `init_time`
  - `generated_at`
  - `forecast_hours`
  - `valid_times`
  - `variables`
  - `routes`
  - `cameras`

This is useful because it shows how one previous effort expected HRRR output to be consumed by BasinWx.

### 5. `ubair-website` is useful for RWIS and interpretation logic, not model-access logic

From `origin/feat/rwis-surface-snow-decisions`:
- `server/snowDetectionService.js` uses RWIS `surfaceStatus`, precipitation, and temperature to assign confidence
- `server/roadWeatherService.js` uses road temp, visibility, precipitation, and status logic to classify conditions
- `public/js/roads/ConditionCards.js` reveals what kinds of downstream summaries/UI values are considered useful

This is relevant to your goals because it suggests good **derived variables** and **decision heuristics** once you have model + obs time series, but it does **not** replace the need for a clean Herbie helper layer in Python.

## Targeted sections only (to avoid wasting context)

### Worth reading in full
- `feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_access.py`
- `feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_config.py`
- `feat/hrrr-road-poc-minimal:tests/test_road_forecast_logic.py`
- `origin/chore/hrrr-road-ops-docs:scripts/run_road_forecast.sh`

### Read only selected parts
- `feat/hrrr-road-poc-minimal:brc_tools/download/get_road_forecast.py`
  - focus on:
    - `derive_road_fields()`
    - `build_road_payload()`
    - `build_route_forecasts()`
    - CLI argument design
- `feat/hrrr-road-poc-minimal:HRRR-MERGE-PLAN.md`
  - focus on:
    - rationale for **single-run hourly HRRR first**
    - notes around `hrrr_access.py` / `hrrr_config.py`
    - warnings against broad merges from old branches
- `origin/chore/hrrr-road-ops-docs:docs/HRRR-ROAD-FORECAST-SPEC.md`
  - focus on:
    - overview
    - endpoints
    - JSON schema
    - cron assumptions
- `origin/feat/rwis-surface-snow-decisions:server/snowDetectionService.js`
  - focus around the RWIS sections called out by grep:
    - around line `144` onward for `surfaceStatus` interpretation
    - around line `438` onward for RWIS confidence use
- `origin/feat/rwis-surface-snow-decisions:server/roadWeatherService.js`
  - focus around the decision blocks flagged by grep:
    - around lines `259-299`
    - around lines `504-567`
    - around lines `669-783`
    - around lines `981-1030`

### Skip or defer unless you truly need them
- `CLAUDE.md` (high-level context only; not HRRR-specific)
- big archived docs in `ubair-website/docs/archive/`
- notebook output blobs in `in_progress/*.ipynb`

These are mostly low-value for your helper-function goal compared with the small HRRR modules above.

## What this means for your stated goals

### Best immediate reuse
- Start from the **minimal HRRR branch** as the model-helper seed
- keep the **helper concepts** (`setup_herbie`, latest init selection, hourly fetch, alias mapping, payload normalization)
- strip away the road-specific JSON/output framing where necessary

### Best conceptual reuse from road-weather work
- use the **route / waypoint / station cohort** pattern for your Uinta Basin warm-front test
- use RWIS-style derived reasoning as inspiration for later **analysis metrics**
- do **not** let the road-UI details drive the helper-layer design

### Important non-finding

I found **no implemented `ubair-website` support** for:
- `GET /api/road-weather/forecast`
- `road-forecast` upload handling
- `hrrr_road_forecast` caching logic

So the **spec exists**, but the **website implementation does not appear to be present** in the branches I checked.

## Suggested extraction strategy

If you later implement this in `main`, the safest pattern is:

1. lift ideas from `hrrr_access.py`
2. generalize `hrrr_config.py` into a model-helper or waypoint-config module
3. keep `get_road_forecast.py` only as a reference, not the final architecture
4. use the `ubair-website` RWIS logic only after the Python helper layer is working

## Quick commands

```bash
# Best files to inspect first
git show feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_access.py
git show feat/hrrr-road-poc-minimal:brc_tools/download/hrrr_config.py
git show feat/hrrr-road-poc-minimal:tests/test_road_forecast_logic.py

# Read only selected parts of these
git show feat/hrrr-road-poc-minimal:brc_tools/download/get_road_forecast.py | sed -n '1,260p'
git show origin/chore/hrrr-road-ops-docs:docs/HRRR-ROAD-FORECAST-SPEC.md | sed -n '1,220p'

# Consumer-side logic in ubair-website
git -C ../ubair-website show origin/feat/rwis-surface-snow-decisions:server/snowDetectionService.js | sed -n '120,240p'
git -C ../ubair-website show origin/feat/rwis-surface-snow-decisions:server/roadWeatherService.js | sed -n '250,320p'
```
