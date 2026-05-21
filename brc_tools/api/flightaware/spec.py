"""Fetch the FlightAware AeroAPI OpenAPI spec on demand.

The spec is large (~1 MB). Don't commit it; fetch when you need it for
client development or to verify endpoint shapes.
"""

import requests
import yaml

SPEC_URL = "https://www.flightaware.com/commercial/aeroapi/resources/aeroapi-openapi.yml"


def fetch_openapi_spec(timeout: float = 30.0) -> dict:
    """Return the parsed OpenAPI YAML as a dict."""
    resp = requests.get(SPEC_URL, timeout=timeout)
    resp.raise_for_status()
    return yaml.safe_load(resp.content)
