# WRF-Input GRIB Staging — Handoff

> **State:** NAM-only is proven end-to-end (WPS → `real.exe` → `wrf.exe`). GEFS+NAM two-stream is **not** proven.
> **brc-wrf side:** `../brc-wrf/brc-docs/BRC-WRF-STATE-PLAYBOOK.md` · `../brc-wrf/brc-docs/BRC-WRF-FIRST-CASE.md` (paths from repo root; both repos checked out as siblings).

**Status:** ✅ **end-to-end validated** (2026-06-13). NAM-only staging drove WPS → `real.exe` →
`wrf.exe` to `SUCCESS COMPLETE WRF` for the Jan-2013 Basin case on `notch392` (full evidence in
§2). The merge gate (Microtask 30, "merge only after a successful `real.exe`") was **met**, and the
work is now **merged to `main`** (NAM-only via PR #22; the staging-hygiene batch — schema v2 + token
preflight — via PR #23, `52908df`, 2026-06-16). **Scope of the proof:**
NAM-only single-stream (`Vtable.NAM`); a *known* 12/4 km nested Basin domain (not a fresh
standalone 4 km); the GEFS reforecast two-stream path is **not** yet run. Validated at commit
`3384912` (this branch's base, == the staged source `33849121…`, before this session's hardening
commits); those changes are **additive** (IPv4-only/timeouts, `--plan`, `verify_manifest`, contract
sidecar) and do not touch how GRIB is downloaded or laid out, so the proof still holds.

**Branch reconciled with `origin/main`.** A merge commit on `feat/wrf-input-staging` folds in
upstream's slimmed `CLAUDE.md`, the `brc_tools/api/` package, and the `in_progress/` cleanup; the
WRF files and `lookups.toml` did not collide. The in-flight `WISHLIST-TASKS.md` /
`docs/CHPC-REFERENCE.md` edits are committed and merged to `main`.

**Goal of this track:** produce, from NWP data, the GRIB inputs WRF/WPS actually want for a Uinta
Basin case (test case: **2013-01-31 12Z → 2013-02-02 00Z**, one domain, ~4 km), stage them to
scratch with provenance, and *prove* WRF ingests them. brc-tools owns the **download + staging +
manifest**; the sibling **brc-wrf** repo owns **ungrib → metgrid → real** and the WRF run.

> **Canonical CHPC references (read these for any run decision):**
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md` — **single source of truth** for nodes, partitions, storage, DTN, login-node etiquette.
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/wrf-on-chpc-quickstart.md` — WRF build/run, module stack, scaling table (§8).
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/run_wrf_feb05.slurm` — **validated** WRF run script for the Feb-2013 Basin case (notch392, 56 tasks). The WRF run is owned by **brc-wrf**; brc-knowledge carries this script as the canonical reference.
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/chpc-slurm-job-examples.md` — DTN + compute-node proxy examples.

---

## 1. What it is (architecture)

| File | Role |
|---|---|
| `brc_tools/nwp/wrf_staging.py` | `stage_reforecast` / `stage_nam_analysis` / `stage_case` / `build_manifest`; reforecast via `Herbie.download()` (retains raw GRIB, never `NWPSource.fetch()`), NAM analysis via a direct auth-free NCEI HTTP GET; both move into the canonical layout + provenance manifest. |
| `scripts/stage_wrf_inputs.py` | thin CLI wrapper. |
| `brc_tools/nwp/wrf_quicklook.py` | cfgrib reopen → crop → `plot_planview` sanity maps; opt-in obs overlay. |
| `tests/test_wrf_staging.py` | 13 mocked tests + 1 opt-in live (`RUN_LIVE_HERBIE=1`). |
| `brc_tools/nwp/lookups.toml` | `[models.gefs_reforecast]` block + S3-confirmed `wps_variable_levels`. |

**Source mapping (decided, evidence-backed):** operational GEFS (Herbie `gefs`) AWS archive starts
**2017** — useless for 2013. The only Herbie-native GEFS-family source for historical dates is
**GEFSv12 Reforecast** (`gefs_reforecast`, 2000–2019, daily 00Z, 5 members c00/p01–p04). It uses a
**per-variable file layout** (one file = one variable across all lead times), pressure fields are
**split at 700 hPa** (`{var}_pres` ≤700 hPa, `{var}_pres_abv700mb` >700 hPa — need **both**),
humidity is **specific** (`spfh_*`, no `rh_pres`/`rh_2m`), 10 m winds are `ugrd_hgt`/`vgrd_hgt`, and
there is **no land-sea mask / no snow depth**. → the gap is filled by an **auth-free NAM 12 km
analysis** (NCEI `namanl_218`, `stage_nam_analysis`) — used either as a standalone single-stream
forcing or as a second ungrib stream (multi-`fg_name` metgrid). **No NCAR RDA / ds083.2 / auth.**

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
python scripts/stage_wrf_inputs.py --case jan2013_basin_gefs \
  --init-time "2013-01-31 00Z" --source nam_analysis --fxx-window 12,48

# GEFS reforecast smoke (2 vars, control member, lead-subset to f12..f48):
python scripts/stage_wrf_inputs.py --case jan2013_basin_gefs \
  --init-time "2013-01-31 00Z" --members 0 --variable-levels tmp_2m,weasd_sfc \
  --fxx-window 12,48 --lead-subset      # --lead-subset = only f12..f48, ~6x smaller
```

---

## 2. What's proven (verification log)

### Validated end-to-end (2026-06-13, NAM-only, Jan-2013 Basin)

The brc-wrf runtime proof closed the loop. Staged from brc-tools `33849121…`
(`feat/wrf-input-staging`) → manifest `…/wrf_inputs/jan2013_basin_gefs/manifest_jan2013_basin_gefs.json`
(`nam_analysis`: 7 files, `gefs_reforecast`: 21 files):

- **WPS:** 14 `met_em` (d01+d02, 6-hourly `2013-01-31_12:00:00` → `2013-02-02_00:00:00`),
  `num_metgrid_levels = 40`, carrying `LANDSEA`, `SOILHGT`, `SKINTEMP`, `SEAICE`, `SNOW`, `SNOWH`,
  4 soil-temperature + 4 soil-moisture layers.
- **`real.exe`:** `d01 2013-02-02_00:00:00 real_em: SUCCESS COMPLETE REAL_EM INIT`, **no missing
  mandatory field** (one non-fatal `forcing artificial silty clay loam at 2 points, out of 18000`).
- **`wrf.exe`:** Slurm step `13472096.0` completed `0:0` on `notch392` (56 tasks);
  `rsl.out.0000` → `d01 2013-02-02_00:00:00 wrf: SUCCESS COMPLETE WRF`; 37 hourly `wrfout`/domain.
- **Archive:** `lawson-group6/jrlawson/wrf_archive/jan2013_basin_gefs/run_20260613T044846Z` (194 files, 2.2 G).

> ⚠️ **Don't read NAM-only WPS truth off this mixed-source manifest.** It lists `nam_analysis`
> (7 files) **and** partial `gefs_reforecast` (21), but WPS consumed **NAM-only**. For what WPS
> actually ingested, trust the contract / source intent (`wps_fg_name`, `sources`) — not the
> manifest file list.

**Interpretation:** NAM-only staging is sufficient for the validated 12/4 km Basin case. The GEFS
reforecast stream stays useful for the optional ensemble/two-stream path, **not** a prerequisite for
making WPS/real/wrf run. **Don't overstate:** known nested domain (not a new standalone 4 km),
NAM-only (no two-stream yet), and the archive wrapper had one post-WRF rsync failure repaired
separately (see §5d).

**DTN IPv6 hang found + fixed:** the first DTN job (`13471949`) wedged in `SYN-SENT` to an NCEI
IPv6 address on :443 (`curl -4` → 200, `curl -6` → timeout); the IPv4-only retry (`13472014`)
finished. Hardened in brc-tools as `--http-ipv4-only` / `BRC_TOOLS_HTTP_IPV4_ONLY=1` (process-global
`socket.getaddrinfo`→AF_INET, covers Herbie/S3 **and** the direct NAM GET) plus split
`(connect=10 s, read=300 s)` timeouts; the DTN job script exports the env var by default.

### Earlier (pre-validation) proofs

- **`pytest tests/` → 92 passed, 2 skipped** (live tests gated by `RUN_LIVE_HERBIE` / `RUN_LIVE_NCEI`). No regressions.
- **NAM analysis staging** (`stage_nam_analysis`) implemented + unit-tested (mocked HTTP: layout, 6-hourly cycle enumeration, isolated-gap skip, all-missing raise, `source="nam_analysis"` manifest). The control-cycle NCEI URL was confirmed live (HTTP 200, `GRIB` magic) and is now proven through the full DTN stage + WPS/`real.exe`/`wrf.exe` run above.
- **Live downloads** on notchpeak1 → scratch, end-to-end (download → move → manifest → quicklook):
  | file | size | lead times |
  |---|---|---|
  | `tmp_2m` | 58 MB | (skip-entry) |
  | `weasd_sfc` | 13 MB | (skip-entry) |
  | `hgt_pres` (≤700 hPa) | **469 MB** | 80 × 3-hourly, f3→f240 |
  | `hgt_pres_abv700mb` (>700 hPa) | **307 MB** | 80 × 3-hourly, f3→f240 |
- The S3-confirmed token list and the **`_abv700mb` split-file path** are proven to download.
- **Lead-time subsetting** (`--lead-subset`) proven: `tmp_2m` **58 MB → 9.7 MB** (only f12–f48, byte-range via Herbie `search=`). Full WPS set drops from ~4 GB to ~650 MB.
- Manifest carries full provenance (`git_sha`, `tool_version`, `herbie_version`, per-file `sha256`,
  `size_bytes`, `remote_url`, empirically-parsed `lead_times`).
- Quicklooks (`figures/jan2013_basin_gefs/`) show the expected physics: `tmp_2m` = the **cold-pool
  inversion**, `weasd_sfc` = the **snowpack**.

**⚠️ Honest scope:** what is on scratch is a **4-variable partial proof, NOT a WPS-runnable set.** A
full single-member WPS set is the 21 `wps_variable_levels` ≈ **~4 GB**, and it downloads f3→f240 when
the case only needs f12→f48 (~84 % wasted) — see Microtask 2 (lead-time subsetting) and §5 (run it on a DTN).

---

## 3. Known gaps / blockers

1. ~~**WPS-field adequacy unverified**~~ **RESOLVED (2026-06-13).** The auth-free NAM 12 km analysis
   (`stage_nam_analysis`, NCEI `namanl_218`) carries the full WRF field set the reforecast lacks
   (land-sea mask, SST, skin temp, `snod`, 4-layer soil). As a **standalone single-stream** forcing
   (`Vtable.NAM`) it produced `met_em` with `LANDSEA`/`SOILHGT`/`SKINTEMP`/soil and drove `real.exe`
   with **no missing mandatory field** (§2). The reforecast's optional **second metgrid stream**
   (two-stream) is the only adequacy question still open.
2. ~~FNL filler stub / NCAR RDA ds083.2~~ **DROPPED.** Herbie's `nam.py` has no NCEI-historical
   source, so NAM-2013 is a direct NCEI HTTP GET (`stage_nam_analysis`) — **no RDA account, no auth**.
   NAM also carries standard 4-layer WRF soil, retiring the reforecast `bgrnd` worry (old Microtask 9).
3. **Full reforecast stage is multi-GB** (~4 GB whole-bucket) → use `--lead-subset` (~650 MB,
   **implemented**) + a DTN (§5). One NAM analysis set for the case window is ~7 files ≈ 0.8 GB.
4. **`obs_sanity_overlay` is wired but untested**; 2013 basin obs are sparse anyway.
5. **Download node tension:** login nodes have internet but shouldn't do heavy I/O; compute/interactive
   nodes may lack internet (proxy). → use a **DTN** (§5).

---

## 4. Microtask backlog

Tags: **[AI]** an agent can do solo · **[H]** needs a human (accounts, judgement, HPC runs) · **[AI+H]**
pair. Rough critical path: **2 → 1 → 23 → 15–19** (subset downloads, stage NAM analysis, stage the
full set on a DTN, then prove through WPS/real on the brc-wrf side).

### A. brc-tools staging (this repo)
- [x] **1. [AI] ✅ DONE** — `stage_nam_analysis()`: auth-free NAM 12 km analysis (NCEI `namanl_218`) staged to `<case>/nam_analysis/` with `source="nam_analysis"` manifest entries. Direct HTTP GET, **no NCAR RDA** (Herbie has no NCEI-historical NAM source). Mocked + opt-in-live (`RUN_LIVE_NCEI`) tests; `--source nam_analysis` CLI.
- [x] **2. [AI] ✅ DONE** — Herbie `search=` lead-time subsetting (`--lead-subset`): only f12–f48 download. Proven `tmp_2m` 58 MB→9.7 MB (6×); full set ~4 GB→~650 MB.
- [x] **3. [AI] ✅ DONE** — `--plan` / `--dry-run` lists every expected NAM cycle + reforecast object (URL, dest path, byte estimate) **offline**, then exits without downloading (`plan_case`).
- [x] **4. [AI] ✅ DONE (offline-tested; live `--preflight` unverified)** — Add a token-preflight: list the S3 prefix for an init and diff against `wps_variable_levels` (catches dataset drift across years 2000–2019).
- [x] **5. [AI] ✅ DONE** — Unit-test `obs_sanity_overlay` with a synthetic polars DataFrame (currently untested).
- [x] **6. [AI] ✅ DONE (label-only; schema v2)** — Have `_record_existing` re-derive `lead_times` from a cached `.idx` if present (avoid degraded skip-manifests), or document the limitation in the manifest itself.
- [ ] **7. [AI]** Multi-member staging proof (c00–p04) + per-member layout/manifest aggregation.
- [x] **8. [AI] ✅ DONE** — `verify_manifest()` / `--verify-manifest <path>`: re-reads the manifest, checks each staged file's existence + size + recomputed `sha256`, exits nonzero on any mismatch.
- [x] **9. [AI] ✅ MOOT** — soil now comes from NAM analysis (standard 4-layer 0-10/10-40/40-100/100-200 cm); the reforecast `bgrnd` mapping question only matters if a reforecast-soil run is attempted later.
- [ ] **10. [AI]** Add an operational `gefs` (post-2017) staging path reusing the same machinery, for recent cases.
- [x] **11. [AI] ✅ DONE** — Record total bytes + elapsed per run into the manifest `provenance` (feeds benchmarking).
- [x] **12. [AI] ✅ DONE (kept warn+partial; test pins it)** — Handle a window that crosses the 240 h bucket boundary (currently warns + stages one bucket only).
- [ ] **13. [AI]** Pin `wps_variable_levels` per data-year if the reforecast token set differs across 2000–2019.

### B. brc-wrf side (WPS/WRF validation — the proof)
- [x] **15. [H] ✅ DONE** — Single-stream NAM via `Vtable.NAM` → ungrib `nam_analysis/` → metgrid `fg_name='NAM'` produced 14 `met_em` (§2). The validated path.
- [ ] **16. [AI+H]** (Two-stream, later) Build a **Vtable** for GEFSv12 reforecast (NCEP GRIB2, `_pres`+`_abv700mb` split, `bgrnd` soil) and run `&metgrid fg_name='GEFS','NAM'` (NAM as filler), if ensemble-reforecast forcing is wanted.
- [ ] **17. [H]** ungrib the staged reforecast dir; confirm intermediate files hold all expected fields.
- [x] **18. [H] ✅ DONE** — NAM `met_em*` confirmed to carry `LANDSEA`, `SOILHGT`, `SKINTEMP`, `SEAICE`, `SNOW`/`SNOWH`, and 4 soil-temp + 4 soil-moisture layers (§2).
- [x] **19. [H] ✅ DONE** — `real.exe` produced `wrfinput_d01`/`wrfbdy_d01` with **no missing mandatory field** (`real_em: SUCCESS COMPLETE REAL_EM INIT`, §2).
- [x] **20. [H] ✅ DONE (this case)** — observed values for the validated run: `interval_seconds = 21600` (6 h NAM cadence — see the contract sidecar), `num_metgrid_levels = 40`. (The two-stream reforecast path would use 10800.)
- [ ] **21. [H]** Confirm geogrid + `geog_data_path` (`/uufs/.../lawson-group6/WPS_GEOG/`) and the 4 km Basin domain in `namelist.wps`.
- [x] **22. [AI+H] ✅ DONE (single-stream)** — `contract_<case>.json` records the forcing provenance brc-tools can know: per-source file counts, cadence, `wps_fg_name`, and `interval_seconds`. The field-level NAM-vs-reforecast split only arises for the two-stream path (still open).

### C. CHPC execution / benchmarking
- [ ] **23. [H]** Run the **full** stage as a `notchpeak-dtn` job (§5 template); confirm the DTN reaches AWS.
- [ ] **24. [H]** Verify whether `lawson-np` compute/interactive nodes can reach AWS (proxy?). Ask helpdesk@chpc.utah.edu; record the answer in brc-knowledge.
- [x] **25. [H] ✅ DONE** — WRF ran on `notch392` (56 tasks, step `13472096.0`) to `SUCCESS COMPLETE WRF`, 37 hourly `wrfout`/domain (§2). Formal scaling/timing sweep (26) still open.
- [ ] **26. [brc-wrf]** Scaling benchmark — **WRF-run tuning, owned by `brc-wrf`** (tracked here only for continuity): sweep `--ntasks` (e.g. 16/28/56), record wall-time per sim-hour, find the knee (Basin domains stop scaling after ~dozens of ranks — wrf-on-chpc §8).
- [ ] **27. [brc-wrf]** Memory benchmark — **WRF-run tuning, owned by `brc-wrf`**: confirm actual peak (~50 GiB for 12/4 km) vs `--mem`; right-size.
- [x] **28. [H] ✅ DONE** — archived to `lawson-group6/jrlawson/wrf_archive/jan2013_basin_gefs/run_20260613T044846Z` (194 files, 2.2 G), incl. the `rsl.out.0000` success marker. See §5d for the colon-filename rsync gotcha hit during this archive.

### D. Cross-cutting / hygiene
- [x] **30. [H] ✅ GATE MET** — a successful `real.exe` (and full `wrf.exe`) is on record (§2), so `feat/wrf-input-staging` → `main` is unblocked. The merge itself is the only remaining action (branch not yet pushed).
- [x] **31. [AI] ✅ DONE** — Add a `WISHLIST-TASKS.md` entry pointing here.
- [ ] **32. [AI+H]** Ensure brc-wrf docs reference this file + the scratch layout (cross-repo sync).
- [ ] **33. [H]** Retention: scratch auto-purges at 60 days — promote proven inputs to `lawson-group6` if reused.

---

## 5. Running on CHPC (where each step belongs)

### 5a. Downloading/staging GRIB — use a **DTN**, not a login or compute node

CHPC reality (from `chpc-slurm-job-examples.md` and the inventory):
- **Login nodes** (`notchpeak1`): direct internet, but **shared** — fine for a 1–2 file smoke; **not** for multi-GB. (`git`, `ls`, short Python, Claude CLI, light conda are the sanctioned uses.)
- **Compute / interactive (`salloc`) nodes** on `lawson-np`: **internet is NOT guaranteed** — "compute nodes may require an http(s) proxy… treat outbound network as *verify first*, not assumed." So an interactive node is **not** a safe place to download from AWS.
- **DTN — `notchpeak-dtn`**: dedicated high-bandwidth node **with internet**, purpose-built for large transfers. **Run the full stage here.**

**DTN staging job:** committed at **`scripts/stage_inputs.dtn.slurm`** — submit with:
```bash
sbatch scripts/stage_inputs.dtn.slurm   # control member, --lead-subset (f12–f48, ~650 MB)
```
It pins `account=dtn / partition=notchpeak-dtn / qos=notchpeak-dtn`, calls the env's python directly
(login env doesn't carry into batch jobs), stages with `--lead-subset`, and writes to
`/scratch/general/vast/$USER/wrf_inputs/jan2013_basin_gefs/`. Quicklook is off on the DTN (no
matplotlib/cartopy) — render figures separately on a login node from the staged files if wanted.

### 5b. Running WRF — owned by `brc-wrf`

brc-tools does **not** own WRF-run Slurm profiles. For the run script, the
node/task/memory profile, the launcher, and any benchmarking sweep, see `brc-wrf`
+ `brc-knowledge` (paths from repo root; both repos checked out as siblings):
`../brc-wrf/brc-docs/BRC-WRF-FIRST-CASE.md` and the validated `run_wrf_feb05.slurm`
it references.

(The DTN **staging** job in §5a is a different thing — that one *is* brc-tools',
because staging GRIB is our lane; running the model is not.)

### 5c. Storage & retention
`/scratch/general/vast/$USER` (50 TiB quota, **60-day atime purge**) for active inputs/runs; promote
durable inputs/outputs to `lawson-group6` (33 TiB, no purge, most reliable compute-node mount).

- **Scratch is not durable.** The 60-day atime purge *will* delete a staged input set you stop
  touching. Treat `wrf_inputs/<case>/` as reproducible-on-demand (re-run the DTN stage), or promote a
  set you intend to reuse to `lawson-group6` and `verify_manifest` it after the copy.
- **One durable tier today.** `lawson-group6` is the durable home for inputs + `wrf_archive/`. There
  is **no** second backup tier — don't claim one in docs/automation unless CHPC/BRC policy confirms
  it (e.g. a tape/offsite copy). Observed headroom at proof time: `/scratch/general/vast` ~62 %,
  `lawson-group6` ~51 % of 33 TiB — adequate for early ops, not a license to hoard runs.

### 5d. Run / archive hygiene (mostly brc-wrf, documented here for the full picture)
The WRF run + archive live in **brc-wrf**; brc-tools owns staging + manifest. Cross-cutting gotchas
the validated proof surfaced:

- **Archive layout:** one run = one timestamped dir,
  `lawson-group6/<namespace>/wrf_archive/<case>/run_<YYYYMMDDTHHMMSSZ>/` (the proof:
  `…/jrlawson/wrf_archive/jan2013_basin_gefs/run_20260613T044846Z`, 194 files, 2.2 G). At minimum
  preserve `wrfout*`, the `namelist.*`, and an `rsl.out.0000` success marker.
- **WRF filenames break naïve `rsync`.** `wrfout` names contain colons
  (`wrfout_d01_2013-02-01_12:00:00`); a bare `rsync wrfout_d0* host:dst` parses the colon as a
  remote host and fails (`All source args must come from the same machine`). **Prefix local sources**:
  `rsync ./wrfout_d0* host:dst` (or pass absolute paths). This bit the proof's archive step.
- **Slurm state ≠ WRF success.** Batch-job state, the `.0` step state, the WRF `SUCCESS COMPLETE WRF`
  marker, and the archive state are **separate facts**. The proof's batch job showed `FAILED` only
  because the *post-WRF rsync* failed — WRF itself completed `0:0` and wrote the success marker. Read
  `rsl.out.0000` + the `wrfout*` set, not just `sacct` state.
- **Don't probe a full allocation with `srun --jobid`.** An `srun --jobid=<run> … ps` into a fully
  occupied 56-task WRF allocation can't create a step and hangs until killed. Use `squeue`, logs, and
  filesystem evidence instead.

---

## 6. Login-node load review (what was run here, and the rule of thumb)

Everything in §2 was run on **notchpeak1 (login node)**. Honest audit:

| action | load | verdict on a login node |
|---|---|---|
| S3 prefix listing (curl) | ~34 KB | ✅ trivial |
| `pytest tests/` | ~5 s CPU, no net | ✅ fine |
| quicklook (cfgrib decode 60 MB + matplotlib) | seconds, ~hundreds MB RAM | ✅ light |
| surface downloads (`tmp_2m`+`weasd_sfc`) | ~73 MB + sha256 | ✅ acceptable smoke |
| **pressure pair (`hgt_pres`+`abv700mb`)** | **776 MB download + sha256 of ~850 MB** | ⚠️ **borderline — the heaviest thing; past "trivia."** |

**Takeaways to stay out of IT trouble:**
- A **1–2 file smoke (≤~100 MB)** on a login node is fine. The **776 MB pressure pair was the limit** of what's polite there; the **full ~4 GB stage must NOT run on a login node.**
- Your instinct about interactive nodes is right to be cautious — but the subtlety is the **opposite of a risk you'd expect**: interactive/compute nodes may have **no internet**, so they can't download at all without a proxy. The correct tool for the heavy download is the **DTN** (§5a), which is both internet-connected and sanctioned for big transfers.
- Rule of thumb: **download/transfer → DTN; model run → notch392; light prep/inspection/Claude → login node.** When unsure of a node's external connectivity, `verify first` (the inventory's words), or ask helpdesk@chpc.utah.edu.

---

## 7. Definition of done ("proof it works")

1. ✅ NAM analysis set staged (`<case>/nam_analysis/`), manifest integrity-checked
   (`verify_manifest`). *(Optional: full reforecast set on a DTN for the two-stream path.)*
2. ✅ brc-wrf: ungrib (`Vtable.NAM`) → metgrid (`fg_name='NAM'`) → `met_em*` with `LANDSEA` + soil +
   skin temp. *(Two-stream `fg_name='GEFS','NAM'` only if reforecast forcing is pursued — still open.)*
3. ✅ `real.exe` produces `wrfinput_d01` + `wrfbdy_d01` with **no missing mandatory field**.
4. ✅ `wrf.exe` reaches **SUCCESS COMPLETE WRF**; `wrfout*` archived to `lawson-group6`.
5. ✅ Merged to `main` — NAM-only via PR #22; staging-hygiene batch via PR #23 (`52908df`, 2026-06-16).

---

## 8. Case contract (brc-tools → brc-wrf)

`stage_case` writes `contract_<case>.json` next to the manifest: the WPS/WRF-relevant facts
brc-tools can authoritatively derive from what it staged, so brc-wrf doesn't reverse-engineer them.
**It emits only staging-derived facts** — `num_metgrid_levels` and the `met_em` field list are
metgrid *outputs* and live below as documented proof constants, not in the sidecar.

Sidecar fields (`build_contract`): `case`, `region`, `valid_window`, `sources`,
`source_file_counts`, `cadence_hours` (per source), `interval_hours` / `interval_seconds`
(**derived from the forcing source's cadence** — NAM-only → 6 h / 21600 s; reforecast → 3 h /
10800 s), `wps_fg_name` (`['NAM']` single-stream; `['GEFS','NAM']` two-stream), `scratch_layout`,
and the manifest filename.

> **Note on the on-scratch proof artifact:** the validated run's
> `manifest_jan2013_basin_gefs.json` was written **before** the interval fix and still records
> `interval_hours=3`. The run itself used the correct 6 h NAM cadence (`interval_seconds=21600`,
> per WPS); a fresh stage now stamps `interval_hours=6`. Diffing the old manifest against a new one
> will show this single expected discrepancy.
>
> **Vocabulary reconcile (brc-tools ↔ brc-wrf):** what this repo calls a "pre-contract manifest"
> (above) is the same artifact `brc-wrf` calls a *reconstructed legacy NAM-only contract*
> (`../brc-wrf/brc-cases/jan2013_basin_nam.contract.json`). The old scratch predates the
> `contract_<case>.json` sidecar, so `brc-wrf` carries a reconstructed NAM-only contract for strict
> validation, while a fresh brc-tools stage emits the real sidecar.

**Proof constants for the validated Jan-2013 Basin run (metgrid/real outputs — not auto-emitted):**

| field | value |
|---|---|
| `interval_seconds` | `21600` (6 h NAM cadence) |
| `num_metgrid_levels` | `40` |
| `met_em` fields | `LANDSEA`, `SOILHGT`, `SKINTEMP`, `SEAICE`, `SNOW`, `SNOWH`, 4 soil-temp + 4 soil-moisture layers |
| `met_em` count | 14 (d01+d02, 6-hourly `2013-01-31_12:00:00`→`2013-02-02_00:00:00`) |
| `wps_fg_name` | `NAM` |
