#!/bin/bash
# fetch_basemap.dtn.slurm -- Stage Natural-Earth reference shapefiles into a PERSISTENT
# cache on a CHPC Data Transfer Node.
#
# Why a DTN: the figure-engine map overlays (brc_tools.visualize.basemap) need the
# Natural-Earth 10 m shapefiles on a path the batch figure jobs can read.  A DTN is the
# only node type with BOTH direct internet (to fetch) AND read-write group storage (to
# persist): login nodes may mount group storage read-only; compute nodes lack internet.
# So stage ONCE here into durable storage; every later figure job just reads it offline.
#
# Submit:  sbatch scripts/fetch_basemap.dtn.slurm
# Refresh: re-submit (cartopy skips layers already present; delete the dir to force).

#SBATCH --job-name=fetch_basemap
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=8G
#SBATCH --time=0-01:00:00
# Job logs to scratch, never into the repo checkout.
#SBATCH --output=/scratch/general/vast/%u/fetch_basemap_%j.out
#SBATCH --error=/scratch/general/vast/%u/fetch_basemap_%j.err

set -euo pipefail

# Login env (conda/modules) does NOT carry into batch jobs; call the env python directly.
PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python
REPO=~/gits/brc-tools

# Persistent cache dir: inherit BRC_TOOLS_BASEMAP_DIR from the submit env if set, else
# default to group storage (survives scratch purges).  Override at submit time with:
#   sbatch --export=ALL,BRC_TOOLS_BASEMAP_DIR=/path scripts/fetch_basemap.dtn.slurm
export BRC_TOOLS_BASEMAP_DIR="${BRC_TOOLS_BASEMAP_DIR:-/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-data/cartopy}"
# cartopy reads/writes its cache under CARTOPY_DATA_DIR; point it at the same dir.
export CARTOPY_DATA_DIR="$BRC_TOOLS_BASEMAP_DIR"

mkdir -p "$BRC_TOOLS_BASEMAP_DIR"
cd "$REPO"
echo "=== fetch_basemap start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) -> $BRC_TOOLS_BASEMAP_DIR ==="

# Seed from an existing scratch cache if present: an offline copy fully populates the
# persistent dir without any download, so the job succeeds even if the DTN's outbound
# IPv6 stalls (see stage_inputs.dtn.slurm).  fetch_basemap.py then only fills real gaps.
SCRATCH_CACHE="/scratch/general/vast/$USER/cartopy"
if [ -d "$SCRATCH_CACHE" ] && [ "$SCRATCH_CACHE" != "$BRC_TOOLS_BASEMAP_DIR" ]; then
  echo "seeding from $SCRATCH_CACHE (offline copy)"
  cp -a "$SCRATCH_CACHE/." "$BRC_TOOLS_BASEMAP_DIR/" 2>/dev/null || true
fi

# Idempotent: cartopy skips any layer already present (so a full seed => no download).
"$PY" scripts/fetch_basemap.py
echo "=== fetch_basemap done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
