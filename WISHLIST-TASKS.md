# BRC Tools - Task Wishlist & Queue

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
1. Verify variable name mapping (PM_25_concentration) matches website
2. Test data pipeline with all stations
3. Create `brc_tools/config.py` for centralized settings
4. Begin AQM code consolidation from `in_progress/`
5. Add error handling and retry logic to API calls

## Notes for Claude Code Sessions
- Always check `reference/` folder for context
- Prefer American English in code/docs
- Keep compatibility with conda environments
- Target Python 3.9+ for team compatibility
- Remember team skill range (high school to professor)