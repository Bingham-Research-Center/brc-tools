#!/usr/bin/env bash
# Run UDOT camera image scraper (one-shot, for cron/Slurm)
# Crontab: */15 * * * * ~/gits/brc-tools/scripts/run_scrape_images.sh
set -euo pipefail

source ~/.bashrc
conda activate brc-tools
cd ~/gits/brc-tools

LOG_DIR=~/logs
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/scrape_images.log"

# Allow override via env var (e.g., CHPC scratch space)
DATA_DIR="${BRC_IMAGE_DIR:-data/images}"

echo "=== $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" >> "$LOG"
python -m brc_tools.download.scrape_images --source udot --data-dir "$DATA_DIR" >> "$LOG" 2>&1
EXIT_CODE=$?
echo "Exit code: $EXIT_CODE" >> "$LOG"
echo "" >> "$LOG"
