#!/usr/bin/env bash
#
# disc-golf-club-results-tracker
#
# Main sync script: reads club members from Google Sheet,
# looks up their tournament results on iDiscGolf,
# and writes results back to the sheet.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_FILE="${SCRIPT_DIR}/.last_sync"

# Load libraries
source "${SCRIPT_DIR}/lib/utils.sh"
source "${SCRIPT_DIR}/lib/google_auth.sh"
source "${SCRIPT_DIR}/lib/google_sheets.sh"
source "${SCRIPT_DIR}/lib/idiscgolf.sh"

# Load config
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env"
else
    log_error "No .env file found. Copy .env.example to .env and configure it."
    exit 1
fi

# Validate required config
: "${GOOGLE_SERVICE_ACCOUNT_JSON:?Set GOOGLE_SERVICE_ACCOUNT_JSON in .env}"
: "${GOOGLE_SHEET_ID:?Set GOOGLE_SHEET_ID in .env}"
: "${MEMBERS_TAB:=Members}"
: "${RESULTS_TAB:=Results}"
: "${SYNC_THRESHOLD_DAYS:=7}"
: "${IDISCGOLF_BASE_URL:=https://www.idiscgolf.eu}"

main() {
    log_info "Starting sync..."

    # Check dependencies
    check_dependencies || exit 1

    # Verify service account file exists
    if [[ ! -f "$GOOGLE_SERVICE_ACCOUNT_JSON" ]]; then
        log_error "Service account JSON not found: ${GOOGLE_SERVICE_ACCOUNT_JSON}"
        exit 1
    fi

    # Authenticate with Google
    log_info "Authenticating with Google Sheets API..."
    local token
    token=$(google_get_access_token "$GOOGLE_SERVICE_ACCOUNT_JSON")
    log_info "Authentication successful."

    # Calculate date range
    local last_sync
    last_sync=$(get_last_sync "$SYNC_FILE")
    local from_date
    from_date=$(calculate_from_date "$last_sync" "$SYNC_THRESHOLD_DAYS")
    local to_date
    to_date=$(date '+%Y-%m-%d')

    if [[ -n "$last_sync" ]]; then
        log_info "Last sync: ${last_sync}"
    else
        log_info "No previous sync found."
    fi
    log_info "Looking up tournaments from ${from_date} to ${to_date}"

    # Read members from sheet
    log_info "Reading members from '${MEMBERS_TAB}' tab..."
    local members_data
    members_data=$(sheets_read "$token" "$GOOGLE_SHEET_ID" "${MEMBERS_TAB}!A1:Z1000")

    local row_count
    row_count=$(printf '%s' "$members_data" | jq '.values | length')
    log_info "Found ${row_count} rows (including header)."

    if [[ "$row_count" -le 1 ]]; then
        log_warn "No member data found (only header or empty)."
        exit 0
    fi

    # TODO: Parse members and look up their tournaments
    # This will be implemented once we know:
    # 1. The exact column structure of the Members tab
    # 2. The iDiscGolf URL/API structure for player lookups
    #
    # The flow will be:
    # for each member:
    #   1. Extract player identifier (name, iDiscGolf ID, etc.)
    #   2. Call idiscgolf_get_player_results
    #   3. Collect results
    # Then write all results to the Results tab

    log_info "Members data preview:"
    printf '%s' "$members_data" | jq '.values[0:3]'

    log_warn "Tournament lookup not yet implemented - waiting for iDiscGolf analysis."

    # Save sync timestamp
    # save_last_sync "$SYNC_FILE"
    # log_info "Sync timestamp saved."

    log_info "Done."
}

main "$@"
