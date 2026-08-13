#!/usr/bin/env bash
# Stage B cron wrapper: export HRRR waypoint-forecast JSON and upload to BasinWX.
#
# No BASINWX_API_URLS pin: website v1.5.0 (2026-08-13) promoted the dev
# consumers to ops, so fan-out is driven by
# ~/.config/ubair-website/website_urls (.com primary, .dev mirror).
#
# Install on notchpeak1:
#   50 * * * * ~/gits/brc-tools/scripts/cron/run_hrrr_waypoint_push.sh
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-brc-tools-2026}"
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
