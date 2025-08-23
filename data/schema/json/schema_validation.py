# brc_tools/schemas/map_obs_schema.py
"""
Canonical schema for map observations data
Ensures consistent encoding/decoding between Polars and website
"""

import polars as pl
from typing import Dict, List, Optional

# STANDARD FIELD STRUCTURE
MAP_OBS_SCHEMA = {
    "stid": str,           # Station ID (46 stations in your network)
    "variable": str,       # Variable name (15 types)
    "value": float,        # Numeric measurement 
    "date_time": str,      # ISO 8601 UTC timestamp
    "units": str          # Unit string
}

# STANDARDIZED VARIABLE NAMES (from your lookups.py + actual data)
STANDARD_VARIABLES = {
    # Core weather
    "air_temp": "Celsius",
    "wind_speed": "m/s", 
    "wind_direction": "Degrees",
    "dew_point_temperature": "Celsius",
    
    # Air quality (your key focus)
    "ozone_concentration": "ppb",
    "PM_25_concentration": "ug/m3",
    "NOx_concentration": "ppb",
    
    # Pressure 
    "pressure": "Pascals",
    "sea_level_pressure": "Pascals",
    "altimeter": "Pascals",
    
    # Environmental
    "soil_temp": "Celsius",
    "snow_depth": "Millimeters", 
    "solar_radiation": "W/m**2",
    "outgoing_radiation_sw": "W/m**2",
    "ceiling": "Meters"
}

# KNOWN STATION NETWORKS (from your analysis)
STATION_NETWORKS = {
    "air_quality": ["UBCSP", "UBHSP", "WBB", "QCV", "QHV", "QHW", "QSM"],
    "airports": ["K40U", "K74V", "KCDC", "KENV", "KHCR", "KHIF", "KOGD", 
                 "KPVU", "KSPK", "KSVR", "KU69", "KVEL"],
    "utah_roads": ["UTASH", "UTCOP", "UTDAN", "UTDCD", "UTECO", "UTFRT", 
                   "UTHEB", "UTICS", "UTMTH", "UTMYT", "UTORM", "UTPET", 
                   "UTSLD", "UTSTV"],
    "research": ["UB7ST", "UCC34", "UINU1", "RVZU1", "UP028"]
}

def validate_map_obs_dataframe(df: pl.DataFrame) -> Dict[str, any]:
    """
    Validate Polars DataFrame before JSON export
    Returns validation results and warnings
    """
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {}
    }
    
    # Check required columns
    required_cols = list(MAP_OBS_SCHEMA.keys())
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        results["valid"] = False
        results["errors"].append(f"Missing columns: {missing_cols}")
        return results
    
    # Check data types
    for col, expected_type in MAP_OBS_SCHEMA.items():
        if expected_type == str and not df[col].dtype.is_string():
            results["warnings"].append(f"{col} should be string, got {df[col].dtype}")
        elif expected_type == float and not df[col].dtype.is_numeric():
            results["warnings"].append(f"{col} should be numeric, got {df[col].dtype}")
    
    # Check variable-unit consistency
    var_units = df.group_by("variable").agg(pl.col("units").unique())
    for row in var_units.iter_rows():
        variable, units_list = row
        if len(units_list) > 1:
            results["warnings"].append(f"{variable} has multiple units: {units_list}")
    
    # Check for extreme values
    extreme_checks = {
        "air_temp": (-60, 60),        # °C
        "wind_speed": (0, 100),       # m/s  
        "ozone_concentration": (0, 200), # ppb
        "PM_25_concentration": (0, 500)  # µg/m³
    }
    
    for variable, (min_val, max_val) in extreme_checks.items():
        var_data = df.filter(pl.col("variable") == variable)
        if var_data.height > 0:
            values = var_data["value"]
            extremes = values.filter((values < min_val) | (values > max_val))
            if extremes.len() > 0:
                results["warnings"].append(f"{variable} has {extremes.len()} extreme values")
    
    # Generate stats
    results["stats"] = {
        "total_records": df.height,
        "unique_stations": df["stid"].n_unique(),
        "unique_variables": df["variable"].n_unique(),
        "time_range": {
            "start": df["date_time"].min(),
            "end": df["date_time"].max()
        }
    }
    
    return results

def standardize_dataframe(df: pl.DataFrame) -> pl.DataFrame:
    """
    Apply standard processing to ensure consistent output
    """
    return (df
        .select([
            pl.col("stid").cast(pl.Utf8),
            pl.col("variable").cast(pl.Utf8), 
            pl.col("value").cast(pl.Float64),
            pl.col("date_time").dt.convert_time_zone("UTC").dt.strftime("%Y-%m-%dT%H:%M:%S.%3fZ"),
            pl.col("units").cast(pl.Utf8)
        ])
        .sort(["stid", "variable", "date_time"])
        .unique(subset=["stid", "variable"], keep="last")  # Keep most recent per station/variable
    )

# EXAMPLE USAGE IN YOUR DOWNLOAD SCRIPT
"""
from brc_tools.schemas.map_obs_schema import validate_map_obs_dataframe, standardize_dataframe

# After downloading from synoptic:
df_processed = standardize_dataframe(latest_obs)

# Validate before sending
validation = validate_map_obs_dataframe(df_processed)
if not validation["valid"]:
    print("❌ Validation failed:", validation["errors"])
    exit(1)

if validation["warnings"]:
    print("⚠️  Warnings:", validation["warnings"])

print(f"✅ Valid dataset: {validation['stats']}")

# Export to JSON
clean_df = clean_dataframe_for_json(df_processed)
save_json(clean_df, map_fpath)
"""