"""Lookup tables/dictionaries for variables, keys, locations, settings, etc.
"""

import os
import re
import sys

import numpy as np


# UDOT Traffic API endpoint for camera data
UDOT_CAMERAS_API_URL = "https://www.udottraffic.utah.gov/api/v2/get/cameras"


def slugify_camera_name(name):
    """Convert a camera name to a filesystem-safe slug.

    Example:
        >>> slugify_camera_name("I-80 @ 150 N / MP 163.05, CLV")
        'i-80_at_150_n_mp_163-05_clv'
    """
    s = name.lower()
    s = s.replace("@", "at")
    s = s.replace("/", " ")
    s = re.sub(r"[^a-z0-9\s.-]", "", s)
    s = re.sub(r"[\s]+", "_", s.strip())
    s = s.replace(".", "-")
    s = re.sub(r"_+", "_", s)
    return s.strip("_")



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

road_corridors = {
    "us40": {
        "name": "US-40 Corridor",
        "waypoints": [
            {"name": "Daniels Summit", "lat": 40.30, "lon": -111.26, "elevation_m": 2438, "reference_stid": "UTDAN"},
            {"name": "Strawberry", "lat": 40.17, "lon": -111.14, "elevation_m": 2316, "reference_stid": None},
            {"name": "Fruitland", "lat": 40.21, "lon": -110.85, "elevation_m": 2042, "reference_stid": "UTFRT"},
            {"name": "Starvation", "lat": 40.19, "lon": -110.45, "elevation_m": 1783, "reference_stid": "UTSTV"},
            {"name": "Duchesne", "lat": 40.16, "lon": -110.40, "elevation_m": 1752, "reference_stid": "KU69"},
            {"name": "Myton", "lat": 40.20, "lon": -110.06, "elevation_m": 1585, "reference_stid": "UTMYT"},
            {"name": "Roosevelt", "lat": 40.30, "lon": -109.99, "elevation_m": 1588, "reference_stid": "K74V"},
            {"name": "Vernal (Asphalt Ridge)", "lat": 40.48, "lon": -109.56, "elevation_m": 1609, "reference_stid": "UTASH"},
            {"name": "Dinosaur", "lat": 40.24, "lon": -109.01, "elevation_m": 1829, "reference_stid": "DNOC2"},
        ]
    },
    "us191": {
        "name": "US-191 North-South",
        "waypoints": [
            {"name": "Vernal", "lat": 40.46, "lon": -109.53, "elevation_m": 1609, "reference_stid": "KVEL"},
            {"name": "Maeser", "lat": 40.50, "lon": -109.58, "elevation_m": 1600, "reference_stid": None},
            {"name": "Ouray", "lat": 40.09, "lon": -109.68, "elevation_m": 1463, "reference_stid": "A1622"},
            {"name": "Indian Canyon Summit", "lat": 39.90, "lon": -110.40, "elevation_m": 2772, "reference_stid": "UTICS"},
        ]
    },
    "basin_roads": {
        "name": "Local Basin Roads",
        "waypoints": [
            {"name": "Roosevelt", "lat": 40.30, "lon": -109.99, "elevation_m": 1588, "reference_stid": "K74V"},
            {"name": "Altamont", "lat": 40.36, "lon": -110.29, "elevation_m": 1612, "reference_stid": None},
            {"name": "Bluebell", "lat": 40.37, "lon": -110.17, "elevation_m": 1612, "reference_stid": "UCC34"},
            {"name": "Starvation Dam", "lat": 40.19, "lon": -110.45, "elevation_m": 1783, "reference_stid": "UTSTV"},
        ]
    }
}

