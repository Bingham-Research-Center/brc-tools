#!/bin/bash
# wrf_winds.dtn.slurm -- Render basin-winds-style figures from a WRF run.
#
#   sbatch scripts/wrf_winds.dtn.slurm --config <case.toml> [--run-dir <run>] \
#          [--valid ...|--lead ...] [--domain N] [--w-exag X] [--output-dir <dir>]
#
# Every argument is forwarded verbatim to scripts/wrf_winds.py.
#
# Why a DTN and not a login node or the owner partition:
#   * `lawson-group6` is mounted READ-ONLY on the notchpeak login nodes, so curated
#     figures can only be written to group storage from a compute or DTN node.
#   * `lawson-np` is a single node, and the usual reason to want these figures is
#     that a WRF run is occupying it -- a figure job queued behind that run would
#     wait for the very thing it is meant to monitor.
#   * The work is I/O-heavy and CPU-light (read one wrfout time, draw a dozen
#     panels), which is exactly what a DTN is for. No internet needed: the
#     Natural-Earth overlays come from the staged cache (fetch_basemap.dtn.slurm).

#SBATCH --job-name=wrf_winds
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=0-03:00:00
#SBATCH --output=/scratch/general/vast/%u/wrf_winds_%j.out
#SBATCH --error=/scratch/general/vast/%u/wrf_winds_%j.err

set -euo pipefail

# The login env does NOT carry into batch jobs; call the conda env's python directly.
PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python
REPO="${BRC_TOOLS_ROOT:-$HOME/gits/brc-tools}"
SCRATCH="/scratch/general/vast/$USER/ub-wx"

# Writable caches on scratch; nothing generated lands in a checkout.
export PYTHONPATH="$REPO:${PYTHONPATH:-}"
export MPLCONFIGDIR="$SCRATCH/mpl"
export PYTHONPYCACHEPREFIX="$SCRATCH/pycache"
export BRC_TOOLS_BASEMAP_DIR="${BRC_TOOLS_BASEMAP_DIR:-/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-data/cartopy}"
mkdir -p "$MPLCONFIGDIR" "$PYTHONPYCACHEPREFIX"

echo "Python:  $PY"
echo "Engine:  $REPO/scripts/wrf_winds.py"
echo "Args:    $*"
# -u: unbuffered. A multi-hour sweep whose progress only appears when the job ends
# is indistinguishable from a hung one.
exec "$PY" -u -B "$REPO/scripts/wrf_winds.py" "$@"
