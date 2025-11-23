# AI Agent Quick Reference - brc-tools

**Current Task:** Supporting Clyfar integration
**Status:** Stable - no changes needed currently
**Session Date:** 2025-11-23

---

## Quick Start

**This repo:** Shared Python tools for BRC projects
**Purpose:** Data download, processing, and upload to BasinWx
**Used by:** clyfar (editable install)

**Key module:** `brc_tools/download/push_data.py` (upload to website)

---

## Package Status

### Installation
- **Version:** 0.1.0
- **Install method:** Editable (`pip install -e .`)
- **Installed in:** clyfar-2025 conda environment
- **Location:** `/Users/johnlawson/PycharmProjects/brc-tools`

**Verify:**
```bash
conda activate clyfar-2025
pip list | grep brc-tools  # Should show: brc-tools 0.1.0 /path/to/brc-tools
```

### Configuration
- **Package file:** `pyproject.toml` (proper package structure)
- **Dependencies:** Listed in pyproject.toml
- **Environment:** Uses `.env` for secrets

---

## Key Modules

**Upload functionality:**
- `brc_tools/download/push_data.py` - POST to website API
  - `send_json_to_server(server_address, fpath, file_data, API_KEY)`
  - Used by clyfar for uploading forecasts

**Observation download:**
- `brc_tools/download/get_map_obs.py` - Synoptic API → website
  - Runs every 10 minutes via cron
  - Self-contained (downloads + uploads)

**Schema:**
- `data/schema/ubair_schema.json` - Station metadata (config file)
- NOT a JSON Schema validator (different from DATA_MANIFEST.json)

---

## Integration Points

**Clyfar uses:**
```python
from brc_tools.download.push_data import send_json_to_server

send_json_to_server(
    server_address="https://basinwx.com",
    fpath="/path/to/forecast.json",
    file_data=forecast_dict,
    API_KEY=os.environ.get('DATA_UPLOAD_API_KEY')
)
```

**Website expects:**
- Header: `x-api-key: <API_KEY>`
- Header: `x-client-hostname: <hostname>` (must end with chpc.utah.edu)
- Method: POST to `/api/upload/:dataType`
- Body: multipart/form-data with file

---

## Current Deployment

**CHPC cron:**
```bash
# Observations - Every 10 minutes
*/10 * * * * source ~/.bashrc && cd ~/brc-tools && ~/brc-tools/venv/bin/python3 ~/brc-tools/brc_tools/download/get_map_obs.py
```

**Status:** ✅ Working in production

---

## Documentation

**In this repo:**
- `README.md` - Updated with CHPC deployment section
- `pyproject.toml` - Package configuration
- `.env.example` - Environment template

**In ubair-website repo:**
- `CHPC-IMPLEMENTATION.md` - Deployment guide
- `PYTHON-PACKAGING-DEPLOYMENT.md` - Packaging education
- `chpc-deployment/` - Cron templates, setup scripts

---

## For AI Agents

**When to modify this repo:**
- Changing upload API protocol
- Adding new data sources
- Updating authentication method
- Fixing bugs in push_data.py

**When NOT to modify:**
- Clyfar-specific code (goes in clyfar repo)
- Website-specific code (goes in ubair-website repo)
- Just using upload functionality (import, don't modify)

**Coordination:**
- See `CROSS-REPO-SYNC.md` (to be created)
- This is a shared library - changes affect multiple projects
- Test thoroughly before deploying

---

## Common Issues

**"Module not found":**
```bash
# Install in editable mode
conda activate <your-env>
pip install -e /Users/johnlawson/PycharmProjects/brc-tools
```

**"API key not set":**
```bash
# Check environment variable
echo $DATA_UPLOAD_API_KEY
# Or add to .env file
```

**"Hostname validation failed":**
- Must run from CHPC (*.chpc.utah.edu)
- Or temporarily disable validation for local testing

---

## Version History

**v0.1.0** (current)
- Initial package structure
- Upload functionality working
- Installed in clyfar for integration

**Future:**
- Tag v0.1.0-clyfar-integration after testing
- Document in tech report
- Consider additional data sources

---

## Cross-Repo Links

**Repos using brc-tools:**
1. **clyfar** - Imports push_data for forecast uploads
2. **ubair-website** - Receives uploaded data
3. **preprint-clyfar-v0p9** - References in methodology

**See also:**
- `../ubair-website/COMPACT-RESUME-POINT.md` - Current session context
- `../clyfar/INTEGRATION_GUIDE.md` - How clyfar uses this package

---

**Last Updated:** 2025-11-23 (pre-compact)
**Package Version:** 0.1.0
**Status:** Stable, no changes needed
