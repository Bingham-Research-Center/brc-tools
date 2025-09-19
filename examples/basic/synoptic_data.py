#!/usr/bin/env python
"""
Basic Synoptic Data Example
============================

This example demonstrates basic usage of BRC Tools for accessing
weather station data through the Synoptic API.

Example output:
- Downloads recent observations from Uinta Basin stations
- Shows data structure and basic statistics
- Demonstrates data filtering and processing

Author: BRC Tools Team  
Date: 2025-01-19
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brc_tools.config import config
from brc_tools.download.download_funcs import (
    download_obs_metadata, 
    download_obs_timeseries,
    compute_start_time
)
from brc_tools.core.logging import setup_logging


def main():
    """Main example function."""
    
    # Setup logging
    setup_logging()
    
    print("=" * 60)
    print("BRC Tools - Basic Synoptic Data Example")
    print("=" * 60)
    
    # Check API key
    if not config.synoptic_api_key:
        print("ERROR: SYNOPTIC_API_KEY environment variable not set")
        print("Please set your Synoptic API key:")
        print("  export SYNOPTIC_API_KEY='your_api_key_here'")
        return
    
    # Configuration
    print("Configuration:")
    print(f"  Synoptic API key: {'*' * 20}{config.synoptic_api_key[-4:]}")
    print(f"  Data root: {config.data_root}")
    print()
    
    # Define stations (subset of Uinta Basin stations)
    stations = ["QV4", "UBHSP", "UB7ST", "A3822"]  # Vernal, Horsepool, Seven Sisters, Dinosaur
    variables = ["air_temp", "wind_speed", "wind_direction", "PM_25_concentration"]
    
    # Time range (last 24 hours)
    end_time = datetime.utcnow()
    start_time = compute_start_time(end_time, history_hours=24)
    
    print(f"Data request:")
    print(f"  Stations: {stations}")
    print(f"  Variables: {variables}")
    print(f"  Time range: {start_time} to {end_time}")
    print()
    
    try:
        # Get station metadata
        print("Downloading station metadata...")
        metadata = download_obs_metadata(stations)
        
        if metadata is not None and len(metadata) > 0:
            print(f"Retrieved metadata for {len(metadata)} stations:")
            for _, station in metadata.iterrows():
                print(f"  {station['stid']}: {station.get('name', 'Unknown')} "
                      f"({station['latitude']:.2f}°N, {station['longitude']:.2f}°W, "
                      f"{station['elevation']:.0f}m)")
        else:
            print("No metadata retrieved")
        print()
        
        # Get time series data
        print("Downloading time series data...")
        data = download_obs_timeseries(stations, start_time, end_time, variables)
        
        if data is not None and len(data) > 0:
            print(f"Retrieved {len(data)} observations")
            print(f"Data columns: {list(data.columns)}")
            print()
            
            # Basic data analysis
            analyze_data(data)
            
            # Show sample data
            print("Sample data (first 5 rows):")
            print(data.head())
            print()
            
            # Data quality summary
            data_quality_summary(data)
            
        else:
            print("No time series data retrieved")
            print("This might be due to:")
            print("  - Stations not reporting recently")
            print("  - Variable names not available")
            print("  - API rate limits")
        
    except Exception as e:
        print(f"Error accessing Synoptic data: {e}")
        print("Check your API key and network connection")


def analyze_data(data):
    """Analyze the downloaded data."""
    
    print("Data Analysis:")
    print("=" * 40)
    
    # Time range
    if 'date_time' in data.columns:
        time_range = data['date_time'].max() - data['date_time'].min()
        print(f"Time span: {time_range}")
        print(f"Number of time steps: {data['date_time'].nunique()}")
    
    # Station coverage
    if 'stid' in data.columns:
        stations = data['stid'].unique()
        print(f"Stations with data: {list(stations)}")
    
    # Variable statistics
    numeric_vars = data.select_dtypes(include=['float64', 'int64']).columns
    
    for var in numeric_vars:
        if var in ['latitude', 'longitude', 'elevation']:
            continue  # Skip coordinate variables
            
        values = data[var].dropna()
        if len(values) > 0:
            print(f"{var}:")
            print(f"  Count: {len(values)}")
            print(f"  Range: {values.min():.2f} to {values.max():.2f}")
            print(f"  Mean: {values.mean():.2f}")
            print(f"  Missing: {data[var].isna().sum()}")
    
    print()


def data_quality_summary(data):
    """Summarize data quality."""
    
    print("Data Quality Summary:")
    print("=" * 40)
    
    total_possible = len(data)
    
    # Missing data by variable
    for col in data.columns:
        if col in ['date_time', 'stid']:
            continue
            
        missing = data[col].isna().sum()
        missing_pct = 100 * missing / total_possible
        
        if missing_pct > 0:
            print(f"{col}: {missing_pct:.1f}% missing ({missing}/{total_possible})")
    
    # Data availability by station
    if 'stid' in data.columns:
        print("\nData availability by station:")
        for station in data['stid'].unique():
            station_data = data[data['stid'] == station]
            total_vars = len([col for col in station_data.columns 
                            if col not in ['date_time', 'stid', 'latitude', 'longitude', 'elevation']])
            
            if total_vars > 0:
                available_data = station_data.select_dtypes(include=['float64', 'int64']).count().sum()
                possible_data = len(station_data) * total_vars
                availability = 100 * available_data / possible_data if possible_data > 0 else 0
                
                print(f"  {station}: {availability:.1f}% complete")
    
    print()


if __name__ == "__main__":
    main()