# Hand-off to `brc-data-ops`: RRFS and the model feeds

Written 2026-11-20 for the repo that will drive the 24/7 Clyfar, LLM-forecast and
BasinWX cycles. brc-tools keeps the generic download and processing code; everything
on this page is an operational decision or an operational fact, and belongs to
`brc-data-ops` once it exists. Move this file there and delete it here.

Facts below were read on 2026-11-20 from `crontab -l` on notchpeak1, the public
bucket `s3://noaa-rrfs-ops-pds`, and Herbie's release notes. Re-check anything dated
before acting on it.

## 1. What is sent today

**Nothing from RRFS.** No script, cron wrapper or website dataType mentions it. The
live crontab has six jobs; the four model jobs are all HRRR.

| Cron (UTC) | Wrapper / command | Source | Sent to BasinWX |
|---|---|---|---|
| `*/5 * * * *` | `brc_tools/download/get_map_obs.py` (env `clyfar-nov2025`) | Synoptic | map observations + metadata |
| `20 * * * *` | `scripts/cron/run_road_forecast_push.sh` | HRRR `sfc` | road forecast (`road-forecast`) |
| `45 0,6,12,18 * * *` | `scripts/cron/run_hrrr_surface_push.sh` | HRRR `sfc`, 3 runs, f00–f18 | `forecast_hrrr_surface_layers_*`: 2 m temperature, 10 m u/v, hourly rain, snowfall since run start |
| `50 * * * *` | `scripts/cron/run_hrrr_waypoint_push.sh` | HRRR `sfc`, f00–f18 | `forecast_hrrr_waypoints_*`: temperature, dewpoint, wind speed/direction, RH, MSLP, rain at named waypoints |
| `55 * * * *` | `scripts/cron/run_hrrr_kvel_crosswind_push.sh` | HRRR `subh` (15-min) | `forecast_hrrr_kvel_crosswind_*`: runway cross/headwind and gust at KVEL |
| `15 3,9,15,21 * * *` | `sbatch clyfar/scripts/submit_clyfar.sh` | GEFS (in `clyfar`) | Clyfar ozone forecasts (seasonal) |

The waypoint and KVEL jobs were live while `docs/CHPC-REFERENCE.md` still listed them
as "deliberately absent"; that doc now matches the crontab.

HRRR is still publishing (checked `hrrr.20261121`). NAM is not: `noaa-nam-pds` has no
keys after `nam.20261103`.

## 2. What RRFS publishes (CONUS 3 km)

RRFS v1 replaced NAM, HREF, SREF and HiresW (NWS SCN 26-48); the operational feed is
`s3://noaa-rrfs-ops-pds/rrfs.YYYYMMDD/HH/` plus NOMADS. The prototype bucket the old
Herbie template used (`noaa-rrfs-pds/rrfs_a/`) is empty.

| Cycles | Files | Leads | On S3 after init |
|---|---|---|---|
| 00, 06, 12, 18Z | `2dfld` + `prslev`, hourly | f000–f084 | f018 about 2 h 20 min; f084 about 3 h 30 min |
| 03, 09, 15, 21Z | `2dfld` + `prslev`, hourly | f000–f018 | about 1 h 45 min |
| every hour | `2dfld…subh` only | f001–f018, 15-min steps | 1 h 45 min to 2 h 15 min |

- `2dfld` (about 355 MB, 314 messages) holds the surface and 2-D fields. `prslev`
  (about 580 MB) holds 45 pressure levels and nothing at the surface. There are no
  native-level files.
- `subh` carries about 37 fields per step, among them 2 m temperature and dewpoint,
  10 m and 80 m u/v, gust, visibility, precipitation rate and totals, snowfall,
  precipitation-type flags, composite reflectivity, cloud base/ceiling and the surface
  radiation terms. No RH, no CAPE, no PBL height.
- **The hourly files do not exist for 16 of the 24 daily cycles.** An hourly cron that
  asks for the newest run's `2dfld` will find it only every third hour.
- The CONUS grid is HRRR's grid exactly (Lambert, LoV 262.5, Latin 38.5, 1799 × 1059),
  so the Basin crop is the same 71 × 76 cells and winds are grid-relative by the same
  angle (about −7.5° at Vernal).

Differences from HRRR that reach a product:

| Field | HRRR | RRFS | Consequence |
|---|---|---|---|
| Sea-level pressure | `MSLMA` (MAPS reduction) | `MSLET` (its only MSL message) | a few hPa apart over high terrain; do not splice or difference the two on one chart |
| Hourly precipitation | `APCP` hourly bucket | same two-bucket layout | none |
| Snowfall | `ASNOW` run total | `ASNOW` run total | none; still not an hourly amount |
| Vertical motion on pressure levels | `VVEL` (Pa/s) | `DZDT` (m/s) | `omega_pl` has no RRFS entry |
| Forecast length | 18 h (48 h at 00/06/12/18Z) | 18 h (84 h at 00/06/12/18Z) | a surface-layers product could run to 84 h |

## 3. What brc-tools now does, and does not

Done in brc-tools (generic, merged with this hand-off):

- `NWPSource("rrfs")` fetches from the operational feed on Herbie ≥ 2026.10.0. The
  `[models.rrfs]` block and every `rrfs` alias search were rebuilt against real index
  files; `tests/test_rrfs_aliases.py` fails if one stops matching exactly one message.
