#!/bin/bash
# wrf_timeheight.dtn.slurm -- Render time-height sections from a WRF run's tslist.
#
#   sbatch scripts/wrf_timeheight.dtn.slurm --config <case.toml> [--run-dir <run>] \
#          [--station KEY] [--start ...] [--end ...] [--stride-min 5]
#
# Every argument is forwarded verbatim to scripts/wrf_timeheight.py.
#
# Same DTN rationale as wrf_winds.dtn.slurm: `lawson-group6` is read-only on the
# login nodes, and `lawson-np` is usually busy running the job being looked at.
# This engine is even more I/O-bound than that one -- it parses tens of MB of
# tslist text per station and draws a handful of panels -- so a DTN is the right
# place for it and it needs no internet.

#SBATCH --job-name=wrf_timeheight
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=0-02:00:00
#SBATCH --output=/scratch/general/vast/%u/wrf_timeheight_%j.out
#SBATCH --error=/scratch/general/vast/%u/wrf_timeheight_%j.err

set -euo pipefail

PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python
REPO="${BRC_TOOLS_ROOT:-$HOME/gits/brc-tools}"
SCRATCH="/scratch/general/vast/$USER/ub-wx"

export PYTHONPATH="$REPO:${PYTHONPATH:-}"
export MPLCONFIGDIR="$SCRATCH/mpl"
export PYTHONPYCACHEPREFIX="$SCRATCH/pycache"
export BRC_TOOLS_BASEMAP_DIR="${BRC_TOOLS_BASEMAP_DIR:-/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-data/cartopy}"
mkdir -p "$MPLCONFIGDIR" "$PYTHONPYCACHEPREFIX"

echo "Python:  $PY"
echo "Engine:  $REPO/scripts/wrf_timeheight.py"
echo "Args:    $*"
exec "$PY" -u -B "$REPO/scripts/wrf_timeheight.py" "$@"
