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
observations | metadata | outlooks | llm_outlooks | images | forecasts | road-forecast | llm_forecasts | aircraft
```
The list is `ubair-website/server/uploadPolicy.js` (`UPLOAD_DATA_TYPES`), read 2026-11-21 on
`dev`. `timeseries` is gone. `llm_forecasts` and `aircraft` are new in website 1.7.3 and are
dev-only until `.com` reports manifest 2.2.0 or later.

## Fan-out — `BASINWX_API_URLS`

Comma-separated list; first = primary (must succeed), rest = best-effort mirrors.
```bash
export BASINWX_API_URLS="https://www.basinwx.com,https://www.basinwx.dev"
```
Use one shared uploader across producers so every product fans out the same way.

## Retries and receipts

`push_data` tries a file again when the failure is transient: a DNS lookup that
fails, a refused or timed-out connection, or a `502`/`503`/`504`. It makes up to
`BASINWX_UPLOAD_ATTEMPTS` attempts per file and host (default 3; `1` turns retrying
off), waiting 5 s and then 20 s. Any other status is final, because the server would
refuse the same bytes again. A host that uses up every attempt gets one attempt per
file for the rest of that process, so an outage costs one round of retries per run
(clyfar sends ~165 files a run through the same code).

Every attempt appends one line to `~/logs/basinwx/push_receipts.jsonl`
(`BASINWX_RECEIPTS_LOG`; empty disables it), with `attempt`, `stage` (`health` or
`upload`), `status`, `error` and `elapsed_ms`.

**Why retries exist:** in the week to 2026-11-21, each of the seven files the website
found on one host only had failed a single DNS lookup (`Name or service not known`) at
the other host's health check, and nothing tried it again. Since receipts began
(2026-09-28), DNS failures are 421 of the 822 failed attempts; the other 401 are
`.com`'s "API key not configured" outage (26–27 Oct, 393) and eight timeouts. Files
missing from *both* hosts were never made: on 18 and 19 Nov the HRRR fetch from AWS
hung on read timeouts until the process was killed, so nothing reached the upload
step. Re-sending a run that a whole cycle missed is an ops decision
(`BRC-DATA-OPS-HANDOFF.md`), not something the uploader does.

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
  "runway_headings_deg": [179, 359], // TOP-LEVEL, degrees true; drives every column pair
  "valid_times": ["Z", ...],         // drives row count
  "series": {
    "wind_speed_kt": [..], "wind_dir_deg": [..],
    // key = "crosswind_kt_" + String(heading).padStart(3, '0')
    "headwind_kt_179": [..], "crosswind_kt_179": [..],
    "headwind_kt_359": [..], "crosswind_kt_359": [..] } }
```
> ⚠️ Earlier revisions of this page (inherited from the 2026-04-27 handoff)
> specified `crosswind_kt_rwy16` and `metadata.runway_headings_deg_true`. Both are
> **wrong** and render an empty table. The keys are zero-padded *headings* and
> `runway_headings_deg` is top-level.

**Every `series` array must be index-aligned with `valid_times`.** Short or
missing arrays render as `—` rather than erroring, so a misalignment looks like
partial data, not a failure.

> ⚠️ **Runway redesignation (2026-08-13).** FAA renamed KVEL 16/34 → 17/35
> (magnetic 169/349, var 10E → true 179/359). The producer now emits
> `runway_headings_deg: [179, 359]` and `*_kt_179`/`*_kt_359` keys. The website
> derives series keys dynamically, but its column headers use
> `Rwy + round(heading/10)`, which mislabels `179` as `Rwy18` — the coordinated
> website release must switch to `Math.floor(heading/10)` (`179` → `Rwy17`,
> `359` → `Rwy35`) alongside a **MAJOR `DATA_MANIFEST.json` bump**. Both sides have
> since shipped and the kvel cron is installed (`55 * * * *`).

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

**RRFS draft (dev-only, hand-run, no cron).** `export_hrrr_surface_layers.py --model rrfs`
writes the same schema with `"model": "rrfs"` to `forecast_rrfs_surface_layers_<init>.json`
and `forecast_rrfs_surface_layers_index.json`. One run (init 2026-11-21 00Z, f00–f18) was
uploaded by hand to `https://www.basinwx.dev` on 2026-11-21; nothing on the site reads those
names, and they are not in `DATA_MANIFEST.json`. It needs env `brc-tools-2026-11`. Do not
schedule it or send it to `.com` before the manifest lists it:
`docs/BRC-DATA-OPS-HANDOFF.md`.

`run_hrrr_waypoint_push.sh` is **not** the road-forecast job — it emits a
different product into `forecasts`. Easy to conflate; don't.

The wrappers default to conda env **`brc-tools-2026`** (road, waypoint and KVEL jobs). The
surface-layers job runs on **`brc-tools-2026-11`** as a pilot since 2026-11-21, and the obs
job on `clyfar-nov2025`. Schedules, in local time: `docs/CHPC-REFERENCE.md`. There is no
`brc-tools` env;
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

As of 2026-08-13 (website v1.5.0 promoted every pending consumer to `ops`)
**no wrapper carries a pin**. The rule above still governs any future
ahead-of-production dataType.

## Status

This page is the **contract reference**, folded from the 2026-04-27 and
2026-08-13 website handoffs. Remaining producer/fan-out work is tracked in
[../WISHLIST-TASKS.md](../WISHLIST-TASKS.md).

Hard rules: temperatures in °C (not Kelvin); never invent dataTypes without a
website-side PR; don't regress the observations channel.

Wind components in every HRRR product are **earth-relative** (east/north) since
brc-tools #78; #83 takes the rotation from the grid the GRIB declares.

Closed gap: `clyfar/export/to_basinwx.py` now fans out through `send_json_to_all` and
reads the plural `BASINWX_API_URLS` (the singular form is a last-resort fallback), so
Clyfar's forecasts, images and LLM outlooks reach both hosts.
