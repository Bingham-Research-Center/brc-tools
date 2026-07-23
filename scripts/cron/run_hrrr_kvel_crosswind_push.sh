#!/usr/bin/env bash
# Stage C cron wrapper: export HRRR KVEL cross-wind forecast and upload to basinwx.dev.
#
# BLOCKED on ubair-website consumer: aviation.html is a scaffold with no JSON
# reader. Do NOT enable this cron until the website PR that renders this
# payload has landed on .dev. Once it does, install on notchpeak1 with:
#   55 * * * * ~/gits/brc-tools/scripts/cron/run_hrrr_kvel_crosswind_push.sh
set -euo pipefail

export BASINWX_API_URLS="https://basinwx.dev"

CONDA_ENV="${CONDA_ENV:-brc-tools}"
REPO_DIR="${REPO_DIR:-$HOME/gits/brc-tools}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/hrrr_kvel_crosswind.log}"
AIRPORT="${AIRPORT:-KVEL}"
PRODUCT="${PRODUCT:-subh}"
MAX_FXX="${MAX_FXX:-6}"

mkdir -p "${LOG_DIR}"

# shellcheck disable=SC1090
source "${HOME}/.bashrc"
conda activate "${CONDA_ENV}"

cd "${REPO_DIR}"

{
  echo "[run_hrrr_kvel_crosswind_push] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  python scripts/export_hrrr_kvel_crosswind.py \
    --upload --airport "${AIRPORT}" --product "${PRODUCT}" --max-fxx "${MAX_FXX}"
} >> "${LOG_FILE}" 2>&1
