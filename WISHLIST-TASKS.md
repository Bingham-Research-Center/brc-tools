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

- [x] **GEFS `omega_pl`: dropped (2026-11-21).** No one GEFS file holds 850/700/500/300 mb VVEL (`atmos.5` has 850 only, `atmos.5b` the rest), and nothing read it (`ub-wx`'s recipes fetch HRRR omega). A GEFS fetch now skips the alias, as RRFS's does. If a consumer appears, add per-level products. The other five `_pl` aliases read `atmos.5`, GEFS LCDC is gone (no GEFS file has it), and TCDC is `absent_at_f00`.
- [ ] Make the tree ruff-clean: ruff is installed in both envs, but `ruff check` still reports pre-existing findings (import order, `datetime.UTC` alias), so it cannot gate a PR yet.

## Priority 2: Operational delivery

Issue #10 is closed: four HRRR jobs upload on cron and RRFS is fetchable. What an RRFS
product on BasinWX would take is ops work, now in the `brc-data-ops` repo (created
2026-11-21; `docs/OPS-BACKLOG.md` there). Left here:

- [ ] **Sub-hourly accumulations** — `NWPSource` keeps the `subh` 15-min axis (GH #82), but
  only for instantaneous fields: HRRR `subh` precip is 15-min buckets, RRFS's runs from the
  top of the hour, and no alias describes either. Needed only if a `subh` product wants precip.
- [ ] Add structured logging to the operational script (replace print statements for scheduled/unattended runs).
- [x] **`.dev` deploy pull** — done: website 1.7.9 on `.dev` (2026-11-21 09:43Z) stopped writing `observations/filelist.json` and removed it; nothing at CHPC reads it. `.com` follows with website 1.8.0.
## Priority 3: Analysis capability

Extend the case study toolkit for deeper diagnostics.

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
  shifts an hour against its cycle at each DST change. Decide in `brc-data-ops` (O5).
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
