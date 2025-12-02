"""Push outlook markdown files to BasinWx website.

Usage:
    python -m brc_tools.download.push_outlook outlook_20251201_1130.md

    # Or from any directory:
    python push_outlook.py /path/to/outlook_YYYYMMDD_HHMM.md

Requires:
    - DATA_UPLOAD_API_KEY environment variable
    - ~/.config/ubair-website/website_url file with server URL

John Lawson, December 2025
"""
import argparse
import os
import re
import socket
import sys
from pathlib import Path

import requests

from .push_data import load_config


def validate_outlook_filename(filepath: Path) -> bool:
    """Check filename matches expected pattern: outlook_YYYYMMDD_HHMM.md"""
    pattern = r'^outlook_\d{8}_\d{4}\.md$'
    if not re.match(pattern, filepath.name):
        print(f"WARNING: Filename '{filepath.name}' doesn't match expected pattern")
        print(f"         Expected: outlook_YYYYMMDD_HHMM.md")
        return False
    return True


def validate_outlook_content(filepath: Path) -> bool:
    """Basic validation of outlook markdown structure."""
    required_phrases = [
        "RISK OF ELEVATED OZONE",
        "CONFIDENCE",
    ]

    try:
        content = filepath.read_text()
        missing = [phrase for phrase in required_phrases if phrase not in content]
        if missing:
            print(f"WARNING: Outlook may be missing required phrases: {missing}")
            return False
        return True
    except Exception as e:
        print(f"WARNING: Could not validate content: {e}")
        return False


def send_markdown_to_server(server_url: str, fpath: Path, api_key: str) -> bool:
    """Upload markdown file to /api/upload/outlooks endpoint."""
    endpoint = f"{server_url}/api/upload/outlooks"
    hostname = socket.getfqdn()

    headers = {
        'x-api-key': api_key,
        'x-client-hostname': hostname
    }

    # Health check first
    try:
        health_response = requests.get(f"{server_url}/api/health", timeout=10)
        if health_response.status_code != 200:
            print(f"WARNING: Health check returned {health_response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"WARNING: Health check failed: {e}")
        # Continue anyway - health endpoint might not exist

    # Upload file
    print(f"Uploading {fpath.name} to {endpoint}...")
    try:
        with open(fpath, 'rb') as f:
            files = {'file': (fpath.name, f, 'text/markdown')}
            response = requests.post(
                endpoint,
                files=files,
                headers=headers,
                timeout=30,
            )

        if response.status_code == 200:
            print(f"Successfully uploaded {fpath.name}")
            print(f"Outlook should appear at: {server_url}/forecast_outlooks")
            return True
        else:
            print(f"Upload failed ({response.status_code}): {response.text}")
            return False
    except requests.exceptions.Timeout:
        print(f"Upload timed out after 30 seconds")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Upload error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Upload outlook markdown file to BasinWx website",
        epilog="Filename must match pattern: outlook_YYYYMMDD_HHMM.md"
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Markdown file to upload"
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip filename and content validation"
    )
    args = parser.parse_args()

    # Resolve path
    fpath = args.file.resolve()

    if not fpath.exists():
        print(f"ERROR: File not found: {fpath}")
        sys.exit(1)

    if not fpath.suffix == '.md':
        print(f"ERROR: File must be a markdown file (.md)")
        sys.exit(1)

    # Validation
    if not args.skip_validation:
        validate_outlook_filename(fpath)
        validate_outlook_content(fpath)

    # Load config
    try:
        api_key, server_url = load_config()
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: Configuration error: {e}")
        print("\nSetup required:")
        print("  1. Set DATA_UPLOAD_API_KEY environment variable")
        print("  2. Create ~/.config/ubair-website/website_url with server URL")
        sys.exit(1)

    # Upload
    success = send_markdown_to_server(server_url, fpath, api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
