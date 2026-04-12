#!/usr/bin/env bash
set -euo pipefail

INIT_TIME="${1:-}"
PYTHON_BIN="${PYTHON_BIN:-python}"
DATA_DIR="${DATA_DIR:-./data/road_forecast_smoke}"
LOG_DIR="${LOG_DIR:-./data/logs}"
LOG_FILE="${LOG_DIR}/road_forecast_smoke.log"

mkdir -p "${DATA_DIR}" "${LOG_DIR}"

CMD=(
  "${PYTHON_BIN}"
  -m
  brc_tools.download.get_road_forecast
  --dry-run
  --data-dir
  "${DATA_DIR}"
)

if [[ -n "${INIT_TIME}" ]]; then
  CMD+=(--init-time "${INIT_TIME}")
fi

echo "[run_road_forecast_smoke] $(date -u '+%Y-%m-%d %H:%M:%S UTC')" | tee -a "${LOG_FILE}"
"${CMD[@]}" 2>&1 | tee -a "${LOG_FILE}"
