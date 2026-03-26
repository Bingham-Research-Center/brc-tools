# Claude Code Knowledge Index

## Quick Navigation
- **🚀 Start Here**: [CLAUDE-CODE-WORKFLOW.md](CLAUDE-CODE-WORKFLOW.md) - Developer workflow guide
- **Project Overview**: [CLAUDE.md](CLAUDE.md) - Main context file
- **Current Tasks**: [WISHLIST-TASKS.md](WISHLIST-TASKS.md) - Prioritized todo list
- **Current Agent Hand-off**: [AGENT-INDEX.md](AGENT-INDEX.md) - Session endpoint and next steps
- **Team Context**: [reference/BRC-TOOLS-SETUP.md](reference/BRC-TOOLS-SETUP.md)

## Project Structure

### Core Package (`brc_tools/`)
- **download/**: Data fetching from APIs (Synoptic, models)
- **aviation/**: FlightAware integration
- **utils/**: Shared utilities, lookups, configurations
- **filter/**: Time series processing
- **visualize/**: Plotting (in development)
- **verify/**: Verification metrics (in development)
- **ml/**: Machine learning tools (planned)

### Active Development (`in_progress/`)
- **aqm/**: Air quality model explorers (needs consolidation)
- **notebooks/**: Experimental scripts for various models

### Documentation (`reference/`)
- **PYTHON-DEVELOPER-TODO.md**: Critical station/data updates needed
- **BRC-TOOLS-SETUP.md**: Setup Q&A and context
- **FLIGHTAWARE-API.md**: Aviation API documentation
- **FLIGHTAWARE-SPEC.md**: FlightAware API specification

## Key Information

### Environment
- **Server**: CHPC (compute) → BasinWX.com (web display)
- **Team**: High school students to professors
- **Workflow**: Git/GitHub based
- **Python**: 3.9+ required

### Critical Context
1. **Missing Stations**: COOPDINU1, COOPALMU1, COOPDSNU1 need adding
2. **API Endpoints**: BasinWX at www.basinwx.com
3. **Data Format**: Specific JSON structure for web compatibility
4. **Language**: American English in code, British OK in communication

### Current Priorities
1. Harden the hourly HRRR road proof-of-concept
2. Keep upload off by default until the road bucket is fixed
3. Keep road and aviation separate products
4. Expand to longer dry-runs before any website-side work

## Quick Commands

### Data Pipeline
```python
# Fetch observations
python -m brc_tools.download.get_map_obs

# Run minimal HRRR road dry-run
/home/johnrobertlawson/.conda/envs/brc-tools/bin/python \
-m brc_tools.download.get_road_forecast \
--dry-run --max-fxx 1 --min-usable-hours 1 \
--data-dir /tmp/brc-tools-road-smoke
```

### Environment Setup
```bash
# Dedicated local Miniforge env used for current HRRR work
/home/johnrobertlawson/.conda/envs/brc-tools/bin/python -m pytest tests/test_road_forecast_logic.py
```

## File Naming Conventions
- Markdown docs: `WORD-WORD.md` (uppercase)
- Python modules: `lowercase_underscore.py`
- Data files: `{prefix}_{YYYYMMDD_HHMM}Z.json`

## API Keys Required
- SYNOPTIC_TOKEN
- FLIGHTAWARE_API_KEY (optional)
- DATA_UPLOAD_API_KEY (for BasinWx uploads)

## Knowledge Base Philosophy
- Keep reference material in `reference/` for persistence
- Use `CLAUDE.md` for primary context (<500 lines)
- Create focused docs in `docs/` for specific topics
- Index everything here for quick access

## Meta-Guidance for Information Transfer
Best practices for giving Claude Code information:
1. **Structured markdown** files in `reference/` (persistent)
2. **Inline TODOs** in code (discovered during exploration)
3. **WISHLIST-TASKS.md** for actionable items
4. **This index** for navigation and quick context

Avoid:
- Very long single files (>1000 lines)
- Unstructured text dumps
- Information only in commit messages
- Critical info in comments only
