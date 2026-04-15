# BRC Tools — Task Backlog

Completed items are removed once merged; git history is the record.

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

- [ ] **Define BasinWX JSON contract for HRRR waypoint forecasts** — document the expected JSON shape, variable names (`PM_25_concentration` vs `pm25_concentration`), and upload endpoint. Needs `reference/WEBSITE-INTEGRATION.md`.
- [ ] **HRRR waypoint forecast script** — scheduled script that calls `NWPSource.fetch()` → `extract_at_waypoints()` → formats JSON → `push_data.send_json_to_server()`. Target: hourly cron on CHPC.
- [ ] Test data export format matches the JSON contract above.
- [ ] Add structured logging to the operational script (replace print statements for scheduled/unattended runs).

## Priority 3: Analysis capability

Extend the case study toolkit for deeper diagnostics.

- [ ] **Cross-section plotting** (`visualize/crosssection.py`) — vertical cross-section along a waypoint transect using pressure-level data. Key for foehn descent analysis. Stubs exist.
- [ ] **Profile plotting** (`visualize/profile.py`) — single-station vertical profile. Stubs exist.
- [ ] HRRR sub-hourly (15-min) support — product "subh" is defined in lookups.toml but untested.
- [ ] GEFS ensemble workflows — spread, probability, lagged ensemble. Config exists; no analysis code yet.
- [ ] Move AQM code from `in_progress/aqm/` to `brc_tools/models/aqm.py`.
- [ ] Extract reusable functions from notebooks in `in_progress/notebooks/`.

## Priority 4: Developer experience

Important before onboarding new contributors.

- [ ] GitHub Actions CI/CD (run pytest + ruff on PRs).
- [ ] Pre-commit hooks for code quality.
- [ ] `CONTRIBUTING.md` with git workflow (document for range of experience levels).
