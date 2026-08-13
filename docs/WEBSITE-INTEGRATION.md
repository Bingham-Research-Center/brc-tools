# BasinWX upload contract

The data contract between brc-tools (producer) and the `ubair-website` receiver
(`basinwx.com` / `.dev`). brc-tools is the single source of truth; both website
boxes are downstream consumers that receive POSTs (they don't pull). Match the
schemas here and the website lights up automatically.

> **Cross-machine invariant** (canonical: CLAUDE.md Conventions → "No path crosses
> machines"): CHPC (producer) and the Linode hub (receiver) share **no filesystem**.
> The *only* interface is the URL contract below — never a shared path. Paths on
> each side are local to that side.

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
**10 MB** limit; extensions **`.json` `.md` `.txt` `.png` `.pdf`**
(`dataUpload.js:167-173`). `.png`/`.pdf` are accepted natively — no gzip+base64
wrapper needed, and `.com` has been receiving both for months.

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
Verified against the consumer (`public/js/aviation.js:33-84`) and live producer
output on 2026-08-13.
```jsonc
{ "product": "aviation_crosswind",   // literal; else the <h2> falls back to "hrrr"
  "model": "hrrr_subh",              // shown in the header when product matches
  "init_time": "Z",                  // rendered verbatim as a string
  "runway_headings_deg": [160, 340], // TOP-LEVEL, degrees true; drives every column pair
  "valid_times": ["Z", ...],         // drives row count
  "series": {
    "wind_speed_kt": [..], "wind_dir_deg": [..],
    // key = "crosswind_kt_" + String(heading).padStart(3, '0')
    "headwind_kt_160": [..], "crosswind_kt_160": [..],
    "headwind_kt_340": [..], "crosswind_kt_340": [..] } }
```
> ⚠️ Earlier revisions of this page (inherited from the 2026-04-27 handoff)
> specified `crosswind_kt_rwy16` and `metadata.runway_headings_deg_true`. Both are
> **wrong** and render an empty table. The keys are zero-padded *headings* and
> `runway_headings_deg` is top-level.

**Every `series` array must be index-aligned with `valid_times`.** Short or
missing arrays render as `—` rather than erroring, so a misalignment looks like
partial data, not a failure. Column headers derive as `Rwy` + `round(heading/10)`,
so `160` → `Rwy16`.

**`forecast_hrrr_surface_layers_*`** — `POST /api/upload/forecasts`,
filename `forecast_hrrr_surface_layers_<YYYYMMDD_HHMMZ>.json`. **Schema already
pinned** at website `DATA_MANIFEST.json:487`; `product_type` enum is
`"surface_layers"`. Read the manifest; don't invent fields.

## Producers and their cron wrappers

| dataType / product | Producer | Wrapper (`scripts/cron/`) | Bucket |
|---|---|---|---|
| `road-forecast` | `brc_tools/download/get_road_forecast.py` | `run_road_forecast_push.sh` | `road-forecast` |
| `forecast_hrrr_kvel_crosswind_*` | `scripts/export_hrrr_kvel_crosswind.py` | `run_hrrr_kvel_crosswind_push.sh` | `forecasts` |
| `forecast_hrrr_surface_layers_*` | `scripts/export_hrrr_surface_layers.py` | `run_hrrr_surface_push.sh` | `forecasts` |
| `forecast_hrrr_waypoints_*` | `scripts/export_hrrr_waypoint_forecast.py` | `run_hrrr_waypoint_push.sh` | `forecasts` |
| observations + metadata | `brc_tools/download/get_map_obs.py` | *(direct crontab entry)* | `observations`, `metadata` |

`run_hrrr_waypoint_push.sh` is **not** the road-forecast job — it emits a
different product into `forecasts`. Easy to conflate; don't.

The conda env on notchpeak1 is **`brc-tools-2026`**. There is no `brc-tools` env;
under `set -euo pipefail` a wrong name aborts the wrapper into its log with no
other symptom.

**Cadence.** `road-forecast` must run **hourly** — the website rejects the file
outright once `init_time` is over 3 h old, and HRRR availability already eats
~1.6 h of that. A 3-hourly job that slips by minutes is permanently rejected.

### Prove a producer before installing its cron

```bash
conda activate brc-tools-2026 && cd ~/gits/brc-tools
python -m brc_tools.download.get_road_forecast --dry-run
python scripts/export_hrrr_kvel_crosswind.py --dry-run --airport KVEL --product subh --max-fxx 6
python scripts/export_hrrr_surface_layers.py --run-count 1   # no --dry-run flag; omitting --upload is equivalent

# then validate against the pinned schema using the website's own validator
cd ~/gits/ubair-website
python3 scripts/chpc_uploader.py --data-type road-forecast \
        --file ~/.cache/brc-tools/basinwx/road_forecast_*.json --validate-only
```

Schema validation catches **structural** errors, not unit errors: `temp_2m` is
typed `[number, null]` with no range bound, so Kelvin passes. Eyeball the values
(−30…45, not 240…320).

### The `.dev` pin rule

A wrapper carries `export BASINWX_API_URLS="https://basinwx.dev"` **if and only
if** its website-side consumer is on the website's `dev` branch but not yet on
`ops`. Unpin in the brc-tools PR that follows the dev→ops promotion carrying that
consumer. A pin is therefore a visible marker for "this dataType runs ahead of
production", and nothing can reach `.com` before `.com` can render it — uploading
a dataType `ops` does not list returns 400.

Unpinned wrappers fall through to `~/.config/ubair-website/website_urls`, which
already reads `https://basinwx.com,https://basinwx.dev`.

## Status

This page is the **contract reference**, folded from the 2026-04-27 and
2026-08-13 website handoffs. Remaining producer/fan-out work is tracked in
[../WISHLIST-TASKS.md](../WISHLIST-TASKS.md).

Hard rules: temperatures in °C (not Kelvin); never invent dataTypes without a
website-side PR; don't regress the observations channel.

Known gap: `push_outlook.py` uses `load_config()`, which returns only the first
URL, so outlooks reach `.com` alone. `clyfar/export/to_basinwx.py` reads the
singular `BASINWX_API_URL` at four sites with the same effect. Both should move
to `load_config_urls()`; neither is urgent while Clyfar is out of season.
