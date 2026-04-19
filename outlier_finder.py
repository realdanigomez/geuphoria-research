"""
Geuphoria Media — YouTube Outlier Finder
Finds competitor videos performing 2x+ above a channel's average.
Runs every Friday via GitHub Actions.
Enriches each outlier with transcript, AI summary, and content hooks
for YouTube longforms, Instagram reels, and Instagram carousels.
Outputs to: Google Sheets + 01_research/outliers/YYYY-MM-DD/
"""

import json, os, re, subprocess, isodate, time
from datetime import datetime, timezone, timedelta
import requests

from outlier_config import (
    HARDCODED_CHANNELS, KEYWORD_SEARCHES,
    OUTLIER_MULTIPLIER_THRESHOLD, MIN_VIDEO_AGE_HOURS,
    VIDEOS_PER_CHANNEL, MAX_OUTLIERS_PER_RUN, TOP_N_FOR_TRANSCRIPTS,
    AI_MODEL, SUMMARY_MIN_WORDS, SUMMARY_MAX_WORDS,
    DATA_DIR, OUTLIERS_DIR, SEEN_IDS_FILE, CHANNEL_CACHE_FILE,
    LOCAL_OUTLIERS_DIR,
)

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YT_BASE = "https://www.googleapis.com/youtube/v3"

VOICE_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "voice-profile", "voice-profile.md"
)


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────

def load_json(path: str, default=None):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


def load_seen_ids() -> set:
    return set(load_json(SEEN_IDS_FILE, []))


def save_seen_ids(seen: set) -> None:
    # Cap at 5000 to prevent unbounded growth
    items = list(seen)[-5000:]
    save_json(SEEN_IDS_FILE, items)


def load_channel_cache() -> dict:
    return load_json(CHANNEL_CACHE_FILE, {})


def save_channel_cache(cache: dict) -> None:
    save_json(CHANNEL_CACHE_FILE, cache)


def load_voice_profile() -> str:
    if os.path.exists(VOICE_PROFILE_PATH):
        raw = open(VOICE_PROFILE_PATH, encoding="utf-8").read()
        # Return the Quick Reference section only (~2000 chars) to stay within prompt limits
        match = re.search(r"## Quick reference.*?(?=^##|\Z)", raw, re.S | re.M)
        if match:
            return match.group(0)[:2500]
        return raw[:2500]
    return ""


# ─────────────────────────────────────────────
# YOUTUBE API
# ─────────────────────────────────────────────

def yt_get(endpoint: str, params: dict) -> dict:
    params["key"] = YOUTUBE_API_KEY
    resp = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def resolve_handle_to_channel_id(handle: str, cache: dict) -> str:
    """Resolve @handle to channel ID. Costs 1 unit. Uses cache."""
    clean = handle.lstrip("@")
    if clean in cache:
        return cache[clean]
    try:
        data = yt_get("channels", {"part": "id,snippet", "forHandle": clean})
        items = data.get("items", [])
        if items:
            cid = items[0]["id"]
            cache[clean] = cid
            return cid
    except Exception as e:
        print(f"    Could not resolve @{clean}: {e}")
    return ""


def discover_channels_from_competitors_md() -> list:
    """Parse 01_research/competitors.md for YouTube channel mentions."""
    md_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "01_research", "competitors.md"
    )
    if not os.path.exists(md_path):
        return []

    text = open(md_path, encoding="utf-8").read()
    channels = []
    seen_handles = set()

    # Match youtube.com/@handle or youtube.com/c/handle or youtube.com/channel/UCxxx
    for m in re.finditer(
        r'youtube\.com/(?:@|c/|channel/)([\w-]+)', text, re.I
    ):
        handle = m.group(1)
        if handle not in seen_handles:
            seen_handles.add(handle)
            channels.append({"name": handle, "handle": handle})

    # Match bare @handles
    for m in re.finditer(r'@([\w]{3,})', text):
        handle = m.group(1)
        if handle not in seen_handles:
            seen_handles.add(handle)
            channels.append({"name": handle, "handle": handle})

    return channels


