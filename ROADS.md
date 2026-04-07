# /roads Page — Complete Architecture

## Overview
Real-time road conditions dashboard for the Uintah Basin. Full-screen Leaflet map at `[40.3033, -109.7]` zoom 10, with UDOT data layers, condition cards, route forecasts, and travel advisories.

## Data Flow
```
UDOT APIs → server/roadWeatherService.js (NodeCache) → /api/road-weather/* → public/js/roads.js → Leaflet layers
```

## Key Files

| File | Purpose | Size |
|------|---------|------|
| `views/roads.html` | Page template, map + sections | ~254 lines |
| `public/js/roads.js` | All frontend logic | ~3116 lines |
| `public/css/roads.css` | All styling | ~1600+ lines |
| `server/routes/roadWeather.js` | 7 API endpoints | ~139 lines |
| `server/roadWeatherService.js` | UDOT API wrappers + caching | Large, class-based |
| `server/routes/trafficEvents.js` | Traffic event endpoints | Separate router |
| `server/backgroundRefresh.js` | Cron-based UDOT data refresh | Runs on server boot |

## Backend: roadWeatherService.js

### Class: `RoadWeatherService`
- **Constructor**: Sets `this.udotApiKey` from env, `this.nwsUserAgent`, `this.uintahBasinBounds` (N:41.0, S:39.5, E:-108.5, W:-111.5)
- **Caching**: Module-level `const cache = new NodeCache({ stdTTL: 300 })` — every method checks cache first
- **Cache pattern**:
  ```js
  const cacheKey = 'udot_road_conditions';
  const cached = cache.get(cacheKey);
  if (cached) return cached;
  // ... fetch + process ...
  cache.set(cacheKey, processedData); // optional custom TTL as 3rd arg
  ```

### Methods & Cache TTLs
| Method | Cache Key | TTL | Source |
|--------|-----------|-----|--------|
| `fetchUDOTRoadConditions()` | `udot_road_conditions` | 300s (default) | UDOT road conditions API |
| `fetchUDOTWeatherStations()` | `udot_weather_stations` | 300s | UDOT weather stations API |
| `fetchUDOTCameras()` | `udot_cameras` | 300s | UDOT cameras API |
| `fetchSnowPlows()` | `udot_snow_plows` | 60s | UDOT service vehicles API |
| `fetchMountainPasses()` | `udot_mountain_passes` | 300s | UDOT mountain passes API |
| `fetchUDOTRestAreas()` | `udot_rest_areas` | 3600s | UDOT rest areas API |
| `fetchUDOTDigitalSigns()` | `udot_digital_signs` | 300s | UDOT digital signs API |
| `fetchNWSData(lat, lon)` | per-location | 300s | NWS API |
| `fetchOpenMeteoData(lat, lon)` | per-location | 300s | Open-Meteo API |
| `getCompleteRoadData()` | none | — | Aggregates multiple fetches via Promise.all |

### Geographic Filtering
All UDOT data is filtered to Uintah Basin bounds using lat/lon checks. Road conditions use polyline decoding to check if any segment passes through bounds.

## Backend: routes/roadWeather.js

### Pattern
```js
import express from 'express';
import RoadWeatherService from '../roadWeatherService.js';
const router = express.Router();
const roadWeatherService = new RoadWeatherService(); // single instance
// ... router.get() handlers ...
export default router;
```

### Endpoints (all prefixed with /api by server.js)
| Endpoint | Handler |
|----------|---------|
| `GET /road-weather` | `getCompleteRoadData()` — aggregated response |
| `GET /road-weather/stations` | Weather stations |
| `GET /road-weather/openmeteo/:lat/:lon` | Open-Meteo point forecast |
| `GET /road-weather/snow-plows` | Snow plow positions |
| `GET /road-weather/mountain-passes` | Pass status |
| `GET /road-weather/rest-areas` | Rest area info |
| `GET /road-weather/digital-signs` | Digital sign messages |

### Response Format
```js
res.json({
    success: true,
    timestamp: new Date().toISOString(),
    totalItems: items.length,
    // ... summary counts specific to data type ...
    items: items  // or plows, passes, restAreas, signs
});
```

### Error Format
```js
res.status(500).json({
    success: false,
    error: 'Human-readable error message',
    message: error.message
});
```

