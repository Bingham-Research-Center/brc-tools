#!/usr/bin/env bash
# Run HRRR road forecast pipeline under conda env
# Crontab: 50 * * * * ~/gits/brc-tools/scripts/run_road_forecast.sh
set -euo pipefail

source ~/.bashrc
conda activate brc-tools
cd ~/gits/brc-tools

LOG_DIR=~/logs
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/road_forecast.log"

echo "=== $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" >> "$LOG"
python -m brc_tools.download.get_road_forecast >> "$LOG" 2>&1
EXIT_CODE=$?
echo "Exit code: $EXIT_CODE" >> "$LOG"
echo "" >> "$LOG"
