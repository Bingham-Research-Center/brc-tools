# BRC Tools - Claude Code Guide

> **Quick Nav**: [Index](CLAUDE-INDEX.md) | [Tasks](WISHLIST-TASKS.md) | [Pipeline](docs/PIPELINE-ARCHITECTURE.md) | [Setup](docs/ENVIRONMENT-SETUP.md)

## Project Overview
Research toolkit for the Bingham Research Center focused on atmospheric/environmental data operations. Primary use cases include fetching weather observations, NWP model data, air quality monitoring, and pushing processed data to BasinWX (www.basinwx.com).

**Context**: This is the Python/CHPC side of a two-part system. Data flows from CHPC compute servers → BasinWX web display. Team includes high school students through professors.

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
- **synoptic**: For weather observations API
- **polars**: DataFrame operations (preferred over pandas)
- **herbie**: NWP model data access
- **requests**: API interactions
- **numpy, scipy, matplotlib**: Scientific computing
- **cartopy**: Map projections

## Environment Variables
```bash
# Expected (need confirmation):
SYNOPTIC_API_KEY=xxx
FLIGHTAWARE_API_KEY=xxx
BRC_SERVER_URL=https://basinwx.com  # or similar
BRC_API_KEY=xxx
TMP_DIR=/path/to/temp
```

## Common Tasks

### Fetch Latest Observations
```python
from brc_tools.download import get_map_obs
# Run the main script to fetch and save latest obs
```

### Download NWP Model Data
```python
# Use Herbie for AQM, HRRR, RRFS data
# See in_progress/aqm/ for examples
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
- Use `generate_json_fpath()` for consistent naming
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
pytest tests/
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
1. ✅ **Stations already present** in `lookups.py`: COOPDINU1, COOPALMU1, COOPDSNU1
2. **Verify variable names**: Ensure PM_25_concentration matches website expectations
3. **Consolidate AQM code** from in_progress/
4. ✅ **American English**: visualize directory renamed

## See Also
- [WISHLIST-TASKS.md](WISHLIST-TASKS.md) - Full prioritized task list
- [reference/PYTHON-DEVELOPER-TODO.md](reference/PYTHON-DEVELOPER-TODO.md) - Station updates
- [docs/](docs/) - Additional documentation