# UDOT camera locations in the Uinta Basin bounding box.
# Source: UDOT Traffic API (/api/v2/get/cameras), 39.5-41.0°N / 111.5-108.5°W
# Each entry has name, roadway, lat, lon — no elevation or reference_stid needed.
udot_cameras = [
    {"name": "I-80 @ 150 N / MP 163.05, CLV", "roadway": "I-80", "lat": 40.91813, "lon": -111.40757},
    {"name": "I-80 @ Wanship / SR-32 / MP 155.46, SU", "roadway": "I-80", "lat": 40.81299, "lon": -111.40143},
    {"name": "I-80 EB @ Milepost 149.62, SU", "roadway": "I-80", "lat": 40.76018, "lon": -111.47101},
    {"name": "I-80 RWIS EB @ Tollgate Canyon Rd / MP 150.7, SU", "roadway": "I-80", "lat": 40.7749, "lon": -111.4678},
    {"name": "I-80 WB @ Echo Canyon / MP 170.44, SU", "roadway": "I-80", "lat": 40.999367, "lon": -111.392389},
    {"name": "I-80 WB @ Milepost 147.56, SU", "roadway": "I-80", "lat": 40.73694, "lon": -111.48655},
    {"name": "I-80 WB @ Silver Creek Jct / US-40 / MP 146.84, SU", "roadway": "I-80", "lat": 40.7319, "lon": -111.49834},
    {"name": "I-84 EB @ I-80 / Echo Jct / MP 119.36, SU (Local)", "roadway": "I-84", "lat": 40.9717, "lon": -111.44275},
    {"name": "I-84 EB @ I-80 / Echo Jct / MP 119.6, SU", "roadway": "I-84", "lat": 40.97022, "lon": -111.43928},
    {"name": "100 S / SR-113 @ 300 W, HBR", "roadway": "SR 113", "lat": 40.50641, "lon": -111.41886},
    {"name": "Charleston Rd / 3600 W / SR-113 @ US-189, CHR", "roadway": "SR 113", "lat": 40.45804, "lon": -111.47188},
    {"name": "Main St / SR-113 / SR-222 @ Center St / SR-113, MWY", "roadway": "SR 113", "lat": 40.51225, "lon": -111.47237},
    {"name": "200 N / SR-121 @ 300 W, RSV", "roadway": "SR 121", "lat": 40.30221, "lon": -109.99724},
    {"name": "500 N / SR-121 @ 2000 W / Aggie Blvd / MP 38.32, MAE", "roadway": "SR 121", "lat": 40.46251, "lon": -109.56664},
    {"name": "SR-121 @ Milepost 25.9, UN", "roadway": "SR 121", "lat": 40.40992, "lon": -109.76381},
    {"name": "SR-121 RWIS EB @ East Lapoint / MP 31.45, UN", "roadway": "SR 121", "lat": 40.4203, "lon": -109.67016},
    {"name": "SR-150 @ Milepost 50, SU", "roadway": "SR 150", "lat": 40.94457, "lon": -110.83905},
    {"name": "6050 N / SR-157 @ 550 E / MP 4.85, CC", "roadway": "SR 157", "lat": 39.68833, "lon": -110.80515},
    {"name": "SR-208 @ Milepost 7.68, DU", "roadway": "SR 208", "lat": 40.31133, "lon": -110.69881},
    {"name": "Deer Valley Dr / SR-224 @ Swede Alley, PKC", "roadway": "SR 224", "lat": 40.64602, "lon": -111.49512},
    {"name": "SR-224 / Marsac Ave RWIS SB @ Ontario Mine / MP 3.22, PKC", "roadway": "SR 224", "lat": 40.6253, "lon": -111.4968},
    {"name": "Kearns Blvd / SR-248 @ Comstock Dr, PKC", "roadway": "SR 248", "lat": 40.66813, "lon": -111.4922},
    {"name": "Kearns Blvd / SR-248 @ Richardson Flat Rd, PKC", "roadway": "SR 248", "lat": 40.6745, "lon": -111.46941},
    {"name": "Kearns Blvd / SR-248 @ Round Valley Dr, PKC", "roadway": "SR 248", "lat": 40.68006, "lon": -111.46591},
    {"name": "SR-248 / 1040 W @ Jordanelle Pkwy / Browns Canyon Rd / 13970 N / MP 4.88, WA", "roadway": "SR 248", "lat": 40.67715, "lon": -111.4321},
    {"name": "SR-264 @ Milepost 10.8, EM", "roadway": "SR 264", "lat": 39.67928, "lon": -111.22028},
    {"name": "SR-31 @ Milepost 13.15, SP", "roadway": "SR 31", "lat": 39.6207, "lon": -111.31337},
    {"name": "SR-31 @ Miller Flat Rd / MP 18.3, SP", "roadway": "SR 31", "lat": 39.582493, "lon": -111.251446},
    {"name": "Main St / SR-32 @ 200 S / SR-248, KMS", "roadway": "SR 32", "lat": 40.64003, "lon": -111.28099},
    {"name": "Main St / SR-32 @ Center St / SR-150, KMS", "roadway": "SR 32", "lat": 40.643092, "lon": -111.280912},
    {"name": "SR-32 @ Milepost 19.55, SU", "roadway": "SR 32", "lat": 40.72397, "lon": -111.31618},
    {"name": "SR-32 @ Milepost 23, SU", "roadway": "SR 32", "lat": 40.74835, "lon": -111.36388},
    {"name": "SR-32 @ Milepost 3.86, HBR", "roadway": "SR 32", "lat": 40.593186, "lon": -111.394845},
    {"name": "SR-32 RWIS NB @ Rob Young Ln / MP 16.46, SU", "roadway": "SR 32", "lat": 40.69837, "lon": -111.28088},
    {"name": "SR-43 RWIS NB @ UT/WY State Line / MP 0.44, DG", "roadway": "SR 43", "lat": 40.991673, "lon": -109.844581},
    {"name": "SR-44 @ Milepost 12.7, DG", "roadway": "SR 44", "lat": 40.8668, "lon": -109.68644},
    {"name": "SR-44 @ Milepost 16.86, DG", "roadway": "SR 44", "lat": 40.90013, "lon": -109.70358},
    {"name": "SR-44 @ Milepost 5.24, DG", "roadway": "SR 44", "lat": 40.85234, "lon": -109.57328},
    {"name": "SR-44 RWIS EB @ Moose Pond / MP 9.5, DG", "roadway": "SR 44", "lat": 40.84185, "lon": -109.64705},
    {"name": "SR-45 @ Milepost 15.55, UN", "roadway": "SR 45", "lat": 40.142, "lon": -109.27873},
    {"name": "SR-45 NB @ Milepost 2.95, UN", "roadway": "SR 45", "lat": 39.99548, "lon": -109.17814},
    {"name": "SR-45 NB @ Milepost 29, UN", "roadway": "SR 45", "lat": 40.26678, "lon": -109.45429},
    {"name": "100 N / SR-55 @ 300 E, PRC", "roadway": "SR 55", "lat": 39.60091, "lon": -110.80528},
    {"name": "100 N / SR-55 @ Carbon Ave / SR-10, PRC", "roadway": "SR 55", "lat": 39.60113, "lon": -110.81113},
    {"name": "100 N / SR-55 @ Main St / Price River Dr, PRC", "roadway": "SR 55", "lat": 39.60076, "lon": -110.82321},
    {"name": "Main St / SR-55 @ 300 S, PRC", "roadway": "SR 55", "lat": 39.59474, "lon": -110.79087},
    {"name": "Main St / SR-55 @ 700 E, PRC", "roadway": "SR 55", "lat": 39.59968, "lon": -110.79809},
    {"name": "SR-87 RWIS WB @ Mountain Home/MP 15.6, DU", "roadway": "SR 87", "lat": 40.35795, "lon": -110.38781},
    {"name": "SR-88 @ Pelican Lake / MP 9.03, UN", "roadway": "SR 88", "lat": 40.21099, "lon": -109.66883},
    {"name": "SR-150 RWIS EB @ Bald Mountain Pass / MP 29.2, SU", "roadway": "Unknown", "lat": 40.68686, "lon": -110.90301},
    {"name": "SR-248 RWIS EB @ Milepost 8.95, WA", "roadway": "Unknown", "lat": 40.6338, "lon": -111.3849},
    {"name": "SR-31 RWIS WB @ Skyline Dr / MP 11.79, SP", "roadway": "Unknown", "lat": 39.63607, "lon": -111.3291},
    {"name": "SR-35 RWIS @ Wolf Creek / MP 9.92, WA", "roadway": "Unknown", "lat": 40.558, "lon": -111.131},
    {"name": "SR-35 RWIS EB @ Wolf Creek Pass / MP 19.33, WA", "roadway": "Unknown", "lat": 40.4872, "lon": -111.0344},
    {"name": "US-189 @ Milepost 25.36, CHR", "roadway": "Unknown", "lat": 40.46106, "lon": -111.46304},
    {"name": "US-191 RWIS NB @ Indian Canyon Summit / MP 266.77, DU", "roadway": "Unknown", "lat": 39.8857, "lon": -110.7479},
    {"name": "US-40 RWIS EB @ Starvation Reservoir / MP 81.5, DU", "roadway": "Unknown", "lat": 40.17259, "lon": -110.493},
    {"name": "US-40 RWIS SB @ Mayflower Summit / MP 6.13, WA", "roadway": "Unknown", "lat": 40.65269, "lon": -111.45715},
    {"name": "US-6 RWIS EB @ Red Narrows / MP 192.9, UT", "roadway": "Unknown", "lat": 39.989, "lon": -111.37},
    {"name": "US-189 @ 3000 S / MP 26.54, CHR", "roadway": "US 189", "lat": 40.47113, "lon": -111.44792},
    {"name": "US-189 @ Charleston Rd / 3600 W / SR-113 / MP 24.92, CHR", "roadway": "US 189", "lat": 40.4558, "lon": -111.4707},
    {"name": "US-189 @ Heber Pkwy / 1300 S, HBR", "roadway": "US 189", "lat": 40.49054, "lon": -111.41688},
    {"name": "US-189 @ Milepost 20.89, WA", "roadway": "US 189", "lat": 40.4134, "lon": -111.47823},
    {"name": "US-189 @ Milepost 21.57, WA", "roadway": "US 189", "lat": 40.41846, "lon": -111.48935},
    {"name": "100 W / US-191 @ 400 S / MP 294.73, DCH", "roadway": "US 191", "lat": 40.15894, "lon": -110.40302},
    {"name": "US-191 @ Antelope Flat / MP 400.8, DG", "roadway": "US 191", "lat": 40.96383, "lon": -109.46875},
    {"name": "US-191 @ Cedar Springs Rd / MP 391.77, DG", "roadway": "US 191", "lat": 40.90236, "lon": -109.44255},
    {"name": "US-191 @ Milepost 259.75, CC", "roadway": "US 191", "lat": 39.79927, "lon": -110.78419},
    {"name": "US-191 @ Milepost 265.7, DU", "roadway": "US 191", "lat": 39.88996, "lon": -110.74939},
    {"name": "US-191 @ Milepost 372.31, UN", "roadway": "US 191", "lat": 40.6774, "lon": -109.4859},
    {"name": "US-191 @ Milepost 380.82, DG", "roadway": "US 191", "lat": 40.78262, "lon": -109.471042},
    {"name": "US-191 RWIS NB @ Bassett Spring / MP 376.75, UN", "roadway": "US 191", "lat": 40.724, "lon": -109.4688},
    {"name": "US-191 RWIS NB @ Willie Spring / MP 385.94, DG", "roadway": "US 191", "lat": 40.8539, "lon": -109.46205},
    {"name": "US-191 RWIS SB @ Windy Point / MP 369.25, UN", "roadway": "US 191", "lat": 40.64125, "lon": -109.4859},
    {"name": "1500 E / US-40 @ 1000 S / MP 146.4, NPL", "roadway": "US 40", "lat": 40.44146, "lon": -109.4995},
    {"name": "1500 E / US-40 @ 1500 E / SR-45 / MP 148.6, NPL", "roadway": "US 40", "lat": 40.414335, "lon": -109.498606},
    {"name": "1500 E / US-40 @ 2500 S / MP 147.9, NPL", "roadway": "US 40", "lat": 40.41873, "lon": -109.4981},
    {"name": "200 E / US-40 @ 200 N / US-40 / SR-121 / MP 114.58, RSV", "roadway": "US 40", "lat": 40.30198, "lon": -109.98874},
    {"name": "200 N / US-40 @ 1500 E / MP 115.42, BAL", "roadway": "US 40", "lat": 40.30212, "lon": -109.97274},
    {"name": "200 N / US-40 @ 5750 E / Whiterocks Hwy / MP 119.66, FTD", "roadway": "US 40", "lat": 40.30202, "lon": -109.89227},
    {"name": "200 N / US-40 @ 7500 E / MP 121.41, FTD", "roadway": "US 40", "lat": 40.302, "lon": -109.85906},
    {"name": "Main St / US-40 @ 100 S / MP 143.4, VNL", "roadway": "US 40", "lat": 40.45404, "lon": -109.5455},
    {"name": "Main St / US-40 @ 100 S / MP 17, HBR", "roadway": "US 40", "lat": 40.50635, "lon": -111.41349},
    {"name": "Main St / US-40 @ 200 S, RSV", "roadway": "US 40", "lat": 40.296883, "lon": -109.988671},
    {"name": "Main St / US-40 @ 2000 W / Hancock Cove Rd / MP 111.5, RSV", "roadway": "US 40", "lat": 40.2741, "lon": -110.02858},
    {"name": "Main St / US-40 @ 2100 W / MP 141.64, VNL", "roadway": "US 40", "lat": 40.43643, "lon": -109.56906},
    {"name": "Main St / US-40 @ 500 N / MP 16.4, HBR", "roadway": "US 40", "lat": 40.51418, "lon": -111.41339},
    {"name": "Main St / US-40 @ 500 W / SR-121, VNL", "roadway": "US 40", "lat": 40.455728, "lon": -109.538204},
    {"name": "Main St / US-40 @ 900 N / MP 16.2, HBR", "roadway": "US 40", "lat": 40.518367, "lon": -111.411544},
    {"name": "Main St / US-40 @ Center St / SR-87 / MP 86.54, DCH", "roadway": "US 40", "lat": 40.16353, "lon": -110.4012},
    {"name": "Main St / US-40 @ US-189 / 1200 S / MP 17.94, HBR", "roadway": "US 40", "lat": 40.49306, "lon": -111.41371},
    {"name": "Main St / US-40 @ Vernal Ave / US-191 / MP 144.3, VNL", "roadway": "US 40", "lat": 40.45578, "lon": -109.52854},
    {"name": "US-40 @ 1500 S / MP 141.36, UN", "roadway": "US 40", "lat": 40.4334, "lon": -109.573},
    {"name": "US-40 @ 2050 S / MP 18.81, HBR", "roadway": "US 40", "lat": 40.48254, "lon": -111.40286},
    {"name": "US-40 @ 500 E / MP 87, DCH", "roadway": "US 40", "lat": 40.16252, "lon": -110.39237},
    {"name": "US-40 @ 500 S / MP 143.12, VNL", "roadway": "US 40", "lat": 40.44827, "lon": -109.55343},
    {"name": "US-40 @ 500 S / MP 146.2, VNL", "roadway": "US 40", "lat": 40.448803, "lon": -109.501962},
    {"name": "US-40 @ Daniels Summit / MP 34.21, WA", "roadway": "US 40", "lat": 40.30295, "lon": -111.25748},
    {"name": "US-40 @ Deer Hollow Rd / SR-319 / MP 8.22, WA", "roadway": "US 40", "lat": 40.62562, "lon": -111.4401},
    {"name": "US-40 @ Gray Mountain Canal / MP 95.92, DU", "roadway": "US 40", "lat": 40.15279, "lon": -110.23552},
    {"name": "US-40 @ Ioka Ln / SR-87 / MP 109.46, DU", "roadway": "US 40", "lat": 40.257935, "lon": -110.060914},
    {"name": "US-40 @ Jordanelle Reservoir / MP 9.8, WA", "roadway": "US 40", "lat": 40.60451, "lon": -111.42882},
    {"name": "US-40 @ Milepost 1.85, SU", "roadway": "US 40", "lat": 40.71104, "lon": -111.48142},
    {"name": "US-40 @ Milepost 10.62, WA", "roadway": "US 40", "lat": 40.59428, "lon": -111.43667},
    {"name": "US-40 @ Milepost 134.85, UN", "roadway": "US 40", "lat": 40.34913, "lon": -109.62483},
    {"name": "US-40 @ Milepost 173.6, UN", "roadway": "US 40", "lat": 40.28015, "lon": -109.06794},
    {"name": "US-40 @ Milepost 27.53, WA", "roadway": "US 40", "lat": 40.38758, "lon": -111.3033},
    {"name": "US-40 @ Milepost 3, SU", "roadway": "US 40", "lat": 40.69769, "lon": -111.47272},
    {"name": "US-40 @ Milepost 49.14, WA", "roadway": "US 40", "lat": 40.18421, "lon": -111.05772},
    {"name": "US-40 @ Milepost 69.81, DU", "roadway": "US 40", "lat": 40.20058, "lon": -110.70278},
    {"name": "US-40 @ River Rd / SR-32 / MP 13.7, WA", "roadway": "US 40", "lat": 40.5572, "lon": -111.426},
    {"name": "US-40 @ Silver Summit Pkwy / MP 1.31, SU", "roadway": "US 40", "lat": 40.71863, "lon": -111.48586},
    {"name": "US-40 @ SR-248 / Kearns Blvd / Quinns Jct / MP 3.89, SU", "roadway": "US 40", "lat": 40.68571, "lon": -111.46245},
    {"name": "US-40 @ State St / MP 114.1, RSV", "roadway": "US 40", "lat": 40.292603, "lon": -109.991679},
    {"name": "US-40 @ Strawberry Rd / MP 40.4, WA", "roadway": "US 40", "lat": 40.24105, "lon": -111.18148},
    {"name": "US-40 @ Strawberry Reservoir / MP 42, WA", "roadway": "US 40", "lat": 40.24123, "lon": -111.15158},
    {"name": "US-40 @ Strawberry Reservoir Ladders / MP 45.2, WA", "roadway": "US 40", "lat": 40.21712, "lon": -111.10391},
    {"name": "US-40 @ WA/DU County Line / MP 59, DU", "roadway": "US 40", "lat": 40.19842, "lon": -110.89071},
    {"name": "US-40 RWIS EB @ Asphalt Ridge / MP 140.1, UN", "roadway": "US 40", "lat": 40.41636, "lon": -109.58223},
    {"name": "US-40 RWIS EB @ Fruitland / MP 66, DU", "roadway": "US 40", "lat": 40.20525, "lon": -110.7714},
    {"name": "US-40 RWIS WB @ Myton / MP 105.3, MYT", "roadway": "US 40", "lat": 40.19943, "lon": -110.06792},
    {"name": "US-40 SB @ Lodge Pole / MP 33.43, WA", "roadway": "US 40", "lat": 40.31373, "lon": -111.25738},
    {"name": "Main St / US-40 @ 100 W / US-191, DCH", "roadway": "US-40", "lat": 40.163547, "lon": -110.403244},
    {"name": "Main St / US-40 @ Coyote Canyon Pkwy, HBR", "roadway": "US-40", "lat": 40.529608, "lon": -111.40958},
    {"name": "Main St / US-6 @ 100 E, WTN", "roadway": "US 6", "lat": 39.54227, "lon": -110.73421},
    {"name": "US-6 @ 100 N / SR-55, PRC", "roadway": "US 6", "lat": 39.60074, "lon": -110.82844},
    {"name": "US-6 @ 1000 N / MP 231.74, HLP", "roadway": "US 6", "lat": 39.70065, "lon": -110.86859},
    {"name": "US-6 @ Billies Mtn / MP 186.37, UT", "roadway": "US 6", "lat": 40.00091, "lon": -111.48781},
    {"name": "US-6 @ Cedar Haven / Sheep Creek Rd / MP 195.08, UT", "roadway": "US 6", "lat": 39.97246, "lon": -111.33565},
    {"name": "US-6 @ Colton Shed / MP 217.11, UT", "roadway": "US 6", "lat": 39.85886, "lon": -111.02763},
    {"name": "US-6 @ Diamond Fork / MP 184.9, UT", "roadway": "US 6", "lat": 40.02107, "lon": -111.498084},
    {"name": "US-6 @ Gilluly Switchback / MP 206.46, UT", "roadway": "US 6", "lat": 39.93311, "lon": -111.15338},
    {"name": "US-6 @ Main St / MP 232.7, HLP", "roadway": "US 6", "lat": 39.69141, "lon": -110.85715},
    {"name": "US-6 @ MP 212.15, WA", "roadway": "US-6", "lat": 39.9124, "lon": -111.06242},
    {"name": "US-6 @ Tie Fork Rest Area / MP 202.05, UT", "roadway": "US 6", "lat": 39.95004, "lon": -111.21818},
    {"name": "US-6 @ US-191 / MP 229.82, CC", "roadway": "US 6", "lat": 39.725804, "lon": -110.867521},
    {"name": "US-6 @ US-191 / MP 230.1, CC", "roadway": "US 6", "lat": 39.727174, "lon": -110.86735},
    {"name": "US-6 @ US-89 / MP 187.47, UT", "roadway": "US 6", "lat": 39.99486, "lon": -111.469},
    {"name": "US-6 RWIS EB @ 200 N / MP 232.4, HLP", "roadway": "US 6", "lat": 39.69346, "lon": -110.86279},
    {"name": "US-6 RWIS EB @ SR-123 / MP 256, CC", "roadway": "US 6", "lat": 39.52615, "lon": -110.5745},
    {"name": "US-6 WB @ Carbon Ave / SR-10, PRC", "roadway": "US 6", "lat": 39.58842, "lon": -110.81163},
    {"name": "US-6 WB @ Milepost 222.3, CC", "roadway": "US 6", "lat": 39.81107, "lon": -110.94144},
    {"name": "US-6 WB @ Soldier Summit / MP 210.36, UT", "roadway": "US 6", "lat": 39.92892, "lon": -111.084},
    {"name": "State St / US-89 @ Main St / SR-116, MTP", "roadway": "US 89", "lat": 39.54686, "lon": -111.45517},
    {"name": "US-89 @ Thistle / MP 311.09, UT", "roadway": "US 89", "lat": 39.9917, "lon": -111.49836},
    {"name": "US-89 RWIS NB @ Hilltop / MP 290.12, SP", "roadway": "US 89", "lat": 39.715619, "lon": -111.470913},
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
