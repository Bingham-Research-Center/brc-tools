#!/usr/bin/env python3
"""
Quick pipeline test - run this to check if your setup works.

This script tests the entire data pipeline without uploading real data.
Perfect for scientists who want to verify their setup before running actual data collection.
"""
import sys
from pathlib import Path

# Add project to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from tests.test_api_pipeline import (
    test_config_loading,
    test_website_health_check,
    test_json_file_creation,
    test_generate_file_paths
)


def main():
    """Run all basic pipeline tests."""
    print("🧪 BRC Tools Pipeline Test")
    print("=" * 50)

    tests = [
        ("Configuration Loading", test_config_loading),
        ("Website Connectivity", test_website_health_check),
        ("JSON File Creation", test_json_file_creation),
        ("File Path Generation", test_generate_file_paths),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n🔍 Testing: {name}")
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if failed == 0:
        print("\n🎉 All tests passed! Your pipeline is ready to use.")
        print("\n💡 Next steps:")
        print("   1. Enable uploads in get_map_obs.py (set send_json = True)")
        print("   2. Run: python brc_tools/download/get_map_obs.py")
        print("   3. Check website for new data")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Check your configuration:")
        print("   1. Set DATA_UPLOAD_API_KEY environment variable")
        print("   2. Create ~/.config/ubair-website/website_url file")
        print("   3. Ensure website is running and accessible")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)