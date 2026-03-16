#!/usr/bin/env python3
"""
Apply formatting to the Google Sheet tabs:
- Reports: conditional gold/silver/bronze colors for Top 3, styled header
- Settings: section headers, borders, readable layout
"""

import os
from pathlib import Path

import requests as http
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEETS_API = 'https://sheets.googleapis.com/v4/spreadsheets'

REPORTS_SHEET_ID = 236964464
SETTINGS_SHEET_ID = 176313296

# Colors (RGB 0-1)
GOLD = {'red': 1.0, 'green': 0.84, 'blue': 0.0}
SILVER = {'red': 0.75, 'green': 0.75, 'blue': 0.75}
BRONZE = {'red': 0.8, 'green': 0.5, 'blue': 0.2}
HEADER_BG = {'red': 0.16, 'green': 0.16, 'blue': 0.16}
HEADER_FG = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
SECTION_BG = {'red': 0.26, 'green': 0.52, 'blue': 0.96}
SECTION_FG = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
SUBHEADER_BG = {'red': 0.9, 'green': 0.93, 'blue': 0.98}
LIGHT_GRAY_BG = {'red': 0.95, 'green': 0.95, 'blue': 0.95}
WHITE = {'red': 1.0, 'green': 1.0, 'blue': 1.0}


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


def get_creds():
    script_dir = Path(__file__).resolve().parent
    load_env(script_dir / '.env')
    sa_path = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    if not os.path.isabs(sa_path):
        sa_path = str(script_dir / sa_path)
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    creds.refresh(Request())
    return creds, os.environ['GOOGLE_SHEET_ID']


def batch_update(creds, sheet_id, requests_list):
    url = f'{SHEETS_API}/{sheet_id}:batchUpdate'
    resp = http.post(
        url,
        headers={'Authorization': f'Bearer {creds.token}'},
        json={'requests': requests_list},
    )
    resp.raise_for_status()
    return resp.json()


def bold_format():
    return {'bold': True}


def format_reports(creds, sheet_id):
    """Format the Reports tab with conditional colors and styled header."""
    sid = REPORTS_SHEET_ID
    umisteni_col = 7  # Column H (0-indexed)

    # Clear all existing conditional format rules
    for i in range(10, -1, -1):
        try:
            batch_update(creds, sheet_id, [{'deleteConditionalFormatRule': {'sheetId': sid, 'index': i}}])
        except Exception:
            pass

    requests_list = []

    # --- Header row formatting ---
    requests_list.append({
        'repeatCell': {
            'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1, 'startColumnIndex': 0, 'endColumnIndex': 12},
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': HEADER_BG,
                    'textFormat': {'foregroundColor': HEADER_FG, **bold_format(), 'fontSize': 10},
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

    # --- Conditional formatting for Umístění column (rows 2+) ---
    # Gold for 1st place
    requests_list.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 7, 'endColumnIndex': 8}],
                'booleanRule': {
                    'condition': {
                        'type': 'CUSTOM_FORMULA',
                        'values': [{'userEnteredValue': '=$H2=1'}],
                    },
                    'format': {'backgroundColor': GOLD, 'textFormat': bold_format()},
                },
            },
            'index': 0,
        }
    })

    # Silver for 2nd place
    requests_list.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 7, 'endColumnIndex': 8}],
                'booleanRule': {
                    'condition': {
                        'type': 'CUSTOM_FORMULA',
                        'values': [{'userEnteredValue': '=$H2=2'}],
                    },
                    'format': {'backgroundColor': SILVER},
                },
            },
            'index': 1,
        }
    })

    # Bronze for 3rd place
    requests_list.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': 7, 'endColumnIndex': 8}],
                'booleanRule': {
                    'condition': {
                        'type': 'CUSTOM_FORMULA',
                        'values': [{'userEnteredValue': '=$H2=3'}],
                    },
                    'format': {'backgroundColor': BRONZE},
                },
            },
            'index': 2,
        }
    })

    # --- Alternating background per tournament group ---
    # Uses COUNTUNIQUE on Tournament ID column (C) to alternate colors
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
    # Read report data to find where tournament ID (column C) changes
    url = f'{SHEETS_API}/{sheet_id}/values/Reports!C2:C5000'
    resp = http.get(url, headers={'Authorization': f'Bearer {creds.token}'})
    tournament_ids = [row[0] if row else '' for row in resp.json().get('values', [])]

    border_style = {'style': 'SOLID_MEDIUM', 'color': {'red': 0.4, 'green': 0.4, 'blue': 0.4}}
    for i in range(1, len(tournament_ids)):
        if tournament_ids[i] != tournament_ids[i - 1]:
            # Add a top border on the row where tournament changes (i+1 because data starts at row 2)
            row_idx = i + 1
            requests_list.append({
                'updateBorders': {
                    'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 0, 'endColumnIndex': 12},
                    'top': border_style,
                }
            })

    batch_update(creds, sheet_id, requests_list)
    print('Reports tab formatted.')