def search_channels_by_keyword(keyword: str, max_results: int = 5) -> list:
    """Search YouTube for channels matching keyword. Costs 100 units."""
    try:
        data = yt_get("search", {
            "part": "snippet",
            "q": keyword,
            "type": "channel",
            "maxResults": max_results,
        })
        return [
            {
                "name": item["snippet"]["title"],
                "channel_id": item["snippet"]["channelId"],
                "handle": item["snippet"].get("customUrl", ""),
            }
            for item in data.get("items", [])
        ]
    except Exception as e:
        print(f"    Keyword search '{keyword}' failed: {e}")
        return []


def fetch_channel_videos(channel_id: str) -> list:
    """Fetch recent video IDs from a channel. Costs 100 units."""
    try:
        data = yt_get("search", {
            "part": "id",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": VIDEOS_PER_CHANNEL,
        })
        return [item["id"]["videoId"] for item in data.get("items", []) if "videoId" in item.get("id", {})]
    except Exception as e:
        print(f"    fetch_channel_videos({channel_id}) failed: {e}")
        return []


def fetch_video_details(video_ids: list) -> list:
    """Batch-fetch full video details (max 50/call). Costs 1 unit per call."""
    results = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        try:
            data = yt_get("videos", {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
            })
            results.extend(data.get("items", []))
        except Exception as e:
            print(f"    fetch_video_details batch failed: {e}")
    return results


def parse_duration_seconds(iso_duration: str) -> int:
    try:
        return int(isodate.parse_duration(iso_duration).total_seconds())
    except Exception:
        return 0


def is_video_too_new(published_at: str) -> bool:
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - pub
        return age < timedelta(hours=MIN_VIDEO_AGE_HOURS)
    except Exception:
        return False


def calculate_channel_stats(videos: list) -> dict:
    view_counts = []
    for v in videos:
        try:
            views = int(v["statistics"].get("viewCount", 0))
            if views > 0:
                view_counts.append(views)
        except Exception:
            pass
    if not view_counts:
        return {"avg_views": 0, "video_count": 0}
    avg = sum(view_counts) / len(view_counts)
    return {"avg_views": avg, "video_count": len(view_counts)}


def detect_outliers(videos: list, channel_avg: float, channel_name: str, channel_handle: str) -> list:
    """Return videos with views >= threshold * channel_avg, sorted by score desc."""
    if channel_avg <= 0:
        return []
    outliers = []
    for v in videos:
        try:
            views = int(v["statistics"].get("viewCount", 0))
            score = views / channel_avg
            if score >= OUTLIER_MULTIPLIER_THRESHOLD:
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                content = v.get("contentDetails", {})
                video_id = v["id"]
                thumb = (
                    snippet.get("thumbnails", {}).get("maxres", {}).get("url") or
                    snippet.get("thumbnails", {}).get("high", {}).get("url") or
                    snippet.get("thumbnails", {}).get("default", {}).get("url") or ""
                )
                outliers.append({
                    "video_id": video_id,
                    "video_url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", "")[:1000],
                    "tags": snippet.get("tags", []),
                    "channel_name": channel_name,
                    "channel_id": snippet.get("channelId", ""),
                    "channel_handle": channel_handle,
                    "published_at": snippet.get("publishedAt", ""),
                    "duration_seconds": parse_duration_seconds(content.get("duration", "")),
                    "definition": content.get("definition", ""),
                    "view_count": views,
                    "like_count": int(stats.get("likeCount", 0) or 0),
                    "comment_count": int(stats.get("commentCount", 0) or 0),
                    "channel_avg_views": round(channel_avg),
                    "outlier_score": round(score, 2),
                    "outlier_multiplier": f"{score:.1f}x",
                    "thumbnail_url": thumb,
                    "transcript": "",
                    "transcript_language": "",
                    "summary": "",
                    "youtube_titles": [],
                    "reel_hooks": [],
                    "carousel_hooks": [],
                    "best_format": "",
                    "funnel_tier": "",
                    "funnel_reason": "",
                    "scraped_at": datetime.utcnow().isoformat() + "Z",
                })
        except Exception:
            pass
    return sorted(outliers, key=lambda x: x["outlier_score"], reverse=True)


