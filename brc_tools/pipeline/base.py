"""Base pipeline class implementing fetch→process→push pattern."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging
from datetime import datetime

from ..core.exceptions import BRCError, APIError, DataError
from ..core.logging import get_logger
from ..core.retry import retry_with_backoff

logger = get_logger(__name__)


class Pipeline(ABC):
    """Abstract base class for data pipelines.
    
    Implements the standard fetch→process→push pattern used throughout
    the BRC Tools package.
    """
    
    def __init__(self, name: str, config: Optional[Dict] = None):
        """Initialize the pipeline.
        
        Args:
            name: Pipeline name for logging
            config: Configuration dictionary
        """
        self.name = name
        self.config = config or {}
        self.last_run = None
        self.last_success = None
        self.error_count = 0
        
        logger.info(f"Initialized pipeline: {self.name}")
    
    @abstractmethod
    def fetch(self) -> Any:
        """Fetch raw data from source.
        
        This method should implement the data acquisition logic
        (API calls, file reads, etc.)
        
        Returns:
            Raw data in source format
            
        Raises:
            APIError: If data source is unavailable
            DataError: If fetched data is invalid
        """
        pass
    
    @abstractmethod
    def process(self, raw_data: Any) -> Dict:
        """Process raw data into standardized format.
        
        This method should transform the raw data into the format
        expected by the target system (usually JSON for BasinWX).
        
        Args:
            raw_data: Raw data from fetch() method
            
        Returns:
            Processed data as dictionary
            
        Raises:
            DataError: If processing fails
        """
        pass
    
    @abstractmethod
    def push(self, processed_data: Dict) -> bool:
        """Push processed data to target system.
        
        This method should send the processed data to its destination
        (typically the BasinWX API).
        
        Args:
            processed_data: Processed data from process() method
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            APIError: If target system is unavailable
        """
        pass
    
    @retry_with_backoff(max_attempts=3)
    def run(self, dry_run: bool = False) -> bool:
        """Execute the complete pipeline.
        
        Args:
            dry_run: If True, don't actually push data
            
        Returns:
            True if successful, False otherwise
        """
        self.last_run = datetime.utcnow()
        
        try:
            logger.info(f"Starting pipeline run: {self.name}")
            
            # Fetch phase
            logger.debug(f"[{self.name}] Fetching data...")
            raw_data = self.fetch()
            
            if raw_data is None:
                logger.warning(f"[{self.name}] No data fetched")
                return False
            
            # Process phase
            logger.debug(f"[{self.name}] Processing data...")
            processed_data = self.process(raw_data)
            
            if not processed_data:
                logger.warning(f"[{self.name}] No data after processing")
                return False
            
            # Push phase
            if dry_run:
                logger.info(f"[{self.name}] Dry run - skipping push phase")
                success = True
            else:
                logger.debug(f"[{self.name}] Pushing data...")
                success = self.push(processed_data)
            
            if success:
                self.last_success = self.last_run
                self.error_count = 0
                logger.info(f"[{self.name}] Pipeline completed successfully")
            else:
                self.error_count += 1
                logger.error(f"[{self.name}] Pipeline failed at push stage")
            
            return success
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"[{self.name}] Pipeline failed with error: {e}")
            raise
    
    def validate_data(self, data: Any, schema: Optional[Dict] = None) -> bool:
        """Validate data against expected format.
        
        Args:
            data: Data to validate
            schema: Optional validation schema
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # Basic validation - ensure data exists
            if data is None:
                return False
            
            # If schema provided, use it for validation
            if schema:
                # TODO: Implement schema validation
                logger.debug("Schema validation not yet implemented")
            
            return True
            
        except Exception as e:
            logger.error(f"Data validation failed: {e}")
            return False
    
    def get_status(self) -> Dict:
        """Get pipeline status information.
        
        Returns:
            Dictionary with status information
        """
        return {
            "name": self.name,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "error_count": self.error_count,
            "status": "healthy" if self.error_count == 0 else "degraded"
        }
    
    def __repr__(self) -> str:
        """String representation of the pipeline."""
        return f"{self.__class__.__name__}(name='{self.name}')"