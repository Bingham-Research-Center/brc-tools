#!/usr/bin/env bash
# Stage A cron wrapper: export HRRR surface layers and upload to BasinWX.
#
# No BASINWX_API_URLS pin: website v1.5.0 (2026-08-13) promoted the HRRR
# display (PR #176) to ops, so load_config_urls() falls back to
# ~/.config/ubair-website/website_urls and fans out (.com primary,
# .dev best-effort mirror).
#
# Install on notchpeak1:
#   45 0,6,12,18 * * * ~/gits/brc-tools/scripts/cron/run_hrrr_surface_push.sh
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-brc-tools-2026}"
REPO_DIR="${REPO_DIR:-$HOME/gits/brc-tools}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/hrrr_surface.log}"

mkdir -p "${LOG_DIR}"

# Ensure DATA_UPLOAD_API_KEY is exported by the user's shell profile.
# shellcheck disable=SC1090
source "${HOME}/.bashrc"
conda activate "${CONDA_ENV}"

cd "${REPO_DIR}"

{
  echo "[run_hrrr_surface_push] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  python scripts/export_hrrr_surface_layers.py --upload
} >> "${LOG_FILE}" 2>&1
