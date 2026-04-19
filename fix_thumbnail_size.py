"""
One-shot: resize existing Google Sheet rows to 200px height + column A to 360px.
Run once: python fix_thumbnail_size.py
"""
import json, os, sys
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE        = Path(__file__).parent
TOKEN_PATH  = Path(r"C:\Users\Dani Gomez\Documents\Content Agent\.google_token.json")
CONFIG_PATH = Path(r"C:\Users\Dani Gomez\Documents\Content Agent\api_config.json")
SHEET_ID_FILE = BASE / "data" / "outlier_sheet_id.json"

SPREADSHEET_ID = "15pZr5-iFz9RaPbTyMJFZ-GfP0ibrz9EZsmobMzWVigI"
SHEET_NAME     = "YouTube Outliers"

def get_service():
    cfg   = json.load(open(CONFIG_PATH))
    token = json.load(open(TOKEN_PATH))
    creds = Credentials(
        token=token.get("token"),
        refresh_token=token["refresh_token"],
        client_id=cfg["google_client_id"],
        client_secret=cfg["google_client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    if not creds.valid:
        creds.refresh(Request())
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def get_sheet_id(service):
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == SHEET_NAME:
            return s["properties"]["sheetId"]
    raise ValueError(f"Sheet '{SHEET_NAME}' not found")

def fix():
    print("Connecting to Google Sheets...")
    service  = get_service()
    sheet_id = get_sheet_id(service)
    print(f"Sheet ID: {sheet_id}")

    requests = [
        # All data rows → 200px tall (16:9 thumbnail clearly visible)
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS",
                          "startIndex": 1, "endIndex": 500},
                "properties": {"pixelSize": 200},
                "fields": "pixelSize",
            }
        },
        # Column A (Thumbnail) → 360px wide  (16:9 at 200px height = 355px)
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 360},
                "fields": "pixelSize",
            }
        },
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()

    print("Done — all rows set to 200px height, column A set to 360px wide.")
    print(f"Sheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")

if __name__ == "__main__":
    fix()
