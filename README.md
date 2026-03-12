# Disc Golf Club Results Tracker

Bash script that syncs club member tournament results from [iDiscGolf](https://www.idiscgolf.eu) into a Google Sheet.

## How it works

1. Reads club members from a Google Sheet tab ("Members")
2. Looks up each member's recent tournaments on iDiscGolf
3. Writes results to a separate tab in the same sheet ("Results")
4. Tracks last sync time to only fetch new data (with configurable overlap threshold)

## Prerequisites

- `bash` 4+
- `curl`
- `jq`
- `openssl`
- `python3`
- A Google Cloud service account with Sheets API enabled
- The Google Sheet must be shared with the service account email

## Setup

1. Clone the repo:
   ```bash
   git clone git@github.com:dominikvoda/disc-golf-club-results-tracker.git
   cd disc-golf-club-results-tracker
   ```

2. Copy and configure the environment file:
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

3. Place your Google service account JSON file somewhere and set the path in `.env`.

4. Share your Google Sheet with the service account email (found in the JSON file as `client_email`).

## Usage

```bash
./sync.sh
```

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account JSON file | (required) |
| `GOOGLE_SHEET_ID` | Google Sheet ID (from the URL) | (required) |
| `MEMBERS_TAB` | Tab name containing club members | `Members` |
| `RESULTS_TAB` | Tab name for tournament results | `Results` |
| `SYNC_THRESHOLD_DAYS` | Days to look back beyond last sync | `7` |
| `IDISCGOLF_BASE_URL` | iDiscGolf base URL | `https://www.idiscgolf.eu` |

## Project Structure

```
.
├── sync.sh              # Main entry point
├── .env.example         # Configuration template
├── lib/
│   ├── google_auth.sh   # JWT auth for Google service account
│   ├── google_sheets.sh # Google Sheets API v4 helpers
│   ├── idiscgolf.sh     # iDiscGolf scraping (TODO)
│   └── utils.sh         # Logging, date math, dependencies
└── README.md
```
