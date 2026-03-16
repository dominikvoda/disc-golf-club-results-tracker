#!/usr/bin/env python3
"""
Disc Golf Club Results Tracker

Syncs club member tournament results from iDiscGolf into a Google Sheet.

Flow:
1. Read settings (club ID, leagues, extra players, last sync) from Settings tab
2. Fetch club members from iDiscGolf club page + extra players from settings
3. Build league -> tournament mapping by scraping league pages
4. Scrape the main tournaments page for all tournaments in the time window
5. For each past tournament, call iDiscGolf API for results
6. Match results against club members, apply Top X filter
7. Write results to the Účast tab
"""

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests as http
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
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
        'base_url': os.environ.get('IDISCGOLF_BASE_URL', 'https://idiscgolf.cz'),
        'api_token': os.environ['IDISCGOLF_API_TOKEN'],
        'date_margin_days': int(os.environ.get('DATE_MARGIN_DAYS', '3')),
    }


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEETS_API = 'https://sheets.googleapis.com/v4/spreadsheets'

REPORTS_SHEET_ID = 236964464

# Colors (RGB 0-1)
GOLD = {'red': 1.0, 'green': 0.84, 'blue': 0.0}
SILVER = {'red': 0.75, 'green': 0.75, 'blue': 0.75}
BRONZE = {'red': 0.8, 'green': 0.5, 'blue': 0.2}
HEADER_BG = {'red': 0.16, 'green': 0.16, 'blue': 0.16}
HEADER_FG = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
LIGHT_GRAY_BG = {'red': 0.95, 'green': 0.95, 'blue': 0.95}
WHITE = {'red': 1.0, 'green': 1.0, 'blue': 1.0}


def get_sheets_credentials(service_account_json: str) -> Credentials:
    creds = Credentials.from_service_account_file(service_account_json, scopes=SCOPES)
    creds.refresh(Request())
    return creds


def sheets_read(creds: Credentials, sheet_id: str, range_: str) -> list[list[str]]:
    url = f'{SHEETS_API}/{sheet_id}/values/{http.utils.quote(range_)}'
    resp = http.get(url, headers={'Authorization': f'Bearer {creds.token}'})
    resp.raise_for_status()
    return resp.json().get('values', [])


def sheets_write(creds: Credentials, sheet_id: str, range_: str, values: list[list]):
    url = f'{SHEETS_API}/{sheet_id}/values/{http.utils.quote(range_)}?valueInputOption=USER_ENTERED'
    body = {'range': range_, 'majorDimension': 'ROWS', 'values': values}
    resp = http.put(url, headers={'Authorization': f'Bearer {creds.token}'}, json=body)
    resp.raise_for_status()
    return resp.json()


def sheets_clear(creds: Credentials, sheet_id: str, range_: str):
    url = f'{SHEETS_API}/{sheet_id}/values/{http.utils.quote(range_)}:clear'
    resp = http.post(url, headers={'Authorization': f'Bearer {creds.token}'}, json={})
    resp.raise_for_status()


