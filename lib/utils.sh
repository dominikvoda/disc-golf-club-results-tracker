#!/usr/bin/env bash
# Common utility functions

LOG_LEVEL="${LOG_LEVEL:-INFO}"

log_info() {
    echo "[INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*"
}

log_warn() {
    echo "[WARN]  $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_debug() {
    if [[ "$LOG_LEVEL" == "DEBUG" ]]; then
        echo "[DEBUG] $(date '+%Y-%m-%d %H:%M:%S') $*"
    fi
}

# Check that required commands are available
check_dependencies() {
    local deps=("curl" "jq" "openssl" "python3")
    local missing=()

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing[*]}"
        log_error "Install them and try again."
        return 1
    fi
}

# Get the last sync timestamp, or a default if none exists
# Usage: get_last_sync <sync_file>
get_last_sync() {
    local sync_file="$1"

    if [[ -f "$sync_file" ]]; then
        cat "$sync_file"
    else
        echo ""
    fi
}

# Save the current time as last sync timestamp
# Usage: save_last_sync <sync_file>
save_last_sync() {
    local sync_file="$1"
    date -u '+%Y-%m-%dT%H:%M:%SZ' > "$sync_file"
}

# Calculate the effective "from" date based on last sync + threshold
# Usage: calculate_from_date <last_sync_timestamp> <threshold_days>
# Returns: YYYY-MM-DD date string
calculate_from_date() {
    local last_sync="$1"
    local threshold_days="$2"

    if [[ -z "$last_sync" ]]; then
        # No previous sync - go back threshold_days from now
        date -v "-${threshold_days}d" '+%Y-%m-%d'
    else
        # Parse last sync and subtract threshold
        local last_sync_epoch
        last_sync_epoch=$(date -j -f '%Y-%m-%dT%H:%M:%SZ' "$last_sync" '+%s' 2>/dev/null)

        if [[ -z "$last_sync_epoch" ]]; then
            # Fallback if parsing fails
            date -v "-${threshold_days}d" '+%Y-%m-%d'
        else
            local adjusted_epoch=$((last_sync_epoch - threshold_days * 86400))
            date -j -f '%s' "$adjusted_epoch" '+%Y-%m-%d'
        fi
    fi
}
