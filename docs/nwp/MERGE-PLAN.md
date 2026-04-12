# HRRR Plan v2: implementation-ready rewrite

Status: rewritten from current repo state on 2026-03-17 UTC

Purpose: build a reliable HRRR waypoint forecast pipeline for BasinWx in `brc-tools`, using `clyfar` as the example of an operational scheduled system, but not copying its GEFS-specific complexity blindly.

This rewrite is intentionally opinionated. Anything marked "Choice" is open for change. Anything marked "Recommended" is the path I would take if I were implementing this now in Codex CLI.

## Active Scope

Current implementation target:
- add the smallest safe hourly HRRR road proof-of-concept
- keep upload off by default
- keep 15-minute output out of scope for the first working version
- keep aviation out of scope for the first working version
- reuse HRRR road branch ideas selectively, not by broad merge

---

## What changed from the old draft

The old draft had the right general direction, but the order was wrong for implementation.

Main changes in this rewrite:
- Freeze the external contract first: endpoint, payload shape, waypoints, variables, horizon.
- Build single-run HRRR first.
- Add 15-minute support only after proving variable/product availability.
- Add lagged ensemble only after single-run output is stable.
- Treat `clyfar` as the operations model for retries, smoke runs, caching, and upload ownership.
- Do **not** assume the referenced PRs or files are present in this checkout.

---

## Repo facts this plan is based on

### In `brc-tools` today
- The only real production-style pipeline here is observations:
  - `brc_tools/download/get_map_obs.py`
  - `brc_tools/download/push_data.py`
- The model pipeline in `docs/PIPELINE-ARCHITECTURE.md` is still proposed structure, not finished implementation.
- The current shared uploader posts to:
  - `/api/upload/{file_data}`
- Current upload helper is shared across repos:
  - `clyfar/export/to_basinwx.py` imports `brc_tools.download.push_data.send_json_to_server`
- The current checkout does **not** contain:
  - `get_road_forecast.py`
  - a waypoint module
  - an HRRR model schema
  - a `tests/` tree

### In `clyfar` today
- `run_gefs_clyfar.py` has retryable exit codes and testing mode.
- `nwp/gefsdata.py` has useful Herbie reliability patterns:
  - cache dir
  - cache validation
  - lock files
  - fallback handling
  - nearest-point extraction
  - Uinta Basin crop
- `nwp/download_funcs.py` has useful slice-by-slice loading and coordinate normalization.
- `scripts/submit_clyfar.sh` is the best local example of an operational wrapper:
  - wrapper owns init-time selection
  - wrapper owns retry policy
  - wrapper owns upload policy
  - wrapper can disable internal export to avoid duplicate uploads
- `scripts/run_smoke.sh` is the best local example of a minimal smoke wrapper.

### Known contradictions already visible in repo
- Docs mention `/api/data/upload/model-data`, but code uses `/api/upload/{file_data}`.
- `push_data.py` expects a 32-character API key, while some docs describe 64 characters.
- The old plan assumes branch and PR state that is not present in this checkout.

---

## Hard truths we should accept up front

1. The first blocker is not HRRR math.
It is the external contract: what JSON shape BasinWx expects for this product.

2. The second blocker is not scheduling.
It is whether HRRR `subh` really provides the variables and horizon we want.

3. The old "merge PRs first" sequence is not safe as a default.
I cannot see those PR contents here, and some of the files named in the old plan are absent.

4. `clyfar` is useful as an operations reference, not as a model-specific template.
GEFS ensemble logic and HRRR lagged-run logic are different problems.

---

## Decisions that must be made early

These are the choices that unblock implementation. Recommended defaults are included.

### Choice 1: upload contract
- Question: what upload route and `file_data` token should HRRR use?
- Current code reality:
  - `push_data.py` posts to `/api/upload/{file_data}`
  - `clyfar` currently uploads forecast JSONs with `file_data="forecasts"`
  - `ubair-website` can already accept arbitrary `dataType` values and store them in matching subdirectories, even if page-specific retrieval code has not been written yet
- Recommended:
  - keep the current uploader unchanged for v1
  - if road and aviation stay separate products, prefer separate bucket names such as `road-forecast` and `aviation-forecast`
  - if we want the least website work at first, use `forecasts` with strict filename prefixes and let each page filter its own files

### Choice 2: v1 output scope
- Question: do we need cropped gridded data, or only waypoint forecast JSON?
- Recommended:
  - waypoint JSON only for v1
- Why:
  - the old plan says "compact waypoint JSON"
  - waypoint output is much easier to validate and upload
  - gridded export can be added later without changing the fetch layer much

