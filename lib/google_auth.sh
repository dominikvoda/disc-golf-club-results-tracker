#!/usr/bin/env bash
# Google Service Account JWT authentication for Sheets API v4

# Generate a JWT token from service account JSON and exchange it for an access token.
# Uses openssl for RS256 signing.

_base64url_encode() {
    openssl base64 -e -A | tr '+/' '-_' | tr -d '='
}

google_get_access_token() {
    local sa_json="$1"

    local client_email
    client_email=$(jq -r '.client_email' "$sa_json")
    local private_key_raw
    private_key_raw=$(jq -r '.private_key' "$sa_json")

    local now
    now=$(date +%s)
    local exp=$((now + 3600))

    local header='{"alg":"RS256","typ":"JWT"}'
    local header_b64
    header_b64=$(printf '%s' "$header" | _base64url_encode)

    local claim
    claim=$(cat <<EOF
{"iss":"${client_email}","scope":"https://www.googleapis.com/auth/spreadsheets","aud":"https://oauth2.googleapis.com/token","iat":${now},"exp":${exp}}
EOF
)
    local claim_b64
    claim_b64=$(printf '%s' "$claim" | _base64url_encode)

    local unsigned="${header_b64}.${claim_b64}"

    # Write private key to temp file for openssl
    local key_file
    key_file=$(mktemp)
    printf '%s' "$private_key_raw" > "$key_file"

    local signature
    signature=$(printf '%s' "$unsigned" | openssl dgst -sha256 -sign "$key_file" | _base64url_encode)
    rm -f "$key_file"

    local jwt="${unsigned}.${signature}"

    # Exchange JWT for access token
    local response
    response=$(curl -s -X POST "https://oauth2.googleapis.com/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}")

    local token
    token=$(printf '%s' "$response" | jq -r '.access_token')

    if [[ "$token" == "null" || -z "$token" ]]; then
        echo "ERROR: Failed to get access token" >&2
        printf '%s' "$response" >&2
        return 1
    fi

    printf '%s' "$token"
}
