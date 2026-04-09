### `brc-tools` - Bingham Research Center (python) Tools

> AI agents: see [`CLAUDE.md`](CLAUDE.md) for project context.
> Documentation index: [`docs/`](docs/). Current focus: HRRR/RRFS ingest in [`docs/nwp/`](docs/nwp/).

Functions that are general to many packages used by the Bingham Research Center. 

Note that the package is under `brc_tools` (note the underscore) and not `brc-tools` (note the hyphen). 

The wishlist includes:

- [x] Basic setup
- [ ] Visualizations 
- [ ] Data download 
  - NWP
  - Observations
  - Satellites
- [ ] Verification/evaluation
- [ ] Filtering methods for time series
- [ ] Machine learning tools for optimising a model 
- [ ] Develop a coding guideline (e.g., consistency in British or American English for a bloody start)
- [ ] **Are we going to do testing?!**

There should be an easy entry point for acquiring data. "If it is saved to disc, load it; else, download it and save it for next time. Either way, show me documentation of its structure". This makes it quick to ask, how is ozone correlated with wind direction at Vernal, and there is a fixed method of, say, subsetting or post-processing data before saving so it is obvious what is being loaded. Documentation about data structure and function use must be written quickly; consider tests and also little dataframes with the data format and for testing itself. 

John Lawson and Michael Davies, Bingham Research Center, 2025

## CHPC Deployment

This package is deployed on CHPC to push weather data to the BasinWx website (`basinwx.com`).

**Canonical reference:** [`docs/CHPC-REFERENCE.md`](docs/CHPC-REFERENCE.md) (account, partitions, salloc, cron).

**Quick reference:**
- **Production script:** `brc_tools/download/get_map_obs.py` (fetches and uploads observations every 10 min)
- **Upload module:** `brc_tools/download/push_data.py` (handles secure POST to website API)
- **Required env vars:** `DATA_UPLOAD_API_KEY`, `SYNOPTIC_API_TOKEN`

**Cross-repo data contract:** `ubair-website/DATA_MANIFEST.json` defines the website expectations; deployment notes live in `ubair-website/CHPC-IMPLEMENTATION.md`.

This is a list of files that are prime for putting into functions from notebooks.

- [AQM 8-hr ozone in parallel](in_progress/notebooks/gemini_parallel-aqm.py)