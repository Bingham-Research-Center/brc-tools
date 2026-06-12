# WRF-Input GRIB Staging — Handoff

**Status:** first proof complete; **NOT yet validated through WRF/WPS.** Work lives on branch
`feat/wrf-input-staging` (do not merge to `main` until `real.exe` succeeds — see Microtask 30).

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
| `brc_tools/nwp/wrf_staging.py` | `stage_reforecast` / `stage_case` / `build_manifest`; downloads with `Herbie.download()` to **retain** raw GRIB (never `NWPSource.fetch()`, which deletes it), moves into the canonical layout, writes a provenance manifest. |
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
there is **no land-sea mask / no snow depth**. → the land-mask gap is closed by **fusing a GFS/FNL
analysis** as a second ungrib stream (multi-`fg_name` metgrid).

**Output layout:**
```
/scratch/general/vast/$USER/wrf_inputs/jan2013_basin_gefs/
  gefs_reforecast/c00/<variable_level>_2013013100_c00.grib2   # primary forcing
  gfs_fnl/                                                     # filler (TODO — stub)
  manifest_jan2013_basin_gefs.json
```

**Quick start (small smoke; see §5 for where to run big stages):**
```bash
python scripts/stage_wrf_inputs.py --case jan2013_basin_gefs \
  --init-time "2013-01-31 00Z" --members 0 --variable-levels tmp_2m,weasd_sfc --fxx-window 12,48
```

---

## 2. What's proven (verification log)

- **`pytest tests/` → 74 passed, 1 skipped** (live test gated by `RUN_LIVE_HERBIE`). No regressions.
- **Live downloads** on notchpeak1 → scratch, end-to-end (download → move → manifest → quicklook):
  | file | size | lead times |
  |---|---|---|
  | `tmp_2m` | 58 MB | (skip-entry) |
  | `weasd_sfc` | 13 MB | (skip-entry) |
  | `hgt_pres` (≤700 hPa) | **469 MB** | 80 × 3-hourly, f3→f240 |
  | `hgt_pres_abv700mb` (>700 hPa) | **307 MB** | 80 × 3-hourly, f3→f240 |
- The S3-confirmed token list and the **`_abv700mb` split-file path** are proven to download.
- Manifest carries full provenance (`git_sha`, `tool_version`, `herbie_version`, per-file `sha256`,
  `size_bytes`, `remote_url`, empirically-parsed `lead_times`).
- Quicklooks (`figures/jan2013_basin_gefs/`) show the expected physics: `tmp_2m` = the **cold-pool
  inversion**, `weasd_sfc` = the **snowpack**.

**⚠️ Honest scope:** what is on scratch is a **4-variable partial proof, NOT a WPS-runnable set.** A
full single-member WPS set is the 21 `wps_variable_levels` ≈ **~4 GB**, and it downloads f3→f240 when
the case only needs f12→f48 (~84 % wasted) — see Microtask 2 (lead-time subsetting) and §5 (run it on a DTN).

---

## 3. Known gaps / blockers

1. **WPS-field adequacy unverified (the real blocker).** Reforecast lacks a land-sea mask; soil is
   `bgrnd`-layer; no `snod`. A reforecast-only metgrid will miss `LANDSEA` etc. and `real.exe` will
   abort. Fix = **two-stream ungrib + GFS/FNL fusion** (lives in brc-wrf).
2. **FNL filler is a stub.** `stage_fnl_filler()` raises `NotImplementedError`; 2013 FNL = **NCAR RDA
   ds083.2** (RDA auth, not Herbie).
3. **Full stage is multi-GB and lead-time-wasteful** → needs Herbie `search=` subsetting + a DTN.
4. **`obs_sanity_overlay` is wired but untested**; 2013 basin obs are sparse anyway.
5. **Download node tension:** login nodes have internet but shouldn't do heavy I/O; compute/interactive
   nodes may lack internet (proxy). → use a **DTN** (§5).

---

## 4. Microtask backlog

Tags: **[AI]** an agent can do solo · **[H]** needs a human (accounts, judgement, HPC runs) · **[AI+H]**
pair. Rough critical path: **2 → 23 → 1 → 15–19** (subset downloads, stage full set on DTN, build FNL
filler, then prove through WPS/real on the brc-wrf side).