### Choice 3: v1 cadence
- Question: do we require full 15-minute output in the first working version?
- Recommended:
  - No.
  - Build hourly single-run HRRR first from a proven product.
  - Add 15-minute support only after availability is explicitly probed.
- Why:
  - this is the fastest honest path to a working model pipeline
  - it reduces failure modes while schema and upload contract are still moving

### Choice 4: missing `subh` behavior
- Question: what should happen when 15-minute slices are missing or partial?
- Recommended:
  - never interpolate silently in v1
  - emit explicit missing values and metadata
  - keep single-run hourly output available as fallback product during development

### Choice 5: waypoint extraction method
- Question: nearest point or bilinear interpolation?
- Recommended:
  - nearest point first
- Why:
  - `clyfar` already uses nearest-point extraction
  - it is simple, reproducible, and easier to debug
  - bilinear can be added after baseline verification

### Choice 6: lagged-ensemble alignment
- Question: when some runs are missing for a valid time, do we fail or renormalize?
- Recommended:
  - renormalize weights over available runs at each valid time
  - record which runs were actually used

### Choice 7: operational path
- Question: cron on login node or wrapper-driven scheduled run?
- Recommended:
  - development: local smoke wrapper
  - production: submission wrapper, following the `clyfar` pattern

### Decisions confirmed after review
- Confirmed:
  - v1 should be hourly first
  - 15-minute output remains an end goal, but not a day-one requirement
  - road and aviation should be separate products, not one shared payload
- Implication:
  - the repo should not start with one generic "all transport forecasts" JSON
  - it should likely produce separate road and aviation exporters, even if they share the same HRRR access layer

---

## Recommended development path

### Path A: recommended
Build in this order:
1. Freeze contract
2. Single-run hourly HRRR
3. Waypoint JSON
4. 15-minute support
5. Lagged ensemble
6. Upload
7. Smoke run
8. Production wrapper

Why this is recommended:
- smallest number of moving parts at each step
- easiest to test
- easiest to debug when Herbie or upload behavior changes

### Path B: aggressive
Try to build 15-minute lagged ensemble from day one.

Why I do **not** recommend it:
- too many simultaneous unknowns
- harder to know whether failures are due to schema, Herbie product search, time alignment, or weighting logic

### Path C: PR-first
Stop and merge PRs `#8`, `#7`, `#9` before any new code.

Why I do **not** recommend it as the default:
- I cannot verify those branches from this checkout
- the files named in the old plan are not present here
- merge order only matters after we know what those PRs actually contain

### PR review result
- The remote branches now visible in git are useful as reference:
  - `origin/fix/synopticpy-requirement-name`
  - `origin/feat/hrrr-road-forecast-core`
  - `origin/chore/hrrr-road-ops-docs`
  - `origin/recovery/brc-tools-hrrr-direct-main-2026-03-02`
- Recommended:
  - treat the road core branch as a source of extraction logic and route/waypoint ideas
  - treat the ops/docs branch as a source of road-product assumptions and shell-wrapper ideas
  - do **not** merge the recovery branch wholesale
  - do **not** assume the road spec is integrated with `ubair-website` yet

---

## Phase 0: freeze the contract

Goal: decide what the product is before writing loader logic.

### Deliverables
- one sample JSON file, even if hand-written
- one short schema note
- one agreed waypoint list
- one agreed variable list
- one agreed horizon

### Microtasks
- [ ] Decide the upload `file_data` token.
- [ ] Decide the top-level payload shape.
- [ ] Decide whether v1 is road-only, aviation-only, or both.
- [ ] Decide the waypoint list and stable waypoint IDs.
- [ ] Decide the v1 variables and output units.
- [ ] Decide the forecast horizon.
- [ ] Decide whether v1 is hourly-only first, or must expose 15-minute slots immediately.
- [ ] Decide what "missing subhourly" looks like in JSON.

### Recommended payload style
- Use a nested forecast payload, not observation-style row records.
- Reason:
  - row records will get large quickly for many times x waypoints x variables
  - `clyfar` already uses nested JSON with metadata plus arrays

### Recommended v1 JSON shape
- `metadata`
- `forecast_times`
- `waypoints`
- `waypoints[waypoint_id].location`
- `waypoints[waypoint_id].variables[var_name]`

### Caveat
- Do not let phase 1 start until this exists as an example file in the repo.

---

## Phase 1: build a reliable HRRR access layer

Goal: create one small loader module that can fetch a single HRRR run reliably.

### What to borrow from `clyfar`
- cache directory pattern
- basic cache validation
- lock file pattern if concurrent downloads are possible
- slice-by-slice logging
- coordinate normalization
- Uinta Basin crop constants
- nearest-point extraction helper

### What not to borrow blindly
- GEFS member logic
- heavy multi-product exporter design
- large Slurm assumptions

