# Python/CHPC Developer To-Do List
## Station Data Export Requirements for brc-tools

### CRITICAL: Stations Missing from Data Export
These stations need to be added to the Synoptic API pull in brc-tools:

1. **COOPDINU1** - Dinosaur NM-QUARRY AREA
   - Display Name: "Dinosaur NM"
   - Location: 40.44°N, -109.31°W
   - Critical for northern basin coverage
   
2. **COOPALMU1** - ALTAMONT
   - Display Name: "Altamont"
   - Location: 40.37°N, -110.30°W
   - Important for NW basin coverage

3. **COOPDSNU1** - DUCHESNE
   - Display Name: "Duchesne"
   - Location: 40.17°N, -110.40°W
   - County seat - important population center
   - **Alternative if unavailable:** KU69 (DUCHESNE Airport) already has data

### NEW STATIONS TO ADD (if available):
4. **Station near Windy Point/Steinaker**
   - Display Name: "Windy Point"
   - Target Location: ~40.52°N, -109.55°W
   - Purpose: Coverage between Vernal and recreation areas
   - **Search for:** Weather stations near Steinaker Reservoir or US-191 north of Vernal

### CONFIRMED WORKING:
- **K40U (MANILA)** - Already has data, good for Dutch John area coverage

### Station ID Mapping Reference
The website expects these exact station IDs (case-sensitive):

```python
# Core Air Quality Monitoring
'UBHSP'      -> 'Horsepool'
'UBCSP'      -> 'Castle Peak'
'UB7ST'      -> 'Seven Sisters'

# Population Centers
'KVEL'       -> 'Vernal'
'K74V'       -> 'Roosevelt'
'COOPDSNU1'  -> 'Duchesne'      # NEEDS ADDING
'KU69'       -> 'Duchesne'      # Alternative (already works)
'UINU1'      -> 'Fort Duchesne'

# Basin Perimeter & Geographic Coverage
'UTMYT'      -> 'Myton'
'COOPDINU1'  -> 'Dinosaur NM'   # NEEDS ADDING
'COOPALMU1'  -> 'Altamont'      # NEEDS ADDING
'UCC34'      -> 'Bluebell'
'UTASH'      -> 'Asphalt Ridge'
'UTSTV'      -> 'Starvation'

# Mountain Passes
'UTDAN'      -> 'Daniels Summit'
'UTICS'      -> 'Indian Canyon'
'UTSLD'      -> 'Soldier Summit'
```

### Variable Name Mapping
Ensure these variable names are used in the JSON export:

```python
variable_mapping = {
    # Required variables
    'air_temp': 'Temperature',
    'ozone_concentration': 'Ozone',  # Critical for color coding
    'PM_25_concentration': 'PM2.5',  # Note: was 'pm25_concentration' 
    'NOx_concentration': 'NOx',
    
    # Supporting variables
    'wind_speed': 'Wind Speed',
    'wind_direction': 'Wind Direction', 
    'relative_humidity': 'Humidity',
    'pressure': 'Pressure',
    'dew_point_temperature': 'Dew Point',
    'snow_depth': 'Snow Depth',
    'soil_temp': 'Soil Temperature'
}
```

### Data Export Format
The website expects this exact JSON structure:

```json
[
  {
    "stid": "COOPDINU1",
    "variable": "air_temp",
    "value": 25.5,
    "date_time": "2025-07-31T02:10:00.000Z",
    "units": "Celsius"
  },
  ...
]
```

### Priority Additions for Complete Coverage

1. **Add COOPDINU1 (Dinosaur NM)** - Currently showing "Data missing" on map
2. **Add COOPALMU1 (Altamont)** - Gap in NW basin coverage
3. **Add COOPDSNU1 (Duchesne)** - Or ensure KU69 is consistently available

### Optional Future Enhancements

Consider adding these stations if available:
- **Rangely, CO** - Eastern basin influence
- **Dry Fork** - Additional coverage
- **Whiterocks** (if different from existing stations)
- **Ouray** (tribal station if data sharing agreed)

### Testing Checklist
After adding stations, verify:
- [ ] Station appears in `map_obs_YYYYMMDD_HHMMZ.json`
- [ ] Station metadata in `map_obs_meta_YYYYMMDD_HHMMZ.json`
- [ ] Station ID matches exactly (case-sensitive)
- [ ] At minimum has `air_temp` data
- [ ] Ideally has `ozone_concentration` for proper color coding

### Files to Update in brc-tools
1. Station list for Synoptic API query
2. Variable name mapping if different
3. Any station ID transformations

### Notes
- The website now displays 16 stations for comprehensive basin coverage
- Kiosk mode cycles through all stations every 4 seconds
- Ozone data determines marker color (green/orange/red)
- Missing ozone defaults to gray marker