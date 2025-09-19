# BRC Tools Examples

This directory contains practical usage examples for the BRC Tools package.

## Directory Structure

- **basic/**: Simple getting-started examples
- **nwp/**: Numerical weather prediction data examples  
- **advanced/**: Complex workflows and research applications

## Quick Start

1. **Basic data access**: See `basic/synoptic_data.py`
2. **AQM air quality**: See `nwp/aqm_ozone_example.py`
3. **Data pipeline**: See `advanced/observation_pipeline.py`

## Prerequisites

```bash
# Install BRC Tools
pip install -e .

# Set environment variables
export SYNOPTIC_API_KEY="your_api_key"
export BRC_DATA_ROOT="./data"
```

## Running Examples

Each example is self-contained and includes documentation:

```bash
# Basic examples
python examples/basic/synoptic_data.py

# NWP examples  
python examples/nwp/aqm_ozone_example.py

# Advanced examples
python examples/advanced/multi_model_comparison.py
```

## Contributing Examples

When adding new examples:

1. Include clear docstrings and comments
2. Add error handling for missing data/API keys
3. Include example output or plots
4. Update this README with the new example