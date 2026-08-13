#!/usr/bin/env bash
# Road-forecast cron wrapper: build the HRRR road forecast and upload it.
#
# Unlike the three run_hrrr_*_push.sh wrappers, this one does NOT pin
# BASINWX_API_URLS. get_road_forecast.py uses load_config_urls(), so it fans out
# to every URL in ~/.config/ubair-website/website_urls on its own. Pin it here
# only if .com is behind .dev on the road-forecast dataType — ops's dataUpload.js
# must list 'road-forecast' or the upload 400s.
#
# Cadence matters: the website rejects the whole file when init_time is more than
# 3 h old (roadWeatherService.js loadHRRRForecast) and caches for 1 h, so run
# hourly. A 3-hourly job that slips by minutes is permanently rejected.
#
# Install on notchpeak1:
#   20 * * * * ~/gits/brc-tools/scripts/cron/run_road_forecast_push.sh
set -eo pipefail

CONDA_ENV="${CONDA_ENV:-brc-tools-2026}"
REPO_DIR="${REPO_DIR:-$HOME/gits/brc-tools}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/road_forecast.log}"

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
  echo "[run_road_forecast_push] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  python -m brc_tools.download.get_road_forecast --upload
} >> "${LOG_FILE}" 2>&1
