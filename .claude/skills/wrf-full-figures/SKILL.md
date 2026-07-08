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
2. **Soundings (optional skew-T obs):** on a login/DTN node run
   `python scripts/fetch_soundings.py --time "<YYYY-MM-DD HH>" --out <scratch>/snd.parquet`,
   then add `--sounding-cache <scratch>/snd.parquet`.
3. **Submit on SLURM (never a login node):** the study repo owns the wrapper --
   `cd ~/gits/wrf-nudge-ozone-air2026 && sbatch slurm/pelican_figures.slurm --case <..> --run <..> [--figure <..>] [--time <..>]`
   (args after the script forward to the driver). Verify with `squeue -j <jobid>`.
4. **Verify output:** on finish, check `<run>/full-figures/` and `pelican_figures_<jobid>.out`;
   spot-check a couple of PNGs. The engine also prints a preflight report -- read it for named
   `[SKIP]`/`[WARN]` lines (missing variable, focus point off-grid).

## Notes
- The slurm wrapper sets the `brc-tools-2026` python, `PYTHONPATH=~/gits/brc-tools`, and
  `MPLCONFIGDIR` on scratch; figures route out of every repo by default.
- Redirect output with `--output-dir <path>` (nests `<case>/<family>/`).
- Families: `domains, section, upperair, surface, difference, profile, skewt, heatdeficit, all`.
