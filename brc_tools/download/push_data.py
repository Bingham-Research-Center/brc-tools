"""Clean and push data to the basinwx website.

John Lawson, July 2025
"""
import socket
import os
import requests

import numpy as np
import pandas as pd

def clean_dataframe_for_json(df):
    # If the dataframe is a Polars dataframe, convert it to Pandas.
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    # Replace NaN with None to become proper JSON null.
    df = df.where(pd.notnull(df), None)

    # Clean string columns (remove unnecessary quotes).
    for col in df.select_dtypes(include=['object']):
        df[col] = df[col].str.strip('"')

    return df

def save_json(df, fpath, orient='records'):
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    # Pandas will map NaN → null automatically
    df.to_json(fpath, orient=orient, indent=2, date_format="iso")
    print(f"Exported {len(df)} records to {fpath}")
    return


def send_json_to_server(server_address, fpath, file_data, API_KEY, max_retries=3):
    """Send JSON file to server with retry logic.

    Args:
        server_address: Base URL of the server
        fpath: Path to JSON file to upload
        file_data: Data type identifier for API endpoint
        API_KEY: Authentication key
        max_retries: Number of retry attempts on failure

    Raises:
        requests.RequestException: If all retry attempts fail
    """
    endpoint = f"{server_address}/api/data/upload/{file_data}"
    hostname = socket.getfqdn()

    headers = {
        'x-api-key': API_KEY,
        'x-client-hostname': hostname
    }

    # Test basic connectivity first
    try:
        health_response = requests.get(f"{server_address}/api/data/health", timeout=10)
        print(f"Health check: {health_response.status_code}")
    except requests.RequestException as e:
        print(f"Warning: Health check failed: {e}")

    # Retry logic for upload
    last_error = None
    for attempt in range(max_retries):
        try:
            with open(fpath, 'rb') as f:
                files = {'file': (os.path.basename(fpath), f, 'application/json')}

                response = requests.post(
                    endpoint,
                    files=files,
                    headers=headers,
                    timeout=30,
                )

            if response.status_code == 200:
                print(f"Successfully uploaded {os.path.basename(fpath)} to {endpoint}")
                return
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"Upload attempt {attempt + 1} failed: {error_msg}")
                last_error = requests.RequestException(error_msg)

        except requests.RequestException as e:
            print(f"Upload attempt {attempt + 1} failed: {e}")
            last_error = e

        if attempt < max_retries - 1:
            import time
            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            print(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    # All retries failed
    raise requests.RequestException(f"Failed to upload after {max_retries} attempts: {last_error}")

def load_config():
    """Load API key and website URL from configuration.

    API key comes from DATA_UPLOAD_API_KEY environment variable.
    Website URL comes from ~/.config/ubair-website/website_url file.

    Returns:
        tuple: (api_key, website_url)

    Raises:
        ValueError: If API key is missing or wrong length
        FileNotFoundError: If website URL file doesn't exist
    """
    api_key = os.environ.get('DATA_UPLOAD_API_KEY')
    if not api_key:
        raise ValueError("DATA_UPLOAD_API_KEY environment variable not set")

    if len(api_key) != 64:
        raise ValueError(f"API key should be 64 characters, got {len(api_key)}")

    config_dir = os.path.join(os.path.expanduser('~'), '.config', 'ubair-website')
    url_file = os.path.join(config_dir, 'website_url')

    if not os.path.exists(url_file):
        raise FileNotFoundError(f"Website URL file not found at {url_file}. Check docs for setup.")

    with open(url_file, 'r') as f:
        website_url = f.read().strip()

    return api_key, website_url