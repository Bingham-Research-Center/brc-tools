"""Simple API pipeline tests for scientists.

These tests verify that our data can flow from CHPC to the website.
Run these before deploying to make sure everything works.
"""
import os
import json
import tempfile
from pathlib import Path

import pytest
import requests

from brc_tools.download.push_data import load_config, send_json_to_server, save_json
from brc_tools.download.download_funcs import generate_json_fpath
from brc_tools.utils.util_funcs import get_current_datetime


def test_config_loading():
    """Test that we can load API configuration."""
    try:
        api_key, website_url = load_config()
        assert len(api_key) == 64, f"API key should be 64 chars, got {len(api_key)}"
        assert website_url.startswith(('http://', 'https://')), f"Invalid URL: {website_url}"
        print(f"✅ Config loaded: {website_url[:20]}...")
    except (ValueError, FileNotFoundError) as e:
        pytest.skip(f"Config not set up: {e}")


def test_website_health_check():
    """Test that the website API is reachable."""
    try:
        api_key, website_url = load_config()
    except:
        pytest.skip("Config not available")

    health_url = f"{website_url}/api/data/health"

    try:
        response = requests.get(health_url, timeout=10)
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print(f"✅ Website is reachable: {response.status_code}")
    except requests.RequestException as e:
        pytest.fail(f"Cannot reach website: {e}")


def test_json_file_creation():
    """Test that we can create properly formatted JSON files."""
    # Create sample data like our weather stations produce
    sample_data = [
        {
            "stid": "TESTST1",
            "variable": "air_temp",
            "value": 25.3,
            "date_time": "2025-09-18T18:00:00Z",
            "units": "Celsius"
        },
        {
            "stid": "TESTST1",
            "variable": "ozone_concentration",
            "value": 45.2,
            "date_time": "2025-09-18T18:00:00Z",
            "units": "ppb"
        }
    ]

    # Create temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_data, f, indent=2)
        temp_path = f.name

    try:
        # Verify file was created and is valid JSON
        with open(temp_path, 'r') as f:
            loaded_data = json.load(f)

        assert len(loaded_data) == 2, f"Expected 2 records, got {len(loaded_data)}"
        assert loaded_data[0]['stid'] == 'TESTST1'
        assert loaded_data[0]['variable'] == 'air_temp'
        print("✅ JSON file creation works")

    finally:
        os.unlink(temp_path)


@pytest.mark.slow
def test_full_api_upload():
    """Test uploading data to the website (slow test, run manually)."""
    try:
        api_key, website_url = load_config()
    except:
        pytest.skip("Config not available")

    # Create test data
    test_data = [
        {
            "stid": "TEST01",
            "variable": "air_temp",
            "value": 20.0,
            "date_time": get_current_datetime().isoformat(),
            "units": "Celsius"
        }
    ]

    # Save to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(test_data, f, indent=2)
        temp_path = f.name

    try:
        # Test upload
        send_json_to_server(website_url, temp_path, "test-data", api_key)
        print("✅ Upload completed (check website logs for success)")

    except Exception as e:
        pytest.fail(f"Upload failed: {e}")
    finally:
        os.unlink(temp_path)


def test_generate_file_paths():
    """Test that our file naming convention works."""
    test_time = get_current_datetime()

    # Test different file types
    map_path = generate_json_fpath("test_data", prefix="map_obs", t=test_time)
    meta_path = generate_json_fpath("test_data", prefix="map_obs_meta", t=test_time)

    assert "map_obs" in map_path
    assert "map_obs_meta" in meta_path
    assert map_path != meta_path
    assert map_path.endswith('.json')

    print(f"✅ File paths: {Path(map_path).name}, {Path(meta_path).name}")


if __name__ == "__main__":
    """Run basic tests manually without pytest."""
    print("🧪 Testing BRC Tools API Pipeline\n")

    # Run each test manually
    tests = [
        test_config_loading,
        test_website_health_check,
        test_json_file_creation,
        test_generate_file_paths
    ]

    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"❌ {test_func.__name__}: {e}")

    print(f"\n💡 To test uploads: pytest -m slow tests/test_api_pipeline.py")