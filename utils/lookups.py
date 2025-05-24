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
map_stids = [
    "A3822",  # Dinosaur National Monument
    "A1633",  # Red Wash
    "UB7ST",  # Seven Sisters
    "UBHSP",  # Horsepool
    "A1622",  # Ouray
    "QV4",    # Vernal
    "A1386",  # Whiterocks
    "QRS",    # Roosevelt OG
    "UBRVT",  # Roosevelt USU
    "A1388",  # Myton
    "UBCSP"   # Castle Peak
]

map_vrbls = [
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