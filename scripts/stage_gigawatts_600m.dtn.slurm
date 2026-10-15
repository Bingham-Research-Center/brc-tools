#!/bin/bash
# Single HRRR cycle, f00-f48 nat+sfc, with GFS f000 soil at the same init.
# Requires a clean, exact brc-tools source checkout supplied by the control packet.
#SBATCH --job-name=stage_gigawatts600m
#SBATCH --account=dtn
#SBATCH --partition=notchpeak-dtn
#SBATCH --qos=notchpeak-dtn
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=06:00:00
set -euo pipefail
: "${BRC_TOOLS_PINNED_ROOT:?set the exact source checkout}"
: "${GW_CONTROL:?set the durable control directory}"
PIN=11eccf1c6ee2d72cf6e79e54e60e962c0feaccbc
[[ "$(git -C "$BRC_TOOLS_PINNED_ROOT" rev-parse HEAD)" == "$PIN" ]]
[[ -z "$(git -C "$BRC_TOOLS_PINNED_ROOT" status --porcelain)" ]]
PY="$HOME/software/pkg/miniforge3/envs/brc-tools-2026/bin/python"
export PYTHONPATH="$BRC_TOOLS_PINNED_ROOT" PYTHONDONTWRITEBYTECODE=1 BRC_TOOLS_HTTP_IPV4_ONLY=1
export BRC_TOOLS_LOCK_DIR="/scratch/general/vast/$USER/herbie_locks"
OUT="/scratch/general/vast/$USER/wrf_inputs"
CASE=gigawatts_600m
mkdir -p "$BRC_TOOLS_LOCK_DIR" "$OUT"
if compgen -G "$OUT/$CASE/hrrr/*.grib2" > /dev/null; then
  echo "Existing HRRR files require explicit resume review; refusing a mixed staging set" >&2
  exit 2
fi
printf 'source=%s job=%s host=%s\n' "$PIN" "$SLURM_JOB_ID" "$(hostname)"
df -h "$OUT" "$GW_CONTROL"
LEADS=$(seq -s, 0 48)
"$PY" -B -m brc_tools.nwp.wrf_staging --case "$CASE" --source gfs_soil --init-time '2025-01-26 18:00' --output-dir "$OUT" --plan
"$PY" -B -m brc_tools.nwp.wrf_staging --case "$CASE" --source hrrr --init-time '2025-01-26 18Z' --leads "$LEADS" --products nat,sfc --interval-seconds 3600 --no-quicklook --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"
"$PY" -B -m brc_tools.nwp.wrf_staging --case "$CASE" --source gfs_soil --init-time '2025-01-26 18:00' --interval-seconds 3600 --output-dir "$OUT" --herbie-save-dir "$OUT/.herbie_cache_$CASE"
"$PY" -B - "$OUT/$CASE" "$GW_CONTROL" <<'PY'
import collections, datetime as dt, json, pathlib, shutil, sys
from brc_tools.nwp.wrf_staging import verify_manifest
root, control = map(pathlib.Path, sys.argv[1:])
manifest = root / 'manifest_gigawatts_600m.json'
contract = root / 'contract_gigawatts_600m.json'
m, c = json.loads(manifest.read_text()), json.loads(contract.read_text())
assert c['sources'] == ['hrrr', 'gfs_soil'], c
assert c['wps_fg_name'] == ['HRRR', 'GFSSOIL'], c
assert c['interval_seconds'] == 3600, c
assert c['source_file_counts'] == {'hrrr': 98, 'gfs_soil': 1}, c
start = dt.datetime(2025, 1, 26, 18, tzinfo=dt.timezone.utc)
expected = collections.Counter({start + dt.timedelta(hours=h): 2 for h in range(49)})
actual = collections.Counter(dt.datetime.fromisoformat(r['valid_time'].replace('Z', '+00:00')) for r in m['staged_files'] if r['source'] == 'hrrr')
assert actual == expected, (actual, expected)
soil = [r for r in m['staged_files'] if r['source'] == 'gfs_soil']
assert len(soil) == 1 and dt.datetime.fromisoformat(soil[0]['valid_time'].replace('Z', '+00:00')) == start
report = verify_manifest(manifest)
assert report['ok'] and report['n_files'] == 99, report
out = control / 'forcing'
out.mkdir(exist_ok=True)
for p in (manifest, contract): shutil.copy2(p, out / p.name)
(out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
(out / 'coverage.json').write_text(json.dumps({'start': start.isoformat(), 'hourly_times': 49, 'hrrr_files': 98, 'gfs_soil_files': 1, 'sha256_verified': True}, indent=2) + '\n')
print('PASS: 99 files hashed, all 49 hourly HRRR times complete, GFS soil valid at init')
PY
date -u +%FT%TZ > "$GW_CONTROL/staging_complete.txt"
