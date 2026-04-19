"""
Geuphoria Media — Google Sheets Writer
Writes outlier video data to a Google Spreadsheet with visible thumbnails.
Auth: OAuth 2.0 refresh token (same credentials as YouTube publisher).
"""

import json, os
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from outlier_config import (
    GOOGLE_SHEET_TITLE, GOOGLE_SHEET_NAME, SHEET_ID_FILE, DATA_DIR
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

HEADER = [
    "Thumbnail", "Title", "Channel", "Outlier Score", "Views",
    "Channel Avg Views", "Published", "Duration", "Likes", "Comments",
    "Funnel Tier", "Best Format",
    "YT Title 1", "YT Title 2", "YT Title 3",
    "Reel Hook 1", "Reel Hook 2", "Reel Hook 3",
    "Carousel Hook 1", "Carousel Hook 2", "Carousel Hook 3",
    "Summary", "Tags", "Run Date", "Video ID",
]

# Orange brand color
HEADER_BG = {"red": 1.0, "green": 0.42, "blue": 0.17}
HEADER_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}


def _get_creds() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def get_sheets_service():
    return build("sheets", "v4", credentials=_get_creds(), cache_discovery=False)


def _load_sheet_id() -> str:
    if os.path.exists(SHEET_ID_FILE):
        return json.load(open(SHEET_ID_FILE)).get("spreadsheet_id", "")
    return ""


