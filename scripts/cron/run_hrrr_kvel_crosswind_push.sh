#!/usr/bin/env bash
# Stage C cron wrapper: export HRRR KVEL cross-wind forecast and upload to BasinWX.
#
# BLOCKED on the KVEL runway redesignation (FAA: 16/34 -> 17/35, ~2022).
# The producer's [160, 340] headings and crosswind_kt_160-style keys are
# stale. Do NOT enable this cron until: (1) the brc-tools heading-rename PR
# is merged and released, (2) the website ships the matching MAJOR
# DATA_MANIFEST bump + aviation.js label fix. Then install on notchpeak1:
#   55 * * * * ~/gits/brc-tools/scripts/cron/run_hrrr_kvel_crosswind_push.sh
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-brc-tools-2026}"
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
