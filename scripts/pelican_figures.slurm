#!/bin/bash
#SBATCH --job-name=pelican_figures
#SBATCH --account=lawson-np
#SBATCH --partition=lawson-np
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=96G
#SBATCH --time=0-02:00:00
#SBATCH --output=pelican_figures_%j.out
#SBATCH --error=pelican_figures_%j.err

# Publication figures for the pelican2013 WRF cold-pool cases.
#   sbatch scripts/pelican_figures.slurm                       # all cases/figures/times
#   sbatch scripts/pelican_figures.slurm --figure section,surface --time 12,18
# Extra args after the script are forwarded to pelican_figures.py.

set -euo pipefail

# Login env does NOT carry into batch jobs; call the env python directly.
PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python
REPO=~/gits/brc-tools

# Writable matplotlib cache (else every run rebuilds it / errors) + pre-populated cartopy
# Natural-Earth data (compute nodes may lack outbound network).
export MPLCONFIGDIR="/scratch/general/vast/$USER/mpl-$SLURM_JOB_ID"
mkdir -p "$MPLCONFIGDIR"
export CARTOPY_DATA_DIR="/scratch/general/vast/$USER/cartopy"
export PYTHONPATH="$REPO:${PYTHONPATH:-}"

# Figures route out of the repo: per-case -> <run>/full-figures/, cross-case ->
# $BRC_WRF_ARCHIVE/pelican2013_pub_figures/compare/.  Override archive root if needed:
# export BRC_WRF_ARCHIVE=/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/wrf_archive

cd "$REPO"
echo "=== pelican_figures start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="

# Soundings need a network node: run scripts/fetch_soundings.py on a login/DTN node
# first, then add: --sounding-cache /scratch/general/vast/$USER/soundings_*.parquet
"$PY" scripts/pelican_figures.py --case all --figure all --time all "$@"

echo "=== pelican_figures done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
