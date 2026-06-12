#!/bin/bash
# stage_inputs.dtn.slurm -- Stage WRF/WPS GRIB inputs on a CHPC Data Transfer Node.
#
# Downloads belong on a DTN: it has direct internet (compute/interactive nodes may
# NOT -- CHPC says "verify first") and is the sanctioned place for large transfers,
# keeping heavy I/O off the shared login nodes. See docs/WRF-INPUT-STAGING.md and
# brc-knowledge chpc-slurm-job-examples.md (DTN template) + chpc-team-resource-inventory.md.
#
# Submit:  sbatch scripts/stage_inputs.dtn.slurm

#SBATCH --job-name=stage_wrf_inputs
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=0-06:00:00
#SBATCH --output=stage_%j.out
#SBATCH --error=stage_%j.err

set -euo pipefail

# Login env does NOT carry into batch jobs; call the conda env's python directly.
PY=~/software/pkg/miniforge3/envs/clyfar-nov2025/bin/python   # herbie 2025.11.3
REPO=~/gits/brc-tools
CASE=jan2013_basin_gefs
OUT=/scratch/general/vast/$USER/wrf_inputs

cd "$REPO"
echo "=== stage start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="

# Stage TWO sources into one case + one manifest:
#  - nam_analysis    : auth-free NAM 12 km analysis (NCEI, no NCAR RDA) -- the validated
#                      single-stream WRF forcing (Vtable.NAM). ~7 files, ~0.8 GB. THE runnable path.
#  - gefs_reforecast : control member, lead-subset to f12..f48 (~650 MB, not the whole ~4 GB
#                      f3..f240 bucket) -- ensemble forcing for the later two-stream path.
# --lead-subset applies to the reforecast only; NAM ignores it. Herbie cache on the SAME
# filesystem as the output makes the reforecast move a rename. Quicklook off on the DTN.
"$PY" scripts/stage_wrf_inputs.py \
  --case "$CASE" --init-time "2013-01-31 00Z" --members 0 \
  --source nam_analysis,gefs_reforecast \
  --fxx-window 12,48 --lead-subset --no-quicklook \
  --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache"

echo "=== staged set ==="
ls -lh "$OUT/$CASE/nam_analysis/" "$OUT/$CASE/gefs_reforecast/c00/" || true
"$PY" -m json.tool "$OUT/$CASE/manifest_$CASE.json" | head -50
rm -rf "$OUT/.herbie_cache"   # leftover .idx; staged GRIB already moved into place
echo "=== stage done $(date -u +%H:%M:%S) ==="

# NEXT (see docs/WRF-INPUT-STAGING.md microtasks):
#  - brc-wrf (single-stream, validated): link $OUT/$CASE/nam_analysis/ into the WRF case
#    grib_data/, then ungrib (Vtable.NAM) -> metgrid (fg_name='NAM') -> real.exe.
#  - brc-wrf (two-stream, later): add the reforecast as fg_name='GEFS','NAM' for ensemble forcing.
