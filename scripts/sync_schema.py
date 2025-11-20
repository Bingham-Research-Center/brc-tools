#!/usr/bin/env python3
"""
Schema Synchronization Script
Validates that CHPC and website definitions match the canonical schema.

Usage:
    python sync_schema.py                    # Validate all
    python sync_schema.py --check-only       # Report mismatches without fixing
    python sync_schema.py --generate-js      # Generate JavaScript files from schema
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Paths
SCRIPT_DIR = Path(__file__).parent
BRC_TOOLS_ROOT = SCRIPT_DIR.parent
SCHEMA_PATH = BRC_TOOLS_ROOT / "data" / "schema" / "ubair_schema.json"
WEBSITE_ROOT = Path.home() / "WebstormProjects" / "ubair-website"

# Website files to validate
WEBSITE_CONFIG = WEBSITE_ROOT / "public" / "js" / "config.js"
WEBSITE_API = WEBSITE_ROOT / "public" / "js" / "api.js"
WEBSITE_METADATA = WEBSITE_ROOT / "public" / "js" / "stationMetadata.js"


def load_schema() -> dict:
    """Load the canonical schema."""
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def extract_js_stations(config_path: Path) -> Dict[str, dict]:
    """Extract station definitions from config.js."""
    stations = {}
    content = config_path.read_text()

    # Match station entries like: 'Horsepool': { lat: 40.144, lng: -109.467 }
    pattern = r"'([^']+)':\s*\{\s*lat:\s*([\d.-]+),\s*lng:\s*([\d.-]+)"
    for match in re.finditer(pattern, content):
        name, lat, lng = match.groups()
        stations[name] = {
            "lat": float(lat),
            "lng": float(lng)
        }

    return stations


def extract_js_mappings(api_path: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Extract station and variable name mappings from api.js."""
    content = api_path.read_text()

    # Extract station name mappings
    station_mappings = {}
    station_pattern = r"'(\w+)':\s*'([^']+)'"

    # Find the mapStationName function
    if "mapStationName" in content:
        # Look for prettyNames object
        start = content.find("const prettyNames = {")
        if start != -1:
            end = content.find("};", start)
            mapping_block = content[start:end]
            for match in re.finditer(station_pattern, mapping_block):
                stid, name = match.groups()
                station_mappings[stid] = name

    # Extract variable name mappings
    variable_mappings = {}
    if "mapVariableName" in content:
        # Find the function and extract mappings object
        func_start = content.find("function mapVariableName")
        if func_start != -1:
            # Look for const mappings = { inside the function
            mapping_start = content.find("const mappings = {", func_start)
            if mapping_start != -1:
                end = content.find("};", mapping_start)
                mapping_block = content[mapping_start:end]
                for match in re.finditer(station_pattern, mapping_block):
                    var_name, display = match.groups()
                    variable_mappings[var_name] = display

    return station_mappings, variable_mappings


def validate_stations(schema: dict) -> List[str]:
    """Validate station definitions between schema and website."""
    issues = []

    schema_stations = schema["stations"]
    homepage_stations = {
        stid: data for stid, data in schema_stations.items()
        if data.get("homepage", False)
    }

    # Check website config.js
    if WEBSITE_CONFIG.exists():
        js_stations = extract_js_stations(WEBSITE_CONFIG)

        # Check schema homepage stations are in website
        for stid, data in homepage_stations.items():
            name = data["name"]
            if name not in js_stations:
                issues.append(f"MISSING in config.js: {name} ({stid})")
            else:
                # Check coordinates match
                js_lat = js_stations[name]["lat"]
                js_lng = js_stations[name]["lng"]
                if abs(js_lat - data["lat"]) > 0.01 or abs(js_lng - data["lng"]) > 0.01:
                    issues.append(
                        f"COORDINATE MISMATCH: {name} - "
                        f"schema ({data['lat']}, {data['lng']}) vs "
                        f"config.js ({js_lat}, {js_lng})"
                    )

        # Check for extra stations in website not in schema
        schema_names = {data["name"] for data in schema_stations.values()}
        for name in js_stations:
            if name not in schema_names:
                issues.append(f"EXTRA in config.js (not in schema): {name}")
    else:
        issues.append(f"FILE NOT FOUND: {WEBSITE_CONFIG}")

    # Check website api.js mappings
    if WEBSITE_API.exists():
        station_mappings, _ = extract_js_mappings(WEBSITE_API)

        for stid, data in homepage_stations.items():
            if stid not in station_mappings:
                # Check alt_ids
                alt_ids = data.get("alt_ids", [])
                if not any(alt in station_mappings for alt in alt_ids):
                    issues.append(f"MISSING in api.js mapStationName: {stid} ({data['name']})")
    else:
        issues.append(f"FILE NOT FOUND: {WEBSITE_API}")

    return issues


