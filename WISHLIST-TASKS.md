# BRC Tools - Task Backlog

## Priority 1: Data Pipeline

- [ ] Variable name mapping for website compatibility (`PM_25_concentration` not `pm25_concentration`)
- [ ] Test data export format matches expected JSON structure
- [ ] Move AQM code from `in_progress/aqm/` to `brc_tools/models/aqm.py`
- [ ] Extract reusable functions from notebooks in `in_progress/notebooks/`

## Priority 2: Infrastructure

- [x] Create `brc_tools/nwp/` with NWPSource and lookups.toml (PR #16)
- [x] Create `brc_tools/obs/` with ObsSource (PR #16)
- [x] Model/obs alignment and unit harmonisation (alignment.py)
- [x] Event detection scanner (obs/scanner.py)
- [x] Case study shared helpers (nwp/case_study.py)
- [ ] Create `brc_tools/config.py` for centralised settings (API endpoints, defaults, station lists)
- [ ] Add structured logging (replace print statements)
- [ ] Create fallback mechanisms for missing data

## Priority 3: Documentation

- [x] CLAUDE.md agent-discoverability update (module reference tables)
- [x] API reference (`docs/API-REFERENCE.md`)
- [x] Case study guide (`docs/CASE-STUDY-GUIDE.md`)
- [x] NWP roadmap status update
- [ ] `reference/WEBSITE-INTEGRATION.md` — frontend context and data contract
- [ ] Document git workflow for team (range of experience levels)

## Priority 4: Features

- [ ] Base Pipeline class with fetch → process → push pattern
- [ ] HRRR sub-hourly (15-min) support
- [ ] GEFS ensemble workflows (lagged, spread, probability)
- [ ] Complete `verify/infogain.py`
- [ ] Add basic ML utilities in `ml/`
- [ ] Export to JSON for web rendering (time series, heatmaps)
- [ ] Cross-section and profile plotting (stubs exist)

## Priority 5: Developer Experience

- [ ] Pre-commit hooks for code quality
- [ ] GitHub Actions CI/CD
- [ ] `CONTRIBUTING.md` with git workflow
- [ ] NWPSource / ObsSource integration tests (with mocked API)
- [ ] `examples/` folder with simple use cases
