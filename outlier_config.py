"""
Geuphoria Media — YouTube Outlier Finder Configuration
"""

# Hardcoded competitor channels (always scanned)
HARDCODED_CHANNELS = [
    {"name": "Alex Hormozi",   "handle": "AlexHormozi"},
    {"name": "Charlie Morgan", "handle": "charliemofficial"},
    {"name": "Daniel Dalen",   "handle": "DanielDalen"},
    {"name": "Iman Gadzhi",    "handle": "ImanGadzhi"},
    # 2026-04-28: expanded pool to surface more outliers per run
    {"name": "Sam Ovens",      "handle": "sam_ovens"},
    {"name": "Dan Martell",    "handle": "danmartell"},
    {"name": "Mark Coles",     "handle": "MarkColesM10"},
    # 2026-06-05: document-the-journey / personal-brand inspiration (cross-pollination, like Hormozi/Martell)
    {"name": "Caleb Ralston",  "handle": "CalebRalston"},
]

# Keyword searches to surface additional relevant channels
KEYWORD_SEARCHES = [
    "online fitness coach business",
    "fitness business coaching",
    "online personal trainer mentor",
    "fitness coach scale 10k month",
    "online coaching client acquisition",
    "personal trainer business systems",
    # 2026-06-05: journey / build-in-public reception in the niche
    "fitness coach build in public",
    "online coach document journey",
    "fitness coach founder vlog",
]

# Outlier detection thresholds
# 2026-04-28: lowered to 1.3x + scan 150 videos per channel to surface 25 new outliers per run
# (the strict 2.0x threshold + 50 videos was finding only ~4 new per week from 4 channels)
OUTLIER_MULTIPLIER_THRESHOLD = 1.3   # was 2.0 — borderline outliers still surface signal
MIN_VIDEO_AGE_HOURS = 48             # exclude videos newer than this (recency bias)
VIDEOS_PER_CHANNEL = 150             # was 50 — deeper history catch
MAX_OUTLIERS_PER_RUN = 25            # top 25 new outliers per weekly run
TOP_N_FOR_TRANSCRIPTS = 25           # all get transcript + AI

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
