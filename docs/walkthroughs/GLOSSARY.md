# Glossary — plain-language terms

One-line definitions for a developer who is **not** a meteorologist. The
walk-throughs link here instead of re-explaining terms inline.

| Term | Plain meaning |
| --- | --- |
| **foehn** | A warm, dry, gusty downslope wind — air heats as it sinks down the lee of mountains. In the Basin it can spike temperature and crash humidity within an hour. |
| **cold pool** | A lake of cold, stagnant air that settles in the Basin in winter and traps pollution. "Cold-pool erosion" (when it clears) is a common forecast question here. |
| **theta-e** (θₑ) | One number bundling an air parcel's heat **and** moisture; used to track air masses. Unit: kelvin. |
| **MSLP** | Mean sea-level pressure — surface pressure adjusted to sea level so stations at different elevations compare fairly. Stored in pascals (Pa). |
| **GRIB** | The binary file format weather-model data ships in (gridded fields; one file holds many variables/times). Tools read it; you rarely open it by hand. |
| **WPS / real.exe / wrf.exe** | The WRF model's three run stages (preprocess GRIB → build initial/boundary conditions → run the forecast). **All three live in the `brc-wrf` repo, not here.** |
| **waypoint** | A named location (lat/lon, e.g. `vernal`) we pull forecasts/obs at. Collected into "waypoint groups" (e.g. `foehn_path`) in `lookups.toml`. |
| **init time** | The start time a forecast was launched from (model initialization), written `YYYY-MM-DD HHZ` in UTC (the trailing `Z`). |
| **fxx / forecast hour** | Hours since the init time. `fxx=6` is the forecast valid 6 h after launch. Also called lead time. |
| **reforecast** | A modern model re-run over historical dates so old events can be studied. We use the GEFSv12 *reforecast* for pre-2017 cases the operational model can't reach. |
| **DTN** | CHPC Data Transfer Node (`notchpeak-dtn`) — the internet-connected machine built for big downloads. Run heavy staging here, not on a login or compute node. |
| **scratch** | Fast, large, **temporary** CHPC disk (`/scratch/general/vast/$USER`). A 60-day purge deletes untouched files — treat it as reproducible-on-demand, not durable storage. |
| **manifest vs. contract** | Two JSON sidecars WRF staging writes: the **manifest** (`manifest_<case>.json`) lists every staged file + checksums (provenance); the **contract** (`contract_<case>.json`) states the WPS-relevant facts `brc-wrf` should trust (sources, cadence, `fg_name`). When they disagree about intent, trust the contract. |

See also: [API reference](../API-REFERENCE.md) · [walk-through index](README.md)
