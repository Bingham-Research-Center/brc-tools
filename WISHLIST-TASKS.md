# BRC Tools — Task Backlog

Completed items are removed once merged; git history is the record.

## Forecast funnel (NAM synoptic montage) — follow-ups

Shipped: `/basin-forecast-funnel` skill + `scripts/forecast_funnel.py` (+ `.dtn.slurm`)
rendering a 250/500/600 hPa + surface-analysis montage from a NAM analysis
(`brc_tools/nwp/forecast_funnel.py` + `brc_tools/visualize/funnel.py`; city labels added to
`visualize/basemap.py`). Reference: **`docs/FORECAST-FUNNEL.md`**.

- **NAM was retired on 2026-11-03** — the funnel has no source for later inits (GH #81).
  A successor (RRFS North America 13 km or GFS) is the one item here that blocks new cases.

Not blocking:

- **Post-2017 NCEI grib2 NAM template** to close the 2017-04 → 2020-03 auto-pick gap
  (`nam_218_<date>_<hhmm>_000.grb2`; a new `[models.*]` block in `lookups.toml`).
- Both data paths are validated against **real GRIB** (Herbie 2025-10-11 18Z from AWS; NCEI
  2013-01-31 00Z) — this surfaced + fixed three bugs (per-variable cfgrib open for grib1,
  TFP gradient-gate for front noise, RH→q fallback because `awphys` has no SPFH aloft).
  Remaining: confirm the DTN `sbatch scripts/forecast_funnel.dtn.slurm` submission mechanics
  on a real DTN (couldn't be run from the dev sandbox).

## Priority 1: Reliability

`NWPSource`, `ObsSource` and the fetch → extract → align → score chain are covered by
mocked-Herbie/SynopticPy integration tests (`tests/test_nwp_source_integration.py`,
`test_obs_source_integration.py`, `test_verification_pipeline.py`; fakes in
`tests/_nwp_fakes.py`). Still open:

- [ ] **GEFS aliases point at a file that cannot serve them.** `NWPSource("gefs")` defaults to `atmos.25`, the *sparse* `pgrb2s.0p25` file (26 messages at f000, 38 at f006; live index 2026-11-20 00Z). It has **no `mb` levels**, so all six `*_pl` aliases (product `atmos.25`) match nothing; `cloud_cover_low` (`LCDC`) is absent too; `cloud_cover_total` is absent at f000 only (a candidate for `absent_at_f00`). Pressure levels live in the `pgrb2a`/`pgrb2b` files. Decide the `_pl` product, then pin a GEFS index fixture test like `tests/test_rrfs_aliases.py`. No known caller fetches these through `NWPSource`, which is how it went unnoticed. (GEFS `precip_1hr` was dropped in #85: GEFS has no hourly bucket.)
- [ ] Make the tree ruff-clean: ruff is installed in both envs, but `ruff check` still reports pre-existing findings (import order, `datetime.UTC` alias), so it cannot gate a PR yet.

## Priority 2: Operational delivery

Issue #10 is closed: four HRRR jobs upload on cron and RRFS is fetchable. What an RRFS
product on BasinWX would take is ops work, parked in `docs/BRC-DATA-OPS-HANDOFF.md` for the
planned `brc-data-ops` repo. Left here:

- [ ] **NWPSource sub-hourly time axis** (GH #82) — needed before any product can update from every RRFS cycle.
- [ ] Add structured logging to the operational script (replace print statements for scheduled/unattended runs).
- [ ] **`.dev` deploy pull** — the `.dev` Linode still needs a deploy pull to close the `filelist.json` fossil; `.com` + `.dev` fan-out itself is live (2026-04-24).
## Priority 3: Analysis capability

Extend the case study toolkit for deeper diagnostics.

- [ ] HRRR/RRFS sub-hourly (15-min) through NWPSource — the KVEL cron reads HRRR `subh` hourly via Herbie directly; NWPSource still collapses it (GH #82).
- [ ] GEFS ensemble workflows — spread, probability, lagged ensemble. Config exists; no analysis code yet.
- [ ] **Synoptic USGS-HYDRO access** — the token lacks network `mnet_id=203`, so `stream_flow`/`gage_height` queries return zero. Email `support@synopticdata.com` to add it; the workaround is built: `brc_tools.hydro` (NWIS + AWDB clients, PR #75). Fact + evidence folded into `docs/CHPC-REFERENCE.md`. `scripts/inventory_streamflow_vernal.py` lights up once granted.

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

## Priority 6: Seasonal ops (pause/resume)

- [ ] **Clyfar's winter job is live again** (crontab, since 2026-11-20) and fans out
  through `send_json_to_all`. Comment it out again around the end of March 2027.
- [ ] **Cron runs in Mountain time, not UTC** (no `CRON_TZ`), so every model-tied job
  shifts an hour against its cycle at each DST change. Decide in `brc-data-ops`.
- [ ] **UDOT camera scraper** (GH #53) — its branch was deleted 2026-11-21; the commit is
  kept as tag `archive/michael-image-gathering`.

## Priority 7: CHPC infra hygiene (from 2026-05-13 sanity check)

Triggered by the live audit on notch392; details in
`brc-knowledge/scholarium/reference-base/chpc/chpc-team-resource-inventory.md`
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
