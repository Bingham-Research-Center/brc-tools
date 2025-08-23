import requests
import yaml
import json
from datetime import datetime

def fetch_flightradar24_openapi_spec(save_path=".claude/flightradar24_openapi.yaml"):
    """
    Fetch and cache the Flightradar24 OpenAPI spec YAML file.

    TODO: actually test and look into as it was generated.
    """
    url = "https://fr24api.flightradar24.com/documentation/Flightradar24-API.yaml"
    res = requests.get(url)
    res.raise_for_status()
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(res.text)
    print(f"Saved OpenAPI spec to {save_path} at {datetime.now()}")

