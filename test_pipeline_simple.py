#!/usr/bin/env python3
"""
Simple pipeline test without heavy dependencies.

Tests the core API functionality without requiring synoptic or other data sources.
Perfect for quick verification that the pipeline setup is working.
"""
import os
import json
import tempfile
import requests
from pathlib import Path


def test_config_exists():
    """Check if basic configuration exists."""
    print("🔍 Testing: Configuration Files")

    api_key = os.environ.get('DATA_UPLOAD_API_KEY')
    if not api_key:
        print("❌ FAILED: DATA_UPLOAD_API_KEY environment variable not set")
        return False

    if len(api_key) != 64:
        print(f"❌ FAILED: API key should be 64 characters, got {len(api_key)}")
        return False

    config_dir = Path.home() / '.config' / 'ubair-website'
    url_file = config_dir / 'website_url'

    if not url_file.exists():
        print(f"❌ FAILED: Website URL file not found at {url_file}")
        return False

    website_url = url_file.read_text().strip()
    if not website_url.startswith(('http://', 'https://')):
        print(f"❌ FAILED: Invalid website URL: {website_url}")
        return False

    print(f"✅ Config loaded: {website_url[:25]}...")
    return True


def test_website_connectivity():
    """Test that the website is reachable."""
    print("🔍 Testing: Website Connectivity")

    try:
        config_dir = Path.home() / '.config' / 'ubair-website'
        url_file = config_dir / 'website_url'
        website_url = url_file.read_text().strip()
    except:
        print("❌ FAILED: Cannot load website URL")
        return False

    health_url = f"{website_url}/api/data/health"

    try:
        response = requests.get(health_url, timeout=10)
        if response.status_code == 200:
            print(f"✅ Website is reachable: {response.status_code}")
            return True
        else:
            print(f"❌ FAILED: Health check returned {response.status_code}")
            return False
    except requests.RequestException as e:
        print(f"❌ FAILED: Cannot reach website: {e}")
        return False


def test_json_creation():
    """Test creating and validating JSON files."""
    print("🔍 Testing: JSON File Creation")

    sample_data = [
        {
            "stid": "TEST01",
            "variable": "air_temp",
            "value": 25.3,
            "date_time": "2025-09-18T18:00:00Z",
            "units": "Celsius"
        },
        {
            "stid": "TEST01",
            "variable": "ozone_concentration",
            "value": 45.2,
            "date_time": "2025-09-18T18:00:00Z",
            "units": "ppb"
        }
    ]

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sample_data, f, indent=2)
            temp_path = f.name

        # Verify we can read it back
        with open(temp_path, 'r') as f:
            loaded_data = json.load(f)

        assert len(loaded_data) == 2
        assert loaded_data[0]['stid'] == 'TEST01'

        os.unlink(temp_path)
        print("✅ JSON file creation works")
        return True

    except Exception as e:
        print(f"❌ FAILED: JSON creation error: {e}")
        return False


def test_api_import():
    """Test that we can import our API functions."""
    print("🔍 Testing: API Function Import")

    try:
        # Import without triggering synoptic dependency
        import sys
        sys.path.insert(0, str(Path(__file__).parent))

        from brc_tools.download.push_data import load_config, send_json_to_server
        print("✅ API functions imported successfully")
        return True

    except ImportError as e:
        print(f"❌ FAILED: Cannot import API functions: {e}")
        return False


def main():
    """Run all basic tests."""
    print("🧪 BRC Tools Simple Pipeline Test")
    print("=" * 50)

    tests = [
        ("Configuration Files", test_config_exists),
        ("Website Connectivity", test_website_connectivity),
        ("JSON File Creation", test_json_creation),
        ("API Function Import", test_api_import),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print()
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if failed == 0:
        print("\n🎉 Basic pipeline tests passed!")
        print("\n💡 Next steps:")
        print("   1. Test with real data: python brc_tools/download/get_map_obs.py")
        print("   2. Enable uploads by setting send_json = True")
        print("   3. Monitor website for incoming data")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Setup required:")
        print("   1. export DATA_UPLOAD_API_KEY='your_64_char_key'")
        print("   2. mkdir -p ~/.config/ubair-website")
        print("   3. echo 'https://basinwx.com' > ~/.config/ubair-website/website_url")

    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)