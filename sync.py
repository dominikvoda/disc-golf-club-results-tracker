#!/usr/bin/env python3
"""
Disc Golf Club Results Tracker

Syncs club member tournament results from iDiscGolf into a Google Sheet.

Flow:
1. Read tracked leagues, members, and last sync date from the sheet
2. Scrape each league page for tournaments within the time window
3. For each past tournament, call iDiscGolf API for results
4. Match results against club members, compute placements
5. Write results to the sheet
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_env(path: Path):
    """Load .env file into os.environ (simple key=value parser)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def get_config():
    script_dir = Path(__file__).resolve().parent
    load_env(script_dir / '.env')

    sa_path = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    if not os.path.isabs(sa_path):
        sa_path = str(script_dir / sa_path)

    return {
        'service_account_json': sa_path,
        'sheet_id': os.environ['GOOGLE_SHEET_ID'],
        'sync_threshold_days': int(os.environ.get('SYNC_THRESHOLD_DAYS', '7')),
        'base_url': os.environ.get('IDISCGOLF_BASE_URL', 'https://idiscgolf.cz'),
        'api_token': os.environ['IDISCGOLF_API_TOKEN'],
        'date_margin_days': int(os.environ.get('DATE_MARGIN_DAYS', '3')),
    }


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEETS_API = 'https://sheets.googleapis.com/v4/spreadsheets'


def get_sheets_credentials(service_account_json: str) -> Credentials:
    creds = Credentials.from_service_account_file(service_account_json, scopes=SCOPES)
    creds.refresh(Request())
    return creds


def sheets_read(creds: Credentials, sheet_id: str, range_: str) -> list[list[str]]:
    url = f'{SHEETS_API}/{sheet_id}/values/{requests.utils.quote(range_)}'
    resp = requests.get(url, headers={'Authorization': f'Bearer {creds.token}'})
    resp.raise_for_status()
    return resp.json().get('values', [])


def sheets_write(creds: Credentials, sheet_id: str, range_: str, values: list[list]):
    url = f'{SHEETS_API}/{sheet_id}/values/{requests.utils.quote(range_)}?valueInputOption=USER_ENTERED'
    body = {'range': range_, 'majorDimension': 'ROWS', 'values': values}
    resp = requests.put(url, headers={'Authorization': f'Bearer {creds.token}'}, json=body)
    resp.raise_for_status()
    return resp.json()


def sheets_clear(creds: Credentials, sheet_id: str, range_: str):
    url = f'{SHEETS_API}/{sheet_id}/values/{requests.utils.quote(range_)}:clear'
    resp = requests.post(url, headers={'Authorization': f'Bearer {creds.token}'}, json={})
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# iDiscGolf
# ---------------------------------------------------------------------------

def scrape_league_tournaments(base_url: str, league_id: str) -> list[dict]:
    """Scrape a league page for tournaments with dates."""
    resp = requests.get(f'{base_url}/ligy/{league_id}')
    html = resp.text

    match = re.search(r'id="gvTournaments".*?</table>', html, re.DOTALL)
    if not match:
        return []

    table = match.group()
    tournaments = []

    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 7:
            continue

        date_str = re.sub(r'<[^>]+>', '', cells[0]).strip()
        name = re.sub(r'<[^>]+>', '', cells[3]).strip()

        t_match = re.search(r'/turnaje/(\d+)', row)
        if not t_match:
            continue

        try:
            dt = datetime.strptime(date_str, '%d.%m.%Y')
        except ValueError:
            continue

        tournaments.append({
            'id': t_match.group(1),
            'date': dt,
            'name': name,
        })

    return tournaments