# ─────────────────────────────────────────────
# TRANSCRIPT
# ─────────────────────────────────────────────

def get_transcript(video_id: str) -> tuple:
    """Returns (transcript_text, language). Falls back through methods."""
    # Attempt 1: youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        entries = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join(e["text"] for e in entries)
        return text, "en"
    except Exception:
        pass

    # Attempt 2: yt-dlp auto-captions
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "yt-dlp", "--skip-download",
                    "--write-auto-sub", "--sub-lang", "en",
                    "--sub-format", "vtt",
                    "-o", os.path.join(tmpdir, "%(id)s"),
                    f"https://www.youtube.com/watch?v={video_id}",
                ],
                capture_output=True, timeout=45, text=True,
            )
            vtt_path = os.path.join(tmpdir, f"{video_id}.en.vtt")
            if os.path.exists(vtt_path):
                raw = open(vtt_path).read()
                # Strip VTT timestamps and tags
                text = re.sub(r'\d{2}:\d{2}:\d{2}\.\d+ --> .*', '', raw)
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'\n{2,}', ' ', text).strip()
                if len(text) > 100:
                    return text, "en"
    except Exception:
        pass

    return "", "unavailable"


# ─────────────────────────────────────────────
# CLAUDE OPUS AI ANALYSIS
# ─────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are a content intelligence analyst for Dani Gomez, an online fitness coaching content creator at @real.danigomez.

DANI'S VOICE (Quick Reference):
{voice_profile}

Your job: analyze a YouTube outlier video and generate content inspiration for Dani across three formats.

Respond ONLY with valid JSON. No markdown fences. No explanation outside JSON."""

USER_PROMPT_TEMPLATE = """Analyze this YouTube outlier video.

VIDEO:
Title: {title}
Channel: {channel_name}
Views: {view_count:,} ({outlier_multiplier} above channel average of {channel_avg_views:,})
Published: {published_at}
Description: {description}

TRANSCRIPT (first 3000 chars):
{transcript}

TASKS:
1. Write a {min_words}-{max_words} word summary of WHY this video outperformed. What hook, insight, or angle drove the views? Quote from the transcript.
2. Write 3 YouTube LONGFORM titles Dani could use for similar content. In his exact voice — direct, punchy, specific numbers, "Online Fitness Coaches" opener where natural.
3. Write 3 Instagram REEL hooks (1-2 short lines, scroll-stopping, spoken-word punchy — e.g. "Online Fitness Coaches. You don't have a lead problem. You have a system problem.").
4. Write 3 Instagram CAROUSEL hooks (educational list-framing — e.g. "5 reasons online fitness coaches stay stuck at $3K/mo" or question hooks like "Are you making these 4 mistakes in your fitness coaching business?").
5. Which format fits this topic best? "YouTube" / "Reel" / "Carousel" / "All"
6. Funnel tier: B (beginner coach, <$2K/mo), M (scaling, $2K-$10K/mo), E (established, $10K+/mo). One-sentence reasoning.

