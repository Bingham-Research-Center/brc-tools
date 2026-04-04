# Ensemble Class Design Document

**Author**: Salvaged from evac + modernized
**Date**: 2025-10-26
**Status**: Research & Design Phase

## Purpose

Create a modern, Pythonic class for managing NWP ensemble forecasts (GEFS, SREF, etc.) that:
1. Handles standard ensembles (control + perturbations from single init time)
2. Supports non-standard ensembles (lagged, mixed-model, custom member selection)
3. Provides probabilistic analysis methods (exceedance, percentiles, spread)
4. Integrates with BasinWx web API (JSON serialization)
5. Follows modern best practices (xarray, lazy loading, type hints)

## Design Decisions

### 1. Core Data Structure: xarray.Dataset

**Decision**: Use `xarray.Dataset` as primary container, not numpy arrays

**Rationale**:
- **Labeled dimensions**: No confusion about axis order - coords named `member`, `time`, `lat`, `lon`, `level`
- **Lazy loading**: Built-in dask integration for large ensembles
- **CF conventions**: Standard meteorological metadata
- **Rich ecosystem**: Works with MetPy, cartopy, xskillscore
- **Serialization**: Native NetCDF, Zarr support + JSON conversion tools

**Trade-offs**:
- Learning curve for users familiar with numpy
- Slightly more memory overhead than raw arrays
- **Mitigation**: Provide simple `.values` accessor for numpy-style operations

**Comparison to evac**:
| evac (2018) | Modern (2025) |
|-------------|---------------|
| `numpy.ndarray` + `multiprocessing.RawArray` | `xarray.Dataset` + `dask` |
| Manual axis management `[member,time,level,lat,lon]` | Named coords `.sel(member='p01', time='2025-10-26')` |
| Custom metadata dicts | CF-compliant attributes |
| Hand-coded parallelization | Dask automatic parallelization |

### 2. Data Acquisition: Herbie Integration

**Decision**: Use Herbie as primary download interface, with fallback for custom data

**Herbie capabilities** (herbie-data>=2024.0.0):
```python
from herbie import Herbie

# Single member
H = Herbie('2025-10-26 00:00', model='gefs', member=1)
ds = H.xarray('TMP:2 m')  # Returns xarray.Dataset

# Does Herbie handle multi-member natively?
# ACTION: Test if Herbie can load all GEFS members at once
```

**API design**:
```python
# Standard ensemble via Herbie (auto-discovery)
ens = Ensemble.from_gefs(
    init_time=datetime(2025, 10, 26, 0),
    members='all',  # or [1,2,3] or 'control'
    forecast_hours=range(0, 48, 3)
)

# Lagged ensemble (mixed init times)
ens = Ensemble.from_lagged(
    model='gefs',
    init_times=[
        datetime(2025, 10, 25, 12),
        datetime(2025, 10, 25, 18),
        datetime(2025, 10, 26, 0),
    ],
    members_per_init=5,
    forecast_hours=range(0, 24, 3)
)

# Custom/manual (for non-standard data)
ens = Ensemble.from_files(
    filepaths=[...],
    member_names=['ctrl', 'p01', 'p02'],
    reader='grib'  # or 'netcdf', 'wrfout'
)

# From existing xarray
ens = Ensemble(ds)  # ds must have 'member' dimension
```

### 3. Lazy Loading Strategy

**Decision**: Default to lazy (dask-backed), allow eager loading for small ensembles

**Implementation**:
```python
class Ensemble:
    def __init__(self, ds: xr.Dataset, lazy: bool = True):
        self.ds = ds

        if lazy and not is_dask_backed(ds):
            # Chunk by member for parallel processing
            self.ds = ds.chunk({'member': 1, 'time': -1})
        elif not lazy:
            self.ds = ds.compute()  # Load into memory
```

**Chunking strategy** (needs testing):
- Small ensembles (<10 members): Load all into memory
- Medium (10-50 members): Chunk by member, keep time/space contiguous
- Large (50+ members or high-res): Chunk space + time too

