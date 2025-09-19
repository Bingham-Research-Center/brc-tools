"""Centralized configuration settings for BRC Tools."""

import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from ..core.exceptions import ConfigurationError


@dataclass
class Config:
    """Main configuration class for BRC Tools.
    
    This class centralizes all configuration settings and provides
    sensible defaults while allowing environment variable overrides.
    """
    
    # API Keys and Authentication
    synoptic_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv('SYNOPTIC_API_KEY')
    )
    flightaware_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv('FLIGHTAWARE_API_KEY')
    )
    basinwx_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv('BRC_API_KEY')
    )
    
    # Server URLs
    basinwx_url: str = field(
        default_factory=lambda: os.getenv('BRC_SERVER_URL', 'https://www.basinwx.com')
    )
    synoptic_base_url: str = "https://api.synopticdata.com/v2"
    flightaware_base_url: str = "https://aeroapi.flightaware.com/aeroapi"
    
    # Data Paths
    data_root: Path = field(
        default_factory=lambda: Path(os.getenv('BRC_DATA_ROOT', './data'))
    )
    cache_dir: Path = field(
        default_factory=lambda: Path(os.getenv('BRC_CACHE_DIR', './cache'))
    )
    tmp_dir: Path = field(
        default_factory=lambda: Path(os.getenv('TMP_DIR', '/tmp'))
    )
    
    # Pipeline Settings
    retry_attempts: int = field(
        default_factory=lambda: int(os.getenv('BRC_RETRY_ATTEMPTS', '3'))
    )
    retry_delay: float = field(
        default_factory=lambda: float(os.getenv('BRC_RETRY_DELAY', '2.0'))
    )
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv('BRC_REQUEST_TIMEOUT', '30'))
    )
    
    # Logging Configuration
    log_level: str = field(
        default_factory=lambda: os.getenv('BRC_LOG_LEVEL', 'INFO')
    )
    log_file: Optional[Path] = field(
        default_factory=lambda: Path(os.getenv('BRC_LOG_FILE')) if os.getenv('BRC_LOG_FILE') else None
    )
    
    # Default Station Lists (from lookups.py)
    uinta_basin_stations: List[str] = field(default_factory=lambda: [
        "A3822",   # Dinosaur National Monument
        "A1633",   # Red Wash
        "UB7ST",   # Seven Sisters
        "UBHSP",   # Horsepool
        "A1622",   # Ouray
        "QV4",     # Vernal
        "A1386",   # Whiterocks
        "QRS",     # Roosevelt OG
        "UBRVT",   # Roosevelt USU
        "A1388",   # Myton
        "UBCSP",   # Castle Peak
        "COOPDINU1",  # Dinosaur NM
        "COOPALMU1",  # Altamont
        "COOPDSNU1",  # Duchesne
    ])
    
    # Variable Mappings
    observation_variables: List[str] = field(default_factory=lambda: [
        "wind_speed",
        "wind_direction", 
        "air_temp",
        "PM_25_concentration",
        "ozone_concentration",
        "sea_level_pressure",
        "snow_depth"
    ])
    
    # Model Configuration
    model_domains: Dict[str, str] = field(default_factory=lambda: {
        "conus": "CS",
        "alaska": "AK", 
        "hawaii": "HI"
    })
    
    # Data Quality Settings
    max_missing_stations: int = 3  # Maximum missing stations before warning
    data_staleness_hours: int = 6  # Hours before data considered stale
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        self.validate()
        self._setup_directories()
    
    def validate(self) -> None:
        """Validate configuration settings.
        
        Raises:
            ConfigurationError: If required settings are missing or invalid
        """
        # Check required API keys
        if not self.synoptic_api_key:
            raise ConfigurationError(
                "SYNOPTIC_API_KEY environment variable is required"
            )
        
        # Validate retry settings
        if self.retry_attempts < 1:
            raise ConfigurationError("retry_attempts must be >= 1")
        
        if self.retry_delay < 0:
            raise ConfigurationError("retry_delay must be >= 0")
        
        # Validate URLs
        if not self.basinwx_url.startswith(('http://', 'https://')):
            raise ConfigurationError("basinwx_url must be a valid URL")
    
    def _setup_directories(self) -> None:
        """Create required directories if they don't exist."""
        for directory in [self.data_root, self.cache_dir]:
            directory.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def from_env_file(cls, env_file: str = ".env") -> "Config":
        """Load configuration from environment file.
        
        Args:
            env_file: Path to environment file
            
        Returns:
            Config instance
        """
        env_path = Path(env_file)
        
        if env_path.exists():
            # Load environment variables from file
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path)
            except ImportError:
                # python-dotenv not available, skip
                pass
        
        return cls()
    
    def get_station_list(self, network: str = "uinta_basin") -> List[str]:
        """Get station list for specified network.
        
        Args:
            network: Network name (default: "uinta_basin")
            
        Returns:
            List of station IDs
        """
        if network == "uinta_basin":
            return self.uinta_basin_stations
        else:
            raise ConfigurationError(f"Unknown network: {network}")
    
    def get_api_headers(self, api: str) -> Dict[str, str]:
        """Get API headers for specified service.
        
        Args:
            api: API service name ("synoptic", "flightaware", "basinwx")
            
        Returns:
            Dictionary of headers
        """
        headers = {"User-Agent": "BRC-Tools/1.0"}
        
        if api == "synoptic":
            headers["token"] = self.synoptic_api_key
        elif api == "flightaware":
            headers["x-apikey"] = self.flightaware_api_key
        elif api == "basinwx":
            if self.basinwx_api_key:
                headers["Authorization"] = f"Bearer {self.basinwx_api_key}"
        
        return headers


# Global configuration instance
config = Config.from_env_file()