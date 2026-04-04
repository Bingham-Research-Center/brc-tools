# Modern Ensemble Class

**Status**: Experimental - needs practical testing

Modernized ensemble forecast management class salvaged from `evac` (2018) with xarray, Herbie, and best practices from 2025.

## Quick Start

```python
import datetime
from ensemble import Ensemble

# Load GEFS ensemble
ens = Ensemble.from_gefs(
    init_time=datetime.datetime(2025, 10, 26, 0),
    members=range(1, 11),  # First 10 perturbations
    forecast_hours=range(0, 48, 6),
    variables=['TMP:2 m', 'APCP']
)

# Compute probability of freezing temps
prob_freeze = ens.get_exceedance_prob(
    var='t2m',
    threshold=273.15,  # 0°C in Kelvin
    operator='<'
)

# Export for web visualization
json_data = ens.to_timeseries_json(
    var='t2m',
    location=(40.5, -110.0),  # Uinta Basin
    members='spread'  # Mean ± std dev
)
```

## Features

### Salvaged from evac (improved)
- ✅ Lagged ensemble support (different init times)
- ✅ Exceedance probability calculations
- ✅ Member iteration and statistics
- ✅ Flexible member configuration

### Modern improvements
- ✅ xarray.Dataset backend (labeled dimensions, CF conventions)
- ✅ Lazy loading with dask (handles large ensembles)
- ✅ Herbie integration (modern NOAA data access)
- ✅ Type hints and validation
- ✅ Web API (JSON serialization for BasinWx)

## Files

- `DESIGN.md` - Architecture decisions and research
- `ensemble.py` - Main Ensemble class
- `examples/basic_usage.ipynb` - Getting started tutorial
- `examples/test_herbie.ipynb` - Test Herbie multi-member loading (TODO)
- `examples/lagged_ensemble.ipynb` - Advanced lagged ensemble (TODO)

## Installation

```bash
cd /Users/johnlawson/PycharmProjects/brc-tools
pip install -e .  # Install brc_tools

# Additional dependencies for ensemble work
pip install herbie-data xarray dask netCDF4
```

## Testing Needed

Before moving to production:

1. **Herbie multi-member loading**: Does Herbie have built-in support for loading all GEFS members at once?
2. **Performance benchmarking**: Compare xarray+dask vs numpy for typical BasinWx use cases
3. **Web format requirements**: Coordinate with BasinWx frontend on JSON structure
4. **Real data validation**: Test with recent GEFS forecasts, verify calculations against known values

## Next Steps

See `DESIGN.md` Section "Research Questions" for open items.

Key priorities:
1. Create `examples/test_herbie.ipynb` to explore Herbie's ensemble capabilities
2. Test with real GEFS data (recent case)
3. Benchmark performance vs evac approach
4. Get feedback on JSON format from BasinWx team

## References

- **evac source**: `/Users/johnlawson/Documents/GitHub/evac/evac/datafiles/ensemble.py`
- **Herbie docs**: https://herbie.readthedocs.io/
- **xarray tutorial**: http://xarray.pydata.org/en/stable/tutorials-and-videos.html
