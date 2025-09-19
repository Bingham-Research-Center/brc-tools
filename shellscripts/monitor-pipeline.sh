#!/bin/bash
# Monitor BRC Tools pipeline health and performance
# Usage: ./monitor-pipeline.sh [--continuous] [--alerts]

CONTINUOUS=false
ALERTS=false
LOG_FILE="/var/log/brc-pipeline-monitor.log"

# Parse arguments
for arg in "$@"; do
    case $arg in
        --continuous) CONTINUOUS=true ;;
        --alerts) ALERTS=true ;;
        *) echo "Usage: $0 [--continuous] [--alerts]"; exit 1 ;;
    esac
done

# Function to log with timestamp
log_with_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to check website health
check_website_health() {
    local url="$1"
    local timeout=10

    if response=$(curl -s -w "%{http_code}" -m $timeout "$url/api/data/health" --output /dev/null); then
        if [[ "$response" == "200" ]]; then
            echo "✅ Website healthy (HTTP $response)"
            return 0
        else
            echo "⚠️  Website returned HTTP $response"
            return 1
        fi
    else
        echo "❌ Website unreachable"
        return 2
    fi
}

# Function to check data freshness
check_data_freshness() {
    local data_dir="./data"
    local max_age_hours=2

    if [[ ! -d "$data_dir" ]]; then
        echo "❌ Data directory not found"
        return 1
    fi

    # Find most recent map observation file
    latest_file=$(find "$data_dir" -name "map_obs_*.json" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)

    if [[ -z "$latest_file" ]]; then
        echo "⚠️  No observation files found"
        return 1
    fi

    # Check file age
    file_age_seconds=$(( $(date +%s) - $(stat -c %Y "$latest_file" 2>/dev/null || stat -f %m "$latest_file") ))
    file_age_hours=$(( file_age_seconds / 3600 ))

    if [[ $file_age_hours -le $max_age_hours ]]; then
        echo "✅ Data fresh (${file_age_hours}h old): $(basename "$latest_file")"
        return 0
    else
        echo "⚠️  Data stale (${file_age_hours}h old): $(basename "$latest_file")"
        return 1
    fi
}

# Function to check system resources
check_system_resources() {
    # Check disk space
    disk_usage=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
    if [[ $disk_usage -gt 90 ]]; then
        echo "⚠️  Disk usage high: ${disk_usage}%"
        return 1
    fi

    # Check memory if available
    if command -v free >/dev/null; then
        mem_usage=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100}')
        if [[ $mem_usage -gt 90 ]]; then
            echo "⚠️  Memory usage high: ${mem_usage}%"
            return 1
        fi
    fi

    echo "✅ System resources OK (disk: ${disk_usage}%)"
    return 0
}

# Function to check API configuration
check_api_config() {
    if [[ -z "$DATA_UPLOAD_API_KEY" ]]; then
        echo "❌ DATA_UPLOAD_API_KEY not set"
        return 1
    fi

    if [[ ${#DATA_UPLOAD_API_KEY} -ne 64 ]]; then
        echo "❌ Invalid API key length: ${#DATA_UPLOAD_API_KEY} (expected 64)"
        return 1
    fi

    echo "✅ API configuration valid"
    return 0
}

# Function to send alert
send_alert() {
    local message="$1"
    local severity="$2"

    log_with_timestamp "ALERT [$severity]: $message"

    # Add your alerting mechanism here:
    # - Email: echo "$message" | mail -s "BRC Pipeline Alert" admin@example.com
    # - Slack: curl -X POST -H 'Content-type: application/json' --data '{"text":"'"$message"'"}' YOUR_SLACK_WEBHOOK
    # - SMS: Use your preferred SMS service API

    if [[ "$ALERTS" == "true" ]]; then
        echo "🚨 ALERT: $message"
    fi
}

# Main monitoring function
run_health_check() {
    log_with_timestamp "Starting pipeline health check..."

    local issues=0
    local warnings=0

    # Load environment if available
    if [[ -f ".env" ]]; then
        source .env
    fi

    # Check API configuration
    if ! check_api_config; then
        ((issues++))
        send_alert "API configuration invalid" "ERROR"
    fi

    # Check website connectivity
    if [[ -n "$BRC_SERVER_URL" ]]; then
        if ! check_website_health "$BRC_SERVER_URL"; then
            ((warnings++))
            send_alert "Website health check failed" "WARNING"
        fi
    else
        echo "ℹ️  Website URL not configured"
    fi

    # Check data freshness
    if ! check_data_freshness; then
        ((warnings++))
        send_alert "Data appears stale" "WARNING"
    fi

    # Check system resources
    if ! check_system_resources; then
        ((warnings++))
        send_alert "System resources constrained" "WARNING"
    fi

    # Summary
    log_with_timestamp "Health check complete: $issues errors, $warnings warnings"

    if [[ $issues -gt 0 ]]; then
        return 1
    elif [[ $warnings -gt 0 ]]; then
        return 2
    else
        return 0
    fi
}

# Main execution
if [[ "$CONTINUOUS" == "true" ]]; then
    log_with_timestamp "Starting continuous monitoring (Ctrl+C to stop)..."
    while true; do
        run_health_check
        sleep 300  # Check every 5 minutes
    done
else
    run_health_check
    exit $?
fi