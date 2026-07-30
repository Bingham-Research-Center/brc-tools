#!/bin/bash
# wrf_convective.dtn.slurm -- Render convective diagnostics from a WRF run.
#
#   sbatch scripts/wrf_convective.dtn.slurm --config <case.toml> [--run-dir <run>] \
#          [--figure beam] [--valid ...|--every 1] [--domain N] [--output-dir <dir>]
#
# Every argument is forwarded verbatim to scripts/wrf_convective.py.
#
# Why a DTN and not a login node or the owner partition:
#   * `lawson-group6` is mounted READ-ONLY on the notchpeak login nodes, so curated
#     figures can only be written to group storage from a compute or DTN node.
#   * `lawson-np` is a single node, and the usual reason to want these figures is
#     that a WRF run is occupying it -- a figure job queued behind that run would
#     wait for the very thing it is meant to monitor.
#   * The work is I/O-heavy and CPU-light. Note the auxiliary-stream families read
#     ~400 MB files holding 60 frames each, and a 1-minute sweep of a 5 h window
#     touches all of them, so this is squarely DTN work.
#   * Internet is NOT needed for the model-only families (the Natural-Earth
#     overlays come from the staged cache). The `--figure beam` family compares
#     against a real radar only if a volume is already cached; fetching NEXRAD
#     Level-II does need outbound HTTPS, which a DTN has.
#
# Time budget: a single time across both nests is ~2-4 min. A 1-minute sweep of
# 02:00-03:00Z is ~60 times; scale --time accordingly and prefer --figure to
# narrow the families rather than rendering everything at every minute.

#SBATCH --job-name=wrf_convective
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=0-06:00:00
#SBATCH --output=/scratch/general/vast/%u/wrf_convective_%j.out
#SBATCH --error=/scratch/general/vast/%u/wrf_convective_%j.err

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
export BRC_TOOLS_RADAR_CACHE="${BRC_TOOLS_RADAR_CACHE:-$SCRATCH/nexrad_cache}"
# Outbound IPv6 from a CHPC DTN to NCEI/S3 has been observed to hang in SYN-SENT;
# force IPv4 for any NEXRAD fetch. Harmless when nothing is fetched.
export BRC_TOOLS_HTTP_IPV4_ONLY="${BRC_TOOLS_HTTP_IPV4_ONLY:-1}"
mkdir -p "$MPLCONFIGDIR" "$PYTHONPYCACHEPREFIX" "$BRC_TOOLS_RADAR_CACHE"

echo "Python:  $PY"
echo "Engine:  $REPO/scripts/wrf_convective.py"
echo "Args:    $*"
# -u: unbuffered. A multi-hour sweep whose progress only appears when the job ends
# is indistinguishable from a hung one.
exec "$PY" -u -B "$REPO/scripts/wrf_convective.py" "$@"
