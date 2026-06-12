# WRF-Input GRIB Staging — Handoff

**Status:** first proof complete; **NOT yet validated through WRF/WPS.** Work lives on branch
`feat/wrf-input-staging` (do not merge to `main` until `real.exe` succeeds — see Microtask 30).

**Branch reconciled with `origin/main`.** A merge commit on `feat/wrf-input-staging` folds in
upstream's slimmed `CLAUDE.md`, the `brc_tools/api/` package, and the `in_progress/` cleanup; the
WRF files and `lookups.toml` did not collide. The in-flight `WISHLIST-TASKS.md` /
`docs/CHPC-REFERENCE.md` edits are committed. (Not pushed — awaiting review.)

**Goal of this track:** produce, from NWP data, the GRIB inputs WRF/WPS actually want for a Uinta
Basin case (test case: **2013-01-31 12Z → 2013-02-02 00Z**, one domain, ~4 km), stage them to
scratch with provenance, and *prove* WRF ingests them. brc-tools owns the **download + staging +
manifest**; the sibling **brc-wrf** repo owns **ungrib → metgrid → real** and the WRF run.

> **Canonical CHPC references (read these for any run decision):**
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md` — **single source of truth** for nodes, partitions, storage, DTN, login-node etiquette.
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/wrf-on-chpc-quickstart.md` — WRF build/run, module stack, scaling table (§8).
> - `~/gits/brc-knowledge/scholarium/reference-base/resources/run_wrf_feb05.slurm` — **validated** WRF run script for the Feb-2013 Basin case (notch392, 56 tasks). Reuse it; don't reinvent.
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

- **`pytest tests/` → 82 passed, 2 skipped** (live tests gated by `RUN_LIVE_HERBIE` / `RUN_LIVE_NCEI`). No regressions.
- **NAM analysis staging** (`stage_nam_analysis`) implemented + unit-tested (mocked HTTP: layout, 6-hourly cycle enumeration, isolated-gap skip, all-missing raise, `source="nam_analysis"` manifest). The control-cycle NCEI URL is **confirmed live** (HTTP 200, `GRIB` magic). Remaining proofs: the full live download (`RUN_LIVE_NCEI`) and the end-to-end WPS/`real.exe` run (brc-wrf side).
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

1. **WPS-field adequacy still unverified, but no longer RDA-gated.** Reforecast lacks a land-sea
   mask, SST, skin temp, and `snod`, and its soil is `bgrnd`-layer — so a reforecast-only metgrid
   would miss `LANDSEA` etc. and `real.exe` would abort. **Fix (implemented, brc-tools side):** an
   **auth-free NAM 12 km analysis** (`stage_nam_analysis`, NCEI `namanl_218`) carrying the full WRF
   field set. NAM is either the **standalone forcing** (single-stream, `Vtable.NAM` — the validated
   Feb-2013 recipe) or the reforecast's **second metgrid stream**. Final adequacy check = `real.exe`
   (brc-wrf side).
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
- [ ] **3. [AI]** Add `--dry-run` / `--plan` that lists every S3 object + total bytes before downloading (so users gauge load before committing a DTN job).
- [ ] **4. [AI]** Add a token-preflight: list the S3 prefix for an init and diff against `wps_variable_levels` (catches dataset drift across years 2000–2019).
- [ ] **5. [AI]** Unit-test `obs_sanity_overlay` with a synthetic polars DataFrame (currently untested).
- [ ] **6. [AI]** Have `_record_existing` re-derive `lead_times` from a cached `.idx` if present (avoid degraded skip-manifests), or document the limitation in the manifest itself.
- [ ] **7. [AI]** Multi-member staging proof (c00–p04) + per-member layout/manifest aggregation.
- [ ] **8. [AI]** Manifest integrity util: re-read manifest, re-hash each staged file, assert `sha256` match before WPS consumes them.
- [x] **9. [AI] ✅ MOOT** — soil now comes from NAM analysis (standard 4-layer 0-10/10-40/40-100/100-200 cm); the reforecast `bgrnd` mapping question only matters if a reforecast-soil run is attempted later.
- [ ] **10. [AI]** Add an operational `gefs` (post-2017) staging path reusing the same machinery, for recent cases.
- [ ] **11. [AI]** Record total bytes + elapsed per run into the manifest `provenance` (feeds benchmarking).
- [ ] **12. [AI]** Handle a window that crosses the 240 h bucket boundary (currently warns + stages one bucket only).
- [ ] **13. [AI]** Pin `wps_variable_levels` per data-year if the reforecast token set differs across 2000–2019.

