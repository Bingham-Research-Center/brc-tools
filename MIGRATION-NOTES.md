# Migration Notes - BRC Tools Reorganization

> **Date**: January 19, 2025  
> **Version**: Post-reorganization

## Summary of Changes

This document summarizes the major reorganization and modernization of the BRC Tools codebase.

## Package Structure Changes

### New Package Organization
```
brc_tools/
├── models/          # NEW: NWP model data access
│   ├── base.py      # Base model interface
│   ├── aqm.py       # Air Quality Model (consolidated from in_progress/)
│   └── __init__.py
├── pipeline/        # NEW: Data pipeline architecture  
│   ├── base.py      # Base pipeline class (fetch→process→push)
│   └── __init__.py
├── config/          # NEW: Centralized configuration
│   ├── settings.py  # Main configuration class
│   └── __init__.py
├── core/            # NEW: Shared utilities
│   ├── exceptions.py # Custom exception classes
│   ├── logging.py    # Centralized logging
│   ├── retry.py      # Retry logic and decorators
│   └── __init__.py
└── [existing packages unchanged]
```

### Documentation Structure
```
docs/
├── NWP-DATA-GUIDE.md           # NEW: Comprehensive NWP data guide
├── NWP-THEORETICAL-WISHLIST.md # NEW: Research applications & future
├── PIPELINE-ARCHITECTURE.md    # Existing
└── ENVIRONMENT-SETUP.md        # Existing

examples/                       # NEW: Practical usage examples
├── basic/                      # Simple getting-started examples
├── nwp/                        # NWP-specific examples
└── advanced/                   # Complex workflows
```

## Code Consolidation

### AQM Model Access
**Before**: 7 duplicate AQM explorers in `in_progress/aqm/`
```
in_progress/aqm/
├── aqm-claude-demo2.py      # CONSOLIDATED
├── aqm-demo.py              # CONSOLIDATED  
├── aqm_explorer.py          # CONSOLIDATED
├── simple_aqm_explorer.py   # CONSOLIDATED → PRIMARY SOURCE
├── updated-aqm-explorer.py  # CONSOLIDATED
├── ext_herbie_tests.ipynb   # ARCHIVED
└── hrrr_test.py            # ARCHIVED
```

**After**: Single, production-ready module
```python
from brc_tools.models import AQMData

# Clean, standardized interface
aqm = AQMData(
    init_time="2025-01-31 12:00",
    forecast_hour=14,
    product="ave_8hr_o3"
)
ozone_data = aqm.get_variable("ozone_concentration")
```

### Variable Naming Standardization
**Fixed PM2.5 inconsistencies throughout codebase:**

| Before | After | Location |
|--------|-------|----------|
| `pm25` | `PM_25_concentration` | All model interfaces |
| `pmtf` | `PM_25_concentration` | Legacy AQM code |
| `pm25_concentration` | `PM_25_concentration` | Variable mappings |

### Configuration Management
**Before**: Scattered settings across files
**After**: Centralized configuration system
```python
from brc_tools.config import config

# All settings in one place
api_key = config.synoptic_api_key
stations = config.get_station_list("uinta_basin")
headers = config.get_api_headers("synoptic")
```

## New Features

### 1. Pipeline Architecture
Standardized fetch→process→push pattern for all data workflows:
```python
from brc_tools.pipeline.base import Pipeline

class CustomPipeline(Pipeline):
    def fetch(self): pass      # Get raw data
    def process(self, data): pass  # Transform data  
    def push(self, data): pass     # Send to destination
```

### 2. Error Handling & Logging
- **Structured logging**: Replace print statements with proper logging
- **Retry logic**: Automatic retry with exponential backoff
- **Custom exceptions**: Domain-specific error types
- **Graceful degradation**: Handle partial failures

### 3. Comprehensive Documentation
- **NWP Data Guide**: Complete reference for all model access
- **Theoretical Wishlist**: Research applications and future development
- **Practical Examples**: Working code for common use cases

## Breaking Changes

### Import Changes
```python
# OLD (deprecated)
from in_progress.aqm.simple_aqm_explorer import initialize_herbie

# NEW (recommended)  
from brc_tools.models import AQMData
```

### Configuration Changes
```python
# OLD (scattered)
SYNOPTIC_API_KEY = "hardcoded_key"
station_list = [...]  # In multiple files

# NEW (centralized)
from brc_tools.config import config
api_key = config.synoptic_api_key  # From environment
stations = config.get_station_list("uinta_basin")
```

## Migration Guide

### For Existing Scripts
1. **Update imports**:
   ```python
   # Replace in_progress imports
   from brc_tools.models import AQMData
   from brc_tools.config import config
   ```

2. **Use new AQM interface**:
   ```python
   # OLD
   H = initialize_herbie(date, product, domain, fxx)
   ds = H.xarray()
   
   # NEW
   aqm = AQMData(date, fxx, product, domain)
   ds = aqm.get_variable()
   ```

3. **Update variable names**:
   ```python
   # Ensure PM2.5 variables use standard naming
   "PM_25_concentration"  # Not "pm25" or "pmtf"
   ```

### For New Development
1. **Use pipeline architecture** for data workflows
2. **Import from brc_tools packages**, not in_progress/
3. **Follow logging patterns** instead of print statements
4. **Use centralized configuration** system

## File Status

### Consolidated Files
These files from `in_progress/` have been consolidated into `brc_tools/models/aqm.py`:
- ✅ `aqm-claude-demo2.py` → Functionality integrated
- ✅ `aqm-demo.py` → Functionality integrated  
- ✅ `aqm_explorer.py` → Functionality integrated
- ✅ `simple_aqm_explorer.py` → Primary source for new module
- ✅ `updated-aqm-explorer.py` → Functionality integrated

### Archived Files  
These files are preserved for reference but should not be used for new development:
- 📁 `in_progress/aqm/ext_herbie_tests.ipynb` → Research notebook
- 📁 `in_progress/aqm/hrrr_test.py` → Exploratory code
- 📁 `in_progress/notebooks/*` → Experimental scripts

### Deprecated Functions
```python
# DEPRECATED - Use AQMData class instead
initialize_herbie()     # → AQMData()
load_aqm_dataset()      # → AQMData.get_variable()
```

## Testing & Validation

### Verify Migration
Run these commands to verify the reorganization:

```bash
# Test new AQM interface
python examples/nwp/aqm_ozone_example.py

# Test pipeline architecture  
python examples/advanced/observation_pipeline.py

# Test basic functionality
python examples/basic/synoptic_data.py
```

### Configuration Check
```bash
# Verify environment variables
echo $SYNOPTIC_API_KEY
echo $BRC_DATA_ROOT

# Test configuration loading
python -c "from brc_tools.config import config; print(config.synoptic_api_key[:10])"
```

## Future Development

### Next Steps
1. **Add HRRR/RRFS models** to `brc_tools/models/`
2. **Implement specific pipelines** in `brc_tools/pipeline/`
3. **Add comprehensive testing** framework
4. **Set up CI/CD** for automated testing

### Guidelines
- **Follow established patterns** from this reorganization
- **Use centralized configuration** for all new features
- **Implement proper error handling** and logging
- **Add examples** for new functionality
- **Update documentation** as features are added

## Questions & Support

For questions about the reorganization:
1. Check the new documentation in `docs/`
2. Review examples in `examples/`
3. Consult this migration guide
4. Reference the original files in `in_progress/` if needed

The reorganization maintains backward compatibility where possible while providing a clear path forward for modern, maintainable code.