# WRF Staging State Playbook

Short print-oriented explanation for John/JRL and Michael: what `brc-tools` owns in the WRF
workflow, what is already proven, and what should happen next. **This is the single cold-start
source of truth for the WRF lane** — start here; the full detail/proof reference follows in
§1–§8 below (this file absorbed the former `docs/WRF-INPUT-STAGING.md`).

## Cold-start handoff (for the next Claude Code session)

**You are in `brc-tools`. GFS analysis is now a supported, staged, verified, and WRF-consumed
second forcing source for the Pelican hot-swap lane. `brc-wrf` already ran WPS (`Vtable.GFS`) ->
metgrid -> `real.exe` -> `wrf.exe`, archived the run, and rendered paired NAM/GFS quicklooks.**

State (2026-06-30):
- **NAM baseline complete:** `brc-wrf` has the successful `pelican2013_nam_3_1_333m_75lev`
  3/1/0.333 km, 75-level, six-hour run.
- **RAP staged + verified, but blocked in WRF:** the RAP bundle under
  `/scratch/general/vast/$USER/wrf_inputs/pelican2013_rap_3_1_333m_75lev/` has 7 hourly RAP-130
  GRIB files and a valid contract, but two WPS-only `brc-wrf` proofs blocked before `real.exe`:
  hybrid RAP lacked a real-ready 3D atmosphere, pressure RAP lacked layered soil temp/moisture.
- **ERA5 blocked locally:** no `era5` WRF-staging source exists here, `brc-tools-2026` lacks
  `cdsapi`/`ecmwfapi`, and CDS credentials were not configured. `brc-wrf` has a plausible
  WPS-side `Vtable.ECMWF`, but staging is not ready.
