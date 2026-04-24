#!/usr/bin/env bash
# Stage A cron wrapper: export HRRR surface layers and upload to basinwx.dev.
#
# Until PR #176 (ubair-website HRRR display) lands on the ops branch, this
# wrapper pins BASINWX_API_URLS to the dev site so .com is not polluted with
# files it cannot render. After ops catches up, unset BASINWX_API_URLS here
# (or delete the line) so load_config_urls() falls back to
# ~/.config/ubair-website/website_urls and fans out to both sites.
#
# Install on notchpeak1:
#   45 0,6,12,18 * * * ~/gits/brc-tools/scripts/cron/run_hrrr_surface_push.sh
set -euo pipefail

export BASINWX_API_URLS="https://basinwx.dev"

CONDA_ENV="${CONDA_ENV:-brc-tools}"
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
