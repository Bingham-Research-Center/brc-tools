"""Thin REST wrapper for FlightAware AeroAPI v4."""

import requests

from brc_tools.api._auth import load_api_key


class FlightAwareClient:
    """AeroAPI client. Auth via `FLIGHTAWARE_API_KEY`."""

    BASE_URL = "https://aeroapi.flightaware.com/aeroapi"

    def __init__(self, *, timeout: float = 10.0):
        self.api_key = load_api_key("FLIGHTAWARE_API_KEY")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["x-apikey"] = self.api_key

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_flight(self, flight_id: str) -> dict:
        """Fetch flight details by FA flight ID or ident."""
        return self._get(f"/flights/{flight_id}")

    def get_airport_arrivals(self, icao: str, *, max_pages: int = 1) -> dict:
        """Fetch recent arrivals at an airport (ICAO code, e.g. `KSLC`)."""
        return self._get(f"/airports/{icao}/flights/arrivals",
                         params={"max_pages": max_pages})