- Winds are rotated by the grid the GRIB declares, not by HRRR's constants
  (GH #80). RRFS CONUS gets the right angle because its GRIB says so; a grid with no
  formula (RRFS Alaska, RRFS North America 13 km) raises instead of rotating wrongly.
- `NWPSource.latest_init()` uses a per-model `availability_lag_hours` (RRFS: 3 h, on
  the 3-hourly cadence of the hourly files).
- Every variable the two HRRR BasinWX builders ask for
  (`basinwx.SURFACE_EXPORT_VARIABLES`, `waypoint_forecast.SOURCE_VARIABLES`) resolves
  for RRFS, so `fetch_surface_dataset(..., source=NWPSource("rrfs"))` and
  `fetch_waypoint_dataset(..., source=NWPSource("rrfs"))` return data. Checked live:
  2026-11-20 12Z, f001–f002, Uinta Basin.

Not done, on purpose:

- No RRFS export script, cron wrapper or upload. The payload builders, filenames and
  index files still say `hrrr`.
- `NWPSource` still collapses a sub-hourly file to its top-of-hour step
  (`normalize_coords` drops the GRIB time axis). The KVEL job reads HRRR `subh` through
  Herbie directly for that reason; an RRFS `subh` product needs the same route or that
  fix (brc-tools #82).

## 4. Ops decisions and actions

Each item is yours to decide; none is started.

1. **Environment cutover.** The HRRR crons run in `brc-tools-2026` (Herbie 2026.3.0,
   SynopticPy 2026.6.0, polars 1.42). That Herbie cannot fetch RRFS. A side-by-side env
   `brc-tools-2026-11` was built on 2026-11-20 with Herbie 2026.10.0 and SynopticPy
   2026.10.0 (which brings polars 2 and numpy ≥ 2.5.3); its test results are in
   `docs/ENVIRONMENT-SETUP.md`. `brc-tools-2026` was not touched: the pelican2013
   manuscript pins against it. Each wrapper takes `CONDA_ENV` from the environment, so
   one cron line can be moved at a time. The obs cron is separate again
   (`clyfar-nov2025`, numpy < 2).
2. **Which RRFS file feeds which product.** Surface layers (4× daily) map cleanly onto
   the 00/06/12/18Z `2dfld` runs. The hourly waypoint product does not: either update it
   every 3 h from `2dfld`, or build it hourly from `subh` (no RH there, so derive it
   from temperature and dewpoint). KVEL crosswind maps onto `subh` on every cycle.
3. **Cron minutes.** With the lags in section 2: an f000–f018 pull is safe from about
   HH+2:30 at 00/06/12/18Z and HH+2:00 at 03/09/15/21Z; an f084 pull from about
   HH+3:45; a `subh` pull from about HH+2:20. The road-forecast receiver rejects
   `init_time` older than 3 h, which RRFS would hit on most hours; that limit is
   website-side.
4. **Website contract.** New dataTypes or filenames (`forecast_rrfs_*`) must be added
   to `ubair-website`'s `DATA_MANIFEST.json` first, on `.dev` with `BASINWX_API_URLS`
   pinned, then promoted. An unknown dataType returns 400. Decide whether RRFS
   replaces HRRR on the site, sits beside it, or is blended; the payloads carry a
   `model` field the pages print.
5. **HRRR's end date.** SCN 26-48 retired NAM, HREF, SREF and HiresW, not HRRR. Watch
   the NWS notices for HRRR and RAP; the four model crons stop the day HRRR does.
6. **NAM is retired.** `scripts/forecast_funnel.py` (the NAM synoptic montage) has no
   source for inits after 2026-11-03 (brc-tools #81); it matters to ops only if the
   funnel is ever scheduled.
7. **Logs.** `~/logs/hrrr_waypoints.log` is 75 MB, `hrrr_kvel_crosswind.log` 54 MB,
   `hrrr_surface.log` 39 MB, and nothing rotates them.
8. **Download volume.** NWPSource byte-ranges single messages (about 1.7 MB each for
   RRFS), so an f000–f018 pull of six fields is roughly 200 MB per run, the same order
   as HRRR. Set `BRC_TOOLS_HERBIE_CACHE` to scratch for any new job.
9. **Availability alerts.** An RRFS job should treat "no hourly files for this cycle"
   as normal on 16 cycles a day and alert only when a 3-hourly cycle is late.

## 5. A rollout order that keeps HRRR untouched

1. Move one HRRR cron to `brc-tools-2026-11` and watch a day of uploads (no RRFS yet).
2. Add an RRFS surface-layers export beside the HRRR one, uploading to `.dev` only.
3. Compare RRFS and HRRR waypoint series against the Synoptic obs already collected
   (`brc_tools.verify.paired_scores`) before any page shows RRFS.
4. Add the manifest entries, promote to `.com`.
5. Decide on the hourly products (item 2) once the 3-hourly ones have run for a week.

## 6. What in brc-tools is really ops

Candidates to move to `brc-data-ops`, leaving the functions they call here:

- `scripts/cron/*.sh` and the `scripts/export_hrrr_*.py` entry points.
- `brc_tools/download/get_map_obs.py` and `get_road_forecast.py` as run scripts (their
  helpers can stay).
- The cron and token sections of `docs/CHPC-REFERENCE.md`, and
  `docs/WEBSITE-INTEGRATION.md`.
- This file.

`brc_tools.download.push_data.send_json_to_server` stays: `clyfar` imports it.
