"""Push outlook markdown files to BasinWx website.

Usage:
    python -m brc_tools.download.push_outlook outlook_20251201_1130.md

    # Or from any directory:
    python push_outlook.py /path/to/outlook_YYYYMMDD_HHMM.md

Requires:
    - DATA_UPLOAD_API_KEY environment variable
    - upload URLs from BASINWX_API_URLS or ~/.config/ubair-website/website_urls
      (first URL is the primary; the rest are best-effort mirrors)

John Lawson, December 2025
"""
import argparse
import re
import sys
from pathlib import Path

from .push_data import load_config_urls, send_json_to_all


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
        api_key, server_urls = load_config_urls()
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: Configuration error: {e}")
        print("\nSetup required:")
        print("  1. Set DATA_UPLOAD_API_KEY environment variable")
        print("  2. Set BASINWX_API_URLS or create "
              "~/.config/ubair-website/website_urls with the upload URL(s)")
        sys.exit(1)

    # Upload: primary must succeed; mirrors are best-effort.
    try:
        send_json_to_all(server_urls, str(fpath), "outlooks", api_key)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"Outlook should appear at: {server_urls[0]}/forecast_outlooks")
    sys.exit(0)


if __name__ == "__main__":
    main()
