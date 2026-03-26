# BRC Tools - Claude Code Guide

> **Quick Nav**: [Index](CLAUDE-INDEX.md) | [Tasks](WISHLIST-TASKS.md) | [Pipeline](docs/PIPELINE-ARCHITECTURE.md) | [Setup](docs/ENVIRONMENT-SETUP.md)

## Project Overview
Research toolkit for the Bingham Research Center focused on atmospheric/environmental data operations. Primary use cases include fetching weather observations, NWP model data, air quality monitoring, and pushing processed data to BasinWX (www.basinwx.com).

**Context**: This is the Python/CHPC side of a two-part system. Data flows from CHPC compute servers → BasinWX web display. Team includes high school students through professors.

## Current Focus
- Production observations already run from `brc_tools/download/get_map_obs.py`.
- Current dev work is a minimal hourly HRRR road proof-of-concept:
  - `brc_tools/download/hrrr_access.py`
  - `brc_tools/download/hrrr_config.py`
  - `brc_tools/download/get_road_forecast.py`
  - `scripts/run_road_forecast_smoke.sh`
  - `tests/test_road_forecast_logic.py`
- Verified on `2026-03-26`:
  - dedicated Miniforge env at `/home/johnrobertlawson/.conda/envs/brc-tools`
  - new road logic tests pass
  - one live `--max-fxx 1` dry-run succeeds locally
- Keep road and aviation separate.
- Keep upload off by default until the road product contract is settled.
- Hourly road MVP comes before 15-minute output.

## Core Functionality

### Data Download (`brc_tools/download/`)
- **get_map_obs.py**: Fetches latest observations from Synoptic API for map visualization
- **download_funcs.py**: Core functions for Synoptic data retrieval
- **push_data.py**: Sends JSON/files to web server API endpoints
- **Key stations**: Uinta Basin focus (Horsepool, Seven Sisters, Castle Peak, etc.)

### Aviation (`brc_tools/aviation/`)
- **flightaware-api-helper.py**: FlightAware API integration for flight tracking
- **Reference spec**: JSON API documentation in reference/

### Utilities (`brc_tools/utils/`)
- **lookups.py**: Station IDs, variable mappings, network definitions
- **util_funcs.py**: Date/time helpers
- **webscraping.py**: Web scraping utilities

### In Progress (`in_progress/`)
- Multiple AQM (Air Quality Model) explorers using Herbie
- HRRR, RRFS, NAM model downloaders
- Notebooks for various NWP products

## Key Dependencies
- **SynopticPy**: For weather observations API
- **polars**: DataFrame operations (preferred over pandas)
- **herbie-data**: NWP model data access
- **requests**: API interactions
- **numpy, scipy, matplotlib**: Scientific computing
- **cartopy**: Map projections

## Environment Variables
```bash
# Common:
DATA_UPLOAD_API_KEY=xxx
SYNOPTIC_TOKEN=xxx
BRC_TOOLS_HRRR_CACHE=/path/to/cache
FLIGHTAWARE_API_KEY=xxx
```

## Common Tasks

### Fetch Latest Observations
```python
from brc_tools.download import get_map_obs
# Run the main script to fetch and save latest obs
```

### Download NWP Model Data
```python
# Minimal hourly HRRR road proof-of-concept
/home/johnrobertlawson/.conda/envs/brc-tools/bin/python \
-m brc_tools.download.get_road_forecast \
--dry-run --max-fxx 1 --min-usable-hours 1 \
--data-dir /tmp/brc-tools-road-smoke
```

### Push Data to Server
```python
from brc_tools.download.push_data import send_json_to_server
send_json_to_server(server_url, filepath, data_type, API_KEY)
```

## Data Formats

### Map Observations JSON
- Station metadata: stid, name, elevation, lat, lon
- Observations: stid, variable, value, date_time, units
- Saved as: `map_obs_YYYYMMDD_HHMMZ.json`

### File Naming Convention
- Format: `{prefix}_{YYYYMMDD_HHMM}Z.json`

## Code Conventions

### Import Order
1. Standard library
2. Third-party packages
3. Local modules

### DataFrame Library
- **Prefer Polars** over Pandas for new code
- Use `.select()`, `.filter()`, `.with_columns()` patterns

### Time Handling
- Always use UTC internally
- Convert to local time only for display
- Use `datetime.timezone.utc` not `pytz`

### Error Handling
- Wrap API calls in try/except blocks
- Log failures but continue processing
- Implement retry logic for network requests

## Testing Commands
```bash
# Lint (when configured)
ruff check .

# Type checking (when configured)
mypy brc_tools/

# Run tests (when written)
/home/johnrobertlawson/.conda/envs/brc-tools/bin/python -m pytest tests/
```

## Project Structure
```
brc_tools/           # Main package
├── download/        # Data fetching and pushing
├── aviation/        # FlightAware integration
├── filter/          # Time series processing
├── visualize/       # Plotting (to be completed)
├── verify/          # Verification metrics
├── ml/              # Machine learning tools
└── utils/           # Shared utilities

in_progress/         # Active development
├── aqm/            # Air quality model work
└── notebooks/      # Experimental scripts

data/               # Local data cache (gitignored?)
└── schema/         # JSON schemas and docs
```

## Critical Updates Needed
1. Run a `6-12` hour HRRR road dry-run and harden missing-hour handling
2. Decide the v1 road upload bucket before enabling upload
3. Keep road and aviation separate as the HRRR work expands
4. Consolidate older `in_progress/` model code only after the HRRR road path is stable

## See Also
- [WISHLIST-TASKS.md](WISHLIST-TASKS.md) - Full prioritized task list
- [reference/PYTHON-DEVELOPER-TODO.md](reference/PYTHON-DEVELOPER-TODO.md) - Station updates
- [docs/](docs/) - Additional documentation