### A. brc-tools staging (this repo)
- [ ] **1. [AI+H]** Implement `stage_fnl_filler()` — GFS/FNL from NCAR RDA ds083.2 (RDA token/globus/wget), stage to `<case>/gfs_fnl/`, append `source="gfs_fnl"` manifest entries. *(H: needs an RDA account.)*
- [ ] **2. [AI]** Add Herbie `search=` lead-time subsetting (`--lead-subset`) so only f12–f48 download, not f3–f240. Cuts the full set from ~4 GB to <1 GB. **Highest-leverage.**
- [ ] **3. [AI]** Add `--dry-run` / `--plan` that lists every S3 object + total bytes before downloading (so users gauge load before committing a DTN job).
- [ ] **4. [AI]** Add a token-preflight: list the S3 prefix for an init and diff against `wps_variable_levels` (catches dataset drift across years 2000–2019).
- [ ] **5. [AI]** Unit-test `obs_sanity_overlay` with a synthetic polars DataFrame (currently untested).
- [ ] **6. [AI]** Have `_record_existing` re-derive `lead_times` from a cached `.idx` if present (avoid degraded skip-manifests), or document the limitation in the manifest itself.
- [ ] **7. [AI]** Multi-member staging proof (c00–p04) + per-member layout/manifest aggregation.
- [ ] **8. [AI]** Manifest integrity util: re-read manifest, re-hash each staged file, assert `sha256` match before WPS consumes them.
- [ ] **9. [AI+H]** Confirm `tsoil_bgrnd`/`soilw_bgrnd` (4 GRIB soil layers) map cleanly to WRF soil; if not, plan FNL-soil fallback.
- [ ] **10. [AI]** Add an operational `gefs` (post-2017) staging path reusing the same machinery, for recent cases.
- [ ] **11. [AI]** Record total bytes + elapsed per run into the manifest `provenance` (feeds benchmarking).
- [ ] **12. [AI]** Handle a window that crosses the 240 h bucket boundary (currently warns + stages one bucket only).
- [ ] **13. [AI]** Pin `wps_variable_levels` per data-year if the reforecast token set differs across 2000–2019.

### B. brc-wrf side (WPS/WRF validation — the proof)
- [ ] **15. [AI+H]** Build/confirm a **Vtable** for GEFSv12 reforecast (NCEP GRIB2 → WPS), covering the `_pres`+`_abv700mb` split and `bgrnd` soil.
- [ ] **16. [H]** `namelist.wps`: two ungrib streams (GEFS Vtable, FNL `Vtable.GFS`), `&metgrid fg_name='GEFS','FNL'`.
- [ ] **17. [H]** ungrib the staged reforecast dir; confirm intermediate files hold all expected fields.
- [ ] **18. [H]** ungrib FNL; metgrid both; confirm `met_em*` has `LANDSEA`, `SOILHGT`, `SKINTEMP`/`SST`, 4 soil layers.
- [ ] **19. [H]** `real.exe` dry-run (1 dom ~4 km); confirm `wrfinput_d01` + `wrfbdy_d01`, **no "missing mandatory field."** If `bgrnd` soil won't map, take soil entirely from FNL.
- [ ] **20. [H]** Set `interval_seconds` to the staged cadence (3 h = 10800) and `num_metgrid_levels` / `num_metgrid_soil_levels` to match the actual files.
- [ ] **21. [H]** Confirm geogrid + `geog_data_path` (`/uufs/.../lawson-group6/WPS_GEOG/`) and the 4 km Basin domain in `namelist.wps`.
- [ ] **22. [AI+H]** Document which IC/LBC fields came from reforecast vs FNL (forcing provenance).

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

**DTN staging job** (`stage_inputs.dtn.slurm`):
```bash
#!/bin/bash
#SBATCH --job-name=stage_wrf_inputs
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=1-00:00:00
#SBATCH --output=stage_%j.out
set -euo pipefail
cd ~/gits/brc-tools
PY=~/software/pkg/miniforge3/envs/clyfar-nov2025/bin/python   # env with herbie 2025.11.3
# Stage on the SAME filesystem as Herbie's cache so the move is a rename, not a copy:
"$PY" scripts/stage_wrf_inputs.py \
  --case jan2013_basin_gefs --init-time "2013-01-31 00Z" --members 0 \
  --fxx-window 12,48 --no-quicklook \
  --herbie-save-dir /scratch/general/vast/$USER/wrf_inputs/.herbie_cache
# (after Microtask 2 lands, add --lead-subset to avoid downloading f3..f240)
```
> Quicklook needs matplotlib/cartopy; keep `--no-quicklook` on the DTN and render figures separately
> on a login node from the already-staged files if you want them.

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

1. Full single-member WPS set staged (DTN), manifest integrity-checked.
2. FNL filler staged into `<case>/gfs_fnl/`.
3. brc-wrf: ungrib×2 → metgrid → `met_em*` with `LANDSEA` + soil + skin temp.
4. `real.exe` produces `wrfinput_d01` + `wrfbdy_d01` with **no missing mandatory field**.
5. `wrf.exe` reaches **SUCCESS COMPLETE WRF**; `wrfout*` archived to `lawson-group6`.
6. Only **then** merge `feat/wrf-input-staging` → `main`.
