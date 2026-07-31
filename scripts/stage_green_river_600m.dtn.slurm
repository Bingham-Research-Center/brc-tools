#!/bin/bash
# Gate A staging for green_river_600m -- HRRR atmosphere + GFS soil.
#
# EVENT: 21-22 NOVEMBER 2025, the Green River corridor as a nocturnal cold-air
# reservoir. Tracked at ub-wx experiments/20251121-green-river-cold-reservoir/.
# Gate A0 evidence lives there; do not restate it here. In one line: the corridor
# network confirms a quiescent drainage night -- PC101 at 302 deg down-canyon,
# Manila 310, Kings Point 288, Split Mountain 292, all at 0.5-3.3 m/s.
#
# INIT 12Z, NOT 18Z. The residual boundary layer that survives into the night is
# that day's CBL top and is one of the layers the experiment measures; an 18Z init
# is after the morning transition, so that layer would be HRRR's and would persist
# all night. A 12Z init inherits HRRR's nocturnal layer instead, which the model's
# own morning transition erases. 21Z is not viable at all -- non-synoptic HRRR
# cycles stop at f18 and cannot reach the 16Z end of the window.
#
# WINDOW vs STAGING SPAN -- deliberately different, same reasoning as the siblings:
#   wrf.exe integrates   12Z 21 Nov -> 16Z 22 Nov   (28 h, run_hours=28)
#   staging + real.exe   12Z 21 Nov -> 22Z 22 Nov   (34 h, HRRR f00..f34)
# real.exe builds wrfbdy_d01 across the FULL staged span, so a restart can run on
# past 16Z WITHOUT re-running WPS or real.exe. The six extra leads cost ~5 GB.
#
# SINGLE CYCLE, NOT SPLICED ANALYSES. brc-docs/BRC-WRF-UINTA-COLD-POOL-WAVES.md:
# "do not splice hourly analyses" -- an hourly analysis increment injected at the
# LBC radiates inward as spurious gravity waves, which is worse than 28 h of
# forecast drift. For this event the drift is small anyway: HRRR carries 700 hPa at
# 1.3-2.7 m/s and 500 hPa at 2.4-3.3 m/s over the box through the whole window.
#
# TWO STREAMS IS NOT OPTIONAL. Public HRRR GRIB (nat+sfc) carries ZERO
# soil-temperature messages and soil moisture only at degenerate 0 / 0.01 m layers,
# so a single-stream metgrid yields num_metgrid_soil_levels=0 and real.exe cannot
# initialise Noah. A property of the product, not of the date. Soil comes from
# --source gfs_soil (Herbie/AWS): it takes the most recent cycle AT OR BEFORE init
# and sets the lead to the gap, so the file is valid AT init -- here the 12Z 21 Nov
# cycle at f000, 0 h staleness. Verified present on noaa-gfs-bdp-pds.
#
# LEADS ARE AN EXPLICIT LIST, not a count. The 37 m case lost two jobs to
# `--max-fhours N` meaning f00..f(N-1) in a different tool; --leads is enumerated
# precisely so that class of off-by-one cannot recur. f00..f34 = 35 valid times.
#
# Expected: 70 HRRR files (35 leads x nat+sfc, ~30 GB at the measured 0.85 GB/lead)
# + 1 GFS soil file (~0.5 GB). Verified live on noaa-hrrr-bdp-pds: the 12Z 21 Nov
# cycle carries wrfnat+wrfsfc f00-f24 plus f30/f36/f48 (12Z is a synoptic hour, so
# the cycle is the extended one).
#
# Submit:  sbatch scripts/stage_green_river_600m.dtn.slurm

#SBATCH --job-name=stage_greenriver600m
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=0-06:00:00
#SBATCH --output=/scratch/general/vast/%u/stage_greenriver600m_%j.out
#SBATCH --error=/scratch/general/vast/%u/stage_greenriver600m_%j.out

set -euo pipefail

PY="$HOME/software/pkg/miniforge3/envs/brc-tools-2026/bin/python"
REPO="$HOME/gits/brc-tools"
CASE=green_river_600m
OUT="/scratch/general/vast/$USER/wrf_inputs"
INIT="2025-11-21 12:00"
LEADS="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34"

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