def sheets_batch_update(creds: Credentials, sheet_id: str, requests_list: list):
    url = f'{SHEETS_API}/{sheet_id}:batchUpdate'
    resp = http.post(
        url,
        headers={'Authorization': f'Bearer {creds.token}'},
        json={'requests': requests_list},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Reports formatting
# ---------------------------------------------------------------------------

def format_reports(creds: Credentials, sheet_id: str, all_rows: list[list]):
    """Apply full formatting to the Reports tab. Resets everything first."""
    sid = REPORTS_SHEET_ID
    num_rows = len(all_rows) + 1  # +1 for header

    # --- Full reset: clear conditional rules ---
    for i in range(10, -1, -1):
        try:
            sheets_batch_update(creds, sheet_id, [{'deleteConditionalFormatRule': {'sheetId': sid, 'index': i}}])
        except Exception:
            pass

    requests_list = []

    # --- Reset all data cell formatting (backgrounds, borders) ---
    requests_list.append({
        'repeatCell': {
            'range': {'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 0, 'endColumnIndex': 12},
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': WHITE,
                    'textFormat': {'bold': False},
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,textFormat.bold)',
        }
    })
    # Reset borders on all data rows
    requests_list.append({
        'updateBorders': {
            'range': {'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 0, 'endColumnIndex': 12},
            'top': {'style': 'NONE'},
            'bottom': {'style': 'NONE'},
            'left': {'style': 'NONE'},
            'right': {'style': 'NONE'},
            'innerHorizontal': {'style': 'NONE'},
            'innerVertical': {'style': 'NONE'},
        }
    })

    # --- Header row formatting ---
    requests_list.append({
        'repeatCell': {
            'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1, 'startColumnIndex': 0, 'endColumnIndex': 12},
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': HEADER_BG,
                    'textFormat': {'foregroundColor': HEADER_FG, 'bold': True, 'fontSize': 10},
                    'horizontalAlignment': 'CENTER',
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)',
        }
    })

    # --- Freeze header row ---
    requests_list.append({
        'updateSheetProperties': {
            'properties': {'sheetId': sid, 'gridProperties': {'frozenRowCount': 1}},
            'fields': 'gridProperties.frozenRowCount',
        }
    })

    # --- Conditional formatting: gold/silver/bronze on Umístění column (H) ---
    for idx, (value, color, bold) in enumerate([
        (1, GOLD, True),
        (2, SILVER, False),
        (3, BRONZE, False),
    ]):
        fmt = {'backgroundColor': color}
        if bold:
            fmt['textFormat'] = {'bold': True}
        requests_list.append({
            'addConditionalFormatRule': {
                'rule': {
                    'ranges': [{'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 7, 'endColumnIndex': 8}],
                    'booleanRule': {
                        'condition': {
                            'type': 'CUSTOM_FORMULA',
                            'values': [{'userEnteredValue': f'=$H2={value}'}],
                        },
                        'format': fmt,
                    },
                },
                'index': idx,
            }
        })

    # --- Alternating background per tournament group ---
    requests_list.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 0, 'endColumnIndex': 12}],
                'booleanRule': {
                    'condition': {
                        'type': 'CUSTOM_FORMULA',
                        'values': [{'userEnteredValue': '=ISEVEN(COUNTUNIQUE($C$2:$C2))'}],
                    },
                    'format': {'backgroundColor': LIGHT_GRAY_BG},
                },
            },
            'index': 3,
        }
    })

    # --- Auto-resize columns ---
    requests_list.append({
        'autoResizeDimensions': {
            'dimensions': {'sheetId': sid, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 12},
        }
    })

    # --- Bold borders between tournament groups ---
    border_style = {'style': 'SOLID_MEDIUM', 'color': {'red': 0.4, 'green': 0.4, 'blue': 0.4}}
    prev_tid = None
    for i, row in enumerate(all_rows):
        tid = row[2] if len(row) > 2 else ''
        if prev_tid is not None and tid != prev_tid:
            row_idx = i + 1  # +1 for header
            requests_list.append({
                'updateBorders': {
                    'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 0, 'endColumnIndex': 12},
                    'top': border_style,
                }
            })
        prev_tid = tid

    sheets_batch_update(creds, sheet_id, requests_list)


# ---------------------------------------------------------------------------
# Settings parser
# ---------------------------------------------------------------------------

def parse_settings(rows: list[list[str]]) -> dict:
    """
    Parse the unified Settings tab.

    Layout:
      Nastavení
      Klub ID              | 15
      Výchozí Top X        | 3
      Poslední synchronizace | <timestamp>
      (empty)
      Sledované ligy
      #iDG Liga ID | Liga | Top X
      ...
      (empty)
      Extra hráči
      #iDG ID | Jméno
      ...
    """
    settings = {
        'club_id': '',
        'default_top_x': 3,
        'last_sync': '',
        'leagues': {},       # league_id -> (name, top_x)
        'extra_players': {}, # player_id -> name
    }

    section = None
    for row in rows:
        cell0 = row[0].strip() if row else ''

        # Detect section headers
        if cell0 == 'Nastavení':
            section = 'settings'
            continue
        elif cell0 == 'Sledované ligy':
            section = 'leagues'
            continue
        elif cell0 == 'Extra hráči':
            section = 'extra'
            continue
        elif cell0 == '' and (len(row) < 2 or not row[1].strip()):
            continue  # empty separator row

        if section == 'settings':
            val = row[1].strip() if len(row) > 1 else ''
            if cell0 == 'Klub ID':
                settings['club_id'] = val
            elif cell0 == 'Výchozí Top X':
                settings['default_top_x'] = int(val) if val.isdigit() else 3
            elif cell0 == 'Poslední synchronizace':
                settings['last_sync'] = val

        elif section == 'leagues':
            if cell0.startswith('#'):  # skip header row
                continue
            if cell0 and len(row) >= 2:
                top_x = int(row[2]) if len(row) >= 3 and row[2].strip().isdigit() else None
                settings['leagues'][cell0] = (row[1].strip(), top_x)

        elif section == 'extra':
            if cell0.startswith('#'):  # skip header row
                continue
            if cell0 and len(row) >= 2:
                settings['extra_players'][cell0] = row[1].strip()

    return settings