## Frontend: roads.html Structure

```
<head>: main.css, roads.css, Leaflet CSS, Google Fonts, Font Awesome
<body data-page-type="roads">
  .colored-bar
  .sidebar_container (loaded via loadSidebar.js)
  <main class="content">
    <h1>Road Weather Conditions</h1>

    Section 1: .road-weather-dashboard
      └ .map-container-fullscreen (600px height, border-radius 16px)
        ├ #road-map (Leaflet map)
        ├ .conditions-overlay (bottom card strip: road surface, visibility, precip, wind)
        └ .units-toggle-container (Imperial/Metric toggle)

    Section 2: .routes-container
      ├ #us40-section (US-40 Corridor)
      ├ #us191-section (US-191 North-South)
      └ #basin-roads-section (Local Basin Roads with carousel)
          └ carousel-controls, carousel-indicators, prev/next buttons

    Section 3: .advisory-section
      └ .traffic-events-container
        ├ .events-tabs: Active | Upcoming | All (data-tab attribute buttons)
        └ .events-content: tab-content divs (#active-events, #upcoming-events, #all-events)

    Section 4: .udot-alerts-section
      └ #alerts-container

    Section 5: .resources-section
      └ .resources-grid (UDOT CommuterLink, Utah Road Weather links)

  <footer>
  Scripts: Leaflet.js, map-state-manager.js, loadSidebar.js (module), roads.js, easter-eggs.js
```

**Loading spinner pattern** (used in every section):
```html
<div class="conditions-loading">
    <i class="fas fa-spinner fa-spin"></i>
    <p>Loading current conditions...</p>
</div>
```

**No Plotly.js currently loaded** — would need to add `<script>` tag if adding meteograms.

## Frontend: roads.js Architecture (~3116 lines)

### File Layout (top to bottom)

#### 1. UnitsSystem class (lines 1-72)
- Conversion methods: `formatTemperature(F)`, `formatWindSpeed(mph)`, `formatVisibility(miles)`
- `toggle()` persists to localStorage key `'unitsSystem'`
- Global instance: `const unitsSystem = new UnitsSystem()`

#### 2. routeDataCache (lines 78-112)
- Client-side 5-minute cache for stations + events
- `isValid()`, `updateCache()`, `getData()` methods
- Fetches from `/api/road-weather/stations` + `/api/traffic-events`

#### 3. RoadWeatherMap class (lines 115-990)
**Constructor** stores layer Maps:
```js
this.roadLayers = new Map();
this.stationMarkers = new Map();
this.cameraMarkers = new Map();
this.trafficEventMarkers = new Map();
this.closureOverlays = new Map();
this.snowPlowMarkers = new Map();
this.snowPlowRoutes = new Map();
this.mountainPassMarkers = new Map();
this.restAreaMarkers = new Map();
```

**init()** calls in order:
1. `initMap()` — L.map setup with OSM tiles, custom closure pane (z-index 10000)
2. `addLegend()` — road condition color legend
3. `loadRoadWeatherData()` — fetch /api/road-weather, render roads + stations + cameras
4. `loadTrafficEvents()` — fetch /api/traffic-events
5. `loadTrafficAlerts()` — fetch digital signs for alerts
6. `loadSnowPlows()` — fetch /api/road-weather/snow-plows (60s refresh)
7. `loadMountainPasses()` — fetch /api/road-weather/mountain-passes
8. `loadRestAreas()` — fetch /api/road-weather/rest-areas
9. `startAutoRefresh()` — 5-minute interval for main data, 1-minute for plows

**Layer rendering pattern** (each data type):
```js
async loadSomething() {
    const response = await fetch('/api/road-weather/something');
    if (!response.ok) throw new Error(...);
    const data = await response.json();
    if (data.success && data.items) {
        this.renderSomething(data.items);
    }
}
renderSomething(items) {
    this.somethingMarkers.forEach(m => this.map.removeLayer(m));
    this.somethingMarkers.clear();
    items.forEach(item => {
        const marker = L.marker([item.lat, item.lon], { ... })
            .bindPopup(this.createSomethingPopup(item))
            .addTo(this.map);
        this.somethingMarkers.set(item.id, marker);
    });
}
```