### Proposed files
- `brc_tools/download/hrrr_access.py`
- `brc_tools/download/hrrr_config.py`

### Microtasks
- [ ] Add a small `setup_herbie` helper for HRRR.
- [ ] Add cache directory handling with an env override.
- [ ] Add minimal cache validation for bad/truncated GRIBs.
- [ ] Add one function to fetch a single variable for one `init_dt`, `fxx`, and product.
- [ ] Add one function to normalize coordinates and valid time.
- [ ] Add one function to crop to the Uinta Basin box.
- [ ] Add one function to extract nearest values for waypoint lat/lon pairs.
- [ ] Log product, query, init time, lead time, and any failures explicitly.

### Explicit probe task
- [ ] Write a small availability probe for each target variable across:
  - `sfc`
  - `subh`
- [ ] Save probe results to a simple markdown or JSON artifact.

### Caveat
- We should not hard-code a "strict 15-minute axis" until the probe confirms what is actually available.

### Gotchas
- HRRR may expose coordinates differently than GEFS.
- Some searches may work in one product and fail in another.
- `subh` may exist for some variables and not others.

---

## Phase 2: single-run waypoint MVP

Goal: produce one clean, local-only HRRR forecast file from one run.

This is the first "real" target, not the lagged ensemble.

### Proposed files
- `brc_tools/download/hrrr_waypoints.py`
- `brc_tools/download/hrrr_export.py`
- `brc_tools/download/get_hrrr_waypoints.py`

### Microtasks
- [ ] Define the canonical waypoint list in code.
- [ ] Define the canonical variable map in code.
- [ ] Build one function that creates the valid-time axis.
- [ ] Build one function that assembles a per-waypoint forecast structure.
- [ ] Build one serializer for the agreed JSON shape.
- [ ] Save one local JSON file without uploading.
- [ ] Compare the file size and readability with expectations.

### Recommended v1 rule
- Hourly first.
- Keep 15-minute logic behind a separate feature flag until proven.

### Exit criteria
- One command produces one JSON file for one HRRR run.
- The file includes metadata, times, waypoints, variables, and units.
- Missing values are explicit.

### Caveat
- If aviation and road products need different waypoint sets or variables, split them early.

---

## Phase 3: add 15-minute support

Goal: extend the single-run pipeline to support subhourly data honestly.

### Microtasks
- [ ] Decide whether the time axis is:
  - one global 15-minute axis, or
  - per-variable cadence
- [ ] Implement `subh` fetches only for variables proven by the probe.
- [ ] Align `subh` slices to valid times explicitly.
- [ ] Mark missing intervals explicitly in output metadata.
- [ ] Keep hourly `sfc` behavior available for comparison during development.

### Recommended rule
- If a variable does not have stable `subh` coverage, do not fake it.
- Keep that variable hourly until we intentionally change the contract.

### Gotchas
- The frontend may assume all variables share one common time axis.
- Mixed hourly and 15-minute variables make the payload more complex.

### Point of choice
- If you want a very simple frontend contract, require all v1 variables to share the same 15-minute axis.
- If you want faster backend progress, allow mixed cadence and describe it in metadata.

---

## Phase 4: add the 5-run lagged ensemble

Goal: compute lagged-run statistics on top of the working single-run product.

### Recommended v1 math
- runs: latest 5 available runs
- raw weight: `exp(-lambda * run_age_index)`
- default `lambda = ln(2)`
- normalize weights over available runs at each valid time

### Microtasks
- [ ] Build a run selector for `R0..R4`.
- [ ] Build per-run single-run payload generation first.
- [ ] Align runs by valid time.
- [ ] Renormalize weights where some runs are missing.
- [ ] Compute weighted mean.
- [ ] Compute weighted spread.
- [ ] Compute min/max envelope.
- [ ] Record run IDs and actual weights used per valid time.

### Recommended implementation rule
- Keep single-run output and lagged-ensemble output separable.
- Do not bury single-run debugging inside ensemble-only code.

### Caveat
- Lagged-run weighting is easy.
- Time alignment and missing-run handling are the real risks.

### Gotchas
- Some valid times may only have 2 or 3 usable runs.
- `subh` availability may differ by run age.
- Cycle rollover logic can produce confusing "latest run" bugs if not logged clearly.

---

## Phase 5: export and upload

Goal: push the working HRRR JSON without breaking the shared upload path.

### Recommended rule
- Keep `send_json_to_server()` unchanged at first.
- Treat upload hardening as a separate task if needed.

### Proposed files
- `brc_tools/download/hrrr_push.py` or reuse `hrrr_export.py`