### B. brc-wrf side (WPS/WRF validation — the proof)
- [ ] **15. [H]** Single-stream NAM first: symlink `Vtable.NAM`, ungrib the staged `nam_analysis/` dir, metgrid `fg_name='NAM'` — the validated Feb-2013 recipe. Fastest path to a `real.exe` run.
- [ ] **16. [AI+H]** (Two-stream, later) Build a **Vtable** for GEFSv12 reforecast (NCEP GRIB2, `_pres`+`_abv700mb` split, `bgrnd` soil) and run `&metgrid fg_name='GEFS','NAM'` (NAM as filler), if ensemble-reforecast forcing is wanted.
- [ ] **17. [H]** ungrib the staged reforecast dir; confirm intermediate files hold all expected fields.
- [ ] **18. [H]** ungrib NAM (`Vtable.NAM`); metgrid; confirm `met_em*` has `LANDSEA`, `SOILHGT`, `SKINTEMP`/`SST`, 4 soil layers.
- [ ] **19. [H]** `real.exe` dry-run (1 dom ~4 km); confirm `wrfinput_d01` + `wrfbdy_d01`, **no "missing mandatory field."** NAM supplies all mandatory surface/soil fields directly.
- [ ] **20. [H]** Set `interval_seconds` to the staged cadence (3 h = 10800) and `num_metgrid_levels` / `num_metgrid_soil_levels` to match the actual files.
- [ ] **21. [H]** Confirm geogrid + `geog_data_path` (`/uufs/.../lawson-group6/WPS_GEOG/`) and the 4 km Basin domain in `namelist.wps`.
- [ ] **22. [AI+H]** Document which IC/LBC fields came from NAM vs (optional) reforecast (forcing provenance).

### C. CHPC execution / benchmarking
- [ ] **23. [H]** Run the **full** stage as a `notchpeak-dtn` job (§5 template); confirm the DTN reaches AWS.
- [ ] **24. [H]** Verify whether `lawson-np` compute/interactive nodes can reach AWS (proxy?). Ask helpdesk@chpc.utah.edu; record the answer in brc-knowledge.
- [ ] **25. [H]** Run WRF via `run_wrf_feb05.slurm` (notch392, 56 tasks); capture timing.
- [ ] **26. [AI+H]** Scaling benchmark: sweep `--ntasks` (e.g. 16/28/56), record wall-time per sim-hour, find the knee (Basin domains stop scaling after ~dozens of ranks — wrf-on-chpc §8).
- [ ] **27. [H]** Memory benchmark: confirm actual peak (~50 GiB for 12/4 km) vs `--mem`; right-size.
- [ ] **28. [H]** Archive `wrfout*` + namelists to `lawson-group6` (the slurm script already does this).

### D. Cross-cutting / hygiene
- [ ] **30. [H]** Keep work on `feat/wrf-input-staging`; merge to `main` **only after** a successful `real.exe`.
- [ ] **31. [AI]** Add a `WISHLIST-TASKS.md` entry pointing here.
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

### 5b. Running WRF — use **notch392** via the validated script

Do **not** reinvent the run script. Submit the validated one:
```bash
sbatch ~/gits/brc-knowledge/scholarium/reference-base/resources/run_wrf_feb05.slurm
```
It pins `notch392` (56 cores, ~1 TB RAM, ConnectX-6), `lawson-np`, `--mem=180G`, `--time=6:00:00`,
the validated module stack, and the **mandatory** launcher `srun --mpi=pmi2 -n "$SLURM_NTASKS" ./wrf.exe`
(bare `mpirun`/`srun -n` are wrong on Intel MPI 2021.1.1). It also archives `wrfout*` to `lawson-group6`.

**Benchmarking sweep** (to "maximise resources"): copy that script per config and vary:
- `--ntasks` ∈ {16, 28, 56} (keep `--nodes=1`; record wall-time per simulated hour → find the scaling knee).
- `--mem`: start `180G`; use `--mem=900G` to reserve the whole big-memory node (owned, sole-user → harmless).
- Keep `--nodelist=notch392` for apples-to-apples; the scaling table is in `wrf-on-chpc-quickstart.md` §8.

### 5c. Storage
`/scratch/general/vast/$USER` (50 TiB quota, **60-day atime purge**) for active inputs/runs; promote
durable inputs/outputs to `lawson-group6` (33 TiB, no purge, most reliable compute-node mount).

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

1. NAM analysis set staged (`<case>/nam_analysis/`), manifest integrity-checked. *(Optional: full
   reforecast set on a DTN for the two-stream path.)*
2. brc-wrf: ungrib (`Vtable.NAM`) → metgrid (`fg_name='NAM'`) → `met_em*` with `LANDSEA` + soil +
   skin temp. *(Two-stream `fg_name='GEFS','NAM'` only if reforecast forcing is pursued.)*
3. `real.exe` produces `wrfinput_d01` + `wrfbdy_d01` with **no missing mandatory field**.
4. `wrf.exe` reaches **SUCCESS COMPLETE WRF**; `wrfout*` archived to `lawson-group6`.
5. Only **then** merge `feat/wrf-input-staging` → `main`.