#### 4. Prototype extensions (lines ~1163-1983)
Additional methods added via `RoadWeatherMap.prototype.methodName = async function() { ... }`:
- `loadTrafficEvents()`, `renderTrafficEvents()`
- `loadTrafficAlerts()`
- `loadSnowPlows()`, `renderSnowPlows()`
- `loadMountainPasses()`, `renderMountainPasses()`
- `loadRestAreas()`, `renderRestAreas()`

#### 5. DOMContentLoaded initialization (lines 995-1046)
```js
roadWeatherMap = new RoadWeatherMap('road-map', {
    center: [40.3033, -109.7],
    zoom: 10
});
window.roadWeatherMap = roadWeatherMap;
roadWeatherMap.init();
updateConditionCards();
trafficEventsManager = new TrafficEventsManager();
loadRouteConditions();
```
Also initializes map state manager for save/restore.

#### 6. Condition cards (lines 1049-1160)
- `updateConditionCardsWithLocation(locationData)` — updates bottom overlay cards
- `updateConditionCards()` — fetches stations, calculates basin-wide averages

#### 7. TrafficEventsManager class (lines ~1988-2371)
- Tab system for Active/Upcoming/All traffic events
- `data-tab` attribute buttons, `.tab-content` divs
- Fetches from `/api/traffic-events/active`, `/upcoming`, `/map`

#### 8. Route conditions (lines ~2378-2890)
- `loadRouteConditions()` → calls `loadUS40Conditions()`, `loadUS191Conditions()`, `loadBasinRoadsConditions()`
- Each route function: fetches cached station + event data, filters by geography, calls `displayRouteConditions()`
- Basin roads: carousel with auto-rotate (30s), road slides, indicators
- `displayRouteConditions()` generates metric cards: temperature, surface, incidents, travel status

#### 9. Units toggle (lines ~2892-3116)
- `initializeUnitsToggle()` on DOMContentLoaded
- `refreshUnitsDisplays()` calls smart refresh functions per section
- `smartRefreshUS40()`, `smartRefreshUS191()`, `smartRefreshBasinRoads()`, `smartRefreshAlerts()`

## Frontend: roads.css Patterns

### CSS Variables
```css
:root {
    --roads-primary: #1e3a8a;    /* Deep blue */
    --roads-secondary: #3b82f6;  /* Medium blue */
    --roads-accent: #60a5fa;     /* Light blue */
    --roads-warning: #f59e0b;    /* Amber */
    --roads-danger: #dc2626;     /* Red */
    --roads-good: #10b981;       /* Green */
    --roads-surface: #374151;    /* Asphalt gray */
    --roads-ice: #bfdbfe;        /* Ice blue */
}
```

### Key Selectors
- `body[data-page-type="roads"]` — page-scoped overrides
- `.map-container-fullscreen` — 600px height, 16px border-radius, box-shadow
- `.conditions-overlay` — absolute positioned at bottom of map
- `.condition-card-compact` — individual metric cards in overlay
- `.route-section` — white card with 16px border-radius, gradient top-border (::before), shadow
- `.route-conditions` — inner container for route metric data
- `.carousel-controls`, `.carousel-btn` — basin roads carousel navigation
- `.events-tabs`, `.tab-btn`, `.tab-content` — traffic events tab system
- `.alert-card` — UDOT alert styling
- `.resource-card` — external links section

### Responsive Breakpoints
Media queries at mobile sizes adjust `.route-section` padding, card layouts, map height.

## Adding New Layers/Sections

### To add a new map layer:
1. Add a `new Map()` in RoadWeatherMap constructor
2. Add `load*()` method (fetch from API) + `render*()` method (create markers/polylines)
3. Call from `init()` and optionally add to auto-refresh interval
4. Add to `clearLayers()` if needed

### To add a new below-map section:
1. Add `<section>` in roads.html between existing sections (follow loading spinner pattern)
2. Add standalone function in roads.js, call from DOMContentLoaded block
3. Add CSS in roads.css following `.route-section` card pattern

### To add a new API endpoint:
1. Add method to roadWeatherService.js (or create new service file)
2. Add `router.get()` in routes file
3. Register route in server.js: `app.use('/api', newRoutes)`
