"""
Geuphoria Media — 24/7 Cloud Research Scraper
Runs via GitHub Actions every 30 minutes.
Two tracks: Niche Research + Competitor Research
AI classifies each finding as KEEP or REJECT.
"""

import json, os, re, hashlib, sys, time
from datetime import datetime
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

NICHE_LOG = os.path.join(DATA_DIR, 'niche_research.json')
COMP_LOG = os.path.join(DATA_DIR, 'competitor_research.json')
KEPT_FILE = os.path.join(DATA_DIR, 'kept_findings.json')

# ============================================================
# TRACK 1: NICHE RESEARCH — Online Fitness Coaches
# ============================================================

NICHE_TERMS = [
    'online fitness coach struggling',
    'online fitness coach getting clients',
    'online personal trainer business problems',
    'fitness coach burnout',
    'online coaching income',
    'fitness coach marketing',
    'online fitness coach niche down',
    'personal trainer client acquisition',
    'fitness coach impostor syndrome',
    'online coaching business systems',
]

NICHE_SUBREDDITS = [
    'personaltraining', 'fitnessbusiness', 'onlinepersonaltraining',
    'personaltrainers', 'Entrepreneur', 'smallbusiness',
]

# ============================================================
# TRACK 2: COMPETITOR RESEARCH — People in the market
# ============================================================

COMPETITOR_NAMES = [
    'Alex Hormozi fitness coach',
    'Charlie Morgan coaching',
    'Daniel Dalen online coaching',
    'Sam Ovens coaching business',
    'Dan Martel coaching',
    'online fitness coach business mentor',
    'fitness business coaching program',
    'coaching business guru',
]

COMPETITOR_CHANNELS = [
    'Alex Hormozi', 'Charlie Morgan', 'Daniel Dalen',
    'Sam Ovens', 'Dan Martel',
]

# ============================================================
# HELPERS
# ============================================================

def load_json(path):
    if os.path.exists(path):
        try: return json.loads(open(path, 'r', encoding='utf-8').read())
        except: pass
    return {'entries': [], 'stats': {'scanned': 0, 'kept': 0, 'rejected': 0, 'last_scan': None}}

def save_json(path, data):
    data['entries'] = data['entries'][-300:]  # Keep last 300
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def content_hash(text):
    return hashlib.md5(text[:200].encode()).hexdigest()

def load_seen():
    path = os.path.join(DATA_DIR, 'seen_hashes.json')
    if os.path.exists(path):
        try: return set(json.loads(open(path).read()))
        except: pass
    return set()

def save_seen(seen):
    path = os.path.join(DATA_DIR, 'seen_hashes.json')
    with open(path, 'w') as f:
        json.dump(list(seen)[-5000:], f)

def is_niche_relevant(text):
    t = text.lower()
    must = ['coach', 'trainer', 'training', 'fitness', 'client', 'online']
    if sum(1 for w in must if w in t) < 2: return False
    biz = ['business', 'income', 'clients', 'coaching', 'charge', 'pricing', 'leads',
           'marketing', 'struggling', 'burnout', 'niche', 'program', 'scaling', 'revenue']
    return any(w in t for w in biz)

def classify_finding(title, text, track):
    """Simple AI classification — KEEP if relevant, REJECT if not."""
    combined = (title + ' ' + text).lower()
    if track == 'niche':
        # Keep if it contains coach pain points, goals, or identity markers
        pain_words = ['struggling', 'can\'t get', 'no clients', 'burnout', 'frustrated',
                      'impostor', 'fraud', 'quit', 'give up', 'broke', 'stuck',
                      'overwhelmed', 'confused', 'lost', 'failing', 'zero dms', 'no leads']
        goal_words = ['scale', '10k', '20k', 'full time', 'freedom', 'grow', 'first client',
                      'consistent income', 'predictable', 'systems', 'automate']
        identity_words = ['i am a coach', 'as a trainer', 'my coaching business',
                          'online coaching', 'fitness business']
        score = sum(1 for w in pain_words if w in combined)
        score += sum(1 for w in goal_words if w in combined)
        score += sum(1 for w in identity_words if w in combined)
        if score >= 1:
            return 'keep', f'Score {score}: relevant pain/goal/identity markers'
        return 'reject', 'No relevant markers found'
    else:  # competitor
        # Keep if it mentions competitor strategies, content, or offers
        strat_words = ['strategy', 'funnel', 'offer', 'program', 'course', 'community',
                       'content', 'youtube', 'instagram', 'tiktok', 'hook', 'thumbnail',
                       'launch', 'revenue', 'million', 'growth', 'audience']
        if any(w in combined for w in strat_words):
            return 'keep', 'Contains competitor strategy/content data'
        return 'reject', 'No competitor strategy data'

# ============================================================
# SCRAPING FUNCTIONS
# ============================================================

