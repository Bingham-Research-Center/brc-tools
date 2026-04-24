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


def _post_json_to_url(server_address, fpath, file_data, api_key, *, role="PRIMARY"):
    """Upload one JSON file to one server. Return True on HTTP 200."""
    endpoint = f"{server_address}/api/upload/{file_data}"
    hostname = socket.getfqdn()
    headers = {'x-api-key': api_key, 'x-client-hostname': hostname}
    prefix = f"[{role} {server_address}]"

    try:
        health_response = requests.get(f"{server_address}/api/health", timeout=10)
        print(f"{prefix} health {health_response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"{prefix} health check failed: {e}")
        return False

    print(f"{prefix} uploading {os.path.basename(fpath)} to {endpoint}")
    try:
        with open(fpath, 'rb') as f:
            files = {'file': (os.path.basename(fpath), f, 'application/json')}
            response = requests.post(endpoint, files=files, headers=headers, timeout=30)
        if response.status_code == 200:
            print(f"{prefix} ✅ uploaded {os.path.basename(fpath)}")
            return True
        print(f"{prefix} ❌ upload failed ({response.status_code}): {response.text}")
        return False
    except requests.exceptions.Timeout:
        print(f"{prefix} ❌ upload timed out after 30s")
        return False
    except requests.exceptions.RequestException as e:
        print(f"{prefix} ❌ upload error: {e}")
        return False


def send_json_to_server(server_address, fpath, file_data, API_KEY):
    """Upload JSON to a single server. Preserved for the clyfar import contract."""
    _post_json_to_url(server_address, fpath, file_data, API_KEY, role="PRIMARY")


def send_json_to_all(server_addresses, fpath, file_data, api_key):
    """Fan-out upload. First URL is primary (failure raises), rest are mirrors
    (failure logged, non-fatal). Returns a {url: ok} mapping.
    """
    if not server_addresses:
        raise ValueError("server_addresses is empty")

    results = {}
    for idx, url in enumerate(server_addresses):
        role = "PRIMARY" if idx == 0 else "MIRROR"
        results[url] = _post_json_to_url(url, fpath, file_data, api_key, role=role)

    primary = server_addresses[0]
    mirror_failures = [u for u in server_addresses[1:] if not results[u]]
    if mirror_failures:
        print(f"WARNING mirror uploads failed: {', '.join(mirror_failures)}")
    if not results[primary]:
        raise RuntimeError(f"Primary upload to {primary} failed for {fpath}")
    return results


def _read_url_file(path):
    with open(path, 'r') as f:
        raw = f.read()
    return [u.strip().rstrip('/') for u in raw.replace('\n', ',').split(',') if u.strip()]


def load_config():
    """Single-URL config loader. Preserved for the clyfar import contract.
    Returns (api_key, primary_url). New brc-tools code should use load_config_urls().
    """
    api_key, urls = load_config_urls()
    return api_key, urls[0]


def load_config_urls():
    """Load API key and the full list of upload destinations.

    Resolution order for URLs:
      1. BASINWX_API_URLS env var (comma-separated; first = primary, rest = mirrors).
      2. ~/.config/ubair-website/website_urls (comma- or newline-separated).
      3. ~/.config/ubair-website/website_url (legacy single URL → one-element list).
    API key is always read from DATA_UPLOAD_API_KEY.
    """
    api_key = os.environ.get('DATA_UPLOAD_API_KEY')
    if not api_key:
        raise ValueError("DATA_UPLOAD_API_KEY environment variable not set")
    if len(api_key) != 32:
        raise ValueError(f"API key should be 32 characters (hex), got {len(api_key)}")

    env_urls = os.environ.get('BASINWX_API_URLS', '').strip()
    if env_urls:
        urls = [u.strip().rstrip('/') for u in env_urls.split(',') if u.strip()]
        if urls:
            return api_key, urls

    config_dir = os.path.join(os.path.expanduser('~'), '.config', 'ubair-website')
    plural = os.path.join(config_dir, 'website_urls')
    if os.path.exists(plural):
        urls = _read_url_file(plural)
        if urls:
            return api_key, urls

    singular = os.path.join(config_dir, 'website_url')
    if os.path.exists(singular):
        urls = _read_url_file(singular)
        if urls:
            return api_key, urls

    raise FileNotFoundError(
        "No upload URL found. Set BASINWX_API_URLS or create "
        "~/.config/ubair-website/website_urls (see docs for setup)."
    )