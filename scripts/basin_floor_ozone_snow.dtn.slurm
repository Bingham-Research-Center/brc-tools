#!/bin/bash
# basin_floor_ozone_snow.dtn.slurm -- Fetch Synoptic obs + render the basin-floor
# winter ozone/snow figure on a CHPC Data Transfer Node.
#
# Why a DTN, not lawson-np/notch392 (the brc-wrf compute pattern): this job needs
# OUTBOUND INTERNET (the Synoptic API). CHPC compute/interactive nodes "may lack
# internet -- verify first" (docs/WRF-INPUT-STAGING.md §5a); the DTN is the
# sanctioned, internet-connected node and keeps the pull off the shared login
# nodes. Conventions (header block, set -euo pipefail, env-python, IPv4-only) and
# template follow scripts/stage_inputs.dtn.slurm.
#
# Submit:  sbatch scripts/basin_floor_ozone_snow.dtn.slurm

#SBATCH --job-name=basin_o3_snow
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --mem=8G
#SBATCH --time=0-00:30:00
#SBATCH --output=basin_o3_snow_%j.out
#SBATCH --error=basin_o3_snow_%j.err

set -euo pipefail

# Login env does NOT carry into batch jobs; call the conda env's python directly.
PY=~/software/pkg/miniforge3/envs/clyfar-nov2025/bin/python   # SynopticPy, polars, matplotlib
REPO=~/gits/brc-tools

cd "$REPO"
echo "=== basin o3/snow start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="

# CHPC DTNs can hang on outbound IPv6 (SYN-SENT); force IPv4 for every socket.
# The plotting script reads this and calls wrf_staging._install_ipv4_only().
export BRC_TOOLS_HTTP_IPV4_ONLY=1
export MPLBACKEND=Agg

# Output goes to CHPC group storage, never the repo. Export the default so the
# Python process and the final 'ls' resolve the SAME location.
export BRC_TOOLS_OUTPUT_DIR="${BRC_TOOLS_OUTPUT_DIR:-/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-output}"
OUTROOT="$BRC_TOOLS_OUTPUT_DIR"

"$PY" scripts/basin_floor_ozone_snow.py \
  --start 2025-12-01 --end 2026-03-31 --max-elev-m 1900

echo "=== rendered figure(s) ==="
ls -lh "$OUTROOT/basin_winter/" || true
echo "=== basin o3/snow done $(date -u +%H:%M:%S) ==="
