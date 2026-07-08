# BRC Tools — Task Backlog

Completed items are removed once merged; git history is the record.

## WRF figure driver — dataset-agnostic engine (in progress)

Done (brc-tools PR1): the reusable engine `brc_tools/nwp/wrf_figures.py`
(`CaseConfig`/`build_tasks`/`preflight`) + generic CLI
`scripts/wrf_figures.py --config <case.toml>` + domain-awareness helpers in
`wrf_output.py` + per-case colour-scale opt-in (`style.resolve_style`) + acceptance
test (`tests/test_wrf_figures.py`). Renders any nest count/region/variable set from a
TOML and reports genuine mismatches as named skips. Reference:
**`docs/WRF-FIGURE-ENGINE.md`**; audit that drove it:
`docs/WRF-FIGURES-ROBUSTNESS-HANDOFF.md`.

Remaining (two-repo cutover):
- **brc-tools PR2** — delete `scripts/pelican_figures.py` + `pelican_figures.slurm`;
  repoint `.claude/skills/wrf-full-figures/SKILL.md` to the generic CLI + the
  experiment-repo case; trim `docs/WRF-ANALYSIS-FIGURES.md` to findings only and drop
  the robustness handoff.
- **`../wrf-nudge-ozone-air2026`** — add `cases/pelican2013.toml` (the only
  pelican-specific artifact) + a thin SLURM wrapper; fill the figure pointers in its
  `docs/EXTERNAL-PATHS.md` / `docs/visualization-products.md`.

## Session closeout (2026-06-29) — open PRs + next steps

Three PRs from this session's docs/RAP/env work (merge order independent; CODEOWNERS review):
- **#25** — CLAUDE.md/docs sync + `docs/nwp/NWP-SOURCE-MATRIX.md` + a "check Herbie first" guard.
- **#26** — `rap_analysis` staging source (offline, NCEI path preflight-confirmed).
- **#27** — `brc-tools-2026` env + Herbie `2024`→`2026.3.0` bump (validated, 107 passed).

Recommended next steps toward the goals (least-recently-mentioned first):
1. **Merge #25/#26/#27**, then migrate the obs/HRRR crons to `brc-tools-2026` (re-verify the
   RRFS path if RRFS ever goes operational — its Herbie template changed at 2026.3.0).
2. **Pelican forcing review** — RAP and GFS are no longer DTN-stage backlog:
   RAP staged but failed WRF-side field adequacy before `real.exe`, while GFS
   staged, verified, and completed WPS/`real.exe`/`wrf.exe` plus paired NAM/GFS
   quicklooks in `brc-wrf`.
3. **clyfar `send_json_to_server`→`send_json_to_all`** — long-parked; needs a cross-repo PR
   (`docs/CROSS-REPO-SYNC.md`) to retire the legacy single-URL path.
4. **NWPSource/ObsSource integration tests** (Priority 1) — still the highest-leverage
   reliability work, untouched this session.

## WRF-input staging (branch `feat/wrf-input-staging`)

A separate active lane: stage GRIB (GEFSv12 reforecast + NAM analysis) to scratch
for WRF/WPS, with a provenance manifest + case contract. **NAM-only single-stream is
proven end-to-end** (WPS → `real.exe` → `wrf.exe`); the **GEFS+NAM two-stream path is
not** proven. brc-tools owns download/staging/manifest only — WPS/`real.exe`/`wrf.exe`/
Slurm run profiles stay in `brc-wrf`.

- Canonical docs: `docs/WRF-INPUT-STAGING.md` (full reference) and
  `docs/WRF-STAGING-STATE-PLAYBOOK.md` (terse state).
- Cross-repo entry point:
  `../brc-wrf/brc-docs/BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md`.