**Question for testing**: What's optimal chunk size for BasinWx use cases?

### 4. Probabilistic Methods

**Decision**: Keep evac's probabilistic methods, reimplement with xarray

**Core methods** (salvaged from evac/datafiles/ensemble.py):

```python
def get_exceedance_prob(
    self,
    var: str,
    threshold: float,
    operator: Literal['>', '<', '>=', '<=', '=='],
    time: Optional[datetime] = None,
    bbox: Optional[BBox] = None
) -> xr.DataArray:
    """
    Compute probability of exceeding threshold across ensemble.

    Returns: DataArray with dims [time, lat, lon] - no member dim
    Values: 0-100 (percentage of members meeting condition)
    """
    # Get data subset
    data = self.ds[var]
    if time:
        data = data.sel(time=time)
    if bbox:
        data = data.sel(lat=slice(bbox.south, bbox.north),
                       lon=slice(bbox.west, bbox.east))

    # Apply operator
    ops = {'>': np.greater, '<': np.less, ...}
    mask = ops[operator](data, threshold)

    # Compute probability
    return 100 * mask.sum(dim='member') / len(data.member)
```

**Additional statistical methods**:
- `mean()`, `median()`, `std()` - Ensemble statistics
- `percentile(q)` - Percentile across members
- `iqr()` - Interquartile range (spread metric)
- `closest_to_mean(var, region)` - Find representative member

**Advantage over evac**: xarray handles dimension broadcasting automatically

### 5. Lagged Ensemble Support

**Decision**: Support lagged ensembles as first-class feature

**Challenge**: Members have different valid times for same forecast lead time

**Example**:
```
Init 00Z: F00 (00Z), F06 (06Z), F12 (12Z)
Init 06Z: F00 (06Z), F06 (12Z), F12 (18Z)
Want: All forecasts valid at 12Z → mixed lead times
```

**Solution**: Store both `init_time` and `valid_time` as coordinates

```python
# Coordinate structure
coords = {
    'member': ['00Z_ctrl', '00Z_p01', '06Z_ctrl', '06Z_p01'],
    'init_time': ('member', [00Z, 00Z, 06Z, 06Z]),
    'forecast_hour': [0, 6, 12, ...],
    'valid_time': init_time + forecast_hour  # computed coord
}
```

**Salvaged from evac** (ensemble.py:41-43):
> "Enable lagged ensembles - the initialisation data must be loaded from the
> metadata and attached to the member attributes"

**Improvement over evac**: xarray multi-index makes this natural

### 6. Web API for BasinWx

**Decision**: Provide multiple export formats based on use case

**Format 1: GeoJSON** (for map overlays)
```python
def to_geojson(
    self,
    var: str,
    statistic: Literal['mean', 'prob', 'spread'],
    time: datetime,
    threshold: Optional[float] = None
) -> dict:
    """Export gridded forecast as GeoJSON features."""
```

**Format 2: Time series** (for charts)
```python
def to_timeseries_json(
    self,
    var: str,
    location: tuple[float, float],  # (lat, lon)
    members: Literal['all', 'mean', 'spread'] = 'all'
) -> dict:
    """Export point forecast as time series JSON."""
```

**Format 3: Zarr** (for advanced web apps)
```python
def to_zarr(self, path: str):
    """Save as chunked Zarr for TileDB/xarray.js consumption."""
```

**Question**: What format does BasinWx frontend currently expect?

### 7. Type Safety

**Decision**: Full type hints + runtime validation with Pydantic

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field
import datetime

class EnsembleConfig(BaseModel):
    """Configuration for ensemble creation."""
    model: Literal['gefs', 'sref', 'ecmwf', 'custom']
    init_time: datetime.datetime
    members: list[str] | Literal['all', 'control']
    forecast_hours: list[int] = Field(default_factory=lambda: list(range(0, 48, 6)))
