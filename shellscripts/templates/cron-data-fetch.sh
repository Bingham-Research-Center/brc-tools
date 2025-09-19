#!/bin/bash
# Template cron job for fetching and pushing data
# Copy this to your server and customize

# Set up environment
export DATA_UPLOAD_API_KEY="your_64_char_api_key_here"
export PYTHONPATH="/path/to/brc-tools:$PYTHONPATH"

# Change to project directory
cd /path/to/brc-tools

# Log file
LOG_FILE="/var/log/brc-tools/data-fetch-$(date +%Y%m%d).log"

# Run data fetch and upload
echo "$(date): Starting data fetch..." >> $LOG_FILE

python -m brc_tools.download.get_map_obs >> $LOG_FILE 2>&1

if [ $? -eq 0 ]; then
    echo "$(date): Data fetch completed successfully" >> $LOG_FILE
else
    echo "$(date): Data fetch failed with exit code $?" >> $LOG_FILE
fi