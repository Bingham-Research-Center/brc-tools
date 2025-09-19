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


def send_json_to_server(server_address, fpath, file_data, API_KEY):
    endpoint = f"{server_address}/api/data/upload/{file_data}"
    hostname = socket.getfqdn()

    headers = {
        'x-api-key': API_KEY,
        'x-client-hostname': hostname
    }

    # Test basic connectivity first
    health_response = requests.get(f"{server_address}/api/data/health")
    print(f"Health check: {health_response.status_code}")

    # Prepare upload file
    with open(fpath, 'rb') as f:
        files = {'file': (os.path.basename(fpath), f, 'application/json')}

        # Send the file
        response = requests.post(
            endpoint,
            files=files,
            headers=headers,
            timeout=30,
        )

    if response.status_code == 200:
        print(f"Successfully uploaded {os.path.basename(fpath)} to {endpoint}")
    else:
        print(f"Failed to upload {os.path.basename(fpath)}: {response.text}")

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