# Aviation Data Module

Simple, accessible aviation data fetching for Basin airports. Mirrors the weather data patterns used elsewhere in BRC Tools.

## Quick Start

1. **Get API Keys**
   - FlightAware: Register at [FlightAware AeroAPI](https://flightaware.com/commercial/aeroapi/)
   - FlightRadar24: Contact FR24 for commercial API access (optional)

2. **Setup Environment**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit .env with your actual API keys
   FLIGHTAWARE_API_KEY=your_key_here
   FLIGHTRADAR24_API_KEY=your_key_here  # optional
   BRC_SERVER_URL=https://basinwx.com   # your website
   BRC_API_KEY=your_server_key_here
   ```

3. **Test Your Setup**
   ```bash
   # From the aviation directory
   python test_aviation.py
   ```
   Look for ✓ checkmarks - these mean everything is working.

4. **Fetch Aviation Data**
   ```bash
   python get_aviation_data.py
   ```

## What It Does

Fetches flight information for these Basin airports:
- **KVEL** (Vernal Regional) - Main hub
- **KHCR** (Heber Valley)
- **U69** (Duchesne Municipal)
- **74V** (Roosevelt Municipal) 
- **4V0** (Rangely)
- Plus smaller fields: UT27, UT62, UT83

For each airport, it gets:
- Recent arrivals (flights that landed)
- Recent departures (flights that left)
- Planned arrivals (expected to land)
- Planned departures (scheduled to leave)

## File Structure

```
aviation/
├── config.py              # Handle API keys securely
├── flightaware_client.py   # FlightAware API wrapper
├── flightradar24_client.py # FlightRadar24 API wrapper
├── get_aviation_data.py    # Main data fetcher (like get_map_obs.py)
├── test_aviation.py        # Test your setup first
└── README.md              # This file
```

## For Students/New Team Members

Start with `test_aviation.py` - it will tell you exactly what's working and what needs fixing. The error messages are designed to be helpful, not scary!

Common issues:
- "API key missing" → Check your .env file
- "Connection failed" → Check internet connection and API key
- "No data returned" → Normal for small airports, try KVEL first

## Data Format

Output JSON matches this structure:
```json
{
  "timestamp": "2024-08-31T10:00:00Z",
  "airports": {
    "KVEL": {
      "arrivals": [...],
      "departures": [...],
      "planned_arrivals": [...],  
      "planned_departures": [...]
    }
  }
}
```

Same pattern as weather data - makes it easy for the website to consume.

## Future Enhancements
- Meteorology from ADS-B plane data
- Flight path visualization
- Historical flight statistics