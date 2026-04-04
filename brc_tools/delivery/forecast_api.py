"""Standard JSON formats for BasinWx forecast API.

Provides unified data structures for:
- Ensemble forecasts (GEFS, SREF)
- Deterministic forecasts (HRRR, GFS)
- Clyfar ozone forecasts
- Meteograms and time series

Author: JRL, 2025-10-26
"""

import datetime
from typing import Optional, Union, Literal
import numpy as np

# Import Ensemble if available (for type hints)
try:
    import sys
    sys.path.insert(0, '/Users/johnlawson/PycharmProjects/brc-tools/in_progress')
    from ensemble.ensemble import Ensemble
    ENSEMBLE_AVAILABLE = True
except ImportError:
    ENSEMBLE_AVAILABLE = False


def create_ensemble_forecast_json(
    ensemble: 'Ensemble',
    location: tuple[float, float],
    variables: list[str],
    include_members: Literal['all', 'mean', 'spread'] = 'spread',
    level: Optional[float] = None
) -> dict:
    """Create standard JSON for ensemble forecast at a point.

    Args:
        ensemble: Ensemble object with forecast data
        location: (lat, lon) point
        variables: Variables to include (must exist in ensemble.ds)
        include_members: How to represent ensemble:
            'all': All individual members
            'mean': Ensemble mean only
            'spread': Mean ± std dev (recommended for web)
        level: Optional vertical level

    Returns:
        Standard JSON dict for BasinWx API

    Example:
        >>> json_data = create_ensemble_forecast_json(
        ...     ensemble=ens,
        ...     location=(40.5, -110.0),
        ...     variables=['t2m', 'wind_speed_10m'],
        ...     include_members='spread'
        ... )
    """
    lat, lon = location

    # Extract init time
    init_time = ensemble.ds.attrs.get('init_time', 'unknown')

    # Build output structure
    output = {
        'metadata': {
            'model': ensemble.ds.attrs.get('model', 'GEFS'),
            'init_time': init_time,
            'location': {'lat': lat, 'lon': lon},
            'generation_time': datetime.datetime.utcnow().isoformat() + 'Z',
            'format_version': '1.0'
        },
        'variables': {}
    }

    # Process each variable
    for var in variables:
        if var not in ensemble.ds:
            print(f"Warning: Variable {var} not found in ensemble")
            continue

        # Use ensemble's JSON export method
        var_json = ensemble.to_timeseries_json(
            var=var,
            location=location,
            members=include_members,
            level=level
        )

        output['variables'][var] = {
            'units': var_json['units'],
            'times': var_json['times'],
            'values': var_json['members']
        }

    return output


def create_meteogram_json(
    ensemble: 'Ensemble',
    location: tuple[float, float],
    location_name: Optional[str] = None
) -> dict:
    """Create meteogram JSON with standard met variables.

    Convenience wrapper for common meteogram variables (temp, wind, precip).

    Args:
        ensemble: Ensemble object
        location: (lat, lon) point
        location_name: Human-readable location name (e.g., "Vernal, UT")

    Returns:
        JSON dict with meteogram data
    """
    # Standard meteogram variables (check what exists in ensemble)
    available_vars = list(ensemble.ds.data_vars)

    # Map common names
    var_mapping = {
        't2m': ['t2m', 'TMP:2 m', 'tmp2m'],
        'wind_speed': ['wind_speed_10m', 'wspd10m'],
        'wind_dir': ['wind_dir_10m', 'wdir10m'],
        'snow_depth': ['SNOD', 'sn depth', 'snowd'],
        'solar': ['DSWRF', 'dswrf', 'sw_down']
    }

    # Find which variables exist
    selected_vars = {}
    for standard_name, possible_names in var_mapping.items():
        for name in possible_names:
            if name in available_vars:
                selected_vars[standard_name] = name
                break

    if not selected_vars:
        raise ValueError("No standard meteogram variables found in ensemble")

    # Create JSON
    json_data = create_ensemble_forecast_json(
        ensemble=ensemble,
        location=location,
        variables=list(selected_vars.values()),
        include_members='spread'
    )

    # Add location name if provided
    if location_name:
        json_data['metadata']['location']['name'] = location_name

    # Add standard variable mapping
    json_data['metadata']['variable_mapping'] = selected_vars

    return json_data


