"""FlightAware API client for Basin aviation data.

Simple wrapper around FlightAware AeroAPI following the same pattern
as Synoptic weather data client. Focuses on airport arrivals/departures.
"""
import requests
from datetime import datetime, timedelta
import polars as pl


class FlightAwareClient:
    """Simple FlightAware API client for airport activity."""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://aeroapi.flightaware.com/aeroapi"
        self.headers = {
            'x-apikey': api_key,
            'Accept': 'application/json; charset=UTF-8'
        }
    
    def get_airport_flights(self, airport_code, hours_back=4, hours_forward=4):
        """Get recent and upcoming flights for an airport.
        
        Args:
            airport_code: ICAO code like 'KVEL' or FAA LID like 'U69'
            hours_back: How many hours back to fetch arrivals/departures
            hours_forward: How many hours forward for planned flights
            
        Returns:
            dict: Contains 'arrivals', 'departures', 'planned_arrivals', 'planned_departures'
        """
        now = datetime.utcnow()
        start_time = now - timedelta(hours=hours_back)
        end_time = now + timedelta(hours=hours_forward)
        
        # Convert to FlightAware format (ISO with Z suffix)
        start_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = end_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        result = {
            'airport_code': airport_code,
            'timestamp': now.isoformat() + 'Z',
            'arrivals': [],
            'departures': [],
            'planned_arrivals': [],
            'planned_departures': []
        }
        
        try:
            # Get arrivals (recent + planned)
            arrivals_url = f"{self.base_url}/airports/{airport_code}/flights/arrivals"
            params = {'start': start_str, 'end': end_str, 'max_pages': 2}
            
            arrivals_resp = requests.get(arrivals_url, headers=self.headers, params=params)
            if arrivals_resp.status_code == 200:
                arrivals_data = arrivals_resp.json()
                result['arrivals'], result['planned_arrivals'] = self._split_flights_by_status(
                    arrivals_data.get('arrivals', []), 'arrival'
                )
            
            # Get departures (recent + planned)  
            departures_url = f"{self.base_url}/airports/{airport_code}/flights/departures"
            departures_resp = requests.get(departures_url, headers=self.headers, params=params)
            if departures_resp.status_code == 200:
                departures_data = departures_resp.json()
                result['departures'], result['planned_departures'] = self._split_flights_by_status(
                    departures_data.get('departures', []), 'departure'
                )
                
        except Exception as e:
            print(f"FlightAware API error for {airport_code}: {e}")
            
        return result
    
    def _split_flights_by_status(self, flights, flight_type):
        """Split flights into completed vs planned based on actual times."""
        completed = []
        planned = []
        
        for flight in flights:
            # Simplify flight data - keep only essential fields
            simplified = {
                'ident': flight.get('ident'),
                'aircraft_type': flight.get('aircraft_type'),
                'origin': flight.get('origin', {}).get('code'),
                'destination': flight.get('destination', {}).get('code'),
            }
            
            if flight_type == 'arrival':
                scheduled_time = flight.get('scheduled_in')
                actual_time = flight.get('actual_in')
                estimated_time = flight.get('estimated_in')
            else:  # departure
                scheduled_time = flight.get('scheduled_out') 
                actual_time = flight.get('actual_out')
                estimated_time = flight.get('estimated_out')
            
            simplified['scheduled_time'] = scheduled_time
            simplified['actual_time'] = actual_time
            simplified['estimated_time'] = estimated_time
            
            # If actual time exists, it's completed
            if actual_time:
                completed.append(simplified)
            else:
                planned.append(simplified)
                
        return completed, planned
    
    def test_connection(self):
        """Test API connectivity - useful for debugging."""
        test_url = f"{self.base_url}/airports/KORD"  # O'Hare for testing
        try:
            resp = requests.get(test_url, headers=self.headers, timeout=10)
            return resp.status_code == 200
        except:
            return False