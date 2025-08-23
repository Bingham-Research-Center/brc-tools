# Data Pipeline Architecture

## Overview
The pipeline system follows a consistent pattern:
**Fetch** → **Process** → **Push**

Each pipeline handles one data source and outputs to BasinWX.

## Proposed Structure

### Base Pipeline Class
```python
# brc_tools/pipeline/base.py
class Pipeline:
    def fetch(self) -> Any:
        """Get raw data from source"""
        pass
    
    def process(self, data: Any) -> dict:
        """Transform to expected format"""
        pass
    
    def push(self, data: dict) -> bool:
        """Send to BasinWX server"""
        pass
    
    def run(self):
        """Execute full pipeline"""
        data = self.fetch()
        processed = self.process(data)
        return self.push(processed)
```

### Specific Pipelines

#### 1. Observation Pipeline
```
Synoptic API → Station Data → JSON → BasinWX
```
- **Fetch**: Latest obs for station list
- **Process**: Format to website JSON spec
- **Push**: POST to `/api/data/upload/map-obs`

#### 2. Model Pipeline  
```
Herbie → GRIB2 → Extracted Fields → JSON → BasinWX
```
- **Fetch**: Model data (HRRR, AQM, RRFS)
- **Process**: Extract variables, interpolate
- **Push**: POST to `/api/data/upload/model-data`

#### 3. Aviation Pipeline
```
FlightAware → Flight Data → Filtered → JSON → BasinWX
```
- **Fetch**: Flights in bounding box
- **Process**: Filter altitude, add metadata
- **Push**: POST to `/api/data/upload/aviation`

## Current Implementation Status

### Working
- Basic Synoptic fetching (`download_funcs.py`)
- JSON generation (`push_data.py`)
- Station lookups (`lookups.py`)

### Needs Integration
- AQM explorers in `in_progress/`
- Error handling and retries
- Logging system
- Scheduling/automation

## Configuration Management

### Centralized Config (`brc_tools/config.py`)
```python
class Config:
    # API Settings
    SYNOPTIC_API_KEY = os.getenv('SYNOPTIC_API_KEY')
    BASINWX_URL = 'https://www.basinwx.com'
    BASINWX_API_KEY = os.getenv('BRC_API_KEY')
    
    # Data Settings
    STATION_LIST = [...]  # From lookups.py
    VARIABLE_MAP = {...}  # From lookups.py
    
    # Pipeline Settings
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 2  # seconds
    TIMEOUT = 30  # seconds
    
    # Paths
    DATA_ROOT = './data'
    CACHE_DIR = './cache'
```

## Error Handling Strategy

### Retry Logic
```python
def retry_with_backoff(func, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return func()
        except requests.RequestException as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)
```

### Graceful Degradation
- Missing stations: Continue with available data
- API failures: Use cached data if recent
- Partial data: Mark as incomplete but push

## Data Flow Diagram

```
CHPC Server (This Repository)
    ├── Fetch Layer
    │   ├── Synoptic API
    │   ├── Herbie (Models)
    │   └── FlightAware API
    │
    ├── Process Layer
    │   ├── Format Conversion
    │   ├── Quality Control
    │   └── Aggregation
    │
    ├── Cache Layer (Local)
    │   └── ./data/*.json
    │
    └── Push Layer
        └── POST → BasinWX API

BasinWX Server (Website)
    ├── API Endpoint
    ├── Data Storage
    └── Web Display
```

## Scheduling Recommendations

### Cron Jobs (CHPC)
```bash
# Every 30 minutes - observations
*/30 * * * * cd /path/to/brc-tools && python -m brc_tools.pipeline.observations

# Every 6 hours - model data
0 */6 * * * cd /path/to/brc-tools && python -m brc_tools.pipeline.models

# Once daily - cleanup old cache
0 3 * * * cd /path/to/brc-tools && python -m brc_tools.utils.cleanup
```

### Alternative: Python Scheduler
```python
import schedule

schedule.every(30).minutes.do(run_observations)
schedule.every(6).hours.do(run_models)
schedule.every().day.at("03:00").do(cleanup_cache)

while True:
    schedule.run_pending()
    time.sleep(60)
```

## Testing Strategy

### Unit Tests
- Mock API responses
- Test data transformations
- Validate output formats

### Integration Tests
- Test with real API (limited)
- End-to-end pipeline runs
- Server response validation

### Monitoring
- Log all pipeline runs
- Track success/failure rates
- Alert on repeated failures

## Migration Path

1. **Phase 1**: Consolidate existing code
   - Move functions to pipeline/
   - Standardize interfaces

2. **Phase 2**: Add robustness
   - Implement retry logic
   - Add comprehensive logging
   - Create fallback mechanisms

3. **Phase 3**: Automation
   - Set up scheduling
   - Add monitoring
   - Create alerts

4. **Phase 4**: Optimization
   - Parallel processing
   - Caching strategies
   - Performance tuning

## Benefits of Pipeline Architecture

1. **Consistency**: Same pattern for all data sources
2. **Maintainability**: Clear separation of concerns
3. **Testability**: Each stage can be tested independently
4. **Scalability**: Easy to add new data sources
5. **Reliability**: Built-in error handling and retries
6. **Flexibility**: Can run manually or scheduled