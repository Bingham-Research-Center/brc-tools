#!/bin/bash
# forecast_funnel.dtn.slurm -- Download NAM + render the forecast-funnel montage on a DTN.
#
# The funnel downloads a NAM analysis (Herbie/S3 or the NCEI direct GET) and then makes
# ONE lightweight 4-panel figure, so download + plot run together in a single DTN job.
# Downloads belong on a DTN: it has direct internet (compute/interactive nodes may NOT)
# and is the sanctioned place for large transfers. See docs/FORECAST-FUNNEL.md.
#
# Submit:  sbatch scripts/forecast_funnel.dtn.slurm "2026-07-20 00Z"
#     or:  sbatch --export=ALL,INIT="2013-01-31 00Z" scripts/forecast_funnel.dtn.slurm

#SBATCH --job-name=forecast_funnel
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --mem=16G
#SBATCH --time=0-01:00:00
#SBATCH --output=/scratch/general/vast/%u/forecast_funnel_%j.out
#SBATCH --error=/scratch/general/vast/%u/forecast_funnel_%j.err

set -euo pipefail

# Login env does NOT carry into batch jobs; call the conda env's python directly.
PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python   # herbie 2026.3.0
REPO=~/gits/brc-tools
OUT=/scratch/general/vast/$USER/forecast_funnel

# brc_tools is not pip-installed; running scripts/ puts scripts/ on sys.path, not the
# repo root — so make the package importable (mirrors the study-repo figure wrapper).
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"

# Init time: positional $1, else $INIT, else a placeholder to edit.
INIT="${1:-${INIT:-2026-07-20 00Z}}"

cd "$REPO"
echo "=== funnel start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) -- init '$INIT' ==="

# CHPC DTNs can hang on outbound IPv6 (see stage_inputs.dtn.slurm); force IPv4 for
# every download (Herbie/S3 + the direct NCEI NAM GET).
export BRC_TOOLS_HTTP_IPV4_ONLY=1

# matplotlib + basemap caches on writable storage (never the repo). Point
# BRC_TOOLS_BASEMAP_DIR at the persistent Natural-Earth cache staged by
# scripts/fetch_basemap.dtn.slurm so state borders + city labels render.
export MPLCONFIGDIR="$OUT/.mplconfig"
export BRC_TOOLS_HERBIE_CACHE="$OUT/.herbie_cache"
: "${BRC_TOOLS_BASEMAP_DIR:=/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-data/cartopy}"
export BRC_TOOLS_BASEMAP_DIR
mkdir -p "$MPLCONFIGDIR" "$BRC_TOOLS_HERBIE_CACHE"

"$PY" scripts/forecast_funnel.py --init-time "$INIT" --output-dir "$OUT"

echo "=== funnel done $(date -u +%H:%M:%S) ==="
ls -lh "$OUT"/forecast_funnel_*.png | tail -3 || true
