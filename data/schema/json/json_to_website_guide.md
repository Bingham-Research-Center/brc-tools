# From JSON to Interactive Maps
**Complete Journey: CHPC Data → Website Display**

## **Quick Overview**
1. **CHPC**: Python creates JSON file → sends via API
2. **Website**: Receives JSON → stores in `/public/data/`
3. **Browser**: JavaScript fetches JSON → displays on interactive map

---

## **1. The Upload Journey (CHPC → Website)**

### **What Happens When You Send JSON**

```python
# Your Python script does this:
send_json_to_server(server_url, map_fpath, "map-obs", API_KEY)
```

**Step-by-step breakdown:**

1. **HTTP POST Request** - Your Python script packages the JSON file and sends it to the website
   - **POST** = "Here's some data for you to store" (vs GET = "give me data")
   - **API** = Application Programming Interface (a way for programs to talk to each other)
   - **Endpoint** = Specific URL that handles data uploads (`/api/data/upload/map-obs`)

2. **Authentication** - Website checks your API key
   - Like showing an ID card to prove you're authorized to upload data
   - API key is a 64-character secret string only you and the server know

3. **File Storage** - Website saves your JSON file
   - File goes to: `ubair-website/public/data/map_obs_20250729_1200Z.json`
   - **public** folder = files accessible from the web

4. **Validation** - Website checks the JSON is valid
   - Ensures it's proper JSON format (not corrupted)
   - Rejects file if malformed

**What Your Python Script Actually Sends:**
```http
POST /api/data/upload/map-obs HTTP/1.1
Host: basinwx.com
x-api-key: your_64_character_secret_key
Content-Type: multipart/form-data

[JSON file content]
```

---

## **2. Website Server Processing**

### **API Endpoint Handling**
Your website has this code (in `server/routes/dataUpload.js`):

```javascript
// When CHPC sends data, this function runs:
router.post('/upload/:dataType', validateApiKey, upload.single('file'), (req, res) => {
  // 1. Check API key is valid
  // 2. Save file to public/data/ folder  
  // 3. Verify JSON is valid
  // 4. Send success/error response back to CHPC
});
```

**Key Concepts:**
- **Route** = URL pattern the server listens for (`/api/data/upload/map-obs`)
- **Middleware** = Functions that run before main handler (authentication, file parsing)
- **Multer** = Library that handles file uploads
- **Express.js** = Web framework that manages HTTP requests/responses

### **File Organization**
```
ubair-website/
├── public/data/           ← Your JSON files land here
│   ├── map_obs_20250729_1200Z.json
│   ├── clyfar_forecast_20250729_1200Z.json
│   └── ...
├── server/routes/         ← API handling code
└── public/js/             ← JavaScript that displays maps
```

---

## **3. Browser Fetches Data**

### **How JavaScript Gets Your Data**

When someone visits `basinwx.com/live_aq`, this happens:

```javascript
// 1. Browser loads the page
// 2. JavaScript runs and fetches your data:
const response = await fetch('/api/live-observations');
const jsonData = await response.json();

// 3. Now JavaScript has your weather station data!
```

**Key Terms:**
- **fetch()** = Modern way for JavaScript to request data from server
- **await** = "Wait for this to complete before continuing"
- **JSON.parse()** = Convert JSON text into JavaScript objects
- **API endpoint** = URL that serves data (`/api/live-observations`)

### **Data Transformation for Maps**

Your JSON structure needs reshaping for map display:

**Your JSON format (optimized for storage):**
```json
[
  {"stid": "UBCSP", "variable": "ozone_concentration", "value": 51.13, "units": "ppb"},
  {"stid": "UBCSP", "variable": "air_temp", "value": 32.17, "units": "Celsius"},
  {"stid": "QCV", "variable": "ozone_concentration", "value": 42.0, "units": "ppb"}
]
```

**Map needs this format (organized by station):**
```javascript
{
  "UBCSP": {
    "ozone_concentration": {value: 51.13, units: "ppb"},
    "air_temp": {value: 32.17, units: "Celsius"}
  },
  "QCV": {
    "ozone_concentration": {value: 42.0, units: "ppb"}
  }
}
```

**JavaScript transformation:**
```javascript
function groupDataByStation(rawData) {
  const stationData = {};
  
  rawData.forEach(record => {
    const {stid, variable, value, units} = record;
    
    // Create station object if doesn't exist
    if (!stationData[stid]) {
      stationData[stid] = {};
    }
    
    // Add this measurement to the station
    stationData[stid][variable] = {value, units};
  });
  
  return stationData;
}
```

---

## **4. Interactive Map Display**

### **Map Library Integration**

Your website uses **Leaflet.js** for interactive maps:

```javascript
// 1. Create the map
const map = L.map('map-container').setView([40.4, -109.5], 8);

// 2. Add base layer (satellite/terrain imagery)
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

// 3. Add weather station markers
stationData.forEach(station => {
  const marker = L.marker([station.lat, station.lon])
    .bindPopup(`
      <h3>${station.name}</h3>
      <p>Ozone: ${station.ozone} ppb</p>
      <p>Temp: ${station.temp}°C</p>
    `);
  
  marker.addTo(map);
});
```