def scrape_reddit(subreddits, seen, log, track):
    count = 0
    for sub in subreddits:
        try:
            url = f'https://www.reddit.com/r/{sub}/new.json?limit=25'
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            posts = r.json().get('data', {}).get('children', [])
            for post in posts:
                p = post.get('data', {})
                title = p.get('title', '')
                selftext = p.get('selftext', '')[:500]
                h = content_hash(title + selftext)
                if h in seen: continue
                seen.add(h)
                log['stats']['scanned'] += 1
                status, reason = classify_finding(title, selftext, track)
                if status == 'keep':
                    log['entries'].append({
                        'source': f'Reddit r/{sub}', 'title': title[:200],
                        'text': selftext[:300], 'url': f"https://reddit.com{p.get('permalink','')}",
                        'time': datetime.utcnow().isoformat(), 'status': 'keep',
                        'reason': reason, 'track': track
                    })
                    log['stats']['kept'] += 1
                    count += 1
                else:
                    log['stats']['rejected'] += 1
            time.sleep(2)
        except: pass
    return count

def scrape_youtube(terms, seen, log, track):
    count = 0
    for term in terms[:3]:
        try:
            url = f'https://www.youtube.com/results?search_query={quote_plus(term)}&sp=CAI'
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', r.text)
            for title in titles[:10]:
                h = content_hash(title)
                if h in seen: continue
                seen.add(h)
                log['stats']['scanned'] += 1
                status, reason = classify_finding(title, term, track)
                if status == 'keep':
                    log['entries'].append({
                        'source': 'YouTube', 'title': title[:200],
                        'text': f'Search: {term}', 'url': '',
                        'time': datetime.utcnow().isoformat(), 'status': 'keep',
                        'reason': reason, 'track': track
                    })
                    log['stats']['kept'] += 1
                    count += 1
                else:
                    log['stats']['rejected'] += 1
            time.sleep(2)
        except: pass
    return count

def scrape_google(queries, seen, log, track):
    count = 0
    for query in queries[:2]:
        try:
            url = f'https://www.google.com/search?q={quote_plus(query)}&tbs=qdr:w'
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for result in soup.select('h3'):
                title = result.get_text()
                if not title: continue
                h = content_hash(title)
                if h in seen: continue
                seen.add(h)
                log['stats']['scanned'] += 1
                status, reason = classify_finding(title, query, track)
                if status == 'keep':
                    log['entries'].append({
                        'source': 'Google', 'title': title[:200],
                        'text': f'Search: {query[:50]}', 'url': '',
                        'time': datetime.utcnow().isoformat(), 'status': 'keep',
                        'reason': reason, 'track': track
                    })
                    log['stats']['kept'] += 1
                    count += 1
                else:
                    log['stats']['rejected'] += 1
            time.sleep(3)
        except: pass
    return count

# ============================================================
# MAIN
# ============================================================

def run():
    print(f'=== Geuphoria Research Scraper ===')
    print(f'Time: {datetime.utcnow().isoformat()}')

    seen = load_seen()

    # TRACK 1: Niche Research
    print('\n--- TRACK 1: Niche Research (Online Fitness Coaches) ---')
    niche = load_json(NICHE_LOG)
    n1 = scrape_reddit(NICHE_SUBREDDITS, seen, niche, 'niche')
    n2 = scrape_youtube(NICHE_TERMS, seen, niche, 'niche')
    n3 = scrape_google([
        'online fitness coach problems site:reddit.com',
        '"online fitness coach" struggling OR burnout OR "no clients"',
    ], seen, niche, 'niche')
    niche['stats']['last_scan'] = datetime.utcnow().isoformat()
    save_json(NICHE_LOG, niche)
    print(f'Niche: {n1+n2+n3} new kept | Total: {niche["stats"]["kept"]} kept, {niche["stats"]["rejected"]} rejected')

    # TRACK 2: Competitor Research
    print('\n--- TRACK 2: Competitor Research ---')
    comp = load_json(COMP_LOG)
    c1 = scrape_youtube(COMPETITOR_NAMES, seen, comp, 'competitor')
    c2 = scrape_google([
        'Alex Hormozi fitness coach strategy',
        'online fitness coaching business mentor program',
    ], seen, comp, 'competitor')
    c3 = scrape_reddit(['Entrepreneur', 'fitnessbusiness'], seen, comp, 'competitor')
    comp['stats']['last_scan'] = datetime.utcnow().isoformat()
    save_json(COMP_LOG, comp)
    print(f'Competitor: {c1+c2+c3} new kept | Total: {comp["stats"]["kept"]} kept, {comp["stats"]["rejected"]} rejected')

    # Save combined kept findings
    kept = load_json(KEPT_FILE)
    all_kept = [e for e in niche.get('entries', []) if e.get('status') == 'keep']
    all_kept += [e for e in comp.get('entries', []) if e.get('status') == 'keep']
    kept['entries'] = all_kept[-500:]
    kept['stats'] = {
        'niche_kept': niche['stats']['kept'],
        'niche_rejected': niche['stats']['rejected'],
        'niche_scanned': niche['stats']['scanned'],
        'comp_kept': comp['stats']['kept'],
        'comp_rejected': comp['stats']['rejected'],
        'comp_scanned': comp['stats']['scanned'],
        'last_scan': datetime.utcnow().isoformat(),
        'total_kept': niche['stats']['kept'] + comp['stats']['kept'],
        'total_rejected': niche['stats']['rejected'] + comp['stats']['rejected'],
    }
    save_json(KEPT_FILE, kept)
    save_seen(seen)

    print(f'\n=== Done. Total kept: {kept["stats"]["total_kept"]} ===')

if __name__ == '__main__':
    run()