### Microtasks
- [ ] Save forecast JSON locally first.
- [ ] Add `--upload` and `--dry-run` flags to the CLI.
- [ ] Use the agreed `file_data` token.
- [ ] Confirm BasinWx accepts one smoke payload.
- [ ] Only then enable upload by default in wrapper scripts.

### Caveats
- `send_json_to_server()` currently prints status and does not return a strong success/failure contract.
- Any change to upload endpoint behavior may affect `clyfar`, because `clyfar` imports the same helper.

### Gotcha
- Do not "fix" the uploader casually in `brc-tools` without checking `clyfar`.

---

## Phase 6: tests and validation

Goal: add the minimum test surface this repo currently lacks.

### Fact
- There is no `tests/` tree in this checkout.

### Proposed files
- `tests/test_hrrr_weights.py`
- `tests/test_hrrr_payload.py`
- `tests/test_hrrr_time_axis.py`

### Microtasks
- [ ] Add a weight-normalization test.
- [ ] Add a missing-run renormalization test.
- [ ] Add a JSON payload shape test.
- [ ] Add a time-axis test.
- [ ] Add a serialization test for `None` / `NaN`.
- [ ] Add one golden-file smoke payload fixture.

### Recommended rule
- A smoke run is not a substitute for tests.

---

## Phase 7: smoke script and operational wrapper

Goal: copy the good operational shape from `clyfar` without copying unnecessary complexity.

### What to copy from `clyfar`
- separate smoke script
- wrapper-owned upload flag
- wrapper-owned retry policy
- explicit UTC/init-time logging
- non-interactive shell safety: `set -euo pipefail`

### Proposed files
- `scripts/run_hrrr_smoke.sh`
- `scripts/submit_hrrr.sh`

### Microtasks
- [ ] Create a local smoke wrapper that runs one init time with upload disabled.
- [ ] Add a wrapper-level `HRRR_ENABLE_UPLOAD=0/1`.
- [ ] Add a wrapper-level `HRRR_SKIP_INTERNAL_EXPORT=0/1` only if we truly need split ownership.
- [ ] Add explicit init-time logging.
- [ ] Add clear exit codes for retryable Herbie/network failures if needed.
- [ ] Only add scheduler integration after local smoke is reliable.

### Recommended rule
- The shell wrapper should own scheduling and upload mode.
- The Python module should own data generation.

### Caveat
- For HRRR waypoint JSON, we may not need the full complexity of `submit_clyfar.sh`.
- Start simpler, then add retries only if real failures justify them.

---

## Proposed implementation order for Codex

This is the order I would actually code in:

1. Create a sample HRRR JSON file and short schema note.
2. Create `hrrr_access.py` with one fetch path for one variable.
3. Create waypoint definitions.
4. Create single-run hourly export CLI.
5. Add tests for payload and time axis.
6. Add `subh` probe and 15-minute extension.
7. Add lagged-ensemble layer.
8. Add local smoke script.
9. Add upload flag and smoke upload.
10. Add production wrapper only after smoke upload passes.

---

## Non-goals for v1

- Do not refactor the whole `brc-tools` architecture first.
- Do not switch the shared upload endpoint first.
- Do not build gridded map products first.
- Do not depend on unverified PR state first.
- Do not silently interpolate missing 15-minute data.

---

## Questions that still need answers

These are the highest-value clarification questions.

1. What exact BasinWx upload type should HRRR use: `forecasts`, `model-data`, or something else?
2. Do you want one shared product for road and aviation waypoints, or two separate products?
3. What is the v1 waypoint list?
4. What are the v1 variables?
5. What forecast horizon do you actually need?
6. Must v1 be truly 15-minute from the start, or is hourly MVP acceptable first?
7. When `subh` is missing, should we emit nulls, omit times, or stop the run?
8. Do you want nearest-point extraction first, or should I spend time on bilinear interpolation up front?
9. Do you want me to inspect the actual PR branches next, or treat this repo state as the source of truth and start implementing here?

---

## Short critique of the old draft

What the old draft got right:
- use `clyfar` as the operational reference
- keep Uinta Basin crop aligned
- make missing `subh` explicit
- keep metadata honest

What the old draft got wrong:
- schema and endpoint were too late in the sequence
- PR merge order was treated as known fact, but the checkout does not show those contents
- lagged ensemble came too early relative to single-run validation
- upload was treated as solved, but repo docs and code disagree
- "road + aviation waypoints" was too vague to implement

---

## Final recommendation

If we want the fastest path to a robust HRRR product, we should:
- freeze the JSON contract first
- build single-run hourly HRRR first
- add 15-minute support second
- add lagged ensemble third
- keep upload and scheduling last

That is the cleanest path from the repo we actually have, not the repo we hope exists in other branches.
