#!/bin/bash
# Gate A staging for ashley_storm_600m -- HRRR atmosphere + GFS soil.
#
# EVENT: 11-12 OCTOBER 2025, the nocturnal rotating cell over Ashley Valley. Tracked at
# ub-wx experiments/20251011-ashley-rotating-cell/. Gate A0 passed on both halves:
# the surface network shows a W->E outflow surge at 01:20-01:50Z and a small cyclonic
# vortex signature at KVEL at 02:30-02:40Z, and HRRR carries the storm in EVERY cycle
# (52-59 dBZ within 55 km of the spotter point; the 02Z/03Z analyses have it too).
# The 23Z cycle is the confirmed control init: 34.4 dBZ already at f00 rising to 56.6
# by 02Z, so the downscale refines an ongoing system rather than generating one.
#
# WINDOW vs STAGING SPAN -- deliberately different, same reasoning as the sibling:
#   wrf.exe integrates   23Z 11 Oct -> 04Z 12 Oct   (5 h, run_hours=5)
#   staging + real.exe   23Z 11 Oct -> 06Z 12 Oct   (7 h, HRRR f00..f07)
# real.exe builds wrfbdy_d01 across the FULL staged span, so a restart from the 04Z
# restart file can run on to 06Z WITHOUT re-running WPS or real.exe. The two extra
# lead times cost ~1.8 GB and nothing else.
#
# TWO STREAMS IS NOT OPTIONAL. Public HRRR GRIB (nat+sfc) carries ZERO soil-temperature
# messages and soil moisture only at degenerate 0 / 0.01 m layers, so a single-stream
# metgrid yields num_metgrid_soil_levels=0 and real.exe cannot initialise Noah. This is
# a property of the product, not of the date -- established at the sibling's gate C and
# re-verified on its September window. Soil comes from --source gfs_soil (Herbie/AWS):
# it takes the most recent cycle AT OR BEFORE init and sets the lead to the gap, so the
# file is valid AT init -- here the 18Z 11 Oct cycle at f005, 0 h staleness.
#
# LEADS ARE AN EXPLICIT LIST, not a count. The sibling case lost two jobs to
# `--max-fhours N` meaning f00..f(N-1) in a different tool; --leads here is enumerated
# precisely so that class of off-by-one cannot recur. f00..f07 = 8 valid times.
#
# Expected: 16 HRRR files (8 leads x nat+sfc, ~7.1 GB at the sibling's measured
# 0.88 GB/lead) + 1 GFS soil file (~0.5 GB).
#
# Submit:  sbatch scripts/stage_ashley_storm_600m.dtn.slurm

#SBATCH --job-name=stage_storm600m
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=0-04:00:00
#SBATCH --output=/scratch/general/vast/%u/stage_storm600m_%j.out
#SBATCH --error=/scratch/general/vast/%u/stage_storm600m_%j.out

set -euo pipefail

PY="$HOME/software/pkg/miniforge3/envs/brc-tools-2026/bin/python"
REPO="$HOME/gits/brc-tools"
CASE=ashley_storm_600m
OUT="/scratch/general/vast/$USER/wrf_inputs"
INIT="2025-10-11 23:00"

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

echo "=== storm 600m gate A staging start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="
echo "    case=$CASE init=$INIT leads=f00..f07 products=nat,sfc"

# A pre-existing directory means a previous attempt, and link_grib.csh would silently
# link any stale GRIB sitting beside the new ones into ungrib. Refuse rather than mix.
if [[ -d "$OUT/$CASE" ]] && compgen -G "$OUT/$CASE/hrrr/*.grib2" > /dev/null; then
  echo "ERROR: $OUT/$CASE already holds HRRR GRIB. Move it aside or delete it before" >&2
  echo "       re-staging -- a stale file beside the new set gets linked silently." >&2
  exit 2
fi

# ---- plan first: list URLs and bytes, download nothing -----------------------
# NOTE: --plan is NOT honoured on the --source hrrr path -- it downloads anyway
# (verified on job 14296762, whose "PLAN" phase staged 5.6 GB). No HRRR plan call.
echo "--- PLAN: GFS soil ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "$INIT" \
  --output-dir "$OUT" --plan

# ---- stage ------------------------------------------------------------------
echo "--- STAGE: HRRR nat+sfc f00..f07 from 2025-10-11 23Z (7 h span for restarts) ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source hrrr --init-time "2025-10-11 23Z" \
  --leads 0,1,2,3,4,5,6,7 \
  --products nat,sfc --interval-seconds 3600 \
  --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

echo "--- STAGE: GFS soil via Herbie/AWS, valid AT init (18Z 11 Oct cycle f005) ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "$INIT" \
  --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

# ---- report -----------------------------------------------------------------
# NOTE: `set -o pipefail` + `| head` makes SIGPIPE fail the job even when staging
# succeeded -- that is what marked job 14298037 FAILED with exit 32 after both
# streams had landed correctly. Every reporting pipe below is guarded.
set +o pipefail
echo "=== staged set ==="
ls -lhR "$OUT/$CASE/" | head -80 || true
n_hrrr=$(ls "$OUT/$CASE"/hrrr/*.grib2 2>/dev/null | wc -l)
n_soil=$(ls "$OUT/$CASE"/gfs_soil/*.grib2 2>/dev/null | wc -l)
echo "hrrr files: $n_hrrr (expect 16 = 8 leads x nat+sfc)"
echo "soil files: $n_soil (expect 1)"
for f in "$OUT/$CASE"/manifest_*.json "$OUT/$CASE"/contract_*.json; do
    [[ -f "$f" ]] && { echo "--- $f ---"; "$PY" -m json.tool "$f" | head -40 || true; }
done
rm -rf "$OUT/.herbie_cache_$CASE" || true

# Gate A does not pass on "the job exited 0". These two counts are the gate.
[[ "$n_hrrr" -eq 16 ]] || echo "WARN: expected 16 HRRR files, found $n_hrrr -- gate A NOT passed"
[[ "$n_soil" -eq 1 ]] || echo "WARN: expected 1 soil file, found $n_soil -- gate A NOT passed"

echo "=== storm 600m gate A staging done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo
echo "NEXT: gate C two-stream metgrid over 8 valid times -> 16 met_em (2 domains x 8),"
echo "      num_metgrid_levels 51, num_metgrid_soil_levels 4."
