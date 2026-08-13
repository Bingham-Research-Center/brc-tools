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
set -eo pipefail

CONDA_ENV="${CONDA_ENV:-brc-tools-2026}"
REPO_DIR="${REPO_DIR:-$HOME/gits/brc-tools}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/hrrr_surface.log}"

mkdir -p "${LOG_DIR}"

# Bootstrap the cron environment. Do NOT source ~/.bashrc here: it bails
# in non-interactive shells, and /etc/bashrc trips `set -u` (unbound
# BASHRCSOURCED). Mirror the proven obs-cron line instead: the
# cron-specific env file (exports DATA_UPLOAD_API_KEY) plus the conda
# hook, with -u deferred until the sourcing is done.
# shellcheck disable=SC1090,SC1091
source "${HOME}/.bashrc_basinwx"
source "${HOME}/software/pkg/miniforge3/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"
set -u

cd "${REPO_DIR}"

{
  echo "[run_hrrr_surface_push] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  python scripts/export_hrrr_surface_layers.py --upload
} >> "${LOG_FILE}" 2>&1
