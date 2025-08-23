"""This should have complete/current API schema in machine-readable format.

It should help Claude Code if output json is consumed directly. Truth potion.
"""
import requests
import json
import yaml
from datetime import datetime

def load_flightaware_schema():
    """Dynamically fetch current FlightAware OpenAPI spec"""
    spec_url = "https://www.flightaware.com/commercial/aeroapi/resources/aeroapi-openapi.yml"

    try:
        response = requests.get(spec_url)
        response.raise_for_status()

        # Parse YAML spec
        api_spec = yaml.safe_load(response.content)

        # Save locally with timestamp for Claude Code reference
        with open('../../reference/FLIGHTAWARE-SPEC.md', 'w') as f:
            json.dump({
                'spec': api_spec,
                'fetched_at': datetime.now().isoformat(),
                'version': api_spec.get('info', {}).get('version', 'unknown')
            }, f, indent=2)

        return api_spec
    except Exception as e:
        print(f"Failed to fetch API spec: {e}")
        return None

def check_endpoint_availability(spec):
    """Verify which endpoints are currently available.

    TODO: IS THIS NEEDED, WHAT DOES IT DO, ETC
    """
    available_endpoints = {}
    for path, methods in spec.get('paths', {}).items():
        available_endpoints[path] = {
            'methods': list(methods.keys()),
            'deprecated': any(m.get('deprecated', False) for m in methods.values()),
            'description': methods.get('get', {}).get('summary', '')
        }

    return available_endpoints

def discover_endpoint_parameters(endpoint_path, method='get'):
    """Dynamically discover current parameters for any endpoint.

    TODO: IS THIS NEEDED, WHAT DOES IT DO, ETC
    """
    spec = load_flightaware_schema()

    endpoint_def = spec['paths'][endpoint_path][method.lower()]
    parameters = endpoint_def.get('parameters', [])

    param_info = {}
    for param in parameters:
        param_info[param['name']] = {
            'type': param.get('schema', {}).get('type'),
            'required': param.get('required', False),
            'description': param.get('description', ''),
            'example': param.get('example')
        }

    return param_info



if __name__ == "__main__":
    spec = load_flightaware_schema()
    if spec:
        print("Successfully loaded FlightAware API schema.")
    else:
        print("Could not load FlightAware API schema.")

    # Check availability of endpoints
    endpoints = check_endpoint_availability(spec)
