# Disc Golf Club Results Tracker

Python script that syncs club member tournament results from [iDiscGolf](https://idiscgolf.cz) into a Google Sheet.

## How it works

1. Reads tracked leagues from the sheet and scrapes their tournament pages
2. For each tournament in the time window, calls the iDiscGolf API for results
3. Matches results against club members, computes placement per division
4. Writes results to the "Účast" tab with finalization status, week number, etc.
5. Tracks last sync time to only fetch new data (with configurable threshold)

## Prerequisites

- Python 3.10+
- A Google Cloud service account with Sheets API enabled
- The Google Sheet must be shared with the service account email
- An iDiscGolf API token

## Setup

```bash
git clone git@github.com:dominikvoda/disc-golf-club-results-tracker.git
cd disc-golf-club-results-tracker

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your values
```

## Usage

```bash
./sync.py
# or
python3 sync.py
```

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account JSON file | (required) |
| `GOOGLE_SHEET_ID` | Google Sheet ID (from the URL) | (required) |
| `IDISCGOLF_API_TOKEN` | iDiscGolf API access token | (required) |
| `SYNC_THRESHOLD_DAYS` | Days to look back beyond last sync | `7` |
| `DATE_MARGIN_DAYS` | Extra days margin on window edges | `3` |
| `IDISCGOLF_BASE_URL` | iDiscGolf base URL | `https://idiscgolf.cz` |

## Sheet structure

| Tab | Purpose |
|---|---|
| **Sledovaní hráči** | Club members: `#iDG ID`, `Jméno` |
| **Sledované ligy** | Tracked leagues: `#iDG Liga ID`, `Liga` |
| **Účast** | Results output (auto-populated by sync) |
| **Nastavení** | Last sync timestamp |
