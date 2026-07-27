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
# GFS cycle choice: our init is 23Z, which is not a GFS cycle. Take the most recent
# analysis AT OR BEFORE init -- 18Z 24 Apr. That is a rule rather than a per-case
# judgement (it can never reach for an analysis from the future), which is what makes
# it safe to put on rails. `--fxx-window 0,0` expresses exactly that: the window
# start is snapped DOWN to the 6-hourly cadence grid, giving one cycle at 18Z.
#
# Omitting --fxx-window is what went wrong on job 14296762: the default (12,48) is
# sized for GFS as DRIVING forcing and enumerated a 6-hourly sequence from 12Z 25
# Apr onward. Not a tool bug -- the wrong window for this use.
#
# Ideal would be 18Z f005, valid exactly at our 23Z init; the analysis stager fetches
# f000 only. The residual is 5 h of soil evolution, and since the top layer is what
# swings diurnally this is a real but second-order error worth stating in notes.
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
  --case "$CASE" --source gfs_analysis --init-time "2026-04-24 23Z" \
  --fxx-window 0,0 --output-dir "$OUT" --plan

# ---- stage ------------------------------------------------------------------
echo "--- STAGE: HRRR nat+sfc f00..f06 from 2026-04-24 23Z ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source hrrr --init-time "2026-04-24 23Z" \
  --leads 0,1,2,3,4,5,6 --products nat,sfc --interval-seconds 3600 \
  --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

echo "--- STAGE: GFS analysis f000 (soil), most recent cycle at/before init = 18Z 24 Apr ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_analysis --init-time "2026-04-24 23Z" \
  --fxx-window 0,0 \
  --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

# ---- report -----------------------------------------------------------------
echo "=== staged set ==="
ls -lhR "$OUT/$CASE/" | head -60
for f in "$OUT/$CASE"/manifest_*.json "$OUT/$CASE"/contract_*.json; do
    [[ -f "$f" ]] && { echo "--- $f ---"; "$PY" -m json.tool "$f" | head -40; }
done
rm -rf "$OUT/.herbie_cache_$CASE"
echo "=== gate A staging done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo
echo "NEXT: gate C is a TWO-STREAM metgrid, not a single ungrib pass --"
echo "  HRRR stream: Vtable.raphrrr.nosoil, prefix HRRR"
echo "  GFS  stream: Vtable.gfssoil,        prefix GFSSOIL"
echo "  metgrid fg_name = 'HRRR','GFSSOIL'  (HRRR first: it wins atmosphere+surface)"
echo "  Both Vtables: \$WRF_ARCHIVE/ashley2026_seiche/control/smoke_20260723T044000Z/"
