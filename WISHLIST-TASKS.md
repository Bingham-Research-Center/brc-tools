# BRC Tools — Task Backlog

Completed items are removed once merged; git history is the record.

## Forecast funnel (NAM synoptic montage) — follow-ups

Shipped: `/basin-forecast-funnel` skill + `scripts/forecast_funnel.py` (+ `.dtn.slurm`)
rendering a 250/500/600 hPa + surface-analysis montage from a NAM analysis
(`brc_tools/nwp/forecast_funnel.py` + `brc_tools/visualize/funnel.py`; city labels added to
`visualize/basemap.py`). Reference: **`docs/FORECAST-FUNNEL.md`**. Not blocking:

- **Post-2017 NCEI grib2 NAM template** to close the 2017-04 → 2020-03 auto-pick gap
  (`nam_218_<date>_<hhmm>_000.grb2`; a new `[models.*]` block in `lookups.toml`).
- Both data paths are validated against **real GRIB** (Herbie 2025-10-11 18Z from AWS; NCEI
  2013-01-31 00Z) — this surfaced + fixed three bugs (per-variable cfgrib open for grib1,
  TFP gradient-gate for front noise, RH→q fallback because `awphys` has no SPFH aloft).
  Remaining: confirm the DTN `sbatch scripts/forecast_funnel.dtn.slurm` submission mechanics
  on a real DTN (couldn't be run from the dev sandbox).

## Priority 1: Reliability

The NWP/obs pipeline is functional but undertested. One regression in
alias resolution or coordinate handling could silently produce wrong data
in every case study.

- [ ] **NWPSource integration tests (mocked Herbie)** — mock `Herbie.xarray()` to return synthetic datasets; test alias resolution, product grouping, coordinate normalization, spatial cropping, waypoint extraction, and failure handling. This is the single highest-leverage task.
- [ ] **ObsSource integration tests (mocked SynopticPy)** — mock `TimeSeries` to return synthetic DataFrames; test alias renaming, waypoint column injection, timezone stripping.
- [ ] **End-to-end pipeline test** — fetch → extract_at_waypoints → align_obs_to_nwp → paired_scores with synthetic data. Validates the full verification workflow.
- [ ] Install and configure ruff in the brc-tools conda env (referenced in docs but not installed).

## Priority 2: Operational delivery (issue #10)

The case study pipeline proves the NWP library works. Closing #10 means
the website receives fresh HRRR forecasts automatically.

- [ ] **Define BasinWX JSON contract for HRRR waypoint forecasts** — document the expected JSON shape, variable names (`PM_25_concentration` vs `pm25_concentration`), and upload endpoint. Generic upload contract now documented in `docs/WEBSITE-INTEGRATION.md`; this item remains for the HRRR-waypoint-specific variable naming.
- [ ] Test data export format matches the JSON contract above.
- [ ] Add structured logging to the operational script (replace print statements for scheduled/unattended runs).
- [ ] **`.dev` deploy pull** — the `.dev` Linode still needs a deploy pull to close the `filelist.json` fossil; `.com` + `.dev` fan-out itself is live (2026-04-24).
## Priority 3: Analysis capability

Extend the case study toolkit for deeper diagnostics.

- [ ] HRRR sub-hourly (15-min) support — product "subh" is defined in lookups.toml but untested.
- [ ] GEFS ensemble workflows — spread, probability, lagged ensemble. Config exists; no analysis code yet.
- [ ] **Synoptic USGS-HYDRO access** — the token lacks network `mnet_id=203`, so `stream_flow`/`gage_height` queries return zero. Email `support@synopticdata.com` to add it; interim workaround = USGS NWIS direct (`dataretrieval`). Fact + evidence folded into `docs/CHPC-REFERENCE.md`. `scripts/inventory_streamflow_vernal.py` lights up once granted.

## Priority 4: Developer experience

Important before onboarding new contributors.

- [ ] GitHub Actions CI/CD (run pytest + ruff on PRs).
- [ ] Pre-commit hooks for code quality.
- [ ] `CONTRIBUTING.md` with git workflow (document for range of experience levels).

## Priority 5: Documentation and agent onboarding

Deferred from Phase 2 of the dual-site fan-out work (2026-04-23); parked
here so the next cold-start agent knows to tackle it.

- [ ] **Roadmap brainstorm** — prepare a small doc (`docs/ROADMAP.md` or
  similar) that captures the next 6–12 months of work in outcome terms, not
  task lists. Input to the CLAUDE.md overhaul.
- [ ] **Update "Key data-flow anchor" in CLAUDE.md** post-fan-out to mention
  `send_json_to_all` + `BASINWX_API_URLS` (small; bundle with the overhaul
  above unless a cold-start agent wants a quick win first).

## Priority 6: Seasonal ops (pause/resume)

- [ ] **Clyfar/FFION/GEFS-plot pipelines paused end-March 2026** for the
  season; resume ~October 2026. When resuming, verify they still use the new
  fan-out path (`send_json_to_all`) — check clyfar's import site first since
  it still uses the legacy `send_json_to_server`.
- [ ] **HRRR surface-layer cron** needs installing on the CHPC cron host
  once fan-out is shipped. Template in `CLAUDE.md` under "HRRR surface layer
  export" (adjust cadence and `--server-url` as needed once `BASINWX_API_URLS`
  is set).

## Priority 7: CHPC infra hygiene (from 2026-05-13 sanity check)

Triggered by the live audit on notch392; details in
`brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md`
(§4 Live mount status, §6 real-world note). Cross-repo items kept here so
the brc-tools cold-start agent surfaces them.

- [ ] **Verify `lawson-group4` / `lawson-group5` mount status from another
  node** — both return "Too many levels of symbolic links" on notch392
  (2026-05-13). Test from a different compute node and from `notchpeak1`
  with `df -hT /uufs/chpc.utah.edu/common/home/lawson-group{4,5,6}`. If
  broken globally, draft a CHPC helpdesk ticket (do not send without
  approval). If only this node, leave a node-blocklist note in
  brc-knowledge.
- [ ] **clyfar `storage_inventory.sh` ARCHIVE_BASE off broken volume**
  (cross-repo) — `clyfar/scripts/storage_inventory.sh:50` hardcodes
  `lawson-group5/clyfar`, which silently reports `N/A` while group5 is
  unreachable. Fix path or unbreak the mount.
- [ ] **clyfar `submit_clyfar.sh` → owned `lawson-np` partition**
  (cross-repo) — currently uses `notchpeak-shared-short` (8h, preemptible).
  Owned partition gives 14d walltime, no preemption, no fairshare cost.
  Trivial sbatch header swap.
