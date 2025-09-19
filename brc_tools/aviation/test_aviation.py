"""Simple test script for aviation data fetching.

Run this first to test your API keys and setup before using the main fetcher.
Great for students/team members to verify everything works.
"""
from brc_tools.aviation.config import load_aviation_config
from brc_tools.aviation.flightaware_client import FlightAwareClient
from brc_tools.aviation.flightradar24_client import FlightRadar24Client


def test_config():
    """Test that API keys are loaded correctly."""
    print("Testing configuration...")
    fa_key, fr24_key, server_url, brc_key = load_aviation_config()
    
    print(f"  FlightAware key: {'✓ Found' if fa_key else '✗ Missing'}")
    print(f"  FlightRadar24 key: {'✓ Found' if fr24_key else '✗ Missing'}")
    print(f"  Server URL: {'✓ Found' if server_url else '✗ Missing'}")
    print(f"  BRC API key: {'✓ Found' if brc_key else '✗ Missing'}")
    
    return fa_key, fr24_key


def test_flightaware(api_key):
    """Test FlightAware API connection."""
    if not api_key:
        print("Skipping FlightAware test - no API key")
        return
        
    print("Testing FlightAware API...")
    client = FlightAwareClient(api_key)
    
    if client.test_connection():
        print("  ✓ FlightAware API connection successful")
        
        # Try getting data for KVEL (Vernal)
        print("  Testing KVEL (Vernal) data fetch...")
        try:
            data = client.get_airport_flights('KVEL')
            arrivals = len(data.get('arrivals', []))
            departures = len(data.get('departures', []))
            print(f"  ✓ KVEL data: {arrivals} arrivals, {departures} departures")
        except Exception as e:
            print(f"  ✗ KVEL data fetch failed: {e}")
    else:
        print("  ✗ FlightAware API connection failed")


def test_flightradar24(api_key):
    """Test FlightRadar24 API connection."""
    print("Testing FlightRadar24 API...")
    client = FlightRadar24Client(api_key)
    
    if client.test_connection():
        print("  ✓ FlightRadar24 API connection successful")
        
        # Try getting data for KVEL
        print("  Testing KVEL (Vernal) data fetch...")
        try:
            data = client.get_airport_flights('KVEL')
            arrivals = len(data.get('arrivals', []))
            departures = len(data.get('departures', []))
            print(f"  ✓ KVEL data: {arrivals} arrivals, {departures} departures")
        except Exception as e:
            print(f"  ✗ KVEL data fetch failed: {e}")
    else:
        print("  ✗ FlightRadar24 API connection failed")
        print("    Note: FR24 API access varies - this may be expected")


def main():
    """Run all tests."""
    print("=== Aviation Setup Test ===")
    print()
    
    # Test 1: Configuration
    fa_key, fr24_key = test_config()
    print()
    
    # Test 2: FlightAware
    test_flightaware(fa_key)
    print()
    
    # Test 3: FlightRadar24  
    test_flightradar24(fr24_key)
    print()
    
    print("=== Test Complete ===")
    print("If you see ✓ marks above, you're ready to run get_aviation_data.py")
    print("If you see ✗ marks, check your .env file and API keys")


if __name__ == "__main__":
    main()