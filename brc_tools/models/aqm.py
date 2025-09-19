"""Air Quality Model (AQM) data access and processing.

This module provides a standardized interface for accessing and processing
AQM data using the Herbie library, with proper error handling and logging.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Tuple

import numpy as np
import xarray as xr

try:
    from herbie import Herbie
except ImportError:
    raise ImportError(
        "Herbie library is required for AQM data access. "
        "Install with: pip install herbie-data"
    )

from .base import BaseModel
from ..core.logging import get_logger
from ..core.exceptions import DataError, ValidationError
from ..core.retry import retry_with_backoff

logger = get_logger(__name__)


class AQMData(BaseModel):
    """Air Quality Model data interface using Herbie.
    
    Provides access to AQM forecast data including ozone and PM2.5 products
    with automatic forecast time handling and data validation.
    """
    
    # Available AQM products
    AVAILABLE_PRODUCTS = {
        "ozone": {
            "ave_8hr_o3": "8-hour average ozone",
            "max_1hr_o3": "1-hour maximum ozone",
            "ave_1hr_o3": "1-hour average ozone",
        },
        "pm25": {
            "ave_24hr_PM_25_concentration": "24-hour average PM2.5",
            "ave_1hr_PM_25_concentration": "1-hour average PM2.5", 
            "max_1hr_PM_25_concentration": "1-hour maximum PM2.5",
        }
    }
    
    # Variable mappings for consistency
    VARIABLE_MAPPING = {
        "pm25": "PM_25_concentration",
        "pmtf": "PM_25_concentration",
        "o3": "ozone_concentration"
    }
    
    def __init__(
        self,
        init_time: Union[str, datetime],
        forecast_hour: int = 8,
        product: str = "ave_8hr_o3",
        domain: str = "CS",
        **kwargs
    ):
        """Initialize AQM data interface.
        
        Args:
            init_time: Model initialization time
            forecast_hour: Forecast hour (default: 8 for 8hr products)
            product: AQM product name (default: "ave_8hr_o3")
            domain: Model domain (CS=CONUS, AK=Alaska, HI=Hawaii)
            **kwargs: Additional parameters
        """
        super().__init__(init_time, forecast_hour, domain, **kwargs)
        
        self.product = product
        self._herbie = None
        self._dataset = None
        
        # Validate product
        self._validate_product()
        
        # Adjust forecast hour for 8-hour products
        if "8hr" in product and forecast_hour < 8:
            logger.warning(
                f"For 8-hour products, forecast_hour should be >= 8. "
                f"Adjusting from {forecast_hour} to 8."
            )
            self.forecast_hour = 8
        
        logger.info(f"Initialized AQM interface for {product} at {init_time}")
    
    def _validate_product(self) -> None:
        """Validate that the product is available."""
        all_products = []
        for category in self.AVAILABLE_PRODUCTS.values():
            all_products.extend(category.keys())
        
        if self.product not in all_products:
            raise ValidationError(
                f"Unknown AQM product: {self.product}. "
                f"Available products: {all_products}"
            )
    
    @property
    def herbie(self) -> Herbie:
        """Get or create Herbie instance."""
        if self._herbie is None:
            self._herbie = self._initialize_herbie()
        return self._herbie
    
    def _initialize_herbie(self) -> Herbie:
        """Initialize Herbie object with AQM parameters."""
        try:
            herbie_params = {
                "date": self.init_time,
                "model": "aqm",
                "product": self.product,
                "domain": self.domain,
                "fxx": self.forecast_hour,
            }
            
            logger.debug(f"Initializing Herbie with: {herbie_params}")
            return Herbie(**herbie_params)
            
        except Exception as e:
            raise DataError(f"Failed to initialize Herbie: {e}")
    
    def available_variables(self) -> List[str]:
        """Get list of available variables for this model.
        
        Returns:
            List of variable names
        """
        try:
            inventory = self.herbie.inventory()
            if inventory.empty:
                logger.warning("No inventory data available")
                return []
            
            return inventory["variable"].unique().tolist()
            
        except Exception as e:
            logger.error(f"Failed to get available variables: {e}")
            return []
    
    def get_available_forecasts(self) -> List[str]:
        """Get all available forecast time periods.
        
        Returns:
            List of forecast time strings
        """
        try:
            inventory = self.herbie.inventory()
            if inventory.empty:
                logger.warning("No inventory data available")
                return []
            
            return inventory["forecast_time"].unique().tolist()
            
        except Exception as e:
            logger.error(f"Failed to get available forecasts: {e}")
            return []
    
    def find_best_forecast(self, target_fxx: Optional[int] = None) -> Optional[str]:
        """Find the best available forecast for the target forecast hour.
        
        Args:
            target_fxx: Target forecast hour (uses self.forecast_hour if None)
            
        Returns:
            Forecast time string or None if not found
        """
        if target_fxx is None:
            target_fxx = self.forecast_hour
        
        try:
            forecasts = self.get_available_forecasts()
            if not forecasts:
                return None
            
            logger.debug(f"Available forecasts: {forecasts}")
            
            # Determine if this is an average product
            is_avg = "max" not in self.product
            
            # Build target forecast strings
            target_formats = []
            
            if "8hr" in self.product:
                # For 8-hour products, center around target_fxx
                start_hr = max(0, target_fxx - 4)
                end_hr = start_hr + 8
                
                if is_avg:
                    target_formats.append(f"{start_hr}-{end_hr} hour ave fcst")
                target_formats.append(f"{start_hr}-{end_hr} hour fcst")
                
            elif "1hr" in self.product:
                if is_avg:
                    target_formats.append(f"{target_fxx-1}-{target_fxx} hour ave fcst")
                target_formats.append(f"{target_fxx} hour fcst")
            else:
                target_formats.append(f"{target_fxx} hour fcst")
            
            # Try each target format
            for fmt in target_formats:
                if fmt in forecasts:
                    logger.debug(f"Using forecast: {fmt}")
                    return fmt
            
            # If no exact match, find closest
            logger.warning(f"No exact forecast match for {target_fxx}h. Using closest available.")
            return forecasts[0] if forecasts else None
            
        except Exception as e:
            logger.error(f"Failed to find best forecast: {e}")
            return None
    
    @retry_with_backoff(max_attempts=3)
    def get_variable(self, variable: Optional[str] = None, **kwargs) -> xr.Dataset:
        """Retrieve AQM variable data.
        
        Args:
            variable: Variable name (if None, gets primary variable for product)
            **kwargs: Additional parameters for data retrieval
            
        Returns:
            xarray Dataset with the requested data
        """
        try:
            if variable is None:
                # Determine primary variable from product name
                if "o3" in self.product:
                    variable = "ozone_concentration"
                elif any(x in self.product for x in ["pm25", "PM_25"]):
                    variable = "PM_25_concentration"
                else:
                    # Get first available variable
                    available = self.available_variables()
                    if available:
                        variable = available[0]
                    else:
                        raise DataError("No variables available")
            
            logger.debug(f"Loading variable: {variable}")
            
            # Load the dataset
            if self._dataset is None:
                self._dataset = self.herbie.xarray()
            
            if variable not in self._dataset.data_vars:
                # Try mapped variable names
                for key, mapped in self.VARIABLE_MAPPING.items():
                    if key in variable.lower():
                        if mapped in self._dataset.data_vars:
                            variable = mapped
                            break
                
                if variable not in self._dataset.data_vars:
                    available = list(self._dataset.data_vars.keys())
                    raise DataError(
                        f"Variable '{variable}' not found. Available: {available}"
                    )
            
            # Extract the variable
            data = self._dataset[variable]
            
            # Add metadata
            data.attrs.update({
                "model": "AQM",
                "product": self.product,
                "init_time": self.init_time.isoformat(),
                "forecast_hour": self.forecast_hour,
                "valid_time": self.valid_time().isoformat(),
            })
            
            logger.info(f"Successfully loaded {variable} data")
            return data.to_dataset()
            
        except Exception as e:
            raise DataError(f"Failed to load variable '{variable}': {e}")
    
    def get_metadata(self) -> Dict:
        """Get metadata for the current AQM run.
        
        Returns:
            Dictionary containing model metadata
        """
        try:
            metadata = {
                "model": "AQM",
                "product": self.product,
                "domain": self.domain,
                "init_time": self.init_time.isoformat(),
                "forecast_hour": self.forecast_hour,
                "valid_time": self.valid_time().isoformat(),
                "source": "NOAA/NWS/NCEP",
                "available_variables": self.available_variables(),
                "available_forecasts": self.get_available_forecasts(),
            }
            
            # Add Herbie metadata if available
            if self._herbie is not None:
                try:
                    herbie_info = {
                        "grib_source": str(self.herbie.grib),
                        "idx_source": str(self.herbie.idx) if hasattr(self.herbie, 'idx') else None,
                    }
                    metadata.update(herbie_info)
                except:
                    pass
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to get metadata: {e}")
            return {"error": str(e)}
    
    def get_utah_subset(self, variable: Optional[str] = None) -> xr.Dataset:
        """Get data subset focused on Utah region.
        
        Args:
            variable: Variable to subset (if None, uses primary variable)
            
        Returns:
            xarray Dataset subset to Utah region
        """
        # Utah bounding box (approximate)
        utah_bounds = {
            "latitude": slice(37.0, 42.0),
            "longitude": slice(-114.5, -109.0)
        }
        
        try:
            data = self.get_variable(variable)
            
            # Try different coordinate names
            lat_names = ["latitude", "lat", "y"]
            lon_names = ["longitude", "lon", "x"]
            
            subset_kwargs = {}
            
            for lat_name in lat_names:
                if lat_name in data.coords:
                    subset_kwargs[lat_name] = utah_bounds["latitude"]
                    break
            
            for lon_name in lon_names:
                if lon_name in data.coords:
                    subset_kwargs[lon_name] = utah_bounds["longitude"]
                    break
            
            if subset_kwargs:
                subset = data.sel(**subset_kwargs)
                logger.info("Successfully created Utah subset")
                return subset
            else:
                logger.warning("Could not identify coordinate names for subsetting")
                return data
                
        except Exception as e:
            logger.error(f"Failed to create Utah subset: {e}")
            return self.get_variable(variable)
    
    @classmethod
    def get_product_info(cls) -> Dict:
        """Get information about available AQM products.
        
        Returns:
            Dictionary with product categories and descriptions
        """
        return cls.AVAILABLE_PRODUCTS
    
    @classmethod
    def list_products(cls, category: Optional[str] = None) -> List[str]:
        """List available AQM products.
        
        Args:
            category: Product category ("ozone" or "pm25", None for all)
            
        Returns:
            List of product names
        """
        if category:
            if category in cls.AVAILABLE_PRODUCTS:
                return list(cls.AVAILABLE_PRODUCTS[category].keys())
            else:
                logger.warning(f"Unknown category: {category}")
                return []
        else:
            products = []
            for cat_products in cls.AVAILABLE_PRODUCTS.values():
                products.extend(cat_products.keys())
            return products


# Convenience functions for backward compatibility
def initialize_herbie(init_date, product, domain="CS", fxx=8):
    """Initialize a Herbie object with AQM parameters.
    
    DEPRECATED: Use AQMData class instead.
    """
    logger.warning("initialize_herbie is deprecated. Use AQMData class instead.")
    
    aqm = AQMData(init_date, fxx, product, domain)
    return aqm.herbie


def load_aqm_dataset(H):
    """Load AQM dataset using Herbie object.
    
    DEPRECATED: Use AQMData.get_variable() instead.
    """
    logger.warning("load_aqm_dataset is deprecated. Use AQMData.get_variable() instead.")
    
    try:
        return H.xarray()
    except Exception as e:
        raise DataError(f"Failed to load dataset: {e}")