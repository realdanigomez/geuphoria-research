"""
Geuphoria Media — YouTube Outlier Finder Configuration
"""

# Hardcoded competitor channels (always scanned)
HARDCODED_CHANNELS = [
    {"name": "Alex Hormozi",   "handle": "AlexHormozi"},
    {"name": "Charlie Morgan", "handle": "CharlieMMorgan"},
    {"name": "Daniel Dalen",   "handle": "DanielDalen"},
    {"name": "Iman Gadzhi",    "handle": "ImanGadzhi"},
]

# Keyword searches to surface additional relevant channels
KEYWORD_SEARCHES = [
    "online fitness coach business",
    "fitness business coaching",
    "online personal trainer mentor",
]

# Outlier detection thresholds
OUTLIER_MULTIPLIER_THRESHOLD = 2.0   # views >= 2x channel average (VIP channels use top-5 override)
MIN_VIDEO_AGE_HOURS = 48             # exclude videos newer than this (recency bias)
VIDEOS_PER_CHANNEL = 50              # how many recent videos to fetch per channel
MAX_OUTLIERS_PER_RUN = 25            # hard cap per weekly run
TOP_N_FOR_TRANSCRIPTS = 25           # all outliers (up to cap) get transcript + AI

# AI model — Claude Opus for highest quality analysis
AI_MODEL = "claude-opus-4-7"
SUMMARY_MIN_WORDS = 200
SUMMARY_MAX_WORDS = 300

# Funnel tier definitions (used in AI prompt)
FUNNEL_TIERS = {
    "B": "Beginner — brand new to online coaching, pre-first-client, <$2K/mo",
    "M": "Mid-tier — established coach, $2K-$10K/mo, in the scaling phase",
    "E": "Established — $10K+/mo coach, team building, systems, ceiling reached",
}

# Google Sheets
GOOGLE_SHEET_TITLE = "Geuphoria — YouTube Outliers"
GOOGLE_SHEET_NAME = "YouTube Outliers"
# GOOGLE_SPREADSHEET_ID is written here after first run to avoid recreating the sheet
GOOGLE_SPREADSHEET_ID = ""  # populated on first run

# Output paths (relative to this file's directory)
import os
_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE, "data")
OUTLIERS_DIR = os.path.join(DATA_DIR, "outliers")
SEEN_IDS_FILE = os.path.join(DATA_DIR, "seen_outlier_ids.json")
CHANNEL_CACHE_FILE = os.path.join(DATA_DIR, "channel_id_cache.json")
SHEET_ID_FILE = os.path.join(DATA_DIR, "outlier_sheet_id.json")

# Local research directory (synced back to Content Agent)
LOCAL_OUTLIERS_DIR = os.path.join(_BASE, "..", "01_research", "outliers")
