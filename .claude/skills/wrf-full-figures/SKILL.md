---
name: wrf-full-figures
description: Generate publication "full-figures" (300-DPI versions of the WRF quicklooks) for a Uinta Basin WRF case on CHPC SLURM, choosing a specific case/run. Use when asked to make full-figures / publication figures for a WRF run.
---

# WRF full-figures on SLURM

Drives `scripts/pelican_figures.py` (brc-tools) to render terrain-following cross-sections,
multi-domain surface panels, GFS/NAM & feedback differences, theta(z)/skew-T profiles, crest
upper-air, a domains map, and the cold-pool heat-deficit series -> `<run>/full-figures/` on
lawson-group6. Reference: `docs/WRF-ANALYSIS-FIGURES.md`.

## Steps
1. **Pick case + run** (ask the user):
   - Known pelican2013 cases -> `--case gfs|nam|nam_oneway|all`.
   - Specific run -> `--run <run_YYYYMMDDT...Z>` (default: latest); list with
     `ls $BRC_WRF_ARCHIVE/<case_dir>/full6h/`.
   - **New case:** add one line to `CASES` in `scripts/pelican_figures.py`
     (`"<key>": ("<case_dir>", "<label>")`), then `--case <key>`. Cross-case families
     (difference, heatdeficit, profile) need the gfs+nam+oneway trio; a lone run gets the
     per-run families (section, surface, upperair, skewt, domains).
2. **Soundings (optional skew-T obs):** on a login/DTN node run
   `python scripts/fetch_soundings.py --time "<YYYY-MM-DD HH>" --out <scratch>/snd.parquet`,
   then add `--sounding-cache <scratch>/snd.parquet`.
3. **Submit on SLURM (never a login node):**
   `sbatch scripts/pelican_figures.slurm --case <..> --run <..> [--figure <..>] [--time <..>]`
   (args after the script forward to the driver). Verify with `squeue -j <jobid>`.
4. **Verify output:** on finish, check `<run>/full-figures/` and `pelican_figures_<jobid>.out`;
   spot-check a couple of PNGs.

## Notes
- The slurm wrapper sets the `brc-tools-2026` python, `PYTHONPATH=~/gits/brc-tools`, and
  `MPLCONFIGDIR` on scratch; figures route out of the repo by default.
- Redirect output with `--output-dir <path>` (nests `<case>/<family>/`).
- Families: `domains, section, upperair, surface, difference, profile, skewt, heatdeficit, all`.
