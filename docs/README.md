# docs/

Project documentation. Topical files only — agent context lives in
`../CLAUDE.md`, the human entry point in `../README.md`.

- **walkthroughs/** — plain-language per-tool guides + GLOSSARY (start here if new).
- **API-REFERENCE.md** — full module / function reference.
- **API-CLIENTS.md** — external API wrappers (FlightAware, FR24, Perplexity, Mistral, soundings, EPA AQS AirData) under `brc_tools/api/`.
- **CASE-STUDY-GUIDE.md** — how to write a case-study script.
- **CHPC-REFERENCE.md** — canonical CHPC account, partitions, salloc, cron (incl. HRRR upload).
- **CROSS-REPO-SYNC.md** — protocol for keeping the four sibling repos aligned.
- **WEBSITE-INTEGRATION.md** — BasinWX upload contract (endpoint, auth, dataTypes, schemas).
- **ENVIRONMENT-SETUP.md** — venv/conda setup for new team members.
- **MODIS-CONTEXT-RENDERER.md** — host-neutral NASA CMR/GIBS MODIS timing,
  rendering, caching, and provenance workflow.
- **WRF-INPUT-STAGING.md** — WRF/WPS GRIB staging reference: status, proof evidence, and microtasks (the playbook is the handoff).
- **WRF-STAGING-STATE-PLAYBOOK.md** — the single WRF cold-start handoff + state packet (start here for the WRF lane).
- **WRF-GEFS-NAM-FIELD-MAP.md** — DRAFT GEFS/NAM two-stream field-map (parked, not proven).
- **WRF-FIGURE-ENGINE.md** — dataset-agnostic WRF figure engine + `scripts/wrf_figures.py --config <case.toml>` CLI (TOML schema, domain-awareness, named-skip preflight). Per-study cases live in the study repo.
- **WRF-WINDS.md** — basin-winds-style plan views + arbitrary-transect cross-sections straight from `wrfout` (native eta levels), `scripts/wrf_winds.py --config <case.toml>` + `/wrf-basin-winds` skill. Works against a run that is still writing.
- **WRF-CONVECTIVE.md** — convective diagnostics from `wrfout`: reflectivity plan views and
  native-eta sections, **reflectivity sampled on a real radar's beam surfaces**, skew-T with a
  parcel path, hodographs, high-cadence `auxhist` access and `tslist` station verification.
  `scripts/wrf_convective.py --config <case.toml>` + `/wrf-convective` skill.
- **VISUAL-SUITE-SOP.md** — the operating procedure for producing a suite of WRF
  visuals across all three engines, plus the method errors already found and the
  gaps still open. Read before a first sweep on a new case.
- **FORECAST-FUNNEL.md** — NAM "forecast funnel" synoptic montage (250/500/600 hPa + surface analysis) + `/basin-forecast-funnel` skill and `scripts/forecast_funnel.py` CLI.
- **nwp/NWP-SOURCE-MATRIX.md** — per-source download matrix (Herbie vs direct) + Herbie currency.
- **nwp/** — HRRR/RRFS roadmap (current operational focus).