def find_last_sync_row(rows: list[list[str]]) -> int:
    """Find the row number (1-indexed) of the 'Poslední synchronizace' cell."""
    for i, row in enumerate(rows):
        if row and row[0].strip() == 'Poslední synchronizace':
            return i + 1  # 1-indexed for Sheets API
    return -1


# ---------------------------------------------------------------------------
# iDiscGolf
# ---------------------------------------------------------------------------

def fetch_club_members(base_url: str, club_id: str) -> dict[str, str]:
    """Fetch all members from a club page. Returns {player_id: name}."""
    resp = http.get(f'{base_url}/kluby/detail/{club_id}')
    html = resp.text

    members = {}
    for match in re.finditer(
        r"Hraci_lblJmeno_\d+\"><a href='/profil/(\d+)'>([^<]*)", html
    ):
        members[match.group(1)] = match.group(2).strip()

    return members


def scrape_league_tournament_ids(base_url: str, league_id: str) -> set[str]:
    resp = http.get(f'{base_url}/ligy/{league_id}')
    return set(re.findall(r'/turnaje/(\d+)', resp.text))


def scrape_all_tournaments(base_url: str) -> list[dict]:
    resp = http.get(f'{base_url}/turnaje')
    html = resp.text

    match = re.search(r'id="gvTurnaje".*?</table>', html, re.DOTALL)
    if not match:
        return []

    table = match.group()
    tournaments = []

    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 7:
            continue

        date_str = re.sub(r'<[^>]+>', '', cells[0]).strip()
        name = re.sub(r'<[^>]+>', '', cells[4]).strip()

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
    resp = http.get(
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

TAB_UCAST = 'Reports'
TAB_SETTINGS = 'Settings'


def main():
    cfg = get_config()

    log('Authenticating with Google Sheets API...')
    creds = get_sheets_credentials(cfg['service_account_json'])
    sheet_id = cfg['sheet_id']
    log('Authentication successful.')

    # Read and parse settings
    log('Reading settings...')
    settings_rows = sheets_read(creds, sheet_id, f'{TAB_SETTINGS}!A1:C100')
    settings = parse_settings(settings_rows)

    club_id = settings['club_id']
    default_top_x = settings['default_top_x']
    last_sync_str = settings['last_sync']
    leagues = settings['leagues']
    extra_players = settings['extra_players']

    if not club_id:
        log('ERROR: Klub ID not set in Settings tab.')
        sys.exit(1)

    log(f'Club ID: {club_id}, Default Top X: {default_top_x}, Leagues: {len(leagues)}, Extra players: {len(extra_players)}')

    # Calculate time window
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sync_threshold_days = int(os.environ.get('SYNC_THRESHOLD_DAYS', '7'))

    if last_sync_str:
        try:
            last_sync = datetime.fromisoformat(last_sync_str.replace('Z', '+00:00')).replace(tzinfo=None)
            from_date = last_sync - timedelta(days=sync_threshold_days)
        except ValueError:
            from_date = today - timedelta(days=sync_threshold_days)
        log(f'Last sync: {last_sync_str}')
    else:
        from_date = today - timedelta(days=sync_threshold_days)
        log('No previous sync found.')

    margin = timedelta(days=cfg['date_margin_days'])
    from_date_m = from_date - margin
    to_date_m = today + margin

    log(f'Time window: {from_date.date()} to {today.date()} (±{cfg["date_margin_days"]}d margin)')

    # Fetch club members
    log(f'Fetching club members from iDiscGolf (club {club_id})...')
    members = fetch_club_members(cfg['base_url'], club_id)
    log(f'Found {len(members)} club members.')

    # Add extra players
    if extra_players:
        members.update(extra_players)
        log(f'Added {len(extra_players)} extra player(s). Total: {len(members)}')

    # Build league -> tournament mapping
    log('Building league-tournament mapping...')
    tournament_league_map: dict[str, tuple[str, int | None]] = {}
    for league_id, (league_name, top_x) in leagues.items():
        tids = scrape_league_tournament_ids(cfg['base_url'], league_id)
        for tid in tids:
            tournament_league_map[tid] = (league_name, top_x)
        log(f'  {league_name}: {len(tids)} tournaments (Top {top_x})')
        time.sleep(0.2)

    # Scrape main tournaments page
    log('Scraping tournaments listing...')
    all_tournaments = scrape_all_tournaments(cfg['base_url'])
    in_window = [t for t in all_tournaments if from_date_m <= t['date'] <= to_date_m]
    log(f'Found {len(all_tournaments)} total, {len(in_window)} in time window.')

    # Process each tournament
    all_results = []
    all_processed_tournament_ids = set()

    for t in in_window:
        if t['date'] > today:
            continue

        all_processed_tournament_ids.add(t['id'])
        league_info = tournament_league_map.get(t['id'])
        league_name = league_info[0] if league_info else ''
        top_x = league_info[1] if league_info else default_top_x

        label = f'{t["name"]} (ID: {t["id"]}, {t["date"].date()})'
        if league_name:
            label += f' [{league_name}, Top {top_x}]'
        else:
            label += f' [Top {top_x}]'

        log(f'  API: {label}...')

        try:
            api_data = api_tournament_detail(cfg['base_url'], cfg['api_token'], t['id'])
        except Exception as e:
            log(f'    API error: {e}')
            continue

        results = api_data.get('results', [])
        if not results:
            log('    No results (score not finalized).')
            continue

        divisions = compute_placements(results)
        iso_date = t['date'].strftime('%Y-%m-%d')
        week = str(t['date'].isocalendar()[1])
        link = f'{cfg["base_url"]}/turnaje/{t["id"]}'
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
                    'link': link,
                })

        log(f'    {len(results)} results, {matched} club member(s) matched.')
        time.sleep(0.2)

    log(f'New results fetched: {len(all_results)}')

    # Deduplication
    HEADER = [
        '#iDG Hráč ID', 'Hráč', '#iDG Turnaj ID', 'Turnaj',
        'Finalizované skore', 'Liga', 'Divize', 'Umístění',
        'Datum', 'Týden', 'Odkaz', 'Poznámka',
    ]
    COL_PLAYER_ID = 0
    COL_TOURNAMENT_ID = 2

    log(f'Reading existing data from {TAB_UCAST}...')
    existing_rows = sheets_read(creds, sheet_id, f'{TAB_UCAST}!A1:L5000')
    existing_data = existing_rows[1:] if len(existing_rows) > 1 else []
    log(f'Existing rows: {len(existing_data)}')

    existing_map: dict[tuple[str, str], list[str]] = {}
    removed_count = 0
    for row in existing_data:
        if len(row) >= 3:
            if row[COL_TOURNAMENT_ID] in all_processed_tournament_ids:
                removed_count += 1
                continue
            key = (row[COL_PLAYER_ID], row[COL_TOURNAMENT_ID])
            existing_map[key] = row

    if removed_count:
        log(f'Removed {removed_count} old rows for re-processed tournaments.')

    new_count = 0
    updated_count = 0
    for r in all_results:
        key = (r['player_id'], r['tournament_id'])
        row = [
            r['player_id'], r['player_name'], r['tournament_id'],
            r['tournament_name'], r['finalized'], r['league_name'],
            r['division'], r['placement'], r['date'], r['week'],
            r['link'], '',
        ]
        if key in existing_map:
            updated_count += 1
        else:
            new_count += 1
        existing_map[key] = row

    all_rows = sorted(
        existing_map.values(),
        key=lambda r: (r[8] if len(r) > 8 else '', r[2] if len(r) > 2 else '', r[1] if len(r) > 1 else ''),
        reverse=True,
    )
    log(f'After merge: {len(all_rows)} total ({new_count} new, {updated_count} updated)')

    if all_rows:
        rows = [HEADER] + all_rows

        log(f'Clearing {TAB_UCAST}...')
        sheets_clear(creds, sheet_id, f'{TAB_UCAST}!A1:L5000')

        log(f'Writing {len(rows)} rows to {TAB_UCAST}...')
        sheets_write(creds, sheet_id, f'{TAB_UCAST}!A1:L{len(rows)}', rows)
        log('Results written.')

        log('Applying Reports formatting...')
        format_reports(creds, sheet_id, all_rows)
        log('Reports formatted.')
    else:
        log('No results to write.')

    # Update last sync timestamp in Settings tab
    sync_row = find_last_sync_row(settings_rows)
    if sync_row > 0:
        now = datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        sheets_write(creds, sheet_id, f'{TAB_SETTINGS}!B{sync_row}', [[now]])
        log(f'Last sync updated to {now}')

    log(f'Sync complete. {len(all_results)} results written.')


if __name__ == '__main__':
    main()
