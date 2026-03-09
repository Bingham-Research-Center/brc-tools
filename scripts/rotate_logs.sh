#!/usr/bin/env bash
# Rotate road_forecast.log — keep last 7 days
LOG=~/logs/road_forecast.log
if [ -f "$LOG" ] && [ $(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG") -gt 10485760 ]; then
    mv "$LOG" "$LOG.$(date +%Y%m%d)"
    find ~/logs -name "road_forecast.log.*" -mtime +7 -delete
fi
