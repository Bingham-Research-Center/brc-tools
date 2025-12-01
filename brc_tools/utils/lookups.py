"""Lookup tables/dictionaries for variables, keys, locations, settings, etc.
"""

import os
import sys

import numpy as np



##### VARIABLES #####
# key is the four-letter variable code we use throughout the BRC package
# label is the human-readable name of the variable for figures, with unit
# synoptic is the variable name used in the synoptic data files (polars columns?)
# TODO - get pint involved for units, and have label dynamically formed

_VRBLS = {
    "snow": {'label': 'Snow depth (mm)',
             'synoptic': 'snow_depth'},
    "mslp": {'label': 'Mean sea level pressure (hPa)',
             'synoptic': 'sea_level_pressure'},
    # "solar": {'label': 'Solar radiation (W/m^2)',
    #           'synoptic': 'solar_radiation'},
    "wspd": {'label': 'Wind speed (m/s)',
             'synoptic': 'wind_speed'},
    "wdir": {'label': 'Wind direction (deg)',
             'synoptic': 'wind_direction'},
    "ozone": {'label': 'Ozone concentration (ppb)',
              'synoptic': 'ozone_concentration',},
    "temp": { 'label': 'Temperature (C)',
              'synoptic': 'air_temp'},
}

### WEBSITE LISTS ###
# Canonical Uinta Basin AQ stations for front page
# Status checked 30 Nov 2025 via synopticpy
ubair_aq_stids = [
    # WORKING (confirmed returning ozone_concentration):
    "A3822",  # Dinosaur National Monument (Network 136)
    "A1633",  # Red Wash (Network 136, =UBRDW location)
    "UB7ST",  # Seven Sisters (Network 209 UBAIR)
    "A1622",  # Ouray (Network 136, =UBORY location)
    "QV4",    # Vernal (Network 9 Utah DAQ)
    "A1386",  # Whiterocks (Network 136, =UBWHR location)
    "QRS",    # Roosevelt (Network 9 Utah DAQ)
    "A1388",  # Myton (Network 136)
    # OFFLINE (investigate later - may come back online):
    # "UBHSP",  # Horsepool - INACTIVE since Sep 2025
    # "UBCSP",  # Castle Peak - No data since Nov 5, 2025
    # "UBRVT",  # Roosevelt USU - INACTIVE (use QRS instead)
]

# Legacy list (kept for reference)
old_ubair_map_stids = [
    "A3822",  # Dinosaur National Monument
    "A1633",  # Red Wash
    "UB7ST",  # Seven Sisters
    "UBHSP",  # Horsepool - OFFLINE
    "A1622",  # Ouray
    "QV4",    # Vernal
    "A1386",  # Whiterocks
    "QRS",    # Roosevelt OG
    "UBRVT",  # Roosevelt USU - OFFLINE
    "A1388",  # Myton
    "UBCSP"   # Castle Peak - OFFLINE
]

obs_map_vrbls = [
    "wind_speed",
    "wind_direction",
    "air_temp",
    "dew_point_temperature",
    "pressure",
    "snow_depth",
    "solar_radiation",
    "altimeter",
    "soil_temp",
    "sea_level_pressure",
    "snow_accum",
    "ceiling",
    "soil_temp_ir",
    "snow_smoothed",
    "snow_accum_manual",
    "snow_water_equiv",
    "net_radiation_sw",
    "sonic_air_temp",
    "sonic_vertical_vel",
    "vertical_heat_flux",
    "outgoing_radiation_sw",
    "PM_25_concentration",
    "ozone_concentration",
    "derived_aerosol_boundary_layer_depth",
    "NOx_concentration",
    "PM_10_concentration",
]