**Key Map Concepts:**
- **Leaflet** = Open-source JavaScript map library
- **Markers** = Icons on map showing station locations
- **Popups** = Info boxes that appear when you click markers
- **Tile Layer** = Background map imagery (satellite, roads, terrain)
- **Coordinates** = [latitude, longitude] pairs for positioning

### **Color-Coding by Air Quality**

```javascript
function getOzoneColor(ozoneValue) {
  if (ozoneValue < 30) return 'green';      // Good
  if (ozoneValue < 50) return 'yellow';     // Moderate  
  if (ozoneValue < 70) return 'orange';     // Unhealthy for sensitive
  return 'red';                             // Unhealthy
}

// Create colored markers based on ozone levels
const marker = L.circleMarker([lat, lon], {
  color: getOzoneColor(station.ozone),
  fillOpacity: 0.7,
  radius: 10
});
```

### **Real-Time Updates**

```javascript
// Update map every 15 minutes with fresh data
setInterval(async () => {
  const newData = await fetch('/api/live-observations');
  const stations = await newData.json();
  
  // Update existing markers with new values
  updateMarkers(stations);
  
  console.log('Map updated with latest data');
}, 15 * 60 * 1000); // 15 minutes in milliseconds
```

---

## **5. Complete Data Flow Example**

### **Live Air Quality Map Process**

1. **CHPC runs your script:**
   ```bash
   python brc_tools/download/get_map_obs.py
   ```

2. **Data upload:**
   ```
   CHPC → POST /api/data/upload/map-obs → Website saves JSON
   ```

3. **User visits live_aq page:**
   ```
   Browser → GET /live_aq → HTML page loads
   ```

4. **JavaScript fetches data:**
   ```
   JavaScript → GET /api/live-observations → JSON data returned
   ```

5. **Map displays stations:**
   ```
   JSON → Transform → Leaflet markers → Interactive map
   ```

### **Error Handling Throughout**

**At upload (CHPC side):**
```python
try:
    send_json_to_server(server_url, map_fpath, "map-obs", API_KEY)
    print("✅ Data uploaded successfully")
except requests.RequestException as e:
    print(f"❌ Upload failed: {e}")
```

**At display (browser side):**
```javascript
try {
    const data = await fetch('/api/live-observations');
    if (!data.ok) throw new Error(`HTTP ${data.status}`);
    
    const stations = await data.json();
    displayOnMap(stations);
} catch (error) {
    console.error('Failed to load station data:', error);
    showErrorMessage('Unable to load latest observations');
}
```

---

## **6. Technical Terms Glossary**

**API (Application Programming Interface)** - Way for different programs to communicate. Your Python script uses the website's API to send data.

**HTTP Methods:**
- **POST** - Send data to server (your uploads)
- **GET** - Request data from server (map loading data)

**JSON (JavaScript Object Notation)** - Text format for structured data that both Python and JavaScript can read.

**Endpoint** - Specific URL that handles requests (e.g., `/api/data/upload/map-obs`)

**Middleware** - Code that runs between receiving a request and sending a response (authentication, file parsing, etc.)

**Frontend** - What users see and interact with (HTML, CSS, JavaScript in browser)

**Backend** - Server-side code that handles data, APIs, file storage (your Node.js server)

**CORS (Cross-Origin Resource Sharing)** - Security mechanism that controls which websites can access your API

**Real-time** - Data that updates automatically without user refresh (your 15-minute updates)

---

## **7. Troubleshooting Common Issues**

### **Data Not Appearing on Map**

**Check 1: Upload successful?**
```bash
# Look for this in CHPC logs:
"Successfully uploaded map_obs_20250729_1200Z.json to /api/data/upload/map-obs"
```

**Check 2: File accessible?**
```bash
# Test in browser:
https://basinwx.com/public/data/map_obs_20250729_1200Z.json
```

**Check 3: JavaScript errors?**
```javascript
// Open browser dev tools (F12) and check console for:
"Error fetching live observations"
"Failed to parse JSON"
```

**Check 4: Data structure correct?**
```javascript
// Verify your JSON has required fields:
[{"stid": "...", "variable": "...", "value": ..., "date_time": "...", "units": "..."}]
```

### **Map Performance Issues**

- **Too many markers**: Limit to ~50 stations for smooth performance
- **Large files**: Keep JSON under 1MB for fast loading
- **Update frequency**: Don't update more than every 5 minutes

---

## **Summary: JSON → Interactive Map**

**🔄 Data Pipeline:**  
CHPC Python → API Upload → File Storage → Browser Fetch → Map Display

**🌐 Technologies:**  
Express.js (server) → Multer (file upload) → Leaflet.js (maps) → JavaScript (frontend)

**📊 Data Transformation:**  
Flat JSON records → Grouped by station → Positioned on map → Color-coded by values

**⏱️ Real-time:**  
Automatic updates every 15 minutes keep maps current with latest observations

The entire system is designed to be **resilient** (handles errors gracefully), **scalable** (can add more stations/variables), and **user-friendly** (interactive maps with clear visual indicators).