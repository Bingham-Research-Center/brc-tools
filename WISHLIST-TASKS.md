# BRC Tools - Task Wishlist & Queue

## Priority 0: HRRR Road Proof-of-Concept

### Done This Session
- [x] Add a shared HRRR access layer in `brc_tools/download/hrrr_access.py`
- [x] Add shared HRRR route/query config in `brc_tools/download/hrrr_config.py`
- [x] Add a minimal hourly road CLI in `brc_tools/download/get_road_forecast.py`
- [x] Add a smoke wrapper in `scripts/run_road_forecast_smoke.sh`
- [x] Add first logic tests in `tests/test_road_forecast_logic.py`
- [x] Fix packaging from `synoptic` to `SynopticPy`
- [x] Verify one live `--max-fxx 1` dry-run succeeds locally

### Next Small Steps
- [ ] Run a `6-12` hour dry-run and inspect partial-hour behaviour
- [ ] Add tests for missing HRRR hours and partially available outputs
- [ ] Decide the v1 road upload bucket before enabling upload by default
- [ ] Keep road and aviation separate as the HRRR work expands
- [ ] Delay 15-minute output until the hourly road path is stable

## Priority 1: Critical Data Pipeline Fixes

### Station Data Updates (URGENT)
- [x] ✅ COOP stations already present in `lookups.py`:
  - [x] COOPDINU1 (Dinosaur NM) - 40.44°N, -109.31°W
  - [x] COOPALMU1 (Altamont) - 40.37°N, -110.30°W  
  - [x] COOPDSNU1 (Duchesne) - 40.17°N, -110.40°W
- [ ] Update variable name mapping for website compatibility:
  - [ ] Ensure PM_25_concentration (not pm25_concentration)
  - [ ] Verify all variables match website expectations
- [ ] Test data export format matches expected JSON structure

### Code Consolidation
- [ ] Move AQM code from `in_progress/aqm/` to `brc_tools/models/aqm.py`
- [ ] Extract reusable functions from notebooks in `in_progress/notebooks/`
- [ ] Combine multiple AQM explorers into single configurable module

## Priority 2: Infrastructure & Best Practices

### Configuration Management
- [ ] Create `brc_tools/config.py` for centralized settings:
  - [ ] API endpoints (BasinWX: www.basinwx.com)
  - [ ] Default parameters
  - [ ] Station lists and mappings
- [ ] Implement proper `.env` loading with python-dotenv
- [ ] Add API key validation on startup

### Error Handling & Reliability
- [ ] Add retry logic to all API calls (exponential backoff)
- [ ] Implement proper exception handling
- [ ] Add logging throughout (replace print statements)
- [ ] Create fallback mechanisms for missing data

### Testing Framework
- [ ] Set up pytest structure in `tests/`
- [ ] Create unit tests for utility functions
- [ ] Add integration tests for API calls (with mocking)
- [ ] Document testing approach for team

## Priority 3: Documentation & Knowledge Base

### File Reorganization
- [x] ✅ Renamed "visualise" to "visualize" (American English)
- [x] ✅ Created `docs/` folder structure:
  - [x] `docs/ENVIRONMENT-SETUP.md` - venv/pip guide
  - [x] `docs/PIPELINE-ARCHITECTURE.md` - data flow documentation
  - [ ] `docs/TEAM-SKILLS.md` - plain language explanations
  - [ ] `docs/API-REFERENCE.md` - consolidated API docs

### Knowledge Base Structure
- [x] ✅ Created `CLAUDE-INDEX.md` as master TOC for Claude Code
- [x] ✅ CLAUDE.md is concise (<150 lines)
- [ ] Add `reference/WEBSITE-INTEGRATION.md` for frontend context
- [ ] Document git workflow for team (high school to professor level)

## Priority 4: Feature Implementation

### Data Pipeline (`brc_tools/pipeline/`)
- [ ] Create base Pipeline class with fetch→process→push pattern
- [ ] Implement specific pipelines:
  - [ ] ObservationPipeline (Synoptic → JSON → BasinWX)
  - [ ] ModelPipeline (Herbie → Process → BasinWX)
  - [ ] AviationPipeline (FlightAware → Process → BasinWX)

### Visualization Module
- [ ] Implement time series plotting
- [ ] Create 2D matrix/heatmap generation
- [ ] Add export to JSON for web rendering

### ML/Verification Modules
- [ ] Complete `verify/infogain.py` implementation
- [ ] Add basic ML utilities in `ml/`
- [ ] Create evaluation metrics framework

## Priority 5: Developer Experience

### Build Tools Understanding
- [ ] Document ruff (fast Python linter) usage
- [ ] Document mypy (static type checker) usage
- [ ] Create pre-commit hooks for code quality
- [ ] Add GitHub Actions for CI/CD

### Team Onboarding
- [ ] Create `CONTRIBUTING.md` with git workflow
- [ ] Add examples/ folder with simple use cases
- [ ] Document conda/venv compatibility approach
- [ ] Create troubleshooting guide

## Task Attributes

### Complexity Levels
- **Simple**: Can be done in <30 minutes (station list updates)
- **Medium**: 1-2 hours (module creation, documentation)
- **Complex**: Multiple sessions (pipeline architecture, testing framework)

### Skill Requirements
- **Basic Python**: File updates, configuration changes
- **Intermediate**: API integration, error handling
- **Advanced**: Architecture design, testing framework

### Dependencies
- Station updates → Test data pipeline → Push to website
- Config management → Error handling → Testing
- Documentation → Team onboarding → Collaborative development

## Next Session Priorities
1. Run a longer HRRR road dry-run (`6-12` hours)
2. Harden HRRR missing-hour handling and add tests
3. Decide the road upload bucket for v1
4. Keep observation upload stable while the HRRR path evolves
5. Start aviation only after the road payload shape is stable

## Notes for Claude Code Sessions
- Always check `reference/` folder for context
- Prefer American English in code/docs
- Keep compatibility with conda environments
- Target Python 3.9+ for team compatibility
- Remember team skill range (high school to professor)
