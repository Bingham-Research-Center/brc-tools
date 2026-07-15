# External API clients (`brc_tools.api`)

Thin Python wrappers for external services. One subpackage each; the
key-based clients share `brc_tools.api._auth.load_api_key` and follow the
same shape as `ObsSource` / `NWPSource`: a class with the credential
loaded in `__init__`, a handful of single-purpose methods, no implicit
retries. Open (auth-free) data pulls are function-based instead of a
credential-holding class.

| Service | Subpackage | Entry point | Env var | Notes |
|---------|-----------|-------|---------|-------|
| FlightAware AeroAPI | `brc_tools.api.flightaware` | `FlightAwareClient` | `FLIGHTAWARE_API_KEY` | Free tier ~$5/mo |
| FlightRadar24 | `brc_tools.api.flightradar24` | `FR24Client` | `FR24_API_KEY` | **Stub** — paid only, min ~$9/mo |
| Perplexity Sonar | `brc_tools.api.perplexity` | `PerplexityClient` | `PERPLEXITY_API_KEY` | Pay-per-request; OpenAI-compatible |
| Mistral | `brc_tools.api.mistral` | `MistralClient` | `MISTRAL_API_KEY` | Usage-based |
| Radiosondes | `brc_tools.api.soundings` | `fetch_sounding()` | — (open) | IGRA2 (NCEI) + Univ. Wyoming; auth-free |
| EPA AQS AirData | `brc_tools.api.aqs` | `download_airdata()` / `load_airdata()` | — (open) | bulk CSV zips, cached with provenance sidecars |

## Install

LLM clients pull large SDKs, so they live behind an extras group:

```bash
pip install -e ".[api]"   # adds openai + mistralai
```

CHPC cron deployments (HRRR upload, obs ingest) do not need this; the
core install stays minimal.

## Auth convention

`load_api_key(env_var, config_subpath=None)` reads the env var first
and optionally falls back to `~/.config/{config_subpath}` (first line
of the file). Raises `RuntimeError` if neither is set. Mirrors the
pattern in `brc_tools.download.push_data.load_config`.

## Quick examples

```python
# FlightAware
from brc_tools.api.flightaware import FlightAwareClient
fa = FlightAwareClient()
fa.get_airport_arrivals("KSLC")

# Perplexity (OpenAI-compatible Sonar endpoint)
from brc_tools.api.perplexity import PerplexityClient
ppl = PerplexityClient()
print(ppl.ask("What is the current PM2.5 forecast for Vernal UT?"))

# Mistral
from brc_tools.api.mistral import MistralClient
m = MistralClient()
print(m.chat([{"role": "user", "content": "Hello"}]))
```

## Soundings (radiosondes) — `brc_tools.api.soundings`

Auth-free, function-based (no credential, so no `_auth`/class). Pulls one
station's upper-air sounding for a valid time from an open archive and
**normalises every provider to one canonical schema** so callers never see
provider quirks (column names, m/s-vs-knot winds, station-id schemes):

```python
from datetime import datetime
from brc_tools.api.soundings import fetch_sounding, STATIONS

df = fetch_sounding("KSLC", datetime(2013, 2, 2, 12))   # provider="auto"
# canonical polars columns, one row per level, surface->top:
#   station | valid_time | pressure_hpa | temperature_c | dewpoint_c | u_kt | v_kt | provider
```

- **Providers** — `igra2` (NOAA IGRA2 via siphon `IGRAUpperAir`, hosted at
  NCEI; winds m/s; ~40 s/station as siphon downloads the station's
  period-of-record file) and `wyoming` (Univ. Wyoming via siphon; winds
  knots). `provider="auto"` tries IGRA2 then Wyoming. **IGRA2 is the
  default** because the UWyo service was migrated/offline as of 2026-07
  (both `weather.uwyo.edu` and `weather.arcc.uwyo.edu` 404).
- **Times are UTC** (naive, matching wrfout filename stamps). Missing launch,
  network failure, or an offline archive all return `None` so batch callers
  skip a station without special-casing.
- **`STATIONS`** registers the operational RAOB proxies overlapping the
  pelican2013 WRF domains — KSLC, KGJT, KRIW (Riverton WY), KDPG (Dugway UT);
  all in d01, since the Uinta Basin launches no sonde. Unknown names pass
  through, so any raw IGRA2 (`USM00072572`) or Wyoming (`72572`) id works too.
- **Consumers**: `scripts/fetch_soundings.py` (writes the offline parquet
  cache the figure batch reads) and `brc_tools.visualize.profile.LiveSounding`.

## EPA AQS AirData — `brc_tools.api.aqs`

Auth-free, function-based. Downloads EPA's quality-assured AirData bulk
files (annual CSV zips) — the citable AQ record for study periods where
Synoptic has nothing (e.g. winter 2012-13 basin ozone):

```python
from brc_tools.api.aqs import download_airdata, load_airdata, basin_site_ids

zp = download_airdata("daily", "ozone", 2013)      # ~5 MB, cached
df = load_airdata(zp, sites=basin_site_ids(),
                  start="2013-01-01", end="2013-02-28")   # polars frame
```

- **Cache**: `BRC_TOOLS_AQS_CACHE` (default `~/.cache/brc-tools/aqs`), with a
  `*.meta.json` provenance sidecar (URL, retrieval time, server Last-Modified).
  Record that vintage in studies — EPA regenerates files as QA updates land.
- **MDA8**: use `"1st Max Value"` on `Pollutant Standard == "Ozone 8-hour 2015"`
  rows from the daily files; **don't recompute from hourly** (EPA already
  applied completeness/day-assignment rules).
- **`UINTA_BASIN_SITES`** registers the basin tribal/regulatory monitors;
  `basin_site_ids()` gives their ids for filtering.
- **Consumers**: `scripts/fetch_aqs_airdata.py` (CLI); walk-through in
  `docs/walkthroughs/aqs.md`.

## MCP servers

`.mcp.json` at the repo root configures two MCP servers that Claude
Code picks up automatically when run from this directory:

| Server | npm package | Verified |
|--------|-------------|----------|
| `perplexity` | `@perplexity-ai/mcp-server` | Official, maintained by Perplexity (2026-05) |
| `mistral` | `mistral-mcp` | Community; broad capability surface |

Set `PERPLEXITY_API_KEY` and/or `MISTRAL_API_KEY` in your shell env.
`npx` will download the server on first invocation.

**MCP vs Python wrapper — when to use which:**

- **MCP** is for agent workflows: Claude Code calls the server directly
  while you work. Best when you want the assistant itself to do a web
  search or fan out to a second model.
- **Python wrapper** is for scripted automation: a case-study script
  that wants to summarise a result, a batch job, anything reproducible.

The same API key works for both — Python and MCP read the same env var.

## Caveats

- **Perplexity is publicly de-prioritising MCP** in favour of their Agent
  API. The OpenAI-compatible REST API used by `PerplexityClient` is
  expected to remain; the MCP server may be deprecated in future.
- **FR24 is stubbed.** Subpackage exists for layout uniformity, but
  every method raises `NotImplementedError` until a subscription
  decision is made.
- **No retries built in.** Each client does one shot per call. Add
  `tenacity` and exponential backoff at the call site if needed; do
  not push the retry into the wrapper without a specific reason.
- **CHPC**: `pip install -e .` (no `[api]` extra) is enough for cron
  jobs. The api/ subpackage will still import — only instantiating the
  Perplexity/Mistral clients requires the extras.
