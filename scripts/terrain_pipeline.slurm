#!/bin/bash
#SBATCH --account=lawson-np
#SBATCH --partition=lawson-np
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=06:00:00
#SBATCH --mem=160G
#SBATCH --job-name=terrain_pipeline
#SBATCH --output=/scratch/general/vast/%u/terrain_pipeline_%j.out
#SBATCH --error=/scratch/general/vast/%u/terrain_pipeline_%j.err
#
# brc_tools.terrain on a compute node (never a login node): 10 m over the Uinta Basin is
# ~6e8 cells and ~60 GB; 30 m takes minutes.  Uses the terrain-2026 env (richdem + rasterio +
# pyproj) with this checkout on PYTHONPATH, because that env carries no editable install.
# Logs go straight into /scratch/general/vast/$USER: Slurm opens them before the script
# runs, so their directory must already exist.  BRC_TOOLS_ROOT picks another checkout.
#   sbatch scripts/terrain_pipeline.slurm --tiles-dir $WRF_ARCHIVE/terrain/usgs_3dep --res 30 ...
set -euo pipefail
mkdir -p "/scratch/general/vast/$USER/brc-tools/terrain"
REPO="${BRC_TOOLS_ROOT:-$HOME/gits/brc-tools}"
PY="$HOME/software/pkg/miniforge3/envs/terrain-2026/bin/python"
export PYTHONPATH="$REPO:${PYTHONPATH:-}"
export PYTHONPYCACHEPREFIX="/scratch/general/vast/$USER/brc-tools/pycache"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}" GDAL_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}" GDAL_CACHEMAX=4096
export BRC_TOOLS_TERRAIN_CACHE="${BRC_TOOLS_TERRAIN_CACHE:-/scratch/general/vast/$USER/brc-tools/terrain/cache}"
exec "$PY" -B "$REPO/scripts/terrain_pipeline.py" "$@"
