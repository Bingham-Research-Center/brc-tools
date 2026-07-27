#!/bin/bash
# Gate A staging for ashley_drainage_120m -- HRRR atmosphere + GFS soil, two streams.
#
# Event: 24-25 April 2026 anabatic->katabatic slope-flow reversal.
# Window: 23Z 24 Apr -> 05Z 25 Apr (6 h), hourly LBCs, so HRRR f00..f06 from the
# 23Z cycle. Tracked in ../ub-wx/experiments/20260424-ashley-drainage-120m/.
#
# TWO STREAMS IS NOT OPTIONAL. Public HRRR GRIB (nat+sfc) carries ZERO
# soil-temperature messages and soil moisture only at degenerate 0 / 0.01 m layers,
# so a single-stream HRRR metgrid yields num_metgrid_soil_levels=0 and real.exe
# cannot initialise Noah. Established by ashley2026_seiche gate C: job 14135619
# failed on exactly this, 14136134 passed once GFS soil was added. RAP 130 was
# checked and also lacks soil. The working soil source is GFS 0.25 f000.
#
# SOIL now comes from --source gfs_soil (Herbie/AWS), not gfs_analysis (NCEI direct).
# NCEI 502'd three times on job 14297023, and the analysis stager could only offer
# f000 on the 6-hourly grid -- soil valid 18Z for a 23Z init, 5 h stale in exactly
# the layer that swings diurnally. gfs_soil takes the most recent cycle AT OR BEFORE
# init and sets the lead to the gap, so the file is valid AT init: 18Z f005 here.
# It also gets 0.25 deg instead of NCEI's 0.5, and falls back gracefully through
# older cycles if an object is missing, logging how far from ideal it landed.
#
# Submit:  sbatch scripts/stage_ashley_drainage_120m.dtn.slurm

#SBATCH --job-name=stage_ashley120m
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=0-03:00:00
#SBATCH --output=/scratch/general/vast/%u/stage_ashley120m_%j.out
#SBATCH --error=/scratch/general/vast/%u/stage_ashley120m_%j.out

set -euo pipefail

PY="$HOME/software/pkg/miniforge3/envs/brc-tools-2026/bin/python"
REPO="$HOME/gits/brc-tools"
CASE=ashley_drainage_120m
OUT="/scratch/general/vast/$USER/wrf_inputs"

cd "$REPO"
export PYTHONPATH="$REPO:${PYTHONPATH:-}"
# CHPC DTNs can hang on outbound IPv6 (job 13471949 wedged in SYN-SENT to an NCEI
# IPv6 address); force IPv4 for every download.
export BRC_TOOLS_HTTP_IPV4_ONLY=1
export PYTHONPYCACHEPREFIX="/scratch/general/vast/$USER/pycache"
# Herbie's per-GRIB lock defaults to node-local /tmp, so fanned-out jobs do NOT
# serialise and one can delete a subset GRIB while another reads it.
export BRC_TOOLS_LOCK_DIR="/scratch/general/vast/$USER/herbie_locks"
mkdir -p "$BRC_TOOLS_LOCK_DIR"

echo "=== gate A staging start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="

# ---- plan first: list URLs and bytes, download nothing -----------------------
# A 2026-04 date is ~3 months old and well inside the HRRR archive, but the plan
# costs seconds and turns a silent 404 storm into a readable failure.
# NOTE: --plan is NOT honoured on the --source hrrr path -- it downloads anyway.
# Verified on job 14296762, whose "PLAN" phase staged 5.6 GB. No HRRR plan call here.

echo "--- PLAN: GFS soil ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "2026-04-24 23:00" \
  --output-dir "$OUT" --plan

# ---- stage ------------------------------------------------------------------
echo "--- STAGE: HRRR nat+sfc f00..f06 from 2026-04-24 23Z ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source hrrr --init-time "2026-04-24 23Z" \
  --leads 0,1,2,3,4,5,6 --products nat,sfc --interval-seconds 3600 \
  --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

echo "--- STAGE: GFS soil via Herbie/AWS, valid AT init (18Z cycle f005) ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "2026-04-24 23:00" \
  --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

# ---- report -----------------------------------------------------------------
# NOTE: `set -o pipefail` + `| head` makes SIGPIPE fail the job even when staging
# succeeded -- that is what marked job 14298037 FAILED with exit 32 after both
# streams had landed correctly. Every reporting pipe below is guarded.
set +o pipefail
echo "=== staged set ==="
ls -lhR "$OUT/$CASE/" | head -60 || true
for f in "$OUT/$CASE"/manifest_*.json "$OUT/$CASE"/contract_*.json; do
    [[ -f "$f" ]] && { echo "--- $f ---"; "$PY" -m json.tool "$f" | head -40 || true; }
done
rm -rf "$OUT/.herbie_cache_$CASE" || true
echo "=== gate A staging done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo
echo "NEXT: gate C is a TWO-STREAM metgrid, not a single ungrib pass --"
echo "  HRRR stream: Vtable.raphrrr.nosoil, prefix HRRR"
echo "  GFS  stream: Vtable.gfssoil,        prefix GFSSOIL"
echo "  metgrid fg_name = 'HRRR','GFSSOIL'  (HRRR first: it wins atmosphere+surface)"
echo "  Both Vtables: \$WRF_ARCHIVE/ashley2026_seiche/control/smoke_20260723T044000Z/"
