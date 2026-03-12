#!/usr/bin/env bash
# Google Sheets API v4 helpers

SHEETS_API="https://sheets.googleapis.com/v4/spreadsheets"

# Read a range from a sheet tab
# Usage: sheets_read <access_token> <sheet_id> <range>
# Range example: "Members!A1:Z1000"
sheets_read() {
    local token="$1"
    local sheet_id="$2"
    local range="$3"

    local encoded_range
    encoded_range=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$range'))")

    curl -s \
        -H "Authorization: Bearer ${token}" \
        "${SHEETS_API}/${sheet_id}/values/${encoded_range}"
}

# Write values to a range in a sheet tab
# Usage: sheets_write <access_token> <sheet_id> <range> <values_json>
# values_json should be a JSON array of arrays, e.g. [["a","b"],["c","d"]]
sheets_write() {
    local token="$1"
    local sheet_id="$2"
    local range="$3"
    local values_json="$4"

    local encoded_range
    encoded_range=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$range'))")

    local body
    body=$(jq -n --argjson vals "$values_json" '{range: "'"$range"'", majorDimension: "ROWS", values: $vals}')

    curl -s -X PUT \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "$body" \
        "${SHEETS_API}/${sheet_id}/values/${encoded_range}?valueInputOption=USER_ENTERED"
}

# Append rows to a sheet tab
# Usage: sheets_append <access_token> <sheet_id> <range> <values_json>
sheets_append() {
    local token="$1"
    local sheet_id="$2"
    local range="$3"
    local values_json="$4"

    local encoded_range
    encoded_range=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$range'))")

    local body
    body=$(jq -n --argjson vals "$values_json" '{range: "'"$range"'", majorDimension: "ROWS", values: $vals}')

    curl -s -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "$body" \
        "${SHEETS_API}/${sheet_id}/values/${encoded_range}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
}

# Clear a range in a sheet tab
# Usage: sheets_clear <access_token> <sheet_id> <range>
sheets_clear() {
    local token="$1"
    local sheet_id="$2"
    local range="$3"

    local encoded_range
    encoded_range=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$range'))")

    curl -s -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        "${SHEETS_API}/${sheet_id}/values/${encoded_range}:clear"
}

# Get all sheet/tab names in a spreadsheet
# Usage: sheets_get_tabs <access_token> <sheet_id>
sheets_get_tabs() {
    local token="$1"
    local sheet_id="$2"

    curl -s \
        -H "Authorization: Bearer ${token}" \
        "${SHEETS_API}/${sheet_id}?fields=sheets.properties.title" \
        | jq -r '.sheets[].properties.title'
}
