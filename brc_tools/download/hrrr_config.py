"""Shared configuration for the minimal HRRR proof-of-concept."""

UINTA_BASIN_SW = (39.4, -110.9)
UINTA_BASIN_NE = (41.1, -108.5)

DEFAULT_HRRR_PRODUCT = "sfc"
DEFAULT_MAX_FXX = 12
DEFAULT_MIN_USABLE_HOURS = 6

# Canonical HRRR surface fields for the road proof-of-concept.
# Keys are internal aliases; values are Herbie search strings.
ROAD_FORECAST_QUERY_MAP = {
    "temp_2m": "TMP:2 m",
    "_ugrd": "UGRD:10 m",
    "_vgrd": "VGRD:10 m",
    "wind_gust": "GUST:surface",
    "visibility": "VIS:surface",
    "precip_1hr": "APCP:surface",
    "_crain": "CRAIN:surface",
    "_csnow": "CSNOW:surface",
    "_cfrzr": "CFRZR:surface",
    "_cicep": "CICEP:surface",
    "snow_depth": "SNOD:surface",
    "cloud_cover": "TCDC:entire",
    "rh_2m": "RH:2 m",
}

ROAD_FORECAST_VARIABLES_META = {
    "temp_2m": {"units": "Celsius", "display": "Temperature"},
    "wind_speed_10m": {"units": "m/s", "display": "Wind Speed"},
    "wind_gust": {"units": "m/s", "display": "Wind Gust"},
    "visibility": {"units": "km", "display": "Visibility"},
    "precip_1hr": {"units": "mm", "display": "1-hr Precip"},
    "precip_type": {"units": "category", "display": "Precip Type"},
    "snow_depth": {"units": "mm", "display": "Snow Depth"},
    "cloud_cover": {"units": "%", "display": "Cloud Cover"},
    "rh_2m": {"units": "%", "display": "Relative Humidity"},
}

ROAD_CORRIDORS = {
    "us40": {
        "name": "US-40 Corridor",
        "waypoints": [
            {
                "name": "Daniels Summit",
                "lat": 40.30,
                "lon": -111.26,
                "elevation_m": 2438,
                "reference_stid": "UTDAN",
            },
            {
                "name": "Strawberry",
                "lat": 40.17,
                "lon": -111.14,
                "elevation_m": 2316,
                "reference_stid": None,
            },
            {
                "name": "Fruitland",
                "lat": 40.21,
                "lon": -110.85,
                "elevation_m": 2042,
                "reference_stid": "UTFRT",
            },
            {
                "name": "Starvation",
                "lat": 40.19,
                "lon": -110.45,
                "elevation_m": 1783,
                "reference_stid": "UTSTV",
            },
            {
                "name": "Duchesne",
                "lat": 40.16,
                "lon": -110.40,
                "elevation_m": 1752,
                "reference_stid": "KU69",
            },
            {
                "name": "Myton",
                "lat": 40.20,
                "lon": -110.06,
                "elevation_m": 1585,
                "reference_stid": "UTMYT",
            },
            {
                "name": "Roosevelt",
                "lat": 40.30,
                "lon": -109.99,
                "elevation_m": 1588,
                "reference_stid": "K74V",
            },
            {
                "name": "Vernal (Asphalt Ridge)",
                "lat": 40.48,
                "lon": -109.56,
                "elevation_m": 1609,
                "reference_stid": "UTASH",
            },
            {
                "name": "Dinosaur",
                "lat": 40.24,
                "lon": -109.01,
                "elevation_m": 1829,
                "reference_stid": "DNOC2",
            },
        ],
    },
    "us191": {
        "name": "US-191 North-South",
        "waypoints": [
            {
                "name": "Vernal",
                "lat": 40.46,
                "lon": -109.53,
                "elevation_m": 1609,
                "reference_stid": "KVEL",
            },
            {
                "name": "Maeser",
                "lat": 40.50,
                "lon": -109.58,
                "elevation_m": 1600,
                "reference_stid": None,
            },
            {
                "name": "Ouray",
                "lat": 40.09,
                "lon": -109.68,
                "elevation_m": 1463,
                "reference_stid": "A1622",
            },
            {
                "name": "Indian Canyon Summit",
                "lat": 39.90,
                "lon": -110.40,
                "elevation_m": 2772,
                "reference_stid": "UTICS",
            },
        ],
    },
    "basin_roads": {
        "name": "Local Basin Roads",
        "waypoints": [
            {
                "name": "Roosevelt",
                "lat": 40.30,
                "lon": -109.99,
                "elevation_m": 1588,
                "reference_stid": "K74V",
            },
            {
                "name": "Altamont",
                "lat": 40.36,
                "lon": -110.29,
                "elevation_m": 1612,
                "reference_stid": None,
            },
            {
                "name": "Bluebell",
                "lat": 40.37,
                "lon": -110.17,
                "elevation_m": 1612,
                "reference_stid": "UCC34",
            },
            {
                "name": "Starvation Dam",
                "lat": 40.19,
                "lon": -110.45,
                "elevation_m": 1783,
                "reference_stid": "UTSTV",
            },
        ],
    },
}
