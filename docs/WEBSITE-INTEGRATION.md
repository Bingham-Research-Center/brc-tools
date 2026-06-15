# BasinWX upload contract

The data contract between brc-tools (producer) and the `ubair-website` receiver
(`basinwx.com` / `.dev`). brc-tools is the single source of truth; both website
boxes are downstream consumers that receive POSTs (they don't pull). Match the
schemas here and the website lights up automatically.

> **Canonical schema source** is the website repo's `DATA_MANIFEST.json`
> (e.g. `hrrr_surface_layers` at `DATA_MANIFEST.json:487`). When in doubt, read it
> there — don't invent fields. The library entry point is
> `brc_tools.download.push_data` (see [walkthroughs/upload.md](walkthroughs/upload.md)).

## Endpoint + auth

```
POST  {server}/api/upload/:dataType        # server = https://www.basinwx.com | https://www.basinwx.dev
```
Both headers required:
- `x-api-key: $DATA_UPLOAD_API_KEY` (32-char hex; same secret on both boxes)
- `x-client-hostname: <host>.chpc.utah.edu` (or source IP reverse-DNS resolves to `*.chpc.utah.edu`)

**Multipart body (multer):** field name is the literal `file`; filename preserved;
**10 MB** limit; extensions **JSON / MD / TXT** only (gzip+base64 inside JSON for binary).

**Response:** `{ "success": true, "filename": "...", "dataType": "..." }`.
`200` stored · `401` bad key · `403` not from CHPC · `413` >10 MB.

**Accepted dataTypes** (anything else → 400):
```
observations | metadata | outlooks | llm_outlooks | images | timeseries | forecasts | road-forecast
```

## Fan-out — `BASINWX_API_URLS`

Comma-separated list; first = primary (must succeed), rest = best-effort mirrors.
```bash
export BASINWX_API_URLS="https://www.basinwx.com,https://www.basinwx.dev"
```
Use one shared uploader across producers so every product fans out the same way.

## Schemas (compact)

**`road-forecast`** — `POST /api/upload/road-forecast`, filename
`road_forecast_<YYYYMMDD_HHMMZ>.json`. Server copies it to
`static/road-forecast/latest.json`. Rejected if `init_time` > 3 h old.
```jsonc
{ "init_time": "ISO-8601 Z", "model": "hrrr", "domain": "uintah_basin_roads",
  "points": [ { "lat": .., "lon": .., "name": "..",
    "forecasts": [ { "valid_time": "Z",
      "temp_2m": -2.3,        // °C — NOT Kelvin
      "precip_1hr": 0.5,      // mm
      "precip_type": "snow",  // snow|rain|mixed|none
      "wind_speed_10m": 4.2,  // m/s
      "visibility": 12.5 } ] } ] }   // km (website ×1000 → metres)
```

**`forecast_hrrr_kvel_crosswind_*`** — `POST /api/upload/forecasts`,
filename `forecast_hrrr_kvel_crosswind_<YYYYMMDD_HHMMZ>.json`.
```jsonc
{ "product": "aviation_crosswind",   // literal; consumer checks it
  "model": "hrrr", "init_time": "Z", "valid_times": ["Z", ...],
  "series": { "crosswind_kt_rwy16": [..], "crosswind_kt_rwy34": [..] },  // knots; ± = side
  "metadata": { "station": "KVEL", "runway_headings_deg_true": [160, 340] } }
```

**`forecast_hrrr_surface_layers_*`** — `POST /api/upload/forecasts`,
filename `forecast_hrrr_surface_layers_<YYYYMMDD_HHMMZ>.json`. **Schema already
pinned** at website `DATA_MANIFEST.json:487`; `product_type` enum is
`"surface_layers"`. Read the manifest; don't invent fields.

## Status

This page is the folded **contract reference** (from the 2026-04-27 website
handoff). The remaining producer/fan-out **work** (the three dark dataTypes,
clustering fan-out to `.dev`) is tracked in [../WISHLIST-TASKS.md](../WISHLIST-TASKS.md).
Hard rules: temperatures in °C (not Kelvin); never invent dataTypes without a
website-side PR; don't regress the observations channel.
