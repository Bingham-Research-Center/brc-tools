#!/bin/bash
# Gate A staging (RE-STAGE) for ashley_drainage_120m -- HRRR atmosphere + GFS soil.
#
# EVENT CHANGED 2026-07-28: 8-9 SEPTEMBER 2025, replacing 24-25 April 2026.
# April failed proposal 4a's weak-synoptic-flow criterion outright -- HRRR showed
# 8-14 m/s across the whole Basin before sunset, which is the mechanical-mixing
# confound that criterion exists to exclude. September is 1-4 m/s outside a single
# surge, and PC101 (the Dry Fork truth site, INSIDE d03) shows a clean bidirectional
# slope-flow reversal.
#
# WINDOW vs STAGING SPAN -- these are deliberately different:
#   wrf.exe integrates   20Z 8 Sep -> 05Z 9 Sep   (9 h, run_hours=9)
#   staging + real.exe   20Z 8 Sep -> 12Z 9 Sep   (16 h, HRRR f00..f16)
# real.exe builds wrfbdy_d01 across the FULL staged span, so a later restart from
# the 05Z restart file can run on to 12Z WITHOUT re-running WPS or real.exe. Boundary
# conditions are the thing that makes an extension legal or not; staging them once,
# now, is what buys that. The extra 7 lead times cost ~6 GB and nothing else.
# HRRR runs to f18 on non-synoptic init hours, so f16 from a 20Z cycle exists.
#
# TWO STREAMS IS NOT OPTIONAL. Public HRRR GRIB (nat+sfc) carries ZERO
# soil-temperature messages and soil moisture only at degenerate 0 / 0.01 m layers,
# so a single-stream metgrid yields num_metgrid_soil_levels=0 and real.exe cannot
# initialise Noah. Re-verified against this case's own April f00 on 2026-07-27.
# Soil comes from --source gfs_soil (Herbie/AWS): it takes the most recent cycle AT
# OR BEFORE init and sets the lead to the gap, so the file is valid AT init --
# here the 18Z 8 Sep cycle at f002.
#
# Submit:  sbatch scripts/stage_ashley_drainage_120m_sep2025.dtn.slurm

#SBATCH --job-name=stage_a120m_sep
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=0-04:00:00
#SBATCH --output=/scratch/general/vast/%u/stage_a120m_sep_%j.out
#SBATCH --error=/scratch/general/vast/%u/stage_a120m_sep_%j.out

set -euo pipefail

PY="$HOME/software/pkg/miniforge3/envs/brc-tools-2026/bin/python"
REPO="$HOME/gits/brc-tools"
CASE=ashley_drainage_120m
OUT="/scratch/general/vast/$USER/wrf_inputs"
INIT="2025-09-08 20:00"

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

echo "=== September re-stage start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="

# The April set must go first: same case name, same directory, and a stale HRRR file
# left beside the new ones would be silently linked into ungrib by link_grib.csh.
APRIL_KEEP="$OUT/$CASE.april2026"
if [[ -d "$OUT/$CASE" ]]; then
  echo "--- moving the April staging aside to $APRIL_KEEP ---"
  rm -rf "$APRIL_KEEP"
  mv "$OUT/$CASE" "$APRIL_KEEP"
fi

# ---- plan first: list URLs and bytes, download nothing -----------------------
# NOTE: --plan is NOT honoured on the --source hrrr path -- it downloads anyway
# (verified on job 14296762, whose "PLAN" phase staged 5.6 GB). No HRRR plan call.
echo "--- PLAN: GFS soil ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "$INIT" \
  --output-dir "$OUT" --plan

# ---- stage ------------------------------------------------------------------
echo "--- STAGE: HRRR nat+sfc f00..f16 from 2025-09-08 20Z (16 h span for restarts) ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source hrrr --init-time "2025-09-08 20Z" \
  --leads 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16 \
  --products nat,sfc --interval-seconds 3600 \
  --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

echo "--- STAGE: GFS soil via Herbie/AWS, valid AT init (18Z cycle f002) ---"
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
echo "hrrr files: $n_hrrr (expect 34 = 17 leads x nat+sfc)"
echo "soil files: $n_soil (expect 1)"
for f in "$OUT/$CASE"/manifest_*.json "$OUT/$CASE"/contract_*.json; do
    [[ -f "$f" ]] && { echo "--- $f ---"; "$PY" -m json.tool "$f" | head -40 || true; }
done
rm -rf "$OUT/.herbie_cache_$CASE" || true
echo "=== September re-stage done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo
echo "April staging retained at $APRIL_KEEP -- delete once September has passed gate C."
echo "NEXT: gate C two-stream metgrid over 17 valid times -> 51 met_em (3 domains x 17)."