def api_tournament_detail(base_url: str, api_token: str, tournament_id: str) -> dict:
    """Fetch tournament details from the iDiscGolf API."""
    resp = requests.get(
        f'{base_url}/api/v1/tournaments/detail',
        params={'tournamentId': tournament_id},
        headers={'X-Access-Token': api_token},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def compute_placements(api_results: list[dict]) -> dict[str, list[dict]]:
    """Group results by division, sum scores, compute rankings."""
    divisions: dict[str, list[dict]] = {}

    for r in api_results:
        pid = str(r['player_id'])
        div = r.get('division', '?')
        total = sum(rs['score'] for rs in r.get('round_scores', []))
        divisions.setdefault(div, []).append({'player_id': pid, 'total': total})

    for div, entries in divisions.items():
        entries.sort(key=lambda x: x['total'])
        for rank, entry in enumerate(entries, 1):
            entry['rank'] = rank
            entry['total_players'] = len(entries)

    return divisions


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TAB_UCAST = 'Účast'
TAB_HRACI = 'Sledovaní hráči'
TAB_LIGY = 'Sledované ligy'
TAB_NASTAVENI = 'Nastavení'


def main():
    cfg = get_config()

    log('Authenticating with Google Sheets API...')
    creds = get_sheets_credentials(cfg['service_account_json'])
    sheet_id = cfg['sheet_id']
    log('Authentication successful.')

    # Read last sync
    settings = sheets_read(creds, sheet_id, f'{TAB_NASTAVENI}!A1:A2')
    last_sync_str = settings[1][0] if len(settings) > 1 and settings[1] else ''

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    to_date = today

    if last_sync_str:
        try:
            last_sync = datetime.fromisoformat(last_sync_str.replace('Z', '+00:00')).replace(tzinfo=None)
            from_date = last_sync - timedelta(days=cfg['sync_threshold_days'])
        except ValueError:
            from_date = today - timedelta(days=cfg['sync_threshold_days'])
        log(f'Last sync: {last_sync_str}')
    else:
        from_date = today - timedelta(days=cfg['sync_threshold_days'])
        log('No previous sync found.')

    margin = timedelta(days=cfg['date_margin_days'])
    from_date_m = from_date - margin
    to_date_m = to_date + margin

    log(f'Looking up tournaments from {from_date.date()} to {to_date.date()} (±{cfg["date_margin_days"]}d margin)')

    # Read leagues
    log('Reading tracked leagues...')
    ligy_rows = sheets_read(creds, sheet_id, f'{TAB_LIGY}!A1:C100')
    # leagues: {id: (name, top_x)}
    leagues = {}
    for row in ligy_rows[1:]:
        if len(row) >= 2:
            top_x = int(row[2]) if len(row) >= 3 and row[2].isdigit() else None
            leagues[row[0]] = (row[1], top_x)
    log(f'Found {len(leagues)} tracked leagues.')

    # Read members
    log('Reading members...')
    members_rows = sheets_read(creds, sheet_id, f'{TAB_HRACI}!A1:B1000')
    members = {row[0]: row[1] for row in members_rows[1:] if len(row) >= 2}
    log(f'Found {len(members)} members.')

    # Process each league
    all_results = []

    for league_id, (league_name, top_x) in leagues.items():
        log(f'League {league_id}: {league_name} (Top {top_x})' if top_x else f'League {league_id}: {league_name}')

        tournaments = scrape_league_tournaments(cfg['base_url'], league_id)
        in_window = [t for t in tournaments if from_date_m <= t['date'] <= to_date_m]
        log(f'  {len(in_window)} tournaments in time window.')

        for t in in_window:
            if t['date'] > today:
                log(f'  Skipping future: {t["name"]} ({t["date"].date()})')
                continue

            log(f'  API: {t["name"]} (ID: {t["id"]}, {t["date"].date()})...')

            try:
                api_data = api_tournament_detail(cfg['base_url'], cfg['api_token'], t['id'])
            except Exception as e:
                log(f'    API error: {e}')
                continue

            results = api_data.get('results', [])
            if not results:
                log('    No results (score not finalized).')
                # TODO: lookup from another source
                continue

            divisions = compute_placements(results)
            iso_date = t['date'].strftime('%Y-%m-%d')
            week = str(t['date'].isocalendar()[1])
            matched = 0

            for div, entries in divisions.items():
                for entry in entries:
                    if entry['player_id'] not in members:
                        continue
                    if top_x is not None and entry['rank'] > top_x:
                        continue
                    matched += 1
                    all_results.append({
                        'player_id': entry['player_id'],
                        'player_name': members[entry['player_id']],
                        'tournament_id': t['id'],
                        'tournament_name': t['name'],
                        'finalized': 'Ano',
                        'league_name': league_name,
                        'division': div,
                        'placement': str(entry['rank']),
                        'date': iso_date,
                        'week': week,
                    })

            log(f'    {len(results)} results, {matched} club member(s) matched.')
            time.sleep(0.2)

    log(f'New results fetched: {len(all_results)}')

    # Deduplication: merge new results with existing sheet data.
    # Key: (player_id, tournament_id) — a player has one result per tournament.
    # New data wins over old (placement may have been updated).

    HEADER = [
        '#iDG Hráč ID', 'Hráč', '#iDG Turnaj ID', 'Turnaj',
        'Finalizované skore', 'Liga', 'Divize', 'Umístění',
        'Datum', 'Týden', 'Poznámka',
    ]
    COL_PLAYER_ID = 0
    COL_TOURNAMENT_ID = 2

    # Read existing rows from sheet
    log(f'Reading existing data from {TAB_UCAST}...')
    existing_rows = sheets_read(creds, sheet_id, f'{TAB_UCAST}!A1:K5000')
    existing_data = existing_rows[1:] if len(existing_rows) > 1 else []  # skip header
    log(f'Existing rows: {len(existing_data)}')

    # Collect tournament IDs that were processed in this sync run.
    # For these tournaments, we trust the new results completely
    # (old rows for these tournaments are replaced, not merged).
    processed_tournament_ids = {r['tournament_id'] for r in all_results}

    # Build map of existing rows, excluding rows from re-processed tournaments
    existing_map: dict[tuple[str, str], list[str]] = {}
    removed_count = 0
    for row in existing_data:
        if len(row) >= 3:
            key = (row[COL_PLAYER_ID], row[COL_TOURNAMENT_ID])
            if row[COL_TOURNAMENT_ID] in processed_tournament_ids:
                removed_count += 1
                continue
            existing_map[key] = row

    if removed_count:
        log(f'Removed {removed_count} old rows for re-processed tournaments.')

    # Add new results
    new_count = 0
    updated_count = 0
    for r in all_results:
        key = (r['player_id'], r['tournament_id'])
        row = [
            r['player_id'], r['player_name'], r['tournament_id'],
            r['tournament_name'], r['finalized'], r['league_name'],
            r['division'], r['placement'], r['date'], r['week'], '',
        ]
        if key in existing_map:
            updated_count += 1
        else:
            new_count += 1
        existing_map[key] = row

    # Sort all rows by date desc, then player name
    all_rows = sorted(existing_map.values(), key=lambda r: (r[8] if len(r) > 8 else '', r[1] if len(r) > 1 else ''), reverse=True)
    log(f'After merge: {len(all_rows)} total ({new_count} new, {updated_count} updated)')

    if all_rows:
        rows = [HEADER] + all_rows

        log(f'Clearing {TAB_UCAST}...')
        sheets_clear(creds, sheet_id, f'{TAB_UCAST}!A1:K5000')

        log(f'Writing {len(rows)} rows to {TAB_UCAST}...')
        sheets_write(creds, sheet_id, f'{TAB_UCAST}!A1:K{len(rows)}', rows)
        log('Results written.')
    else:
        log('No results to write.')

    # Update sync timestamp
    now = datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    sheets_write(creds, sheet_id, f'{TAB_NASTAVENI}!A1:A2', [['Naposledy synchronizováno'], [now]])
    log(f'Sync complete. {len(all_results)} results written.')


if __name__ == '__main__':
    main()
