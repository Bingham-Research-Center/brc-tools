"""Fetch Basin aviation data and optionally push to website.

Mirrors the pattern from get_map_obs.py for weather data.
Fetches flight arrivals/departures from FlightAware and FlightRadar24,
combines the data, and optionally pushes to the website server.
"""
import os
import json
from datetime import datetime

from brc_tools.aviation.config import load_aviation_config
from brc_tools.aviation.flightaware_client import FlightAwareClient
from brc_tools.aviation.flightradar24_client import FlightRadar24Client
from brc_tools.download.download_funcs import generate_json_fpath
from brc_tools.download.push_data import send_json_to_server
from brc_tools.utils.util_funcs import get_current_datetime


# Basin airports from docs/AVIATION-AIRPORTS.md
BASIN_AIRPORTS = [
    {'code': 'KVEL', 'name': 'Vernal Regional', 'priority': 1},
    {'code': 'KHCR', 'name': 'Heber Valley', 'priority': 2},
    {'code': 'U69', 'name': 'Duchesne Municipal', 'priority': 2},
    {'code': '74V', 'name': 'Roosevelt Municipal', 'priority': 2},
    {'code': '4V0', 'name': 'Rangely', 'priority': 3},
    {'code': 'UT27', 'name': 'CCR Field', 'priority': 3},
    {'code': 'UT62', 'name': 'Wooden Shoe/Peoa', 'priority': 3},
    {'code': 'UT83', 'name': 'Thunder Ridge', 'priority': 3},
]


def fetch_airport_data(fa_client, fr24_client, airport_info):
    """Fetch flight data for one airport from both APIs."""
    airport_code = airport_info['code']
    airport_name = airport_info['name']
    
    print(f"Fetching flights for {airport_name} ({airport_code})...")
    
    # Initialize result
    result = {
        'airport_code': airport_code,
        'airport_name': airport_name,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'arrivals': [],
        'departures': [],
        'planned_arrivals': [],
        'planned_departures': [],
        'sources': []
    }
    
    # Try FlightAware first
    if fa_client:
        try:
            fa_data = fa_client.get_airport_flights(airport_code)
            if fa_data:
                result['arrivals'].extend(fa_data.get('arrivals', []))
                result['departures'].extend(fa_data.get('departures', []))
                result['planned_arrivals'].extend(fa_data.get('planned_arrivals', []))
                result['planned_departures'].extend(fa_data.get('planned_departures', []))
                result['sources'].append('FlightAware')
                print(f"  FlightAware: {len(fa_data.get('arrivals', []))} arrivals, {len(fa_data.get('departures', []))} departures")
        except Exception as e:
            print(f"  FlightAware error: {e}")
    
    # Try FlightRadar24
    if fr24_client:
        try:
            fr24_data = fr24_client.get_airport_flights(airport_code)
            if fr24_data:
                # Simple merge - could be more sophisticated to deduplicate
                result['arrivals'].extend(fr24_data.get('arrivals', []))
                result['departures'].extend(fr24_data.get('departures', []))  
                result['planned_arrivals'].extend(fr24_data.get('planned_arrivals', []))
                result['planned_departures'].extend(fr24_data.get('planned_departures', []))
                result['sources'].append('FlightRadar24')
                print(f"  FlightRadar24: {len(fr24_data.get('arrivals', []))} arrivals, {len(fr24_data.get('departures', []))} departures")
        except Exception as e:
            print(f"  FlightRadar24 error: {e}")
    
    return result


def main():
    """Main function - mirrors get_map_obs.py structure."""
    print("=== Basin Aviation Data Fetcher ===")
    
    # Load configuration (API keys, server URL)
    fa_key, fr24_key, server_url, brc_api_key = load_aviation_config()
    
    # Initialize API clients
    fa_client = FlightAwareClient(fa_key) if fa_key else None
    fr24_client = FlightRadar24Client(fr24_key) if fr24_key else None
    
    if not fa_client and not fr24_client:
        print("ERROR: No API keys found. Please check .env or ~/.config setup")
        return
    
    # Test connections
    if fa_client and not fa_client.test_connection():
        print("Warning: FlightAware API connection failed")
        fa_client = None
    
    if fr24_client and not fr24_client.test_connection():
        print("Warning: FlightRadar24 API connection failed")  
        fr24_client = None
    
    # Fetch data for all airports
    data_root = "../../data"  # Same as weather data
    fetch_datetime = get_current_datetime()
    all_airport_data = {}
    
    for airport_info in BASIN_AIRPORTS:
        airport_data = fetch_airport_data(fa_client, fr24_client, airport_info)
        all_airport_data[airport_info['code']] = airport_data
    
    # Combine into final structure
    combined_data = {
        'timestamp': fetch_datetime.isoformat() + 'Z',
        'airports': all_airport_data,
        'summary': {
            'total_airports': len(BASIN_AIRPORTS),
            'airports_with_data': len([a for a in all_airport_data.values() if a['sources']]),
            'data_sources': list(set([s for a in all_airport_data.values() for s in a['sources']]))
        }
    }
    
    # Save to JSON file (same pattern as weather data)
    aviation_fpath = generate_json_fpath(data_root, prefix="aviation", t=fetch_datetime)
    with open(aviation_fpath, 'w') as f:
        json.dump(combined_data, f, indent=2)
    print(f"Saved aviation data to {aviation_fpath}")
    
    # Push to website server (same as weather data)
    send_to_server = False  # Set to True when ready to test
    if send_to_server and server_url and brc_api_key:
        print(f"Pushing to server {server_url[:20]}...")
        try:
            send_json_to_server(server_url, aviation_fpath, "aviation", brc_api_key)
            print("Successfully pushed aviation data to server")
        except Exception as e:
            print(f"Failed to push to server: {e}")
    
    print(f"Aviation data fetch complete. Processed {len(BASIN_AIRPORTS)} airports.")


if __name__ == "__main__":
    main()