echo "=== green river 600m gate A staging start $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ==="
echo "    case=$CASE init=$INIT leads=f00..f34 products=nat,sfc"

# A pre-existing directory means a previous attempt, and link_grib.csh would silently
# link any stale GRIB sitting beside the new ones into ungrib. Refuse rather than mix.
if [[ -d "$OUT/$CASE" ]] && compgen -G "$OUT/$CASE/hrrr/*.grib2" > /dev/null; then
  echo "ERROR: $OUT/$CASE already holds HRRR GRIB. Move it aside or delete it before" >&2
  echo "       re-staging -- a stale file beside the new set gets linked silently." >&2
  exit 2
fi

# ---- plan first: list URLs and bytes, download nothing -----------------------
# NOTE: --plan is NOT honoured on the --source hrrr path -- the tool now refuses it
# outright (exit 2) because it used to fall through to a real download, which cost
# 5.6 GB on a login node in job 14296762. No HRRR plan call here.
echo "--- PLAN: GFS soil ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "$INIT" \
  --output-dir "$OUT" --plan

# ---- stage ------------------------------------------------------------------
# ORDER MATTERS: HRRR first, then soil. The soil run merges into the existing
# manifest and contract, and metgrid reads fg_name in PRIORITY order -- the
# atmosphere source must come first or the supplement wins fields it should not.
echo "--- STAGE: HRRR nat+sfc f00..f34 from 2025-11-21 12Z (34 h span for restarts) ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source hrrr --init-time "2025-11-21 12Z" \
  --leads "$LEADS" \
  --products nat,sfc --interval-seconds 3600 \
  --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

echo "--- STAGE: GFS soil via Herbie/AWS, valid AT init (12Z 21 Nov cycle f000) ---"
"$PY" -B -m brc_tools.nwp.wrf_staging \
  --case "$CASE" --source gfs_soil --init-time "$INIT" \
  --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"

# ---- verify -----------------------------------------------------------------
# NOTE: `set -o pipefail` + `| head` makes SIGPIPE fail the job even when staging
# succeeded -- that is what marked job 14298037 FAILED with exit 32 after both
# streams had landed correctly. Every reporting pipe below is guarded.
set +o pipefail
echo "=== staged set ==="
du -sh "$OUT/$CASE"/* || true
n_hrrr=$(ls "$OUT/$CASE"/hrrr/*.grib2 2>/dev/null | wc -l)
n_soil=$(ls "$OUT/$CASE"/gfs_soil/*.grib2 2>/dev/null | wc -l)
echo "hrrr files: $n_hrrr (expect 70 = 35 leads x nat+sfc)"
echo "soil files: $n_soil (expect 1)"

echo "--- MANIFEST VERIFY (existence + size + sha256 of every staged file) ---"
for m in "$OUT/$CASE"/manifest_*.json; do
    [[ -f "$m" ]] && "$PY" -B -m brc_tools.nwp.wrf_staging --verify-manifest "$m" || true
done
echo "--- CONTRACT (fg_name order is the two-stream contract) ---"
for c in "$OUT/$CASE"/contract_*.json; do
    [[ -f "$c" ]] && { echo "--- $c ---"; "$PY" -m json.tool "$c" | head -40 || true; }
done
rm -rf "$OUT/.herbie_cache_$CASE" || true

# Gate A does not pass on "the job exited 0". These are the gate.
[[ "$n_hrrr" -eq 70 ]] || echo "WARN: expected 70 HRRR files, found $n_hrrr -- gate A NOT passed"
[[ "$n_soil" -eq 1 ]] || echo "WARN: expected 1 soil file, found $n_soil -- gate A NOT passed"

echo "=== green river 600m gate A staging done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo
echo "NEXT: gate C two-stream metgrid over 35 valid times -> 70 met_em (2 domains x 35),"
echo "      num_metgrid_levels 51, num_metgrid_soil_levels 4, ST spatial std > 2 K."
