#!/usr/bin/env bash
# Stage B cron wrapper: export HRRR waypoint-forecast JSON and upload to basinwx.dev.
#
# Pin to .dev until the ubair-website waypoint consumer lands on ops. After
# that, drop BASINWX_API_URLS so fan-out is driven by website_urls.
#
# Install on notchpeak1:
#   50 * * * * ~/gits/brc-tools/scripts/cron/run_hrrr_waypoint_push.sh
set -euo pipefail

export BASINWX_API_URLS="https://basinwx.dev"

CONDA_ENV="${CONDA_ENV:-brc-tools}"
REPO_DIR="${REPO_DIR:-$HOME/gits/brc-tools}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/hrrr_waypoints.log}"
GROUP="${GROUP:-us40_dense}"

mkdir -p "${LOG_DIR}"

# shellcheck disable=SC1090
source "${HOME}/.bashrc"
conda activate "${CONDA_ENV}"

cd "${REPO_DIR}"

{
  echo "[run_hrrr_waypoint_push] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  python scripts/export_hrrr_waypoint_forecast.py --upload --group "${GROUP}"
} >> "${LOG_FILE}" 2>&1
