#!/usr/bin/env python
"""
Observation Data Pipeline Example
=================================

This example demonstrates the complete data pipeline implementation
using the BRC Tools fetch→process→push architecture.

Example workflow:
1. Fetch recent observations from Synoptic API
2. Process data into BasinWX-compatible format
3. Push to target endpoint (or simulate push)

Author: BRC Tools Team
Date: 2025-01-19
"""

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brc_tools.pipeline.base import Pipeline
from brc_tools.download.download_funcs import (
    download_obs_metadata,
    download_obs_timeseries, 
    compute_start_time
)
from brc_tools.config import config
from brc_tools.core.logging import setup_logging, get_logger
from brc_tools.core.exceptions import APIError, DataError

logger = get_logger(__name__)


class ObservationPipeline(Pipeline):
    """Pipeline for processing weather station observations."""
    
    def __init__(self, stations=None, variables=None, history_hours=1):
        """Initialize the observation pipeline.
        
        Args:
            stations: List of station IDs (uses default if None)
            variables: List of variables to fetch (uses default if None)
            history_hours: Hours of data to fetch (default: 1)
        """
        super().__init__("ObservationPipeline")
        
        self.stations = stations or config.get_station_list("uinta_basin")[:5]  # Subset for example
        self.variables = variables or config.observation_variables[:4]  # Subset for example
        self.history_hours = history_hours
        
        logger.info(f"Initialized pipeline with {len(self.stations)} stations, {len(self.variables)} variables")
    
    def fetch(self) -> Dict[str, Any]:
        """Fetch raw observation data from Synoptic API."""
        
        logger.info("Fetching observation data...")
        
        if not config.synoptic_api_key:
            raise APIError("SYNOPTIC_API_KEY not configured")
        
        # Calculate time range
        end_time = datetime.utcnow()
        start_time = compute_start_time(end_time, self.history_hours)
        
        logger.debug(f"Time range: {start_time} to {end_time}")
        logger.debug(f"Stations: {self.stations}")
        logger.debug(f"Variables: {self.variables}")
        
        try:
            # Fetch metadata
            metadata = download_obs_metadata(self.stations)
            if metadata is None or len(metadata) == 0:
                raise DataError("No station metadata retrieved")
            
            # Fetch time series data
            timeseries = download_obs_timeseries(
                self.stations, start_time, end_time, self.variables
            )
            if timeseries is None or len(timeseries) == 0:
                raise DataError("No time series data retrieved")
            
            raw_data = {
                "metadata": metadata,
                "timeseries": timeseries,
                "fetch_time": end_time,
                "time_range": {"start": start_time, "end": end_time}
            }
            
            logger.info(f"Fetched {len(timeseries)} observations from {len(metadata)} stations")
            return raw_data
            
        except Exception as e:
            raise APIError(f"Failed to fetch observation data: {e}")
    
    def process(self, raw_data: Dict[str, Any]) -> Dict:
        """Process raw data into BasinWX-compatible format."""
        
        logger.info("Processing observation data...")
        
        try:
            metadata = raw_data["metadata"]
            timeseries = raw_data["timeseries"]
            fetch_time = raw_data["fetch_time"]
            
            # Create station lookup
            station_info = {}
            for _, row in metadata.iterrows():
                station_info[row["stid"]] = {
                    "name": row.get("name", "Unknown"),
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                    "elevation": float(row["elevation"])
                }
            
            # Process observations into website format
            observations = []
            
            for _, obs in timeseries.iterrows():
                stid = obs["stid"]
                
                if stid not in station_info:
                    continue
                
                # Create observation record for each variable
                for var in self.variables:
                    if var in obs and not pd.isna(obs[var]):
                        observation = {
                            "stid": stid,
                            "name": station_info[stid]["name"],
                            "latitude": station_info[stid]["latitude"],
                            "longitude": station_info[stid]["longitude"],
                            "elevation": station_info[stid]["elevation"],
                            "date_time": obs["date_time"].isoformat() + "Z",
                            "variable": var,
                            "value": float(obs[var]),
                            "units": self._get_units(var)
                        }
                        observations.append(observation)
            
            # Create processed data structure
            processed_data = {
                "data_type": "map_observations",
                "fetch_time": fetch_time.isoformat() + "Z",
                "valid_time": raw_data["time_range"]["end"].isoformat() + "Z",
                "source": "Synoptic API",
                "processing_version": "1.0",
                "stations": len(station_info),
                "observations": observations
            }
            
            logger.info(f"Processed {len(observations)} observations")
            
            # Validate processed data
            if not self.validate_data(processed_data):
                raise DataError("Processed data failed validation")
            
            return processed_data
            
        except Exception as e:
            raise DataError(f"Failed to process observation data: {e}")
    
    def push(self, processed_data: Dict) -> bool:
        """Push processed data to target endpoint."""
        
        logger.info("Pushing processed data...")
        
        try:
            # In this example, we'll simulate the push by saving to file
            # In production, this would POST to the BasinWX API
            
            output_file = Path(config.data_root) / f"map_obs_{datetime.utcnow().strftime('%Y%m%d_%H%M')}Z.json"
            
            # Ensure output directory exists
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Save processed data
            with open(output_file, 'w') as f:
                json.dump(processed_data, f, indent=2)
            
            logger.info(f"Data saved to: {output_file}")
            
            # Simulate API push (replace with actual API call in production)
            if config.basinwx_url and config.basinwx_api_key:
                logger.info(f"Would push to: {config.basinwx_url}/api/data/upload/map-obs")
                # Here you would make the actual HTTP POST request
            else:
                logger.warning("BasinWX URL/API key not configured, skipping actual push")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to push data: {e}")
            return False
    
    def _get_units(self, variable: str) -> str:
        """Get units for a variable."""
        
        units_map = {
            "air_temp": "C",
            "wind_speed": "m/s", 
            "wind_direction": "degrees",
            "PM_25_concentration": "ug/m3",
            "ozone_concentration": "ppb",
            "sea_level_pressure": "hPa",
            "snow_depth": "mm"
        }
        
        return units_map.get(variable, "unknown")