def format_settings(creds, sheet_id):
    """Format the Settings tab with styled sections."""
    sid = SETTINGS_SHEET_ID

    # First, read the settings to find section rows
    url = f'{SHEETS_API}/{sheet_id}/values/Settings!A1:C50'
    resp = http.get(url, headers={'Authorization': f'Bearer {creds.token}'})
    rows = resp.json().get('values', [])

    ALL_SECTIONS = ('Nápověda', 'Nastavení', 'Sledované ligy', 'Extra hráči')

    section_rows = []
    subheader_rows = []
    help_rows = []
    kv_rows = []

    current_section = None
    for i, row in enumerate(rows):
        cell0 = row[0].strip() if row else ''
        if cell0 in ALL_SECTIONS:
            section_rows.append(i)
            current_section = cell0
        elif cell0.startswith('#iDG'):
            subheader_rows.append(i)
        elif cell0 and current_section == 'Nápověda':
            help_rows.append(i)
        elif cell0 and current_section in ('Nastavení',):
            kv_rows.append(i)

    requests_list = []

    # --- Full reset: clear all formatting on Settings data area ---
    requests_list.append({
        'repeatCell': {
            'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 50, 'startColumnIndex': 0, 'endColumnIndex': 3},
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': WHITE,
                    'textFormat': {'bold': False, 'italic': False, 'fontSize': 10,
                                   'foregroundColor': {'red': 0, 'green': 0, 'blue': 0}},
                    'horizontalAlignment': 'LEFT',
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)',
        }
    })
    # Unmerge all cells
    requests_list.append({
        'unmergeCells': {
            'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 50, 'startColumnIndex': 0, 'endColumnIndex': 3},
        }
    })
    # Reset borders
    requests_list.append({
        'updateBorders': {
            'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 50, 'startColumnIndex': 0, 'endColumnIndex': 3},
            'top': {'style': 'NONE'}, 'bottom': {'style': 'NONE'},
            'left': {'style': 'NONE'}, 'right': {'style': 'NONE'},
            'innerHorizontal': {'style': 'NONE'}, 'innerVertical': {'style': 'NONE'},
        }
    })

    # --- Section headers (blue background, white bold text, merged across 3 cols) ---
    for row_idx in section_rows:
        requests_list.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 0, 'endColumnIndex': 3},
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': SECTION_BG,
                        'textFormat': {'foregroundColor': SECTION_FG, **bold_format(), 'fontSize': 11},
                        'horizontalAlignment': 'LEFT',
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)',
            }
        })

    # --- Help rows (Nápověda section): italic key, normal description) ---
    for row_idx in help_rows:
        requests_list.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 0, 'endColumnIndex': 1},
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {'bold': True, 'fontSize': 9},
                    }
                },
                'fields': 'userEnteredFormat(textFormat)',
            }
        })
        requests_list.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 1, 'endColumnIndex': 3},
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {'italic': True, 'fontSize': 9,
                                       'foregroundColor': {'red': 0.4, 'green': 0.4, 'blue': 0.4}},
                    }
                },
                'fields': 'userEnteredFormat(textFormat)',
            }
        })

    # --- Sub-headers (#iDG Liga ID, #iDG ID rows) ---
    for row_idx in subheader_rows:
        requests_list.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 0, 'endColumnIndex': 3},
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': SUBHEADER_BG,
                        'textFormat': {**bold_format(), 'fontSize': 10},
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,textFormat)',
            }
        })

    # --- Key-value settings rows: bold key in col A, light gray background ---
    for row_idx in kv_rows:
        requests_list.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 0, 'endColumnIndex': 1},
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {**bold_format()},
                        'backgroundColor': LIGHT_GRAY_BG,
                    }
                },
                'fields': 'userEnteredFormat(textFormat,backgroundColor)',
            }
        })
        requests_list.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': row_idx, 'endRowIndex': row_idx + 1, 'startColumnIndex': 1, 'endColumnIndex': 3},
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': LIGHT_GRAY_BG,
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor)',
            }
        })

    # --- Column widths ---
    col_widths = {0: 200, 1: 400, 2: 80}
    for col, width in col_widths.items():
        requests_list.append({
            'updateDimensionProperties': {
                'range': {'sheetId': sid, 'dimension': 'COLUMNS', 'startIndex': col, 'endIndex': col + 1},
                'properties': {'pixelSize': width},
                'fields': 'pixelSize',
            }
        })

    # --- Borders around sections ---
    for i, section_start in enumerate(section_rows):
        # Find end of section (next section or end of data)
        if i + 1 < len(section_rows):
            section_end = section_rows[i + 1]
            # Go back to skip empty separator row
            while section_end > section_start + 1:
                prev = section_end - 1
                if prev < len(rows) and rows[prev] and rows[prev][0].strip():
                    break
                section_end -= 1
        else:
            section_end = len(rows)

        border_style = {'style': 'SOLID', 'color': {'red': 0.7, 'green': 0.7, 'blue': 0.7}}
        requests_list.append({
            'updateBorders': {
                'range': {'sheetId': sid, 'startRowIndex': section_start, 'endRowIndex': section_end, 'startColumnIndex': 0, 'endColumnIndex': 3},
                'top': border_style,
                'bottom': border_style,
                'left': border_style,
                'right': border_style,
            }
        })

    batch_update(creds, sheet_id, requests_list)
    print('Settings tab formatted.')


def main():
    creds, sheet_id = get_creds()
    format_reports(creds, sheet_id)
    format_settings(creds, sheet_id)
    print('All formatting applied.')


if __name__ == '__main__':
    main()
