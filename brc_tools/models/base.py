"""Base classes for NWP model data access."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Union, Any
import logging

from ..core.exceptions import DataError, ValidationError
from ..core.logging import get_logger

logger = get_logger(__name__)


class BaseModel(ABC):
    """Abstract base class for all NWP model data interfaces.
    
    This class defines the standard interface that all model-specific
    classes should implement.
    """
    
    def __init__(
        self,
        init_time: Union[str, datetime],
        forecast_hour: int = 0,
        domain: str = "conus",
        **kwargs
    ):
        """Initialize the model interface.
        
        Args:
            init_time: Model initialization time
            forecast_hour: Forecast hour (default: 0 for analysis)
            domain: Model domain (default: "conus")
            **kwargs: Additional model-specific parameters
        """
        self.init_time = self._parse_datetime(init_time)
        self.forecast_hour = forecast_hour
        self.domain = domain
        self.metadata = {}
        
        logger.info(
            f"Initialized {self.__class__.__name__} for "
            f"{self.init_time} +{forecast_hour}h"
        )
    
    @staticmethod
    def _parse_datetime(dt_input: Union[str, datetime]) -> datetime:
        """Parse datetime from string or datetime object.
        
        Args:
            dt_input: DateTime as string or datetime object
            
        Returns:
            datetime object
            
        Raises:
            ValidationError: If datetime cannot be parsed
        """
        if isinstance(dt_input, datetime):
            return dt_input
        
        if isinstance(dt_input, str):
            try:
                # Try common formats
                for fmt in ["%Y-%m-%d %H:%M", "%Y%m%d_%H%M", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        return datetime.strptime(dt_input, fmt)
                    except ValueError:
                        continue
                
                # If none work, raise error
                raise ValueError("No matching format found")
                
            except ValueError as e:
                raise ValidationError(f"Cannot parse datetime '{dt_input}': {e}")
        
        raise ValidationError(f"Invalid datetime type: {type(dt_input)}")
    
    @abstractmethod
    def available_variables(self) -> List[str]:
        """Get list of available variables for this model.
        
        Returns:
            List of variable names
        """
        pass
    
    @abstractmethod
    def get_variable(self, variable: str, **kwargs) -> Any:
        """Retrieve a specific variable.
        
        Args:
            variable: Variable name
            **kwargs: Additional parameters for data retrieval
            
        Returns:
            Variable data (typically xarray.Dataset or numpy.ndarray)
        """
        pass
    
    @abstractmethod
    def get_metadata(self) -> Dict:
        """Get metadata for the current model run.
        
        Returns:
            Dictionary containing model metadata
        """
        pass
    
    def valid_time(self) -> datetime:
        """Calculate valid time (init_time + forecast_hour).
        
        Returns:
            Valid time as datetime object
        """
        from datetime import timedelta
        return self.init_time + timedelta(hours=self.forecast_hour)
    
    def is_analysis(self) -> bool:
        """Check if this is an analysis (forecast_hour == 0).
        
        Returns:
            True if this is an analysis
        """
        return self.forecast_hour == 0
    
    def __repr__(self) -> str:
        """String representation of the model instance."""
        return (
            f"{self.__class__.__name__}("
            f"init_time={self.init_time.isoformat()}, "
            f"forecast_hour={self.forecast_hour}, "
            f"domain={self.domain})"
        )