obs_map_stids = [
    # General weather stations (SLV)
    "WBB",
    # SLV air quality
    # Hawthorne, Copperview, Harrisville, Smithsfield
    "QHW", "QCV", "QHV", "QSM",
    # Centerville windstorm monitoring
    "UP028", "UFD04", "UFD05", "UFD06", "CEN",
    # General weather stations (Wasatch high-elevation)
    # Alta, Ogden, Provo
    "CLN", "OGP", "BUNUT",
    # General weather stations (Transition zone)
    # Rays Valley
    "RVZU1",
    # General weather stations (Uinta Basin)
    # Bluebell, Chepata Peak (highest in Uintas?), Fort Duchesne
    "UCC34", "CHPU1", "UINU1",
    # Dino NM, CO (north "Success" and south town sections)
    "SURC2", "DNOC2",


    # Price windstorm monitoring?
    # Scan all stids for interesting shifts (e.g., pressure, wind etc)
    # What are Utah and Basin's "cool" trivia microclimates?


    # UT DoT and road weather
    # Orem, Heber, Daniels, Cooper, Fruitland, Starvation, Myton, Vernal Asphalt Ridge
    "UTORM", "UTHEB", "UTDAN", "UTCOP", "UTFRT", "UTSTV", "UTMYT", "UTASH",
    # Wolf Creek, Hanna, Mtn Home
    "KMS", "HANU1", "UTMTH",
    # Red Narrows, Soldier, Indian, Echo Canyon, Peterson, Deer Creek,
    "RDN", "UTSLD", "UTICS", "UTECO", "UTPET", "UTDCD",

    # All airports
    # (U42 or KSVR) is West Valley SLC airport
    # U69 is Duschene, UT
    # 74V is Roosevelt, UT
    # 40U is Manila, UT
    # 33U is Dutch John, UT
    # 4VO is Rangely, CO
    "KPVU", "KOGD", "KHIF", "KSVR", "KSPK", "KHCR",
    "KU69", "K74V", "KCDC", "KENV", "KVEL", "K4V0", "K40U", "K33U",

    # COOP snow depth stations
    'COOPDINU1', 'COOPROSU1',  'COOPVELU1', 'COOPFTDU1', 'COOPALMU1',
    'COOPDSNU1', 'COOPNELU1',

    # UBAIR network (ozone monitoring)
    # NOTE (30 Nov 2025): Some UB-series stations are offline or not returning data.
    # A-series IDs (Network 136) return ozone data for same physical locations.
    #
    # A-series stations (Network 136) - confirmed returning ozone:
    "A3822",   # Dinosaur National Monument
    "A1633",   # Red Wash (same location as UBRDW)
    "A1622",   # Ouray (same location as UBORY)
    "A1386",   # Whiterocks (same location as UBWHR)
    "A1388",   # Myton
    # Utah DAQ stations (Network 9) - confirmed returning ozone:
    "QV4",     # Vernal
    "QRS",     # Roosevelt
    # UBAIR Network 209 - working:
    "UB7ST",   # Seven Sisters - confirmed working
    #
    # OFFLINE/NOT RETURNING DATA (do not include):
    # "UBHSP",   # Horsepool - INACTIVE since Sep 2025
    # "UBCSP",   # Castle Peak - No data since Nov 5, 2025
    # "UBRDW",   # Red Wash - use A1633 instead
    # "UBORY",   # Ouray - use A1622 instead
    # "UBDRF",   # Dry Fork - not returning data
    # "UBWHR",   # Whiterocks - use A1386 instead

    # Coupled pairs for, e.g., contrasting temp, or tracking fronts

    # 2x Duchesne/Myton with westerly extent
    # 2x Browns Park
    # Other AQ

]

def load_variable_mapping(path='variable-mapping.txt'):
    """
    Reads a plain-text lookup file where each line is 'raw=Pretty Name,'
    and returns a dict mapping raw → pretty. Use with `raw_to_pretty` and
    `pretty_to_raw` functions.

    Example:
        mapping = load_variable_mapping('variable_mapping.txt')
        print(raw_to_pretty('ozone_concentration', mapping))
        # → "Ozone Concentration"
    """
    mapping = {}
    with open(path) as f:
        for line in f:
            line = line.strip().rstrip(',')
            if not line or line.startswith('#'):
                continue
            key, val = line.split('=', 1)
            mapping[key] = val
    return mapping

def raw_to_pretty(key, mapping=None, path='variable_mapping.txt'):
    if mapping is None:
        mapping = load_variable_mapping(path)
    return mapping.get(key, key)

def pretty_to_raw(pretty, mapping=None, path='variable_mapping.txt'):
    if mapping is None:
        mapping = load_variable_mapping(path)
    inv = {v: k for k, v in mapping.items()}
    return inv.get(pretty, pretty)
