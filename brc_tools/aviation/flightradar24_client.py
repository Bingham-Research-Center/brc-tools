"""FlightRadar24 API client for Basin aviation data.

Simple wrapper for FlightRadar24 API. Note: This is a basic implementation
that may need adjustment based on actual FR24 API access and endpoints.
FR24 API documentation varies and some endpoints require special access.
"""
import requests
from datetime import datetime, timedelta


class FlightRadar24Client:
    """Simple FlightRadar24 API client for airport activity."""
    
    def __init__(self, api_key=None):
        self.api_key = api_key
        # Note: FR24 public API endpoints may not require auth
        # Commercial API would use different base URL and auth
        self.base_url = "https://api.flightradar24.com/common/v1"
        
        self.headers = {
            'Accept': 'application/json',
            'User-Agent': 'BRC-Tools/1.0'
        }
        if api_key:
            self.headers['Authorization'] = f'Bearer {api_key}'
    
    def get_airport_flights(self, airport_code, hours_back=4, hours_forward=4):
        """Get recent and upcoming flights for an airport.
        
        Args:
            airport_code: ICAO code like 'KVEL' or IATA like 'VEL'
            hours_back: How many hours back to fetch
            hours_forward: How many hours forward for planned flights
            
        Returns:
            dict: Contains 'arrivals', 'departures', 'planned_arrivals', 'planned_departures'
            
        Note: This is a placeholder implementation. FR24 API access varies.
        """
        now = datetime.utcnow()
        
        result = {
            'airport_code': airport_code,
            'timestamp': now.isoformat() + 'Z',
            'arrivals': [],
            'departures': [],
            'planned_arrivals': [],
            'planned_departures': []
        }
        
        try:
            # Try airport info endpoint first
            airport_url = f"{self.base_url}/airport/{airport_code}"
            resp = requests.get(airport_url, headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                airport_data = resp.json()
                
                # Extract flight data if available
                # Note: Actual FR24 API structure may differ
                if 'flights' in airport_data:
                    flights = airport_data['flights']
                    result['arrivals'] = self._extract_arrivals(flights.get('arrivals', []))
                    result['departures'] = self._extract_departures(flights.get('departures', []))
                
            else:
                print(f"FR24 API returned status {resp.status_code} for {airport_code}")
                
        except Exception as e:
            print(f"FlightRadar24 API error for {airport_code}: {e}")
            # Return empty result rather than failing completely
            
        return result
    
    def _extract_arrivals(self, arrivals_data):
        """Extract and simplify arrivals data."""
        simplified_arrivals = []
        for flight in arrivals_data:
            simplified = {
                'ident': flight.get('flight', flight.get('callsign')),
                'aircraft_type': flight.get('aircraft', {}).get('model'),
                'origin': flight.get('origin', {}).get('code'),
                'scheduled_time': flight.get('scheduled'),
                'actual_time': flight.get('actual'),
                'estimated_time': flight.get('estimated')
            }
            simplified_arrivals.append(simplified)
        return simplified_arrivals
    
    def _extract_departures(self, departures_data):
        """Extract and simplify departures data."""
        simplified_departures = []
        for flight in departures_data:
            simplified = {
                'ident': flight.get('flight', flight.get('callsign')),
                'aircraft_type': flight.get('aircraft', {}).get('model'),
                'destination': flight.get('destination', {}).get('code'),
                'scheduled_time': flight.get('scheduled'),
                'actual_time': flight.get('actual'),
                'estimated_time': flight.get('estimated')
            }
            simplified_departures.append(simplified)
        return simplified_departures
    
    def test_connection(self):
        """Test API connectivity."""
        try:
            # Test with a major airport
            resp = requests.get(f"{self.base_url}/airport/KORD", headers=self.headers, timeout=10)
            return resp.status_code in [200, 401, 403]  # 401/403 = auth issue but API is reachable
        except:
            return False
    
    def get_live_flights_in_bounds(self, north, south, east, west):
        """Get live flights in a geographic bounding box.
        
        This is often more reliable than airport-specific endpoints for FR24.
        Useful for getting flights near Uinta Basin airports.
        """
        try:
            bounds_url = f"{self.base_url}/flights/bounds/{north},{south},{east},{west}"
            resp = requests.get(bounds_url, headers=self.headers, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"FR24 bounds API returned status {resp.status_code}")
                return {}
                
        except Exception as e:
            print(f"FR24 bounds API error: {e}")
            return {}