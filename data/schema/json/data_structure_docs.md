# Map Observations Data Structure Guide
**For Uinta Basin Air Quality Website**

## **Quick Summary**
- **298 records** from **46 weather stations**
- **15 different variables** (temperature, wind, air quality, etc.)
- **5-field structure**: station ID, variable name, value, timestamp, units
- **6 air quality stations** with ozone/PM2.5 data

---

## **1. Basic Structure (For Beginners)**

Each record represents **one measurement from one station at one time**:

```json
{
  "stid": "UBCSP",                        // Station ID
  "variable": "ozone_concentration",       // What was measured
  "value": 51.13,                        // The measurement
  "date_time": "2025-07-29T23:15:00.000Z", // When (UTC time)
  "units": "ppb"                         // Units (parts per billion)
}
```

**Think of it like:** "At station UBCSP, ozone was 51.13 ppb at 23:15 UTC"

---

## **2. Station Coverage (46 Stations)**

**Air Quality Stations (6):** UBCSP, WBB, QCV, QHV, QHW, QSM
**Airport/METAR (11):** K40U, K74V, KCDC, KENV, KHCR, KHIF, KOGD, KPVU, KSPK, KSVR, KU69, KVEL
**University of Utah (17):** UT* stations (UTASH, UTCOP, UTDAN, etc.)
**Other Networks (12):** Mix of research and operational stations

**Station Data Completeness:**
- UBCSP: 12 variables (most complete air quality station)
- UBHSP, WBB: 10 variables each
- Many stations: 2-8 variables (typical for focused measurements)

---

## **3. Variable Types (15 Total)**

### **Core Weather Variables**
```
air_temp           → Celsius      → -48.34 to 38.89°C
wind_speed         → m/s          → 0.00 to 6.53 m/s  
wind_direction     → Degrees      → 0 to 360°
dew_point_temperature → Celsius   → -12.6 to 4.2°C
```

### **Air Quality Variables**
```
ozone_concentration → ppb         → 27.75 to 51.13 ppb (6 stations)
PM_25_concentration → ug/m3       → 1.0 to 16.9 µg/m³ (5 stations)
NOx_concentration   → ppb         → 0.79 ppb (1 station)
```

### **Pressure Variables**
```
pressure           → Pascals      → ~82,000-87,000 Pa
sea_level_pressure → Pascals      → ~100,000-101,500 Pa  
altimeter          → Pascals      → ~101,000-103,500 Pa
```

### **Other Variables**
```
solar_radiation    → W/m**2       → 0.98 to 752 W/m²
soil_temp         → Celsius      → 10.9 to 31.8°C
snow_depth        → Millimeters  → 0 to 355.6 mm
ceiling           → Meters       → 1,676 to 5,486 m
outgoing_radiation_sw → W/m**2   → 14.5 to 52.5 W/m²
```

---

## **4. Website Integration Guide**

### **For Interactive Map Display**
```javascript
// Group by station for map markers
const stationData = {};
data.forEach(record => {
  if (!stationData[record.stid]) {
    stationData[record.stid] = {};
  }
  stationData[record.stid][record.variable] = {
    value: record.value,
    units: record.units,
    time: record.date_time
  };
});
```

### **For Data Tables**
```javascript
// Filter by variable type
const ozoneStations = data
  .filter(d => d.variable === 'ozone_concentration')
  .map(d => ({
    station: d.stid,
    ozone: `${d.value} ${d.units}`,
    time: new Date(d.date_time).toLocaleString()
  }));
```

### **For Charts/Time Series**
```javascript
// Get temperature data for plotting
const tempData = data
  .filter(d => d.variable === 'air_temp')
  .map(d => ({
    x: new Date(d.date_time),
    y: d.value,
    station: d.stid
  }));
```

---

## **5. Data Quality & Edge Cases**

### **✅ Good Data Patterns**
- All records have required fields
- Units are consistent per variable
- Timestamps in ISO 8601 format (UTC)
- Reasonable value ranges

### **⚠️ Watch Out For**
```javascript
// Missing data - not all stations have all variables
if (stationData[stid]?.ozone_concentration) {
  // Station has ozone data
} else {
  // Show "No ozone data available"
}

// Zero wind speed/direction (calm conditions)
if (windSpeed === 0 && windDirection === 0) {
  // Display as "Calm" instead of "0 m/s from 0°"
}

// Extreme values (check for sensor errors)
if (airTemp < -50 || airTemp > 50) {
  // Flag as potentially erroneous
}
```

### **Station Coverage Gaps**
- Only **6 of 46 stations** have air quality data
- Airport stations (K*) focus on aviation variables
- Research stations (UT*) vary in sensor suites
- Timing differences: some stations update every 15min, others hourly

---

## **6. Polars DataFrame → JSON Best Practices**

### **Standard Processing Pipeline**
```python
# In your download script
from brc_tools.schemas.canonical_examples import validate_schema

# After processing synoptic data:
df_clean = df.select([
    pl.col("stid"),           # Station ID
    pl.col("variable"),       # Variable name  
    pl.col("value"),          # Numeric value
    pl.col("date_time"),      # UTC timestamp
    pl.col("units")           # Units string
])

# Validate structure
validate_schema(df_clean, "map_obs")

# Export to JSON
df_clean.to_pandas().to_json(filepath, orient='records', indent=2)
```

### **Standardized Variable Names**
```python
# Use consistent naming (from your utils/lookups)
VARIABLE_MAPPING = {
    'temp': 'air_temp',
    'ozone': 'ozone_concentration', 
    'pm25': 'PM_25_concentration',
    'wspd': 'wind_speed',
    'wdir': 'wind_direction'
}
```

---

## **7. Error Handling for Website**

```javascript
// Robust data access
function getStationValue(stid, variable) {
  const records = data.filter(d => 
    d.stid === stid && d.variable === variable
  );
  
  if (records.length === 0) {
    return { value: null, status: 'no_data' };
  }
  
  const latest = records.sort((a, b) => 
    new Date(b.date_time) - new Date(a.date_time)
  )[0];
  
  return {
    value: latest.value,
    units: latest.units,
    time: latest.date_time,
    status: 'ok'
  };
}
```

---

## **8. File Naming Convention**

Your current format: `map_obs_20250204_0000Z.json`
- ✅ Includes data type prefix
- ✅ ISO date format  
- ✅ UTC timezone indicator
- ✅ Consistent with `generate_json_fpath()` function

**Website expects:** Files in `/public/data/` accessible via `/api/live-observations`

---

## **Summary for Developers**

**🔍 Data Structure:** Simple 5-field records, one per measurement  
**🌐 Coverage:** 46 stations, 15 variables, focus on Uinta Basin  
**💨 Air Quality:** 6 stations with ozone/PM2.5 (UBCSP most complete)  
**⚠️ Gaps:** Not all stations measure all variables  
**📊 Usage:** Group by station for maps, filter by variable for analysis  
**🔄 Updates:** Real-time data, expect ~298 records per file  

The structure is designed to be **flexible** (easy to add new stations/variables) and **predictable** (consistent field names and units).