- **GFS analysis SUPPORTED + STAGED + VERIFIED + CONSUMED (2026-06-30):** `[models.gfs_analysis]`
  (NCEI grid-004 0.5° GRIB2 `gfsanl_4`, auth-free direct GET, same lane as NAM/RAP) +
  `stage_gfs_analysis()` + matrix row + tests. Maps to `Vtable.GFS`, `wps_fg_name=["GFS"]`,
  humidity = RH; the live `.inv` confirms 4-layer soil T/moisture, land-sea mask, skin temp,
  snow/ice, and a real-ready 26-level atmosphere — clearing the RAP
  `NUM_METGRID_SOIL_LEVELS = 0` blocker. Staged + `verify_manifest` 2/2 OK to
  `/scratch/general/vast/$USER/wrf_inputs/pelican2013_gfs_3_1_333m_75lev/` (12Z+18Z,
  `interval_seconds=21600`, a structural mirror of the NAM baseline); `brc-wrf` consumed the
  contract in job `13753673` (WPS/`real.exe`/`wrf.exe`/archive complete,
  `NUM_METGRID_SOIL_LEVELS = 4`, `num_metgrid_levels = 27`); paired NAM/GFS quicklooks (30 PNGs
  per forcing) in job `13755401`. Chosen over NCAR-RDA FNL (auth-gated; 0.5° GFS is finer than
  2013 FNL's 1°). NCEI product:
  https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast
- **Environment guardrail:** every brc-tools Python, Herbie, staging, manifest-verification, or
  pytest command must use `conda run -n brc-tools-2026 ...` or
  `/uufs/chpc.utah.edu/common/home/u0737349/software/pkg/miniforge3/envs/brc-tools-2026/bin/python`.
  Do not rely on inherited shells; Codex has inherited `clyfar-nov2025` in this lane.

Current stop point:
1. Default next work is in `brc-wrf`: review the completed NAM/GFS paired quicklooks and write
   the science-review packet. Do not redo GFS source support.
2. Optional new-source work belongs here only if John explicitly asks for FNL, corrected RAP, or
   ERA5/CDS support.
3. Cross-repo handoff: `../brc-wrf/brc-docs/BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md`.

Optional brc-tools fast-follow (only if `brc-wrf` wants finer LBCs): grid-4 ships `_003`/`_006`
offsets, so 3-hourly boundaries (`interval_seconds=10800`) are available from the 12Z+18Z cycles
with a small stager change (forecast-offset enumeration; the analysis filename template currently
hardcodes `_000`).

Caretaker: when a brc-tools path moves, re-check that `../brc-tools` <-> `../brc-wrf` doc links
still resolve. `brc-wrf` consumes the contract sidecar, not `staged_files`.

Stop points (still `brc-wrf`/human-owned): WPS, `real.exe`, `wrf.exe`, `sbatch`, NetCDF-heavy
reads, archive inventories, and quicklooks. brc-tools staging for the GFS hot-swap is done
(John-authorized 2026-06-30); any *further new-source* downloads/staging still warrant a
heads-up first. Remaining brc-tools backlog (not blocking brc-wrf): `WISHLIST-TASKS.md` →
"Session closeout" section.

Maintenance check after WRF-lane doc edits:

```bash
conda run -n brc-tools-2026 python scripts/check_wrf_doc_freshness.py
```

## One-Sentence State

`brc-tools` can stage WRF-ready GRIB inputs (NAM, RAP, and now GFS analysis; GEFS reforecast
partial), verify their integrity, and hand `brc-wrf` a manifest/contract boundary; the NAM-only
single-stream path is proven through WPS, `real.exe`, and `wrf.exe`, and GFS analysis is staged,
verified, and consumed by the completed Pelican GFS WRF-side run plus paired NAM/GFS quicklooks.

## What This Repo Owns

| Owns | Plain language |
| --- | --- |
| NWP source access | Herbie/NCEI/S3-facing data discovery and downloads. |
| WRF input staging | Put GRIB files under `/scratch/general/vast/$USER/wrf_inputs/<case>/`. |
| Manifest verification | Prove every staged file still exists and matches size/hash. |
| Case contract | Tell `brc-wrf` the WPS-relevant facts: sources, cadence, `fg_name`, `interval_seconds`. |
| Input quicklooks | Sanity maps of staged source data before WPS/WRF consumes it. |

This repo does not run WPS, `real.exe`, `wrf.exe`, or Slurm WRF integrations. Those belong in
`brc-wrf`, using CHPC settings from `brc-knowledge`.

## What Is Proven (summary — evidence in §2)

| Item | Status |
| --- | --- |
| NAM analysis staging | Proven; drove the successful Jan-2013 WRF proof (§2). |
| GFS analysis staging | Staged + verified + consumed — see the cold-start GFS bullet above. |
| Manifest verification | Proven: the existing proof manifest verifies `28/28 OK`. |
| Contract sidecar | Implemented for fresh stages; old proof scratch predates this sidecar (§8). |
| Lead-time subsetting | Implemented for GEFS reforecast to cut unnecessary download volume. |
| GEFSv12 reforecast download | Partial staged files proven; full WPS two-stream path not proven. |
| DTN posture | Full transfer work runs on `notchpeak-dtn`, not login nodes (§5). |

## Where We Should Go Next

Done already: `feat/wrf-input-staging` merged to `main` (PR #22 NAM-only; PR #23 hygiene batch,
`52908df`, 2026-06-16); `gfs_analysis` support added on branch `nwp/gfs-analysis-source`, staged,
verified, and consumed by the completed `brc-wrf` GFS run.

| Order | Next move | Stop point |
| --- | --- | --- |
| 1 | Keep NAM-only as the baseline proof. | Do not rename it as GEFS+NAM. |
| 2 | Review the paired NAM/GFS quicklooks. | Before approving more source work. |
| 3 | Keep every full-stage or full-run step behind CHPC ownership boundaries. | DTN for downloads, `brc-wrf` for WPS/WRF, `brc-knowledge` for Slurm truth. |

Open microtasks live in §4.

## Reading Packet

Read with the matching `brc-wrf` packet (sibling checkouts; paths from repo root):

1. This file (§1–§8 below are the detail/proof reference).
2. `docs/nwp/NWP-SOURCE-MATRIX.md` — per-source Herbie-vs-direct decisions + Herbie currency.
3. `../brc-wrf/brc-docs/BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md` — active cross-repo handoff.
4. `../brc-wrf/brc-docs/BRC-WRF-STATE-PLAYBOOK.md` and `BRC-WRF-FIRST-CASE.md`.
5. `../brc-wrf/brc-docs/BRC-WRF-PELICAN-RAP-FEASIBILITY.md` — only if RAP is explicitly revived.
6. `../brc-knowledge/scholarium/reference-base/resources/`:
   `chpc-team-resource-inventory.md` (sections 1-3 + Q1 — SSOT for nodes, partitions, storage,
   DTN, login-node etiquette); `wrf-on-chpc-quickstart.md` (sections 2, 3, 8 — build/run, module
   stack, scaling); `run_wrf_feb05.slurm` (validated Feb-2013 Basin run script, notch392,
   56 tasks — the run itself is `brc-wrf` work); `chpc-slurm-job-examples.md` (DTN +
   compute-node proxy examples).

For a new developer, the key idea is simple: `brc-tools` makes the input pile clean and
auditable; `brc-wrf` proves WRF can consume it.

---

# Detail reference (formerly `docs/WRF-INPUT-STAGING.md`)

**Goal of this track:** produce, from NWP data, the GRIB inputs WRF/WPS actually want for a Uinta
Basin case (test case: **2013-01-31 12Z → 2013-02-02 00Z**), stage them to scratch with
provenance, and *prove* WRF ingests them. brc-tools owns the **download + staging + manifest**;
`brc-wrf` owns **ungrib → metgrid → real** and the WRF run.

**Status:** end-to-end validated 2026-06-13 — NAM-only staging drove WPS → `real.exe` →
`wrf.exe` to `SUCCESS COMPLETE WRF` on `notch392` (evidence in §2); merged to `main` (PR #22
NAM-only; PR #23 schema v2 + token preflight). **Scope of the proof:** NAM-only single-stream
(`Vtable.NAM`); a *known* 12/4 km nested Basin domain (not a fresh standalone 4 km); the GEFS
reforecast two-stream path is **not** yet run. Validated at commit `3384912`; the later
hardening (IPv4-only/timeouts, `--plan`, `verify_manifest`, contract sidecar) is additive and
does not touch how GRIB is downloaded or laid out, so the proof holds.

## 1. What it is (architecture)

| File | Role |
|---|---|
| `brc_tools/nwp/wrf_staging.py` | `stage_reforecast` / `stage_nam_analysis` / `stage_case` / `build_manifest`; reforecast via `Herbie.download()` (retains raw GRIB, never `NWPSource.fetch()`), NAM analysis via a direct auth-free NCEI HTTP GET; both move into the canonical layout + provenance manifest. |
| `scripts/stage_wrf_inputs.py` | thin CLI wrapper. |
| `brc_tools/nwp/wrf_quicklook.py` | cfgrib reopen → crop → `plot_planview` sanity maps; opt-in obs overlay. |
| `tests/test_wrf_staging.py` | mocked tests + opt-in live (`RUN_LIVE_HERBIE=1` / `RUN_LIVE_NCEI=1`). |
| `brc_tools/nwp/lookups.toml` | `[models.gefs_reforecast]` + S3-confirmed `wps_variable_levels`; `[models.gfs_analysis]`. |

**Source mapping (decided, evidence-backed):** operational GEFS (Herbie `gefs`) AWS archive
starts **2017** — useless for 2013. The only Herbie-native GEFS-family source for historical
dates is **GEFSv12 Reforecast** (`gefs_reforecast`, 2000–2019, daily 00Z, 5 members c00/p01–p04):
**per-variable file layout** (one file = one variable across all lead times), pressure fields
**split at 700 hPa** (`{var}_pres` ≤700 hPa, `{var}_pres_abv700mb` >700 hPa — need **both**),
humidity **specific** (`spfh_*`, no `rh_pres`/`rh_2m`), 10 m winds `ugrd_hgt`/`vgrd_hgt`, and
**no land-sea mask / no snow depth**. → the gap is filled by an **auth-free NAM 12 km analysis**
(NCEI `namanl_218`, `stage_nam_analysis`) — a standalone single-stream forcing or a second
ungrib stream (multi-`fg_name` metgrid). **No NCAR RDA / ds083.2 / auth.** The second
independent forcing, `gfs_analysis` (the Pelican hot-swap), is summarised in the cold-start
handoff above.

**Output layout:**
```
/scratch/general/vast/$USER/wrf_inputs/jan2013_basin_gefs/
  gefs_reforecast/c00/<variable_level>_2013013100_c00.grib2   # ensemble forcing (two-stream path)
  nam_analysis/namanl_218_<YYYYMMDD>_<HHMM>_000.grb           # NAM analysis (forcing OR filler)
  manifest_jan2013_basin_gefs.json
```

**Quick start (small smoke; see §5 for where to run big stages):**
```bash
# NAM analysis — the validated single-stream forcing (auth-free NCEI, no RDA):
conda run -n brc-tools-2026 python -m brc_tools.nwp.wrf_staging --case jan2013_basin_gefs \
  --init-time "2013-01-31 00Z" --source nam_analysis --fxx-window 12,48

# GEFS reforecast smoke (2 vars, control member, lead-subset to f12..f48, ~6x smaller):
conda run -n brc-tools-2026 python -m brc_tools.nwp.wrf_staging --case jan2013_basin_gefs \
  --init-time "2013-01-31 00Z" --members 0 --variable-levels tmp_2m,weasd_sfc \
  --fxx-window 12,48 --lead-subset

# GFS 0.5° analysis — Pelican hot-swap second forcing (12Z+18Z mirror the NAM baseline):
conda run -n brc-tools-2026 python -m brc_tools.nwp.wrf_staging --case pelican2013_gfs_3_1_333m_75lev \
  --init-time "2013-02-02 12Z" --source gfs_analysis --fxx-window 0,6 --http-ipv4-only --no-quicklook
```

## 2. What's proven (verification log)

### Validated end-to-end (2026-06-13, NAM-only, Jan-2013 Basin)

The brc-wrf runtime proof closed the loop. Staged from brc-tools `33849121…`
(`feat/wrf-input-staging`) → manifest `…/wrf_inputs/jan2013_basin_gefs/manifest_jan2013_basin_gefs.json`
(`nam_analysis`: 7 files, `gefs_reforecast`: 21 files):

- **WPS:** 14 `met_em` (d01+d02, 6-hourly `2013-01-31_12:00:00` → `2013-02-02_00:00:00`),
  `num_metgrid_levels = 40`, carrying `LANDSEA`, `SOILHGT`, `SKINTEMP`, `SEAICE`, `SNOW`,
  `SNOWH`, 4 soil-temperature + 4 soil-moisture layers.
- **`real.exe`:** `d01 2013-02-02_00:00:00 real_em: SUCCESS COMPLETE REAL_EM INIT` →
  `wrfinput_d01` + `wrfbdy_d01`, **no missing mandatory field** (one non-fatal
  `forcing artificial silty clay loam at 2 points, out of 18000`).
- **`wrf.exe`:** Slurm step `13472096.0` completed `0:0` on `notch392` (56 tasks);
  `rsl.out.0000` → `d01 2013-02-02_00:00:00 wrf: SUCCESS COMPLETE WRF`; 37 hourly `wrfout`/domain.
- **Archive:** `lawson-group6/jrlawson/wrf_archive/jan2013_basin_gefs/run_20260613T044846Z`
  (194 files, 2.2 G).

> ⚠️ **Don't read NAM-only WPS truth off this mixed-source manifest.** It lists `nam_analysis`
> (7 files) **and** partial `gefs_reforecast` (21), but WPS consumed **NAM-only**. Trust the
> contract / source intent (`wps_fg_name`, `sources`), not the manifest file list.

**Interpretation:** NAM-only staging is sufficient for the validated 12/4 km Basin case; the GEFS
reforecast stream serves the optional ensemble/two-stream path, not a prerequisite. **Don't
overstate:** known nested domain, NAM-only (no two-stream yet), and the archive wrapper had one
post-WRF rsync failure repaired separately (§5d).

**DTN IPv6 hang found + fixed:** the first DTN job (`13471949`) wedged in `SYN-SENT` to an NCEI
IPv6 address on :443 (`curl -4` → 200, `curl -6` → timeout); the IPv4-only retry (`13472014`)
finished. Hardened as `--http-ipv4-only` / `BRC_TOOLS_HTTP_IPV4_ONLY=1` (process-global
`socket.getaddrinfo`→AF_INET, covers Herbie/S3 **and** the direct NAM GET) plus split
`(connect=10 s, read=300 s)` timeouts; the DTN job script exports the env var by default.

### Earlier (pre-validation) proofs

- **NAM analysis staging** (`stage_nam_analysis`) unit-tested (mocked HTTP: layout, 6-hourly
  cycle enumeration, isolated-gap skip, all-missing raise, `source="nam_analysis"` manifest);
  the control-cycle NCEI URL confirmed live (HTTP 200, `GRIB` magic), then proven through the
  full DTN stage + WPS/`real.exe`/`wrf.exe` run above.
- **Live downloads** on notchpeak1 → scratch (download → move → manifest → quicklook):
  `tmp_2m` 58 MB, `weasd_sfc` 13 MB (skip-entries); `hgt_pres` (≤700 hPa) **469 MB** and
  `hgt_pres_abv700mb` (>700 hPa) **307 MB**, each 80 × 3-hourly, f3→f240. The S3-confirmed token
  list and the **`_abv700mb` split-file path** are proven to download.
- **Lead-time subsetting** (`--lead-subset`) proven: `tmp_2m` **58 MB → 9.7 MB** (only f12–f48,
  byte-range via Herbie `search=`). Full WPS set drops from ~4 GB to ~650 MB.
- Manifest carries full provenance (`git_sha`, `tool_version`, `herbie_version`, per-file
  `sha256`, `size_bytes`, `remote_url`, empirically-parsed `lead_times`).
- Quicklooks showed the expected physics: `tmp_2m` = the **cold-pool inversion**, `weasd_sfc` =
  the **snowpack**.

**⚠️ Honest scope of the reforecast files on scratch:** a 4-variable partial proof, NOT a
WPS-runnable set. A full single-member WPS set is the 21 `wps_variable_levels` ≈ ~4 GB, and
without `--lead-subset` it downloads f3→f240 when the case needs f12→f48 (~84 % wasted) — see §5.

## 3. Known gaps / blockers

1. ~~WPS-field adequacy unverified~~ **RESOLVED (2026-06-13).** The auth-free NAM 12 km analysis
   carries the full WRF field set the reforecast lacks (land-sea mask, SST, skin temp, `snod`,
   4-layer soil) — see §2. The reforecast's optional **second metgrid stream** (two-stream) is
   the only adequacy question still open.
2. ~~FNL filler stub / NCAR RDA ds083.2~~ **DROPPED.** Herbie's `nam.py` has no NCEI-historical
   source, so NAM-2013 is a direct NCEI HTTP GET (`stage_nam_analysis`) — no RDA account, no
   auth. NAM also carries standard 4-layer WRF soil, retiring the reforecast `bgrnd` worry.
3. **Full reforecast stage is multi-GB** (~4 GB whole-bucket) → use `--lead-subset` (~650 MB) +
   a DTN (§5). One NAM analysis set for the case window is ~7 files ≈ 0.8 GB.
4. **`obs_sanity_overlay` live behaviour untested** (unit-tested with synthetic data); 2013 basin
   obs are sparse anyway.
5. **Download node tension:** login nodes have internet but shouldn't do heavy I/O;
   compute/interactive nodes may lack internet (proxy). → use a **DTN** (§5).

## 4. Microtask backlog

Tags: **[AI]** an agent can do solo · **[H]** needs a human · **[AI+H]** pair.

### A. brc-tools staging (this repo)
- [x] **Done:** `stage_nam_analysis()`; `--lead-subset`; `--plan`/`--dry-run` (`plan_case`,
  offline); `obs_sanity_overlay` unit test; `verify_manifest()` / `--verify-manifest <path>`
  (existence + size + recomputed `sha256`, nonzero exit on mismatch); total bytes + elapsed
  recorded into manifest `provenance`; token-preflight diffing the S3 prefix against
  `wps_variable_levels` (offline-tested; live `--preflight` unverified); degraded skip-manifest
  `lead_times` limitation documented in the manifest (label-only; schema v2); a window crossing
  the 240 h bucket boundary warns + stages one bucket only (kept; test pins it). Reforecast
  `bgrnd` soil mapping is **moot** — soil comes from NAM analysis (standard 4-layer
  0-10/10-40/40-100/100-200 cm) unless a reforecast-soil run is attempted later.
- [ ] **7. [AI]** Multi-member staging proof (c00–p04) + per-member layout/manifest aggregation.
- [ ] **10. [AI]** Operational `gefs` (post-2017) staging path reusing the same machinery.
- [ ] **13. [AI]** Pin `wps_variable_levels` per data-year if the reforecast token set differs
  across 2000–2019.

### B. brc-wrf side (WPS/WRF validation — the proof)
- [x] **Done:** the validated NAM single-stream path (§2): `Vtable.NAM` → 14 `met_em` with full
  soil/mask/skin fields → `real.exe`/`wrf.exe` success; single-stream `contract_<case>.json`.
- [ ] **16. [AI+H]** (Two-stream, later) Build a **Vtable** for GEFSv12 reforecast (NCEP GRIB2,
  `_pres`+`_abv700mb` split, `bgrnd` soil) and run `&metgrid fg_name='GEFS','NAM'` (NAM as
  filler), if ensemble-reforecast forcing is wanted. Two-stream uses `interval_seconds = 10800`;
  the field-level NAM-vs-reforecast contract split only arises here.
- [ ] **17. [H]** ungrib the staged reforecast dir; confirm intermediate files hold all expected fields.
- [ ] **21. [H]** Confirm geogrid + `geog_data_path` (`/uufs/.../lawson-group6/WPS_GEOG/`) and
  the 4 km Basin domain in `namelist.wps`.

### C. CHPC execution / benchmarking
- [ ] **23. [H]** Run the **full** reforecast stage as a `notchpeak-dtn` job (§5a); confirm the
  DTN reaches AWS.
- [ ] **24. [H]** Verify whether `lawson-np` compute/interactive nodes can reach AWS (proxy?).
  Ask helpdesk@chpc.utah.edu; record the answer in brc-knowledge.
- [ ] **26/27. [brc-wrf]** Scaling + memory benchmarks — WRF-run tuning owned by `brc-wrf`
  (tracked here for continuity): sweep `--ntasks` (e.g. 16/28/56), find the knee (wrf-on-chpc
  §8); confirm actual peak (~50 GiB for 12/4 km) vs `--mem`.

### D. Cross-cutting / hygiene
- [ ] **32. [AI+H]** Ensure brc-wrf docs reference this file + the scratch layout (cross-repo sync).
- [ ] **33. [H]** Retention: scratch auto-purges at 60 days — promote proven inputs to
  `lawson-group6` if reused.

## 5. Running on CHPC (where each step belongs)

### 5a. Downloading/staging GRIB — use a **DTN**, not a login or compute node

CHPC reality (from `chpc-slurm-job-examples.md` and the inventory):
- **Login nodes** (`notchpeak1`): direct internet, but shared — fine for a 1–2 file smoke, not
  for multi-GB (`git`, `ls`, short Python, Claude CLI, light conda are the sanctioned uses).
- **Compute / interactive (`salloc`) nodes** on `lawson-np`: internet is **not guaranteed** —
  "compute nodes may require an http(s) proxy… treat outbound network as *verify first*, not
  assumed." Not a safe place to download from AWS.
- **DTN — `notchpeak-dtn`**: dedicated high-bandwidth node **with internet**, purpose-built for
  large transfers. **Run the full stage here.**

**DTN staging job:** committed at **`scripts/stage_inputs.dtn.slurm`** — submit with:
```bash
sbatch scripts/stage_inputs.dtn.slurm   # control member, --lead-subset (f12–f48, ~650 MB)
```
It pins `account=dtn / partition=notchpeak-dtn / qos=notchpeak-dtn`, calls the env's python
directly (login env doesn't carry into batch jobs), stages with `--lead-subset`, and writes to
`/scratch/general/vast/$USER/wrf_inputs/jan2013_basin_gefs/`. Quicklook is off on the DTN (no
matplotlib/cartopy) — render figures separately on a login node from the staged files if wanted.

### 5b. Running WRF — owned by `brc-wrf`

brc-tools does not own WRF-run Slurm profiles. For the run script, node/task/memory profile,
launcher, and any benchmarking sweep, see `brc-wrf` + `brc-knowledge`:
`../brc-wrf/brc-docs/BRC-WRF-FIRST-CASE.md` and the validated `run_wrf_feb05.slurm` it
references. (The DTN **staging** job in §5a is brc-tools' — staging GRIB is our lane; running
the model is not.)

### 5c. Storage & retention

`/scratch/general/vast/$USER` (50 TiB quota, **60-day atime purge**) for active inputs/runs;
promote durable inputs/outputs to `lawson-group6` (33 TiB, no purge, most reliable compute-node
mount).

- **Scratch is not durable.** The 60-day atime purge *will* delete a staged input set you stop
  touching. Treat `wrf_inputs/<case>/` as reproducible-on-demand (re-run the DTN stage), or
  promote a set you intend to reuse to `lawson-group6` and `verify_manifest` it after the copy.
- **One durable tier today.** `lawson-group6` is the durable home for inputs + `wrf_archive/`.
  There is **no** second backup tier — don't claim one in docs/automation unless CHPC/BRC policy
  confirms it. Observed headroom at proof time: `/scratch/general/vast` ~62 %, `lawson-group6`
  ~51 % of 33 TiB — adequate for early ops, not a license to hoard runs.

### 5d. Run / archive hygiene (mostly brc-wrf, documented here for the full picture)

Cross-cutting gotchas the validated proof surfaced:

- **Archive layout:** one run = one timestamped dir,
  `lawson-group6/<namespace>/wrf_archive/<case>/run_<YYYYMMDDTHHMMSSZ>/`. At minimum preserve
  `wrfout*`, the `namelist.*`, and an `rsl.out.0000` success marker.
- **WRF filenames break naïve `rsync`.** `wrfout` names contain colons
  (`wrfout_d01_2013-02-01_12:00:00`); a bare `rsync wrfout_d0* host:dst` parses the colon as a
  remote host and fails (`All source args must come from the same machine`). **Prefix local
  sources**: `rsync ./wrfout_d0* host:dst` (or absolute paths). This bit the proof's archive step.
- **Slurm state ≠ WRF success.** Batch-job state, the `.0` step state, the WRF
  `SUCCESS COMPLETE WRF` marker, and the archive state are separate facts. The proof's batch job
  showed `FAILED` only because the *post-WRF rsync* failed — WRF itself completed `0:0` and
  wrote the success marker. Read `rsl.out.0000` + the `wrfout*` set, not just `sacct` state.
- **Don't probe a full allocation with `srun --jobid`.** An `srun --jobid=<run> … ps` into a
  fully occupied 56-task WRF allocation can't create a step and hangs until killed. Use
  `squeue`, logs, and filesystem evidence instead.

## 6. Login-node load review (what was run there, and the rule of thumb)

The §2 pre-validation proofs ran on **notchpeak1 (login node)**. Honest audit: an S3 prefix
listing (~34 KB), `pytest` (~5 s CPU, no net), a quicklook (cfgrib decode 60 MB + matplotlib),
and the ~73 MB surface-download smoke were all fine; the **776 MB pressure pair (+ sha256 of
~850 MB) was borderline — the limit of what's polite on a login node.**

- A 1–2 file smoke (≤~100 MB) on a login node is fine; the **full ~4 GB stage must NOT run on a
  login node.**
- Interactive/compute nodes carry the opposite risk: they may have **no internet**, so they
  can't download at all without a proxy.
- Rule of thumb: **download/transfer → DTN; model run → notch392; light prep/inspection/Claude →
  login node.** When unsure of a node's connectivity, verify first, or ask helpdesk@chpc.utah.edu.

## 7. Definition of done — all met

Staged + integrity-checked NAM set; `met_em*` with `LANDSEA` + soil + skin temp; `real.exe` →
`wrfinput_d01`/`wrfbdy_d01` with no missing mandatory field; `wrf.exe` → `SUCCESS COMPLETE WRF`
+ durable archive; merged to `main` (PR #22/#23). The only open extension is the two-stream
`fg_name='GEFS','NAM'` path, pursued only if reforecast forcing is wanted.

## 8. Case contract (brc-tools → brc-wrf)

`stage_case` writes `contract_<case>.json` next to the manifest: the WPS/WRF-relevant facts
brc-tools can authoritatively derive from what it staged, so brc-wrf doesn't reverse-engineer
them. **It emits only staging-derived facts** — `num_metgrid_levels` and the `met_em` field list
are metgrid *outputs* and live below as documented proof constants, not in the sidecar.

Sidecar fields (`build_contract`): `case`, `region`, `valid_window`, `sources`,
`source_file_counts`, `cadence_hours` (per source), `interval_hours` / `interval_seconds`
(**derived from the forcing source's cadence** — NAM-only → 6 h / 21600 s; reforecast → 3 h /
10800 s), `wps_fg_name` (`['NAM']` single-stream; `['GEFS','NAM']` two-stream),
`scratch_layout`, and the manifest filename.

> **Note on the on-scratch proof artifact:** the validated run's
> `manifest_jan2013_basin_gefs.json` was written **before** the interval fix and still records
> `interval_hours=3`. The run itself used the correct 6 h NAM cadence (`interval_seconds=21600`,
> per WPS); a fresh stage now stamps `interval_hours=6`. Diffing old vs new manifests shows this
> single expected discrepancy.
>
> **Vocabulary reconcile (brc-tools ↔ brc-wrf):** what this repo calls a "pre-contract manifest"
> is the same artifact `brc-wrf` calls a *reconstructed legacy NAM-only contract*
> (`../brc-wrf/brc-cases/jan2013_basin_nam.contract.json`). The old scratch predates the
> `contract_<case>.json` sidecar, so `brc-wrf` carries a reconstructed NAM-only contract for
> strict validation, while a fresh brc-tools stage emits the real sidecar.

**Proof constants for the validated Jan-2013 Basin run (metgrid/real outputs — not auto-emitted):**

| field | value |
|---|---|
| `interval_seconds` | `21600` (6 h NAM cadence) |
| `num_metgrid_levels` | `40` |
| `met_em` fields | `LANDSEA`, `SOILHGT`, `SKINTEMP`, `SEAICE`, `SNOW`, `SNOWH`, 4 soil-temp + 4 soil-moisture layers |
| `met_em` count | 14 (d01+d02, 6-hourly `2013-01-31_12:00:00`→`2013-02-02_00:00:00`) |
| `wps_fg_name` | `NAM` |