def validate_variables(schema: dict) -> List[str]:
    """Validate variable definitions between schema and website."""
    issues = []

    schema_variables = schema["variables"]

    if WEBSITE_API.exists():
        _, variable_mappings = extract_js_mappings(WEBSITE_API)

        for var_name, data in schema_variables.items():
            if var_name not in variable_mappings:
                issues.append(f"MISSING in api.js mapVariableName: {var_name} ({data['display']})")
            elif variable_mappings[var_name] != data["display"]:
                issues.append(
                    f"DISPLAY NAME MISMATCH: {var_name} - "
                    f"schema ({data['display']}) vs "
                    f"api.js ({variable_mappings[var_name]})"
                )

    return issues


def generate_js_config(schema: dict) -> str:
    """Generate config.js content from schema."""
    lines = ["export const stations = {"]

    # Group by type
    homepage_stations = {
        stid: data for stid, data in schema["stations"].items()
        if data.get("homepage", False)
    }

    # Sort by name for consistent output
    for stid, data in sorted(homepage_stations.items(), key=lambda x: x[1]["name"]):
        type_str = f", type: 'road'" if data["type"] == "road_weather" else ""
        lines.append(f"    '{data['name']}': {{ lat: {data['lat']}, lng: {data['lng']}{type_str} }},  // {stid}")

    lines.append("};")
    lines.append("")
    lines.append("export const thresholds = {")

    for var_name, data in schema["variables"].items():
        if data.get("thresholds"):
            t = data["thresholds"]
            lines.append(f"    '{data['display']}': {{ warning: {t['warning']}, danger: {t['danger']} }},")

    lines.append("};")

    return "\n".join(lines)


def print_report(station_issues: List[str], variable_issues: List[str]):
    """Print validation report."""
    print("\n" + "=" * 60)
    print("SCHEMA SYNC VALIDATION REPORT")
    print("=" * 60)

    if station_issues:
        print("\n🚨 STATION ISSUES:")
        for issue in station_issues:
            print(f"  • {issue}")
    else:
        print("\n✅ Stations: All synchronized")

    if variable_issues:
        print("\n🚨 VARIABLE ISSUES:")
        for issue in variable_issues:
            print(f"  • {issue}")
    else:
        print("\n✅ Variables: All synchronized")

    total_issues = len(station_issues) + len(variable_issues)
    print("\n" + "-" * 60)
    if total_issues == 0:
        print("✅ All checks passed!")
    else:
        print(f"⚠️  Total issues found: {total_issues}")
    print("=" * 60 + "\n")

    return total_issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate schema sync between CHPC and website")
    parser.add_argument("--check-only", action="store_true", help="Only report, don't suggest fixes")
    parser.add_argument("--generate-js", action="store_true", help="Generate JavaScript files from schema")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Load schema
    try:
        schema = load_schema()
        if args.verbose:
            print(f"Loaded schema v{schema['version']} with {len(schema['stations'])} stations, {len(schema['variables'])} variables")
    except FileNotFoundError:
        print(f"❌ Schema not found: {SCHEMA_PATH}")
        sys.exit(1)

    if args.generate_js:
        print("\n📝 Generated config.js:\n")
        print(generate_js_config(schema))
        return

    # Validate
    station_issues = validate_stations(schema)
    variable_issues = validate_variables(schema)

    # Report
    total_issues = print_report(station_issues, variable_issues)

    sys.exit(1 if total_issues > 0 else 0)


if __name__ == "__main__":
    main()
