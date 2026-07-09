---
name: wrf-full-figures
description: Generate publication "full-figures" (300-DPI versions of the WRF quicklooks) for a Uinta Basin WRF case on CHPC SLURM, choosing a specific case/run. Use when asked to make full-figures / publication figures for a WRF run.
---

# WRF full-figures on SLURM

Drives the dataset-agnostic engine `scripts/wrf_figures.py --config <case.toml>` (brc-tools)
to render terrain-following cross-sections, multi-domain surface panels, GFS/NAM & feedback
differences, theta(z)/skew-T profiles, crest upper-air, a domains map, and the cold-pool
heat-deficit series -> `<run>/full-figures/` on lawson-group6. Engine + TOML schema:
`docs/WRF-FIGURE-ENGINE.md`. The pelican2013 study's case config lives in the experiment
repo (`../wrf-nudge-ozone-air2026/cases/pelican2013.toml`), not in brc-tools.

## Steps
1. **Pick case config + run** (ask the user):
   - Default study: `--config ~/gits/wrf-nudge-ozone-air2026/cases/pelican2013.toml`.
   - Case keys within that config -> `--case gfs|nam|nam_oneway|nam_terrain5m|nam_terrain3s|all`.
   - Specific run dir -> `--run <run_YYYYMMDDT...Z>` (default: latest); list with
     `ls $BRC_WRF_ARCHIVE/<case_dir>/full6h/`.
   - **New case/run:** add a `[runs.<key>]` block (and optionally `[[differences]]`) to the
     case TOML -- no code change. Cross-case families (difference, heatdeficit, profile) need
     both cases of a pair present; a lone run gets the per-run families (section, surface,
     upperair, skewt, domains).
2. **Target a forecast lead time (optional):** `--lead N` renders the **N-hour
   forecast** instead of every output time. Init is the run's start (the first
   wrfout / its `SIMULATION_START_DATE`), so `--lead 1` = init + 1 h (e.g. a 12Z
   init → the 13Z valid time). Whole hours only; comma lists ok (`--lead 0,1,6`).
   - `--lead` **overrides** `--time` (which is instead a valid *hour-of-day* filter).
   - The engine works out which leads exist from the wrfout files on disk: a lead
     WRF hasn't reached yet is **named-skipped** (`[SKIP] … lead 6h → …Z not
     available yet`), never a crash — so asking for `--lead 6` before hour 6 is
     written is safe. The preflight report lists the available valid times (or
     `ls $BRC_WRF_ARCHIVE/<case_dir>/full6h/run_*/`).
   - Applies to section/upperair/surface, the focus skew-T, difference maps/sections,
     and (when set) the θ(z) profile. Station RAOB skew-Ts stay at the analysis hour
     and the heat-deficit series always spans all times.
3. **Incremental re-runs (optional):** add `--skip-existing` so a re-submit renders
   only new/missing leads and skips any figure already newer than its source wrfout
   (a wrfout rewritten by a later run regenerates its figure). Pair with `--lead`
   to advance a run as it writes output — e.g. re-submit (or wrap the sbatch in
   `/loop`) and each pass picks up the next available lead hour.
4. **Soundings (optional skew-T obs):** on a login/DTN node run
   `python scripts/fetch_soundings.py --time "<YYYY-MM-DD HH>" --out <scratch>/snd.parquet`,
   then add `--sounding-cache <scratch>/snd.parquet`.
5. **Submit on SLURM (never a login node):** the study repo owns the wrapper --
   `cd ~/gits/wrf-nudge-ozone-air2026 && sbatch slurm/pelican_figures.slurm --case <..> --run <..> [--figure <..>] [--lead <..>] [--skip-existing]`
   (args after the script forward to the driver; `--lead` overrides the wrapper's
   default `--time all`). Example — the 1-hour surface panels for every case, latest
   run: `sbatch slurm/pelican_figures.slurm --figure surface --lead 1`. Verify with
   `squeue -j <jobid>`.
6. **Verify output:** on finish, check `<run>/full-figures/` and `pelican_figures_<jobid>.out`;
   spot-check a couple of PNGs. The engine also prints a preflight report -- read it for named
   `[SKIP]`/`[WARN]` lines (missing variable, focus point off-grid, unavailable lead).

## Notes
- The slurm wrapper sets the `brc-tools-2026` python, `PYTHONPATH=~/gits/brc-tools`, and
  `MPLCONFIGDIR` on scratch; figures route out of every repo by default.
- Redirect output with `--output-dir <path>` (nests `<case>/<family>/`).
- Families: `domains, section, upperair, surface, difference, profile, skewt, heatdeficit, all`.
- Figure filenames encode the **valid hour** only (`…_13z.png`), so `--skip-existing`
  is safe for hourly (or coarser) output; a sub-hourly run would collide within an hour
  (see `docs/WRF-FIGURE-ENGINE.md`).
