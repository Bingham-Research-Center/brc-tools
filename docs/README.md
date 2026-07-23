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
- **FORECAST-FUNNEL.md** — NAM "forecast funnel" synoptic montage (250/500/600 hPa + surface analysis) + `/basin-forecast-funnel` skill and `scripts/forecast_funnel.py` CLI.
- **nwp/NWP-SOURCE-MATRIX.md** — per-source download matrix (Herbie vs direct) + Herbie currency.
- **nwp/** — HRRR/RRFS roadmap (current operational focus).