def _save_sheet_id(spreadsheet_id: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump({"spreadsheet_id": spreadsheet_id}, open(SHEET_ID_FILE, "w"))


def create_or_get_spreadsheet(service) -> str:
    spreadsheet_id = _load_sheet_id()
    if spreadsheet_id:
        # Verify it still exists
        try:
            service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            return spreadsheet_id
        except Exception:
            pass

    # Create new spreadsheet
    body = {
        "properties": {"title": GOOGLE_SHEET_TITLE},
        "sheets": [{"properties": {"title": GOOGLE_SHEET_NAME}}],
    }
    resp = service.spreadsheets().create(body=body).execute()
    spreadsheet_id = resp["spreadsheetId"]
    _save_sheet_id(spreadsheet_id)
    print(f"  Created spreadsheet: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    return spreadsheet_id


def get_sheet_id(service, spreadsheet_id: str) -> int:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == GOOGLE_SHEET_NAME:
            return sheet["properties"]["sheetId"]
    # Sheet tab doesn't exist — add it
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": GOOGLE_SHEET_NAME}}}]},
    ).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


def get_existing_video_ids(service, spreadsheet_id: str) -> set:
    """Read column Y (Video ID, index 24) to find already-inserted videos."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{GOOGLE_SHEET_NAME}!Y:Y",
        ).execute()
        values = result.get("values", [])
        return {row[0] for row in values if row and row[0] != "Video ID"}
    except Exception:
        return set()


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def outlier_to_row(outlier: dict, run_date: str) -> list:
    thumb = outlier.get("thumbnail_url", "")
    vid_url = outlier.get("video_url", "")
    title = outlier.get("title", "")
    yt = outlier.get("youtube_titles", ["", "", ""])
    rh = outlier.get("reel_hooks", ["", "", ""])
    ch = outlier.get("carousel_hooks", ["", "", ""])

    return [
        f'=IMAGE("{thumb}")' if thumb else "",        # A — Thumbnail
        f'=HYPERLINK("{vid_url}","{title.replace(chr(34), chr(39))}")' if vid_url else title,  # B — Title
        outlier.get("channel_name", ""),              # C
        outlier.get("outlier_multiplier", ""),        # D
        outlier.get("view_count", 0),                 # E
        outlier.get("channel_avg_views", 0),          # F
        (outlier.get("published_at", "") or "")[:10], # G — date only
        _fmt_duration(outlier.get("duration_seconds", 0)),  # H
        outlier.get("like_count", 0),                 # I
        outlier.get("comment_count", 0),              # J
        outlier.get("funnel_tier", ""),               # K
        outlier.get("best_format", ""),               # L
        yt[0] if len(yt) > 0 else "",                 # M
        yt[1] if len(yt) > 1 else "",                 # N
        yt[2] if len(yt) > 2 else "",                 # O
        rh[0] if len(rh) > 0 else "",                 # P
        rh[1] if len(rh) > 1 else "",                 # Q
        rh[2] if len(rh) > 2 else "",                 # R
        ch[0] if len(ch) > 0 else "",                 # S
        ch[1] if len(ch) > 1 else "",                 # T
        ch[2] if len(ch) > 2 else "",                 # U
        outlier.get("summary", ""),                   # V
        ", ".join(outlier.get("tags", [])[:10]),      # W
        run_date,                                     # X
        outlier.get("video_id", ""),                  # Y
    ]


def ensure_header(service, spreadsheet_id: str) -> None:
    """Write header row if the sheet is empty."""
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{GOOGLE_SHEET_NAME}!A1:A1",
    ).execute()
    if result.get("values"):
        return  # Header already exists

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{GOOGLE_SHEET_NAME}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [HEADER]},
    ).execute()
    print("  Header row written.")


def format_sheet(service, spreadsheet_id: str, sheet_id: int) -> None:
    """Apply orange header styling, freeze row 1, set thumbnail row height."""
    col_count = len(HEADER)
    requests = [
        # Orange header background + white bold text
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": col_count},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": HEADER_BG,
                        "textFormat": {"foregroundColor": HEADER_FG, "bold": True, "fontSize": 10},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        # Freeze header row
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        # Row height 200px — tall enough for 16:9 thumbnails to be clearly visible
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS",
                           "startIndex": 1, "endIndex": 500},
                "properties": {"pixelSize": 200},
                "fields": "pixelSize",
            }
        },
        # Thumbnail column (A) width = 360px — matches 16:9 at 200px height
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                           "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 360},
                "fields": "pixelSize",
            }
        },
        # Title column (B) width = 280px
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                           "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 280},
                "fields": "pixelSize",
            }
        },
        # Summary column (V = index 21) width = 400px
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                           "startIndex": 21, "endIndex": 22},
                "properties": {"pixelSize": 400},
                "fields": "pixelSize",
            }
        },
        # Wrap text for summary column
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1,
                           "startColumnIndex": 21, "endColumnIndex": 22},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }
        },
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()
    print("  Sheet formatted (orange header, thumbnail rows, column widths).")


def prepend_rows(service, spreadsheet_id: str, rows: list) -> None:
    """Insert rows at position 2 (below header) so newest is always at top."""
    if not rows:
        return
    # Insert blank rows first
    sheet_id = get_sheet_id(service, spreadsheet_id)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [{
                "insertDimension": {
                    "range": {"sheetId": sheet_id, "dimension": "ROWS",
                               "startIndex": 1, "endIndex": 1 + len(rows)},
                    "inheritFromBefore": False,
                }
            }]
        },
    ).execute()

    # Write the data
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{GOOGLE_SHEET_NAME}!A2",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def write_outliers_to_sheet(outliers: list) -> str:
    """
    Main entry point. Writes new outliers to the Google Sheet.
    Returns the sheet URL.
    """
    if not all(os.environ.get(k) for k in ["GOOGLE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]):
        print("  Sheets: missing Google OAuth env vars — skipping sheet write.")
        return ""

    print("Writing to Google Sheets...")
    service = get_sheets_service()
    spreadsheet_id = create_or_get_spreadsheet(service)
    sheet_id = get_sheet_id(service, spreadsheet_id)

    ensure_header(service, spreadsheet_id)
    format_sheet(service, spreadsheet_id, sheet_id)

    existing_ids = get_existing_video_ids(service, spreadsheet_id)
    run_date = datetime.utcnow().strftime("%Y-%m-%d")

    new_rows = []
    for outlier in outliers:
        vid_id = outlier.get("video_id", "")
        if vid_id and vid_id in existing_ids:
            continue
        new_rows.append(outlier_to_row(outlier, run_date))

    if new_rows:
        prepend_rows(service, spreadsheet_id, new_rows)
        print(f"  Added {len(new_rows)} new outliers to sheet.")
    else:
        print("  No new outliers to add (all already in sheet).")

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"  Sheet URL: {url}")
    return url
