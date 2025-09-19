"""Aviation configuration module - handles API keys securely.

Mirrors the weather data config pattern used in push_data.py.
Works across development (uses .env) and production (uses ~/.config).
"""
import os
from pathlib import Path


def load_aviation_config():
    """Load aviation API keys and server config.

    Returns:
        tuple: (flightaware_key, flightradar24_key, server_url, data_upload_key)

    Similar to push_data.load_config() but for aviation APIs.
    Uses DATA_UPLOAD_API_KEY for consistency with weather data uploads.
    """
    # Try .env file first (development)
    env_path = Path.cwd() / '.env'
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)

    # Get API keys from environment
    flightaware_key = os.environ.get('FLIGHTAWARE_API_KEY')
    flightradar24_key = os.environ.get('FLIGHTRADAR24_API_KEY')
    server_url = os.environ.get('BRC_SERVER_URL')
    data_upload_key = os.environ.get('DATA_UPLOAD_API_KEY')
    
    # Fall back to ~/.config for production (like weather data does)
    if not flightaware_key:
        config_dir = os.path.join(os.path.expanduser('~'), '.config', 'brc-tools')
        fa_key_file = os.path.join(config_dir, 'flightaware_api_key')
        if os.path.exists(fa_key_file):
            with open(fa_key_file, 'r') as f:
                flightaware_key = f.read().strip()
    
    if not server_url:
        config_dir = os.path.join(os.path.expanduser('~'), '.config', 'brc-tools')
        url_file = os.path.join(config_dir, 'server_url')
        if os.path.exists(url_file):
            with open(url_file, 'r') as f:
                server_url = f.read().strip()
    
    # Basic validation
    if not flightaware_key:
        print("Warning: No FlightAware API key found")
    if not server_url:
        print("Warning: No server URL found")
    
    return flightaware_key, flightradar24_key, server_url, data_upload_key