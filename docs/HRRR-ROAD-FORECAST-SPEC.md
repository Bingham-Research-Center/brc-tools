# HRRR Road Forecast — Website Integration Spec

Handoff document for the BasinWX website repo. The Python script (`brc_tools/download/get_road_forecast.py`) runs on CHPC and pushes forecast JSON to the website hourly.

## 1. Overview

- **Source model**: HRRR (High-Resolution Rapid Refresh), 3-km grid, hourly runs
- **Forecast range**: Hours 1–12 from the latest available initialization
- **Update frequency**: Hourly at `:50` via cron (`50 * * * *`)
- **Coverage**: 3 routes (~17 waypoints) + 146 UDOT cameras (~80–100 unique grid cells)
- **Output size**: ~150–200 KB JSON

## 2. Upload Endpoint

Follows the existing `push_data.py` pattern (multipart file upload with API key header).

```
POST /api/upload/road-forecast
```

**Headers:**
```
x-api-key: <DATA_UPLOAD_API_KEY>
x-client-hostname: <CHPC hostname>
Content-Type: multipart/form-data
```

**Body:**
- `file`: The JSON file (`road_forecast_YYYYMMDD_HHMMZ.json`)

**Response (success):**
```json
{ "success": true, "message": "road-forecast data uploaded" }
```

**Server-side**: Store the uploaded JSON (overwrite previous). Suggested path: `data/road-forecast/latest.json`.

## 3. Retrieval Endpoint

```
GET /api/road-weather/forecast
```

Returns the latest stored road forecast JSON (see schema below). If no forecast has been uploaded yet, return:

```json
{ "success": false, "error": "No road forecast data available" }
```

## 4. JSON Schema

```json
{
  "model": "hrrr",
  "init_time": "2026-03-02T12:00:00Z",
  "generated_at": "2026-03-02T12:50:00Z",
  "forecast_hours": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
  "valid_times": [
    "2026-03-02T13:00:00Z",
    "2026-03-02T14:00:00Z",
    "..."
  ],
  "variables": {
    "temp_2m":        { "units": "Celsius",  "display": "Temperature" },
    "wind_speed_10m": { "units": "m/s",      "display": "Wind Speed" },
    "wind_gust":      { "units": "m/s",      "display": "Wind Gust" },
    "visibility":     { "units": "km",       "display": "Visibility" },
    "precip_1hr":     { "units": "mm",       "display": "1-hr Precip" },
    "precip_type":    { "units": "category", "display": "Precip Type" },
    "snow_depth":     { "units": "mm",       "display": "Snow Depth" },
    "cloud_cover":    { "units": "%",        "display": "Cloud Cover" },
    "rh_2m":          { "units": "%",        "display": "Relative Humidity" }
  },
  "routes": {
    "us40": {
      "name": "US-40 Corridor",
      "waypoints": [
        {
          "name": "Daniels Summit",
          "lat": 40.30,
          "lon": -111.26,
          "elevation_m": 2438,
          "reference_stid": "UTDAN",
          "forecasts": {
            "temp_2m": [-5.2, -5.8, -6.1, -6.3, -5.9, -5.0, -4.2, -3.8, -3.5, -4.1, -5.0, -5.5],
            "wind_speed_10m": [3.1, 3.5, 4.2, 4.8, 5.1, 4.9, 4.3, 3.8, 3.2, 3.0, 2.8, 2.5],
            "wind_gust": [6.2, 7.1, 8.4, 9.6, 10.2, 9.8, 8.6, 7.6, 6.4, 6.0, 5.6, 5.0],
            "visibility": [10.0, 10.0, 8.5, 4.2, 2.1, 3.5, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "precip_1hr": [0.0, 0.0, 0.5, 1.2, 1.8, 0.8, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0],
            "precip_type": ["none", "none", "snow", "snow", "snow", "snow", "none", "none", "none", "none", "none", "none"],
            "snow_depth": [152.0, 152.0, 155.0, 160.0, 168.0, 172.0, 172.0, 172.0, 172.0, 172.0, 172.0, 172.0],
            "cloud_cover": [25.0, 45.0, 80.0, 95.0, 100.0, 90.0, 60.0, 30.0, 20.0, 15.0, 10.0, 10.0],
            "rh_2m": [55.0, 65.0, 82.0, 95.0, 98.0, 90.0, 70.0, 55.0, 50.0, 48.0, 45.0, 42.0]
          }
        }
      ]
    },
    "us191": { "name": "US-191 North-South", "waypoints": ["..."] },
    "basin_roads": { "name": "Local Basin Roads", "waypoints": ["..."] }
  },
  "cameras": [
    {
      "name": "US-40 @ Daniels Summit / MP 34.21, WA",
      "roadway": "US 40",
      "lat": 40.30295,
      "lon": -111.25748,
      "forecasts": {
        "temp_2m": [-5.2, -5.8, "...12 values..."],
        "wind_speed_10m": [3.1, 3.5, "..."],
        "...same 9 variables as route waypoints..."
      }
    }
  ]
}
```