```

**Benefits**:
- Catch errors before data download
- Auto-generate JSON schemas for web API
- Better IDE autocomplete

## Research Questions (To Be Answered)

### Q1: Does Herbie support multi-member ensemble loading?
**Status**: NEEDS TESTING

Check if:
```python
# Can we do this?
H = Herbie('2025-10-26', model='gefs', member='all')
ds = H.xarray('TMP:2 m')  # Returns ds with 'member' dimension?
```

If not, we'll need to loop and concatenate:
```python
members = []
for m in range(1, 31):
    H = Herbie('2025-10-26', model='gefs', member=m)
    members.append(H.xarray('TMP:2 m'))
ds = xr.concat(members, dim='member')
```

### Q2: What's the state of existing ensemble tools?

**Tools to evaluate**:
- **xskillscore**: Ensemble verification metrics (CRPS, ranked probability score)
- **climpred**: Initialized forecast verification (may have ensemble utilities)
- **xesmf**: Regridding for mixed-resolution ensembles
- **intake-esm**: Catalog-driven data access (CMIP6 style)

**Question**: Can we leverage these instead of building from scratch?

### Q3: Performance - xarray vs numpy for large ensembles?

**Benchmark needed**:
- 30-member GEFS, 0.5° resolution, 48 forecast hours
- Operations: mean, exceedance probability, percentiles
- Compare: numpy (evac style) vs xarray eager vs xarray+dask

**Hypothesis**: xarray+dask wins for large data, slight overhead for small

### Q4: JSON serialization - best approach?

**Options**:
1. **Custom**: Convert xarray → dict → JSON (full control)
2. **cf-xarray**: `.to_json()` following CF-JSON spec
3. **geojson**: Convert to RFC 7946 GeoJSON via `geojson-xarray`
4. **Zarr + HTTP**: Serve chunked data, client-side assembly

**Trade-off**: Simplicity vs web performance vs standards compliance

## Implementation Phases

### Phase 1: Core Functionality ✓ (in progress)
- [ ] Basic Ensemble class with xarray backend
- [ ] from_gefs() constructor via Herbie
- [ ] Statistical methods (mean, std, percentiles)
- [ ] Exceedance probability (salvaged from evac)
- [ ] Example notebook with real GEFS data

### Phase 2: Advanced Features
- [ ] Lagged ensemble support
- [ ] Mixed-model ensembles (GEFS + SREF)
- [ ] Custom member weighting
- [ ] Closest-to-mean member identification

### Phase 3: Web Integration
- [ ] to_geojson() for map overlays
- [ ] to_timeseries_json() for charts
- [ ] Coordinate with BasinWx team on format requirements
- [ ] Optimize for web performance (compression, downsampling)

### Phase 4: Production Hardening
- [ ] Comprehensive test suite with real data
- [ ] Performance benchmarking
- [ ] Error handling and retries
- [ ] Documentation and examples
- [ ] Migration guide from evac

## Open Questions for User

1. **BasinWx format**: What JSON structure does the frontend expect? GeoJSON? Custom?
2. **Variables**: Which GEFS variables are priority? (T2m, precip, wind, ...)
3. **Resolution**: Should we downsample GEFS (0.5°) for web performance?
4. **Caching**: Where should downloaded GEFS data be cached? (CHPC scratch?)
5. **Update frequency**: How often does BasinWx need new ensemble forecasts?

## References

- **Herbie docs**: https://herbie.readthedocs.io/
- **xarray ensemble examples**: http://xarray.pydata.org/en/stable/examples/ensemble-weather-data.html
- **CF conventions**: http://cfconventions.org/
- **xskillscore**: https://xskillscore.readthedocs.io/
- **evac source**: `/Users/johnlawson/Documents/GitHub/evac/evac/datafiles/ensemble.py`

## Next Steps

1. ✅ Create this design doc
2. Test Herbie multi-member loading (create notebook)
3. Research xskillscore and climpred capabilities
4. Prototype basic Ensemble class
5. Get feedback from BasinWx team on JSON format needs
