# NWP Data Guide - BRC Tools

> **Quick Start**: [Examples](#quick-start-examples) | [Available Models](#available-models) | [Installation](#installation)

## Overview

The BRC Tools package provides standardized access to numerical weather prediction (NWP) data for atmospheric research. This guide covers all available models, data formats, and usage patterns.

## Installation & Setup

### Dependencies
```bash
# Core requirements
pip install herbie-data xarray numpy pandas

# For visualization (optional)
pip install matplotlib cartopy

# For BRC Tools
pip install -e .
```

### Environment Setup
```bash
# Required environment variables
export BRC_DATA_ROOT="./data"
export BRC_CACHE_DIR="./cache"
export BRC_LOG_LEVEL="INFO"

# Optional for enhanced functionality
export SYNOPTIC_API_KEY="your_synoptic_key"
```

## Available Models

### 1. Air Quality Model (AQM)
**Purpose**: Air quality forecasts (ozone, PM2.5)  
**Resolution**: 12 km CONUS  
**Update Frequency**: 2x daily (06Z, 18Z)  
**Forecast Length**: 72 hours  

#### Available Products
```python
# Ozone products
"ave_8hr_o3"      # 8-hour average ozone (primary for air quality)
"max_1hr_o3"      # 1-hour maximum ozone
"ave_1hr_o3"      # 1-hour average ozone

# PM2.5 products
"ave_24hr_PM_25_concentration"  # 24-hour average PM2.5
"ave_1hr_PM_25_concentration"   # 1-hour average PM2.5
"max_1hr_PM_25_concentration"   # 1-hour maximum PM2.5
```

### 2. High Resolution Rapid Refresh (HRRR)
**Purpose**: High-resolution weather forecasts  
**Resolution**: 3 km CONUS  
**Update Frequency**: Hourly  
**Forecast Length**: 18-48 hours (varies)  

#### Key Variables
- Surface temperature, pressure, humidity
- Wind speed and direction (multiple levels)
- Precipitation
- Cloud cover and radiation
- Boundary layer parameters

### 3. Rapid Refresh Forecast System (RRFS)
**Purpose**: Next-generation high-resolution forecasts  
**Resolution**: 3 km CONUS  
**Update Frequency**: Hourly  
**Forecast Length**: 60 hours  

### 4. North American Mesoscale (NAM)
**Purpose**: Regional weather forecasts  
**Resolution**: 12 km North America  
**Update Frequency**: 4x daily  
**Forecast Length**: 84 hours  

### 5. Global Forecast System (GFS)
**Purpose**: Global weather forecasts  
**Resolution**: 13 km (0.125°) global  
**Update Frequency**: 4x daily  
**Forecast Length**: 384 hours (16 days)  

## Quick Start Examples

### Basic AQM Usage
```python
from brc_tools.models import AQMData
from datetime import datetime

# Initialize for 8-hour ozone forecast
aqm = AQMData(
    init_time="2025-01-31 12:00",
    forecast_hour=14,
    product="ave_8hr_o3"
)

# Get ozone data
ozone_data = aqm.get_variable("ozone_concentration")
print(f"Data shape: {ozone_data.dims}")
print(f"Valid time: {aqm.valid_time()}")

# Get Utah subset
utah_ozone = aqm.get_utah_subset()
```

### PM2.5 Data Access
```python
# 24-hour average PM2.5
pm25_aqm = AQMData(
    init_time=datetime.now(),
    forecast_hour=24,
    product="ave_24hr_PM_25_concentration"
)

pm25_data = pm25_aqm.get_variable()
print(f"PM2.5 data range: {pm25_data.min().values:.2f} - {pm25_data.max().values:.2f}")
```

### Multi-Model Comparison
```python
from brc_tools.models import AQMData, HRRRData  # (when implemented)

# Same forecast time for comparison
init_time = "2025-01-31 12:00"
forecast_hour = 12

# Get AQM ozone
aqm = AQMData(init_time, forecast_hour, "ave_1hr_o3")
aqm_ozone = aqm.get_variable()

# Get HRRR meteorology (when available)
# hrrr = HRRRData(init_time, forecast_hour)
# hrrr_wind = hrrr.get_variable("wind_speed")
```

## Data Formats & Structure

### xarray Dataset Structure
All models return data as xarray Datasets with consistent metadata:

```python
<xarray.Dataset>
Dimensions:     (latitude: 265, longitude: 442)
Coordinates:
  * latitude    (latitude) float32 21.14 21.27 21.41 ... 59.84 59.97
  * longitude   (longitude) float32 -134.1 -133.9 -133.8 ... -60.88 -60.73
Data variables:
    ozone_concentration  (latitude, longitude) float32 ...
Attributes:
    model:         AQM
    product:       ave_8hr_o3
    init_time:     2025-01-31T12:00:00
    forecast_hour: 14
    valid_time:    2025-02-01T02:00:00
```

### Variable Naming Conventions
- **Temperature**: `air_temperature` (K), `temperature_2m` (surface)
- **Wind**: `wind_speed` (m/s), `wind_direction` (degrees)
- **Pressure**: `pressure` (Pa), `sea_level_pressure` (Pa)
- **Air Quality**: `ozone_concentration` (ppb), `PM_25_concentration` (μg/m³)
- **Moisture**: `relative_humidity` (%), `specific_humidity` (kg/kg)

## Geographic Domains

### Standard Domains
```python
domains = {
    "CS": "CONUS (Continental US)",
    "AK": "Alaska", 
    "HI": "Hawaii",
    "PR": "Puerto Rico"  # Limited models
}
```

### Custom Regions
```python
# Utah region bounds
utah_bounds = {
    "latitude": slice(37.0, 42.0),
    "longitude": slice(-114.5, -109.0)
}

# Uinta Basin focus
uinta_bounds = {
    "latitude": slice(39.5, 41.0),
    "longitude": slice(-111.0, -109.0)
}
```

## Time Handling

### Initialization Times
```python
# Common AQM runs
aqm_runs = ["06:00", "18:00"]  # UTC

# HRRR runs (every hour)
hrrr_runs = [f"{h:02d}:00" for h in range(24)]

# NAM/GFS runs
synoptic_runs = ["00:00", "06:00", "12:00", "18:00"]  # UTC
```

### Forecast Hours
```python
# AQM: 0-72 hours
aqm_hours = range(0, 73)

# HRRR: 0-18 hours (some runs to 48h)
hrrr_hours = range(0, 19)

# NAM: 0-84 hours
nam_hours = range(0, 85)
```

### Time Conversion
```python
from datetime import datetime, timezone

# Always work in UTC internally
init_utc = datetime(2025, 1, 31, 12, 0, tzinfo=timezone.utc)

# Convert to local (Mountain Time) for display
import pytz
mt = pytz.timezone('US/Mountain')
init_local = init_utc.astimezone(mt)
```

## Data Quality & Validation

### Quality Control Checks
```python
def validate_aqm_data(data):
    """Basic quality control for AQM data."""
    
    # Check for reasonable ranges
    if "ozone_concentration" in data:
        ozone = data["ozone_concentration"]
        if (ozone < 0).any() or (ozone > 200).any():
            print("Warning: Ozone values outside expected range (0-200 ppb)")
    
    if "PM_25_concentration" in data:
        pm25 = data["PM_25_concentration"]
        if (pm25 < 0).any() or (pm25 > 500).any():
            print("Warning: PM2.5 values outside expected range (0-500 μg/m³)")
    
    # Check for missing data
    missing_fraction = data.isnull().sum() / data.size
    if missing_fraction > 0.1:
        print(f"Warning: {missing_fraction:.1%} missing data")
```

### Data Availability
```python
# Check what's available for a given time
aqm = AQMData("2025-01-31 12:00", 14)
available_vars = aqm.available_variables()
available_forecasts = aqm.get_available_forecasts()

print(f"Variables: {available_vars}")
print(f"Forecasts: {available_forecasts}")
```

## Error Handling

### Common Issues & Solutions

#### 1. Data Not Available
```python
try:
    aqm = AQMData("2025-01-31 12:00", 14)
    data = aqm.get_variable()
except DataError as e:
    print(f"Data access failed: {e}")
    # Try different forecast hour or init time
```

#### 2. Network Issues
```python
from brc_tools.core.retry import retry_with_backoff

@retry_with_backoff(max_attempts=3)
def robust_data_fetch():
    aqm = AQMData("2025-01-31 12:00", 14)
    return aqm.get_variable()
```

#### 3. Memory Issues with Large Datasets
```python
# Use lazy loading with dask
data = aqm.get_variable()
data = data.chunk({'latitude': 100, 'longitude': 100})

# Process in smaller regions
utah_data = aqm.get_utah_subset()  # Smaller memory footprint
```

## Performance Optimization

### Caching
```python
# Automatic caching through Herbie
# Cache location controlled by environment
export HERBIE_CACHE_DIR="/path/to/cache"

# Manual cache management
from brc_tools.config import config
cache_size = sum(f.stat().st_size for f in config.cache_dir.rglob('*') if f.is_file())
print(f"Cache size: {cache_size / 1e9:.2f} GB")
```

### Parallel Processing
```python
import concurrent.futures
from datetime import timedelta

def fetch_multiple_forecasts(init_time, forecast_hours):
    """Fetch multiple forecast hours in parallel."""
    
    def fetch_single(fhour):
        aqm = AQMData(init_time, fhour)
        return fhour, aqm.get_variable()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_single, fh): fh for fh in forecast_hours}
        results = {}
        
        for future in concurrent.futures.as_completed(futures):
            fhour, data = future.result()
            results[fhour] = data
    
    return results
```

## Integration with BasinWX

### Data Pipeline
```python
from brc_tools.pipeline import ModelPipeline

# Automated AQM data pipeline
pipeline = ModelPipeline(
    model_class=AQMData,
    product="ave_8hr_o3",
    target_endpoint="https://www.basinwx.com/api/aqm"
)

# Run pipeline
success = pipeline.run()
if success:
    print("Data successfully pushed to BasinWX")
```

### Data Format for Website
```python
# Standard format expected by BasinWX
website_format = {
    "model": "AQM",
    "product": "ave_8hr_o3", 
    "init_time": "2025-01-31T12:00:00Z",
    "valid_time": "2025-02-01T02:00:00Z",
    "data": {
        "latitudes": [...],
        "longitudes": [...],
        "values": [...]
    },
    "metadata": {...}
}
```

## Troubleshooting

### Debug Mode
```python
import logging
from brc_tools.core.logging import setup_logging

# Enable debug logging
setup_logging(level=logging.DEBUG)

# Check what Herbie is doing
aqm = AQMData("2025-01-31 12:00", 14)
print(f"Herbie GRIB source: {aqm.herbie.grib}")
print(f"Herbie inventory: {aqm.herbie.inventory()}")
```

### Manual Herbie Access
```python
# Direct Herbie usage for debugging
from herbie import Herbie

H = Herbie(
    date="2025-01-31 12:00",
    model="aqm", 
    product="ave_8hr_o3",
    fxx=14
)

# Check available data
print(H.inventory())
print(f"GRIB file: {H.grib}")

# Raw xarray access
ds = H.xarray()
print(ds)
```

### Common Solutions
1. **"No data found"**: Check init time, forecast hour, and product name
2. **"Permission denied"**: Check cache directory permissions
3. **"Memory error"**: Use smaller spatial subsets or chunking
4. **"Network timeout"**: Enable retry logic or check internet connection

## Best Practices

### 1. Always Use UTC Internally
```python
# Good
from datetime import datetime, timezone
init_time = datetime(2025, 1, 31, 12, 0, tzinfo=timezone.utc)

# Avoid
init_time = "2025-01-31 12:00"  # Ambiguous timezone
```

### 2. Handle Missing Data Gracefully
```python
try:
    data = aqm.get_variable()
    if data is None or data.size == 0:
        raise DataError("No data returned")
except DataError as e:
    logger.warning(f"Data fetch failed: {e}")
    # Use backup data source or skip
```

### 3. Validate Data Ranges
```python
# Check for reasonable physical values
ozone = data["ozone_concentration"]
if (ozone < 0).any():
    logger.warning("Negative ozone values detected")
    ozone = ozone.where(ozone >= 0)
```

### 4. Use Appropriate Forecast Hours
```python
# For 8-hour ozone, need at least 8 hours of data
if "8hr" in product and forecast_hour < 8:
    forecast_hour = 8
    logger.info(f"Adjusted forecast hour to {forecast_hour} for 8-hour product")
```

## See Also

- [NWP Theoretical Wishlist](NWP-THEORETICAL-WISHLIST.md) - Research applications and future capabilities
- [Pipeline Architecture](PIPELINE-ARCHITECTURE.md) - Data processing workflows  
- [Examples Directory](../examples/nwp/) - Practical usage examples
- [Herbie Documentation](https://herbie.readthedocs.io/) - Underlying data access library