Each waypoint's `forecasts` object contains arrays of length 12, indexed by forecast hour (position 0 = fxx 1, position 11 = fxx 12). Use `valid_times[i]` to get the valid time for position `i`.

The `cameras` array is flat (not grouped by route). Each camera has a `roadway` field that the frontend can use to filter by road. Because HRRR is 3-km resolution, multiple cameras in the same town will map to the same grid cell and share identical forecast arrays. The script deduplicates by grid cell so extraction is efficient (~80–100 unique cells for 146 cameras).

## 5. Variable Reference

| Variable | Units | Typical Range | Description |
|----------|-------|---------------|-------------|
| `temp_2m` | Celsius | -30 to 45 | 2-meter air temperature |
| `wind_speed_10m` | m/s | 0 to 30 | 10-meter wind speed (derived from U/V components) |
| `wind_gust` | m/s | 0 to 50 | Surface wind gust |
| `visibility` | km | 0 to 24+ | Surface visibility |
| `precip_1hr` | mm | 0 to 50 | 1-hour accumulated precipitation |
| `precip_type` | category | — | One of: `none`, `rain`, `snow`, `freezing_rain`, `ice_pellets`, `mixed` |
| `snow_depth` | mm | 0 to 5000 | Snow depth on ground |
| `cloud_cover` | % | 0 to 100 | Total cloud cover |
| `rh_2m` | % | 0 to 100 | 2-meter relative humidity |

## 6. Frontend Integration

### Where it fits in `roads.html`

Add forecast sections inside each `.route-section` (US-40, US-191, Basin Roads), below the existing `displayRouteConditions()` output. Suggested structure:

```html
<div class="route-forecast">
    <h3>12-Hour HRRR Forecast</h3>
    <div class="forecast-timeline" data-route="us40">
        <!-- Populated by JS -->
    </div>
</div>
```

### Display suggestions

- **Hour-by-hour cards**: A scrollable row of compact cards (one per forecast hour) showing temp, wind icon, precip icon, visibility
- **Weather icons per precip type**: snowflake for `snow`, raindrop for `rain`, warning triangle for `freezing_rain`/`ice_pellets`/`mixed`
- **Color-coding**: Temperature gradient (blue for cold, red for hot); visibility red/yellow/green bands
- **Mini meteogram**: Simple bar chart or sparkline per waypoint (no Plotly needed — CSS bars or inline SVG work fine since Plotly is not currently loaded per ROADS.md line 142)
- **Waypoint selector**: Dropdown or clickable list to switch between waypoints within a route

### Fetching data

```javascript
async function loadRoadForecast() {
    const response = await fetch('/api/road-weather/forecast');
    if (!response.ok) return;
    const data = await response.json();
    if (data.routes) {
        renderRouteForecast('us40', data);
        renderRouteForecast('us191', data);
        renderRouteForecast('basin_roads', data);
    }
}
```

Call from the `DOMContentLoaded` block alongside `loadRouteConditions()`.

### Units toggle

The existing `UnitsSystem` class handles Fahrenheit/Celsius and mph/m-s conversions. Hook into `refreshUnitsDisplays()` to re-render forecast cards when the user toggles units.

## 7. Cache Strategy

Use `NodeCache` with a 3600-second TTL (data updates hourly at :50). Fits the existing `roadWeatherService.js` pattern:

```javascript
const FORECAST_CACHE_KEY = 'hrrr_road_forecast';
const FORECAST_TTL = 3600; // seconds

async fetchRoadForecast() {
    const cached = cache.get(FORECAST_CACHE_KEY);
    if (cached) return cached;

    // Read from stored file or DB
    const data = await this.loadLatestForecast();
    cache.set(FORECAST_CACHE_KEY, data, FORECAST_TTL);
    return data;
}
```

Invalidate the cache when a new upload arrives at `POST /api/upload/road-forecast`.

## 8. Cron Schedule

On CHPC, add to crontab (see `docs/CHPC-REFERENCE.md` for full cron listing):

```
50 * * * * ~/gits/brc-tools/scripts/run_road_forecast.sh
0 4 * * * ~/gits/brc-tools/scripts/rotate_logs.sh
```

The wrapper script (`scripts/run_road_forecast.sh`) handles conda activation, logging to `~/logs/road_forecast.log`, and exit-code tracking. HRRR data is typically available ~45 minutes after initialization, so running at :50 gives a 5-minute buffer.
