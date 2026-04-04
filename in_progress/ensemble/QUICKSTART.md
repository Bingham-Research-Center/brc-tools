# GEFS Ensemble Forecast System - Quick Start

**Status**: Ready for testing
**Date**: 2025-10-26

Complete pipeline: Federal servers → Download → Process → Visualize → Deliver to BasinWx

## What Was Built

### 1. Standardized Download (`brc_tools/download/nwp.py`)
- `download_gefs_ensemble()` - Downloads GEFS using Herbie, saves to Zarr
- `download_latest_gefs_for_clyfar()` - Convenience wrapper with clyfar defaults
- Auto-detects latest available GEFS cycle
- Handles spatial subsetting (Uinta Basin)
- **Output**: Zarr format (fast, web-friendly, chunked)

### 2. Modern Ensemble Class (`in_progress/ensemble/ensemble.py`)
- `Ensemble.from_zarr()` - Load downloaded data
- Statistical methods: `mean()`, `std()`, `percentile()`
- Probabilistic: `get_exceedance_prob()` - threshold probabilities
- Utility: `closest_to_mean()` - find representative member
- **Foundation**: xarray + dask (lazy loading, CF conventions)

### 3. Delivery Format (`brc_tools/delivery/forecast_api.py`)
- `create_meteogram_json()` - Standard JSON for BasinWx
- `create_clyfar_json()` - Clyfar-specific format with ozone forecasts
- Unified structure for all forecast types
- **Output**: Timestamped JSON files

### 4. Testing & Operations
- `test_end_to_end.py` - Full pipeline test with visualizations
- `run_operational_gefs.py` - Cron-ready operational script

## Quick Test

```bash
cd /Users/johnlawson/PycharmProjects/brc-tools/in_progress/ensemble

# Test mode (quick, ~5 min)
python test_end_to_end.py

# Check outputs
ls test_data/       # Downloaded GEFS data (Zarr)
ls test_plots/      # Visualization plots
ls test_json/       # Exported JSON for BasinWx
```

**What the test does**:
1. Downloads 2 GEFS members, 2-day forecast
2. Loads into Ensemble class
3. Computes statistics and probabilities
4. Creates plots (time series, spatial map)
5. Exports JSON for BasinWx

## Installation

```bash
# Core dependencies (should already have from brc-tools)
pip install herbie-data xarray dask zarr netCDF4

# For plotting
pip install matplotlib cartopy

# Optional (for advanced features)
pip install cf-xarray xskillscore
```

## Usage Patterns

### Pattern 1: Interactive Analysis (Notebooks)

```python
import datetime
from brc_tools.download.nwp import download_gefs_ensemble
from ensemble.ensemble import Ensemble

# Download
zarr_path = download_gefs_ensemble(
    init_time=datetime.datetime(2025, 10, 26, 0),
    members=[0, 1, 2],  # Quick test
    forecast_hours=range(0, 48, 6),
    subset_bbox=(39.4, 41.1, -110.9, -108.5),
    save_dir='./data'
)

# Load
ens = Ensemble.from_zarr(zarr_path)

# Analyze
mean_temp = ens.mean('t2m')
prob_freeze = ens.get_exceedance_prob('t2m', threshold=273.15, operator='<')

# Plot
import matplotlib.pyplot as plt
prob_freeze.isel(time=0).plot()
plt.show()
```

### Pattern 2: Operational (Cron Job)

```bash
# Setup on CHPC
cd /uufs/chpc.utah.edu/common/home/u0123456/brc-tools

# Edit paths in run_operational_gefs.py (lines 32-40)
# Then add to crontab:

crontab -e

# Run 4x/day after GEFS cycles (4-hour delay)
30 4,10,16,22 * * * cd /path/to/ensemble && python run_operational_gefs.py

# Or run once daily
30 5 * * * cd /path/to/ensemble && python run_operational_gefs.py
```

### Pattern 3: Clyfar Integration

```python
from brc_tools.download.nwp import download_latest_gefs_for_clyfar
from ensemble.ensemble import Ensemble
from brc_tools.delivery.forecast_api import create_clyfar_json

# 1. Download with clyfar settings (15 days, all members, clyfar variables)
zarr_path = download_latest_gefs_for_clyfar(save_dir='/scratch/general/lustre/...')

# 2. Load into Ensemble
ens = Ensemble.from_zarr(zarr_path)

# 3. Run your clyfar processing (fuzzy logic, etc.)
ozone_forecasts = run_clyfar_model(ens)  # Your clyfar code

# 4. Create standard JSON
json_data = create_clyfar_json(
    ensemble=ens,
    ozone_forecasts=ozone_forecasts,
    location=(40.5, -110.0)
)

# 5. Save and deliver
save_json_with_timestamp(json_data, output_dir='./output', prefix='clyfar')
```