- The remaining staging-microtask backlog (#4–#13, #31, …) lives in
  `../brc-wrf/doc/BRC_WRF_MICROTASK_HANDOFF.md` — that handoff is the source of truth
  for this lane; not duplicated here.
- [x] **RAP forcing — staged, then blocked in WRF field proof** — source support
  landed in #26 and the 7 RAP cycles were staged. `brc-wrf` WPS-only proofs
  showed unchanged RAP-only is not safe for `real.exe`: hybrid RAP lacked a
  real-ready 3D atmosphere, and pressure RAP lacked layered soil
  temperature/moisture. Future RAP work is a corrected source/product or an
  explicit filler-stream design, not another unchanged DTN stage. Memo:
  `../brc-wrf/brc-docs/BRC-WRF-PELICAN-RAP-FEASIBILITY.md`.

## Priority 1: Reliability

The NWP/obs pipeline is functional but undertested. One regression in
alias resolution or coordinate handling could silently produce wrong data
in every case study.

- [ ] **NWPSource integration tests (mocked Herbie)** — mock `Herbie.xarray()` to return synthetic datasets; test alias resolution, product grouping, coordinate normalization, spatial cropping, waypoint extraction, and failure handling. This is the single highest-leverage task.
- [ ] **ObsSource integration tests (mocked SynopticPy)** — mock `TimeSeries` to return synthetic DataFrames; test alias renaming, waypoint column injection, timezone stripping.
- [ ] **End-to-end pipeline test** — fetch → extract_at_waypoints → align_obs_to_nwp → paired_scores with synthetic data. Validates the full verification workflow.
- [ ] Install and configure ruff in the brc-tools conda env (referenced in docs but not installed).

## Priority 2: Operational delivery (issue #10)

The case study pipeline proves the NWP library works. Closing #10 means
the website receives fresh HRRR forecasts automatically.

- [ ] **Define BasinWX JSON contract for HRRR waypoint forecasts** — document the expected JSON shape, variable names (`PM_25_concentration` vs `pm25_concentration`), and upload endpoint. Generic upload contract now documented in `docs/WEBSITE-INTEGRATION.md`; this item remains for the HRRR-waypoint-specific variable naming.
- [ ] **HRRR waypoint forecast script** — scheduled script that calls `NWPSource.fetch()` → `extract_at_waypoints()` → formats JSON → `push_data.send_json_to_server()`. Target: hourly cron on CHPC.
- [ ] Test data export format matches the JSON contract above.
- [ ] Add structured logging to the operational script (replace print statements for scheduled/unattended runs).
- [ ] **Road-forecast `points[]` projection** — `brc_tools/download/get_road_forecast.py` currently emits `routes{routeId: {waypoints[]}}` but `ubair-website/server/roadWeatherService.js:400` (`getHRRRConditionAtPoint`) reads `hrrrForecast.points[]`. Without a flat `points[]` the website parser returns `null` even when the file is uploaded. Design questions to resolve: (a) replace `routes{}` or supplement it (downstream consumers TBD); (b) per-point `forecasts[{valid_time, temp_2m, ...}]` array vs single `forecasts[0]` only — `roadWeatherService.js:420` reads index 0 only; (c) cardinality — flatten all route waypoints into one `points[]` or sample a denser grid. Cite: `docs/WEBSITE-INTEGRATION.md` (road-forecast §) and `dataUpload.js:189` (only `dataType==='road-forecast'` triggers `latest.json` side-effect — keep that bucket).
- [ ] **Dark website dataTypes (2026-04-27 handoff)** — three products the website expects but brc-tools never emits: `forecast_hrrr_kvel_crosswind_*` (PR #183), `forecast_hrrr_surface_layers_*` (PR #176), and the `forecasts` clustering fan-out gap to `.dev`. Schemas + endpoint contract in `docs/WEBSITE-INTEGRATION.md`.

## Priority 3: Analysis capability

Extend the case study toolkit for deeper diagnostics.

- [ ] **Cross-section plotting** (`visualize/crosssection.py`) — vertical cross-section along a waypoint transect using pressure-level data. Key for foehn descent analysis. Stubs exist.
- [ ] **Profile plotting** (`visualize/profile.py`) — single-station vertical profile. Stubs exist.
- [ ] HRRR sub-hourly (15-min) support — product "subh" is defined in lookups.toml but untested.
- [ ] GEFS ensemble workflows — spread, probability, lagged ensemble. Config exists; no analysis code yet.
- [ ] **Synoptic USGS-HYDRO access** — the token lacks network `mnet_id=203`, so `stream_flow`/`gage_height` queries return zero. Email `support@synopticdata.com` to add it; interim workaround = USGS NWIS direct (`dataretrieval`). Fact + evidence folded into `docs/CHPC-REFERENCE.md`. `scripts/inventory_streamflow_vernal.py` lights up once granted.

## Priority 4: Developer experience

Important before onboarding new contributors.

- [ ] GitHub Actions CI/CD (run pytest + ruff on PRs).
- [ ] Pre-commit hooks for code quality.
- [ ] `CONTRIBUTING.md` with git workflow (document for range of experience levels).

## Priority 5: Documentation and agent onboarding

Deferred from Phase 2 of the dual-site fan-out work (2026-04-23); parked
here so the next cold-start agent knows to tackle it.

- [ ] **CLAUDE.md overhaul** — current file is accurate but grew ad-hoc.
  Goal: reorganise around "what an AI agent needs to know on a cold start"
  with clear sections for (a) active pipelines + cadences, (b) load-bearing
  data-flow anchors, (c) quick-start for case-study construction, (d) what
  *not* to change without a cross-repo PR. Keep it under 200 lines.
- [ ] **Roadmap brainstorm** — prepare a small doc (`docs/ROADMAP.md` or
  similar) that captures the next 6–12 months of work in outcome terms, not
  task lists. Input to the CLAUDE.md overhaul.
- [ ] **Prune root + file contents** for AI-and-human readability: keep
  `docs/nwp/` tight and make sure every top-level file earns its place.
- [ ] **Update "Key data-flow anchor" in CLAUDE.md** post-fan-out to mention
  `send_json_to_all` + `BASINWX_API_URLS` (small; bundle with the overhaul
  above unless a cold-start agent wants a quick win first).

## Priority 6: Seasonal ops (pause/resume)

- [ ] **Clyfar/FFION/GEFS-plot pipelines paused end-March 2026** for the
  season; resume ~October 2026. When resuming, verify they still use the new
  fan-out path (`send_json_to_all`) — check clyfar's import site first since
  it still uses the legacy `send_json_to_server`.
- [ ] **HRRR surface-layer cron** needs installing on the CHPC cron host
  once fan-out is shipped. Template in `CLAUDE.md` under "HRRR surface layer
  export" (adjust cadence and `--server-url` as needed once `BASINWX_API_URLS`
  is set).

## Priority 7: CHPC infra hygiene (from 2026-05-13 sanity check)

Triggered by the live audit on notch392; details in
`brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md`
(§4 Live mount status, §6 real-world note). Cross-repo items kept here so
the brc-tools cold-start agent surfaces them.

- [ ] **Verify `lawson-group4` / `lawson-group5` mount status from another
  node** — both return "Too many levels of symbolic links" on notch392
  (2026-05-13). Test from a different compute node and from `notchpeak1`
  with `df -hT /uufs/chpc.utah.edu/common/home/lawson-group{4,5,6}`. If
  broken globally, draft a CHPC helpdesk ticket (do not send without
  approval). If only this node, leave a node-blocklist note in
  brc-knowledge.
- [ ] **clyfar `storage_inventory.sh` ARCHIVE_BASE off broken volume**
  (cross-repo) — `clyfar/scripts/storage_inventory.sh:50` hardcodes
  `lawson-group5/clyfar`, which silently reports `N/A` while group5 is
  unreachable. Fix path or unbreak the mount.
- [ ] **clyfar `submit_clyfar.sh` → owned `lawson-np` partition**
  (cross-repo) — currently uses `notchpeak-shared-short` (8h, preemptible).
  Owned partition gives 14d walltime, no preemption, no fairshare cost.
  Trivial sbatch header swap.
