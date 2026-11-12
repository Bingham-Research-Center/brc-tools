#!/usr/bin/env bash
# Stage C cron wrapper: export HRRR KVEL cross-wind forecast and upload to BasinWX.
#
# UNBLOCKED and installed 2026-08-27. The KVEL runway redesignation
# (FAA: 16/34 -> 17/35) has shipped on both sides: lookups.toml carries
# runway_headings_deg = [179, 359] (#59), the website pins crosswind_kt_179 /
# _359 in DATA_MANIFEST 2.0.0, and aviation.js floors heading/10 to label
# Rwy17/Rwy35. Both basinwx.com and basinwx.dev serve manifest 2.0.0, so the
# contract matches on each. Installed on notchpeak1 as:
#   55 * * * * ~/gits/brc-tools/scripts/cron/run_hrrr_kvel_crosswind_push.sh
set -eo pipefail

CONDA_ENV="${CONDA_ENV:-brc-tools-2026}"
REPO_DIR="${REPO_DIR:-$HOME/gits/brc-tools}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/hrrr_kvel_crosswind.log}"
AIRPORT="${AIRPORT:-KVEL}"
PRODUCT="${PRODUCT:-subh}"
MAX_FXX="${MAX_FXX:-6}"

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

# Cron mails only when a job writes to stdout. Redirecting the whole block into
# the log file made every failure silent -- which is how four months of .dev
# 413s went unnoticed. Capture this run, append it to the log either way, and
# re-emit a summary on stdout when something went wrong so MAILTO fires.
RUN_LOG="$(mktemp)"
trap 'rm -f "${RUN_LOG}"' EXIT

rc=0
{
  echo "[run_hrrr_kvel_crosswind_push] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  python scripts/export_hrrr_kvel_crosswind.py \
    --upload --airport "${AIRPORT}" --product "${PRODUCT}" --max-fxx "${MAX_FXX}"
} > "${RUN_LOG}" 2>&1 || rc=$?

cat "${RUN_LOG}" >> "${LOG_FILE}"

if [ "${rc}" -ne 0 ]; then
  echo "[run_hrrr_kvel_crosswind_push] FAILED (exit ${rc}) -- full log: ${LOG_FILE}"
  tail -n 40 "${RUN_LOG}"
  exit "${rc}"
fi

if grep -q 'ALERT_MIRROR_INCOMPLETE' "${RUN_LOG}"; then
  echo "[run_hrrr_kvel_crosswind_push] mirror upload incomplete; primary OK -- full log: ${LOG_FILE}"
  grep 'ALERT_MIRROR_INCOMPLETE' "${RUN_LOG}"
fi