## File Structure

```
brc-tools/
├── brc_tools/
│   ├── download/
│   │   └── nwp.py              # NEW: GEFS/HRRR download
│   └── delivery/
│       ├── __init__.py         # NEW: Delivery module
│       └── forecast_api.py     # NEW: JSON formats
│
└── in_progress/ensemble/
    ├── DESIGN.md               # Architecture decisions
    ├── README.md               # Overview
    ├── QUICKSTART.md           # This file
    ├── ensemble.py             # Main Ensemble class
    ├── test_end_to_end.py      # Testing script
    ├── run_operational_gefs.py # Operational script
    └── examples/
        └── basic_usage.ipynb   # Tutorial notebook
```

## Next Steps

### Immediate (This Week)

1. **Test with real data**:
   ```bash
   python test_end_to_end.py --full  # Downloads full 31-member ensemble
   ```

2. **Verify visualizations**:
   - Check `test_plots/` - do plots look reasonable?
   - Verify JSON structure in `test_json/`

3. **Coordinate with BasinWx frontend**:
   - Share JSON format from `brc_tools/delivery/forecast_api.py`
   - Confirm structure meets website needs

### Short Term (Before Clyfar Operations Dec 1)

1. **Integrate with clyfar**:
   - Refactor clyfar to use `download_latest_gefs_for_clyfar()`
   - Use Ensemble class for statistics
   - Output via `create_clyfar_json()`

2. **Setup on CHPC**:
   - Update paths in `run_operational_gefs.py`
   - Test manual run
   - Add to crontab
   - Monitor logs

3. **Implement BasinWx upload**:
   - Add upload logic to `run_operational_gefs.py:send_to_basinwx()`
   - Options: scp, rsync, API POST

### Medium Term (Throughout Winter)

1. **Add more models**:
   - HRRR ensemble (if available)
   - RRFS ensemble
   - Mixed-model ensembles

2. **Performance optimization**:
   - Benchmark Zarr vs NetCDF
   - Optimize chunk sizes
   - Add caching layer

3. **Advanced features**:
   - Lagged ensembles
   - Bias correction
   - Downscaling for local stations

## Troubleshooting

### Download fails

```python
# Check latest GEFS availability
from brc_tools.download.nwp import get_latest_gefs_init
print(get_latest_gefs_init())

# Try with earlier init time
download_gefs_ensemble(
    init_time=datetime.datetime(2025, 10, 25, 12),  # Yesterday
    ...
)
```

### Variable names different

```python
# Check what variables were downloaded
import xarray as xr
ds = xr.open_zarr('./test_data/gefs_20251026_0000.zarr')
print(list(ds.data_vars))  # See actual variable names

# Adjust in Ensemble
ens = Ensemble.from_zarr(...)
mean = ens.mean('actual_variable_name')  # Use real name from above
```

### Memory issues

```python
# Use lazy loading (default)
ens = Ensemble.from_zarr(zarr_path, lazy=True)

# Or process in chunks
for member in ens:
    member_data = ens.ds.sel(member=member).compute()
    # Process one member at a time
```

### Cron job not running

```bash
# Check cron logs
grep CRON /var/log/syslog

# Check script logs
cat /path/to/logs/gefs/last_run_status.json

# Test manually
cd /path/to/ensemble
python run_operational_gefs.py
```

## Key Design Decisions

**Why Zarr over NetCDF?**
- Faster for large arrays
- Web-friendly (can serve chunks directly)
- Better compression
- Cloud-native format

**Why xarray over numpy?**
- Labeled dimensions (no axis confusion)
- Lazy loading built-in
- CF conventions standard
- Rich ecosystem (MetPy, cartopy)

**Why separate download/process/deliver?**
- Team can work on parts independently
- Download code (Herbie) maintained externally
- Ensemble class reusable for other models
- JSON format standard across all forecasts

## Questions?

See:
- `DESIGN.md` - Detailed architecture decisions
- `ensemble.py` docstrings - API documentation
- `examples/basic_usage.ipynb` - Interactive tutorial
- `brc-knowledge/active-projects/clyfar/` - Clyfar context

Or test interactively:
```python
from ensemble import ensemble
help(ensemble.Ensemble)
```