Return this exact JSON (no extra keys):
{{
  "summary": "...",
  "youtube_titles": ["...", "...", "..."],
  "reel_hooks": ["...", "...", "..."],
  "carousel_hooks": ["...", "...", "..."],
  "best_format": "YouTube|Reel|Carousel|All",
  "funnel_tier": "B|M|E",
  "funnel_reason": "..."
}}"""


def call_claude_for_outlier(outlier: dict, voice_profile: str) -> dict:
    """Call Claude Opus for AI analysis. Returns dict of AI fields."""
    if not ANTHROPIC_KEY:
        return {}

    system = SYSTEM_PROMPT_TEMPLATE.format(voice_profile=voice_profile[:2000])
    user = USER_PROMPT_TEMPLATE.format(
        title=outlier["title"],
        channel_name=outlier["channel_name"],
        view_count=outlier["view_count"],
        outlier_multiplier=outlier["outlier_multiplier"],
        channel_avg_views=outlier["channel_avg_views"],
        published_at=outlier["published_at"][:10],
        description=outlier["description"][:400],
        transcript=outlier["transcript"][:3000],
        min_words=SUMMARY_MIN_WORDS,
        max_words=SUMMARY_MAX_WORDS,
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "max_tokens": 1500,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["text"].strip()
        # Strip markdown fences if model added them
        content = re.sub(r'^```json?\s*', '', content, flags=re.M)
        content = re.sub(r'```\s*$', '', content, flags=re.M)
        return json.loads(content)
    except Exception as e:
        print(f"    Claude call failed for '{outlier['title'][:50]}': {e}")
        return {}


# ─────────────────────────────────────────────
# CHANNEL PROCESSING
# ─────────────────────────────────────────────

def process_channel(channel_info: dict, cache: dict) -> list:
    """Full pipeline for one channel. Returns list of outlier dicts."""
    name = channel_info.get("name", "")
    handle = channel_info.get("handle", "")
    channel_id = channel_info.get("channel_id", "")

    # Resolve channel ID if not already known
    if not channel_id and handle:
        channel_id = resolve_handle_to_channel_id(handle, cache)
    if not channel_id:
        print(f"  Skipping {name} — could not resolve channel ID")
        return []

    video_ids = fetch_channel_videos(channel_id)
    if not video_ids:
        print(f"  {name}: no videos found")
        return []

    videos = fetch_video_details(video_ids)
    # Filter out too-new videos
    eligible = [v for v in videos if not is_video_too_new(v.get("snippet", {}).get("publishedAt", ""))]

    stats = calculate_channel_stats(eligible)
    avg = stats["avg_views"]
    if avg <= 0:
        print(f"  {name}: avg views = 0, skipping")
        return []

    # For hardcoded VIP channels (Hormozi, Morgan, Dalen etc.) their averages are so
    # high that standard outlier detection misses their best work. Always include
    # their top 5 videos by absolute view count, then add any standard outliers on top.
    is_hardcoded = any(
        ch.get("handle", "").lower() == handle.lower()
        for ch in HARDCODED_CHANNELS
    )

    if is_hardcoded:
        # Top 5 by raw views, regardless of threshold
        sorted_by_views = sorted(
            eligible,
            key=lambda v: int(v.get("statistics", {}).get("viewCount", 0)),
            reverse=True
        )
        top5 = detect_outliers(sorted_by_views[:5], avg, name, handle)
        # Also run standard detection and merge (dedup by video_id)
        standard = detect_outliers(eligible, avg, name, handle)
        seen = {o["video_id"] for o in top5}
        for o in standard:
            if o["video_id"] not in seen:
                top5.append(o)
                seen.add(o["video_id"])
        outliers = top5
        print(f"  {name} [VIP]: {len(eligible)} videos, avg {avg:,.0f} views → {len(outliers)} included (top-5 + outliers)")
    else:
        outliers = detect_outliers(eligible, avg, name, handle)
        print(f"  {name}: {len(eligible)} videos, avg {avg:,.0f} views → {len(outliers)} outliers")

    return outliers


# ─────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────

def fmt_num(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def generate_report_md(outliers: list, run_date: str, channels_scanned: int, total_evaluated: int) -> str:
    lines = [
        f"# YouTube Outlier Report — {run_date}",
        "",
        f"**Run date:** {run_date}  ",
        f"**Channels scanned:** {channels_scanned}  ",
        f"**Videos evaluated:** {total_evaluated}  ",
        f"**Outliers found:** {len(outliers)} (≥{OUTLIER_MULTIPLIER_THRESHOLD}x channel avg)  ",
        f"**With transcripts:** {sum(1 for o in outliers if o.get('transcript'))}  ",
        f"**AI-processed:** {sum(1 for o in outliers if o.get('summary'))}  ",
        "",
        "---",
        "",
        "## Summary Table",
        "",
        "| Rank | Score | Channel | Title | Views | Avg | Tier | Format |",
        "|------|-------|---------|-------|-------|-----|------|--------|",
    ]

    for i, o in enumerate(outliers, 1):
        title_short = o["title"][:50] + ("…" if len(o["title"]) > 50 else "")
        lines.append(
            f"| {i} | {o['outlier_multiplier']} | {o['channel_name']} | "
            f"{title_short} | {fmt_num(o['view_count'])} | {fmt_num(o['channel_avg_views'])} | "
            f"{o.get('funnel_tier','?')} | {o.get('best_format','?')} |"
        )

    lines += ["", "---", "", "## Outlier Details", ""]

    for i, o in enumerate(outliers, 1):
        lines += [
            f"### #{i} — {o['outlier_multiplier']} — {o['channel_name']}",
            "",
            f"**Title:** {o['title']}  ",
            f"**URL:** {o['video_url']}  ",
            f"**Published:** {o['published_at'][:10]} · "
            f"Duration: {o['duration_seconds']//60}:{o['duration_seconds']%60:02d} · "
            f"Definition: {o.get('definition','').upper()}  ",
            f"**Views:** {fmt_num(o['view_count'])} · "
            f"Likes: {fmt_num(o['like_count'])} · "
            f"Comments: {fmt_num(o['comment_count'])}  ",
            f"**Channel avg:** {fmt_num(o['channel_avg_views'])} views  ",
            f"**Outlier score:** {o['outlier_multiplier']}  ",
            f"**Funnel tier:** {o.get('funnel_tier','?')} — {o.get('funnel_reason','')}  ",
            f"**Best format:** {o.get('best_format','?')}  ",
            "",
        ]

        if o.get("summary"):
            lines += ["**AI Summary:**  ", o["summary"], ""]

        if o.get("youtube_titles"):
            lines.append("**YouTube Longform Titles (Dani's voice):**  ")
            for t in o["youtube_titles"]:
                lines.append(f"→ {t}  ")
            lines.append("")

        if o.get("reel_hooks"):
            lines.append("**Instagram Reel Hooks:**  ")
            for t in o["reel_hooks"]:
                lines.append(f"→ {t}  ")
            lines.append("")

        if o.get("carousel_hooks"):
            lines.append("**Instagram Carousel Hooks:**  ")
            for t in o["carousel_hooks"]:
                lines.append(f"→ {t}  ")
            lines.append("")

        transcript_status = "Available" if o.get("transcript") else "Not available"
        lines.append(f"**Transcript:** {transcript_status} · See `{o['video_id']}.md`  ")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def save_outlier_md(outlier: dict, output_dir: str) -> None:
    path = os.path.join(output_dir, f"{outlier['video_id']}.md")
    lines = [
        f"# {outlier['title']}",
        "",
        f"**Channel:** {outlier['channel_name']} ({outlier['channel_handle']})  ",
        f"**URL:** {outlier['video_url']}  ",
        f"**Published:** {outlier['published_at'][:10]}  ",
        f"**Views:** {fmt_num(outlier['view_count'])} ({outlier['outlier_multiplier']} above {fmt_num(outlier['channel_avg_views'])} avg)  ",
        f"**Duration:** {outlier['duration_seconds']//60}:{outlier['duration_seconds']%60:02d}  ",
        f"**Likes:** {fmt_num(outlier['like_count'])} · Comments: {fmt_num(outlier['comment_count'])}  ",
        f"**Funnel tier:** {outlier.get('funnel_tier','')} — {outlier.get('funnel_reason','')}  ",
        f"**Best format:** {outlier.get('best_format','')}  ",
        f"**Tags:** {', '.join(outlier.get('tags', [])[:15])}  ",
        "",
        "---",
        "",
    ]

    if outlier.get("summary"):
        lines += ["## AI Summary", "", outlier["summary"], ""]

    if outlier.get("youtube_titles"):
        lines += ["## YouTube Longform Titles", ""]
        for t in outlier["youtube_titles"]:
            lines.append(f"1. {t}")
        lines.append("")

    if outlier.get("reel_hooks"):
        lines += ["## Instagram Reel Hooks", ""]
        for t in outlier["reel_hooks"]:
            lines.append(f"- {t}")
        lines.append("")

    if outlier.get("carousel_hooks"):
        lines += ["## Instagram Carousel Hooks", ""]
        for t in outlier["carousel_hooks"]:
            lines.append(f"- {t}")
        lines.append("")

    if outlier.get("transcript"):
        lines += ["## Full Transcript", "", f"*Language: {outlier.get('transcript_language', 'en')}*", ""]
        lines.append(outlier["transcript"])
    else:
        lines += ["## Transcript", "", "*Not available for this video.*"]

    open(path, "w", encoding="utf-8").write("\n".join(lines))


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run():
    now = datetime.utcnow()
    run_date = now.strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"Geuphoria YouTube Outlier Finder — {run_date}")
    print(f"{'='*60}\n")

    if not YOUTUBE_API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set. Exiting.")
        return
    if not ANTHROPIC_KEY:
        print("WARNING: ANTHROPIC_API_KEY not set — transcripts will be fetched but AI analysis skipped.")

    # Load state
    seen_ids = load_seen_ids()
    channel_cache = load_channel_cache()
    voice_profile = load_voice_profile()

    # Build channel list
    print("Building channel list...")
    raw_channels = list(HARDCODED_CHANNELS)

    md_channels = discover_channels_from_competitors_md()
    print(f"  competitors.md: {len(md_channels)} channels found")
    raw_channels.extend(md_channels)

    for keyword in KEYWORD_SEARCHES:
        kw_channels = search_channels_by_keyword(keyword)
        print(f"  Keyword '{keyword}': {len(kw_channels)} channels found")
        raw_channels.extend(kw_channels)
        time.sleep(0.5)

    # Deduplicate channels by channel_id (resolve first)
    deduped = {}
    for ch in raw_channels:
        cid = ch.get("channel_id", "")
        if not cid:
            handle = ch.get("handle", "")
            if handle:
                cid = resolve_handle_to_channel_id(handle, channel_cache)
                ch["channel_id"] = cid
                time.sleep(0.2)
        if cid and cid not in deduped:
            deduped[cid] = ch

    channels = list(deduped.values())
    print(f"\nTotal unique channels to scan: {len(channels)}\n")

    # Process each channel
    all_outliers = []
    total_videos_evaluated = 0

    for ch in channels:
        outliers = process_channel(ch, channel_cache)
        all_outliers.extend(outliers)
        total_videos_evaluated += VIDEOS_PER_CHANNEL
        time.sleep(0.5)

    # Sort by outlier_score and apply hard cap
    all_outliers.sort(key=lambda x: x["outlier_score"], reverse=True)
    all_outliers = all_outliers[:MAX_OUTLIERS_PER_RUN]
    print(f"\nTotal outliers found (capped at {MAX_OUTLIERS_PER_RUN}): {len(all_outliers)}")

    # Fetch transcripts + AI analysis for top N that haven't been processed yet
    to_process = [o for o in all_outliers[:TOP_N_FOR_TRANSCRIPTS] if o["video_id"] not in seen_ids]
    print(f"New outliers to process: {len(to_process)}\n")

    for i, outlier in enumerate(to_process, 1):
        title_short = outlier["title"][:60]
        print(f"[{i}/{len(to_process)}] {title_short}")

        # Transcript
        transcript, lang = get_transcript(outlier["video_id"])
        outlier["transcript"] = transcript
        outlier["transcript_language"] = lang
        print(f"    Transcript: {'✓' if transcript else '✗'} ({lang})")

        # AI analysis
        if ANTHROPIC_KEY:
            ai = call_claude_for_outlier(outlier, voice_profile)
            if ai:
                outlier["summary"] = ai.get("summary", "")
                outlier["youtube_titles"] = ai.get("youtube_titles", [])
                outlier["reel_hooks"] = ai.get("reel_hooks", [])
                outlier["carousel_hooks"] = ai.get("carousel_hooks", [])
                outlier["best_format"] = ai.get("best_format", "")
                outlier["funnel_tier"] = ai.get("funnel_tier", "")
                outlier["funnel_reason"] = ai.get("funnel_reason", "")
                print(f"    AI: ✓ (tier={outlier['funnel_tier']}, format={outlier['best_format']})")
            else:
                print("    AI: ✗ (call failed)")
        time.sleep(1)  # Rate limit buffer

        seen_ids.add(outlier["video_id"])

    # Write outputs
    output_dir = os.path.join(OUTLIERS_DIR, run_date)
    os.makedirs(output_dir, exist_ok=True)

    # Also write to local 01_research/outliers/ if the path exists (local machine only)
    local_dir = os.path.join(LOCAL_OUTLIERS_DIR, run_date)
    write_local = os.path.exists(os.path.dirname(LOCAL_OUTLIERS_DIR))
    if write_local:
        os.makedirs(local_dir, exist_ok=True)

    envelope = {
        "run_date": run_date,
        "scraped_at": now.isoformat() + "Z",
        "channels_scanned": len(channels),
        "total_videos_evaluated": total_videos_evaluated,
        "total_outliers_found": len(all_outliers),
        "transcripts_fetched": sum(1 for o in all_outliers if o.get("transcript")),
        "ai_processed": sum(1 for o in all_outliers if o.get("summary")),
        "outliers": all_outliers,
    }

    save_json(os.path.join(output_dir, "outliers.json"), envelope)
    if write_local:
        save_json(os.path.join(local_dir, "outliers.json"), envelope)

    report = generate_report_md(all_outliers, run_date, len(channels), total_videos_evaluated)
    open(os.path.join(output_dir, "report.md"), "w", encoding="utf-8").write(report)
    if write_local:
        open(os.path.join(local_dir, "report.md"), "w", encoding="utf-8").write(report)

    for o in to_process:
        save_outlier_md(o, output_dir)
        if write_local:
            save_outlier_md(o, local_dir)

    # Persist state
    save_seen_ids(seen_ids)
    save_channel_cache(channel_cache)

    # Google Sheets
    try:
        from sheets_writer import write_outliers_to_sheet
        sheet_url = write_outliers_to_sheet(all_outliers)
    except Exception as e:
        print(f"  Sheets write failed: {e}")
        sheet_url = ""

    # Summary
    print(f"\n{'='*60}")
    print(f"Run complete — {run_date}")
    print(f"  Channels scanned:    {len(channels)}")
    print(f"  Videos evaluated:    {total_videos_evaluated}")
    print(f"  Outliers found:      {len(all_outliers)}")
    print(f"  Transcripts:         {sum(1 for o in all_outliers if o.get('transcript'))}")
    print(f"  AI-processed:        {sum(1 for o in all_outliers if o.get('summary'))}")
    print(f"  Output dir:          {output_dir}")
    if sheet_url:
        print(f"  Google Sheet:        {sheet_url}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