def create_clyfar_json(
    ensemble: 'Ensemble',
    ozone_forecasts: dict,
    location: tuple[float, float] = (40.5, -110.0),
    location_name: str = "Uinta Basin Representative"
) -> dict:
    """Create standard JSON for Clyfar ozone forecasts.

    Combines NWP ensemble data with Clyfar ozone predictions.

    Args:
        ensemble: Ensemble object with NWP data
        ozone_forecasts: Dict with ozone forecast data:
            {
                'ozone_max_daily': [val1, val2, ...],  # ppb
                'category': ['background', 'moderate', ...],
                'possibility': [[π1, π2, π3, π4], ...],  # For each day
                'valid_dates': [date1, date2, ...]
            }
        location: Representative location
        location_name: Name for location

    Returns:
        JSON dict for Clyfar display on BasinWx

    Example:
        >>> clyfar_json = create_clyfar_json(
        ...     ensemble=ens,
        ...     ozone_forecasts={
        ...         'ozone_max_daily': [45, 52, 68, ...],
        ...         'category': ['background', 'moderate', 'elevated', ...],
        ...         'possibility': [[1.0, 0.0, 0.0, 0.0], [0.8, 0.2, 0.0, 0.0], ...],
        ...         'valid_dates': [date(2025, 10, 27), ...]
        ...     }
        ... )
    """
    # Get meteogram data for standard variables
    meteogram_data = create_meteogram_json(
        ensemble=ensemble,
        location=location,
        location_name=location_name
    )

    # Add Clyfar-specific data
    output = {
        'metadata': meteogram_data['metadata'],
        'forecast_type': 'clyfar_ozone',
        'meteogram': meteogram_data['variables'],
        'ozone': {
            'daily_max_ozone': {
                'values': ozone_forecasts['ozone_max_daily'],
                'units': 'ppb',
                'description': 'Predicted daily maximum 8-hour average ozone'
            },
            'categories': {
                'values': ozone_forecasts['category'],
                'thresholds': {
                    'background': '<60 ppb',
                    'moderate': '60-70 ppb',
                    'elevated': '70-80 ppb',
                    'extreme': '>80 ppb'
                }
            },
            'possibility_distribution': {
                'values': ozone_forecasts['possibility'],
                'categories': ['background', 'moderate', 'elevated', 'extreme'],
                'description': 'Fuzzy logic possibility values for each category'
            },
            'valid_dates': [d.isoformat() for d in ozone_forecasts['valid_dates']],
            'exceedance_probabilities': _compute_exceedance_probs(ozone_forecasts)
        },
        'visualization_hints': {
            'default_view': 'simplified',  # For general public
            'available_views': ['simplified', 'standard', 'technical'],
            'color_scale': {
                'background': '#00ff00',  # Green
                'moderate': '#ffff00',    # Yellow
                'elevated': '#ff8800',    # Orange
                'extreme': '#ff0000'      # Red
            }
        }
    }

    return output


def _compute_exceedance_probs(ozone_forecasts: dict) -> dict:
    """Compute exceedance probabilities from possibility distribution.

    Helper function for Clyfar JSON creation.
    """
    thresholds = {
        '60ppb': [],
        '70ppb': [],
        '80ppb': []
    }

    for possibility in ozone_forecasts['possibility']:
        # π(background=0, moderate=1, elevated=2, extreme=3)

        # Probability of exceeding 60 ppb (moderate or higher)
        thresholds['60ppb'].append(sum(possibility[1:]))

        # Probability of exceeding 70 ppb (elevated or higher)
        thresholds['70ppb'].append(sum(possibility[2:]))

        # Probability of exceeding 80 ppb (extreme)
        thresholds['80ppb'].append(possibility[3])

    return thresholds


def create_deterministic_forecast_json(
    model_data: dict,
    location: tuple[float, float],
    model_name: str = "HRRR"
) -> dict:
    """Create JSON for deterministic (non-ensemble) forecasts.

    For models like HRRR, NAM, GFS (deterministic control).

    Args:
        model_data: Dict with model output:
            {
                'init_time': datetime,
                'valid_times': [datetime, ...],
                'variables': {
                    't2m': [val1, val2, ...],
                    'wind_speed': [val1, val2, ...],
                    ...
                }
            }
        location: (lat, lon) point
        model_name: Name of model

    Returns:
        Standard JSON dict
    """
    lat, lon = location

    output = {
        'metadata': {
            'model': model_name,
            'forecast_type': 'deterministic',
            'init_time': model_data['init_time'].isoformat() + 'Z',
            'location': {'lat': lat, 'lon': lon},
            'generation_time': datetime.datetime.utcnow().isoformat() + 'Z',
            'format_version': '1.0'
        },
        'variables': {}
    }

    # Add each variable
    for var_name, values in model_data['variables'].items():
        output['variables'][var_name] = {
            'times': [t.isoformat() + 'Z' for t in model_data['valid_times']],
            'values': values if isinstance(values, list) else values.tolist(),
            'units': _get_units(var_name)
        }

    return output


def _get_units(var_name: str) -> str:
    """Get units for common variables."""
    units_map = {
        't2m': 'K',
        'temp_2m': 'K',
        'wind_speed': 'm/s',
        'wind_speed_10m': 'm/s',
        'wind_dir': 'degrees',
        'wind_dir_10m': 'degrees',
        'snow_depth': 'm',
        'SNOD': 'm',
        'precip': 'mm',
        'solar': 'W/m^2',
        'DSWRF': 'W/m^2',
        'ozone': 'ppb'
    }
    return units_map.get(var_name, 'unknown')


def save_json_with_timestamp(
    json_data: dict,
    output_dir: str,
    prefix: str = "forecast"
) -> str:
    """Save JSON with standardized timestamp filename.

    Args:
        json_data: JSON dict to save
        output_dir: Directory to save to
        prefix: Filename prefix

    Returns:
        Path to saved file
    """
    import json
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M')
    filename = f"{prefix}_{timestamp}Z.json"
    filepath = output_dir / filename

    # Save
    with open(filepath, 'w') as f:
        json.dump(json_data, f, indent=2)

    return str(filepath)


if __name__ == '__main__':
    print("Delivery module - Standard JSON formats for BasinWx")
    print("\nAvailable functions:")
    print("  - create_ensemble_forecast_json()")
    print("  - create_meteogram_json()")
    print("  - create_clyfar_json()")
    print("  - create_deterministic_forecast_json()")
    print("\nSee function docstrings for usage examples")