def main():
    """Main example function."""
    
    # Setup logging
    setup_logging()
    
    print("=" * 60)
    print("BRC Tools - Observation Pipeline Example")
    print("=" * 60)
    
    # Check configuration
    if not config.synoptic_api_key:
        print("ERROR: SYNOPTIC_API_KEY environment variable not set")
        print("Please set your Synoptic API key to run this example")
        return
    
    # Create and configure pipeline
    stations = ["QV4", "UBHSP", "UB7ST"]  # Subset for example
    variables = ["air_temp", "wind_speed", "PM_25_concentration"]  # Subset for example
    
    pipeline = ObservationPipeline(
        stations=stations,
        variables=variables,
        history_hours=2  # Last 2 hours
    )
    
    print("Pipeline Configuration:")
    print(f"  Stations: {stations}")
    print(f"  Variables: {variables}")
    print(f"  History: 2 hours")
    print()
    
    try:
        # Run the complete pipeline
        print("Running observation pipeline...")
        success = pipeline.run(dry_run=False)
        
        if success:
            print("✓ Pipeline completed successfully!")
            
            # Show pipeline status
            status = pipeline.get_status()
            print(f"\nPipeline Status:")
            for key, value in status.items():
                print(f"  {key}: {value}")
            
        else:
            print("✗ Pipeline failed!")
            
    except Exception as e:
        print(f"Pipeline error: {e}")
        logger.exception("Pipeline execution failed")
    
    print("\nExample completed.")


if __name__ == "__main__":
    # Import pandas here to avoid import error if not available
    try:
        import pandas as pd
    except ImportError:
        print("ERROR: pandas is required for this example")
        print("Install with: pip install pandas")
        sys.exit(1)
    
    main()