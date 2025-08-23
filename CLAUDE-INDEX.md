# Claude Code Knowledge Index

## Quick Navigation
- **🚀 Start Here**: [CLAUDE-CODE-WORKFLOW.md](CLAUDE-CODE-WORKFLOW.md) - Developer workflow guide
- **Project Overview**: [CLAUDE.md](CLAUDE.md) - Main context file
- **Current Tasks**: [WISHLIST-TASKS.md](WISHLIST-TASKS.md) - Prioritized todo list
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
1. Fix station data pipeline
2. Consolidate AQM code
3. Create testing framework
4. Document for team accessibility

## Quick Commands

### Data Pipeline
```python
# Fetch observations
python -m brc_tools.download.get_map_obs

# Check station list
from brc_tools.utils.lookups import obs_map_stids
```

### Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
```

## File Naming Conventions
- Markdown docs: `WORD-WORD.md` (uppercase)
- Python modules: `lowercase_underscore.py`
- Data files: `{prefix}_{YYYYMMDD_HHMM}Z.json`

## API Keys Required
- SYNOPTIC_API_KEY
- FLIGHTAWARE_API_KEY (optional)
- BRC_API_KEY (for BasinWX server)

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