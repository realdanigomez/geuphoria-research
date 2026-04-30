"""
Geuphoria Media — 24/7 Cloud Research Scraper v3
Runs via GitHub Actions every 30 minutes.
Three tracks:
  - Niche:      pain points, struggles, goals of online fitness coaches
  - Competitor: people who specifically help online fitness coaches grow their business
  - Business:   broad business insights, AI news, creators, entrepreneurship
AI: Claude Haiku classifies each finding.
Platforms: Reddit, YouTube, Google, LinkedIn, Quora, Medium, Twitter, Facebook, Skool, Instagram
"""

import json, os, re, hashlib, time
from datetime import datetime
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

NICHE_LOG = os.path.join(DATA_DIR, 'niche_research.json')
COMP_LOG  = os.path.join(DATA_DIR, 'competitor_research.json')
BUSI_LOG  = os.path.join(DATA_DIR, 'business_research.json')
KEPT_FILE = os.path.join(DATA_DIR, 'kept_findings.json')
API_KEY   = os.environ.get('ANTHROPIC_API_KEY', '')

# ============================================================
# HAIKU AI CLASSIFIER
# ============================================================

TRACK_PROMPTS = {
    'niche': (
        "NICHE TRACK: Classify if this is relevant to online fitness coaches — "
        "their pain points, struggles, goals, income, client acquisition, burnout, "
        "marketing, systems, scaling. We want to understand their problems deeply."
    ),
    'competitor': (
        "COMPETITOR TRACK: Classify if this contains useful intelligence about people "
        "who specifically help online fitness coaches build their business — mentors, "
        "coaches, programs, or communities targeting online fitness coaches as clients "
        "(e.g. Vince Del Monte, Bedros Keuilian, Charlie Johnson Fitness, Brian Mark, "
        "and similar fitness business coaches). Strategy, content, offers, positioning."
    ),
    'business': (
        "BUSINESS TRACK: Classify if this contains useful business insights, strategies, "
        "entrepreneurship lessons, AI/tech news, creator economy trends, or content from "
        "influential business thinkers (Alex Hormozi, Charlie Morgan, Dan Martell, Sam Ovens, "
        "Daniel Dalen, etc.) that could inspire content ideas or business strategy. "
        "Be inclusive — broad business value counts."
    ),
}

def classify_with_haiku(title, text, track):
    if not API_KEY:
        return classify_local(title, text, track)
    try:
        prompt = f"""You are a research analyst for an online fitness coaching content business.

TRACK: {track.upper()}

{TRACK_PROMPTS.get(track, TRACK_PROMPTS['business'])}

FINDING:
Title: {title}
Text: {text}

Respond with EXACTLY one line in this format:
KEEP|reason why this is valuable
or
REJECT|reason why this is not relevant

Be strict. Only KEEP findings that contain specific, actionable intelligence."""

        resp = requests.post('https://api.anthropic.com/v1/messages', headers={
            'x-api-key': API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json'
        }, json={
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 100,
            'messages': [{'role': 'user', 'content': prompt}]
        }, timeout=15)

        if resp.status_code == 200:
            result = resp.json()['content'][0]['text'].strip()
            if result.startswith('KEEP'):
                return 'keep', result.split('|', 1)[1].strip() if '|' in result else 'Haiku: relevant'
            return 'reject', result.split('|', 1)[1].strip() if '|' in result else 'Haiku: not relevant'
    except Exception as e:
        print(f'  Haiku error: {e}')
    return classify_local(title, text, track)

# ============================================================
# LOCAL CLASSIFIER (200+ patterns fallback)
# ============================================================

NICHE_PAIN = ['struggling','can\'t get clients','no clients','burnout','frustrated','impostor','fraud',
    'quit','give up','broke','stuck','overwhelmed','confused','lost','failing','zero dms','no leads',
    'no engagement','not growing','plateaued','exhausted','underpaid','overworked','imposter syndrome',
    'comparison trap','self doubt','no systems','disorganized','unpredictable income','feast or famine',
    'trading time for money','can\'t scale','working too hard','no referrals','dead leads','ghost',
    'not converting','low conversion','bad clients','toxic clients','scope creep','undercharging',
    'afraid to charge','money mindset','broke coach','free coaching','giving away','not valued',
    'invisible online','algorithm','shadow banned','content not working','posting every day',
    'no one sees','crickets','no comments','no saves','no shares','wasting time on social media']

NICHE_GOALS = ['scale','10k','20k','50k','100k','full time','freedom','grow','first client',
    'consistent income','predictable','systems','automate','passive income','group coaching',
    'high ticket','premium pricing','raise prices','6 figures','quit 9 to 5','leave job',
    'financial freedom','time freedom','location freedom','laptop lifestyle','online business',
    'recurring revenue','monthly recurring','subscription','community','membership','course',
    'digital product','leverage','hire','team','delegate','ceo mindset','business owner']

NICHE_IDENTITY = ['i am a coach','as a trainer','my coaching business','online coaching',
    'fitness business','pt business','personal training business','coaching practice',
    'online trainer','virtual training','remote coaching','certified trainer','nasm','ace',
    'issa','cscs','coaching certification','fitness cert','cpt']

COMP_STRATEGY = ['vince del monte','bedros keuilian','charlie johnson','brian mark',
    'fitness coach mentor','fitness business coach','online fitness coach program',
    'fitness coach community','fitness coaching mentorship','help fitness coaches',
    'fitness coach clients','fitness business mentor','fitness entrepreneur',
    'strategy','funnel','offer','program','course','community','content','youtube',
    'instagram','tiktok','hook','thumbnail','launch','revenue','growth','audience',
    'email list','webinar','vsl','sales page','landing page','lead magnet',
    'challenge','masterclass','workshop','coaching call','discovery call','application',
    'high ticket close','objection handling','sales script','dm strategy',
    'testimonial','case study','transformation','before after','social proof',
    'authority','positioning','niche down','ideal client avatar']

BUSI_STRATEGY = ['hormozi','alex hormozi','charlie morgan','dan martell','sam ovens','daniel dalen',
    'entrepreneur','entrepreneurship','business growth','scaling business','revenue',
    'profit margin','cash flow','sales funnel','lead generation','content strategy',
    'personal brand','creator economy','youtube strategy','social media strategy',
    'ai tools','artificial intelligence','automation','productivity','deep work',
    'marketing strategy','offer creation','pricing strategy','team building','hiring',
    'delegation','systems thinking','business model','startup','bootstrapped',
    'mastermind','accountability','mindset','discipline','habits','morning routine',
    'networking','joint venture','affiliate','passive income','investment',
    'business news','tech news','ai news','creator tips','audience growth']

def classify_local(title, text, track):
    combined = (title + ' ' + text).lower()
    if track == 'niche':
        pain     = sum(1 for w in NICHE_PAIN     if w in combined)
        goal     = sum(1 for w in NICHE_GOALS    if w in combined)
        identity = sum(1 for w in NICHE_IDENTITY if w in combined)
        score = pain * 2 + goal + identity
        if score >= 2:
            return 'keep', f'Local score {score}: {pain} pain, {goal} goal, {identity} identity'
        return 'reject', f'Local score {score}: below threshold'
    elif track == 'competitor':
        strat = sum(1 for w in COMP_STRATEGY if w in combined)
        if strat >= 2:
            return 'keep', f'Local score {strat}: competitor strategy markers'
        return 'reject', f'Local score {strat}: below threshold'
    else:  # business
        strat = sum(1 for w in BUSI_STRATEGY if w in combined)
        if strat >= 2:
            return 'keep', f'Local score {strat}: business insight markers'
        return 'reject', f'Local score {strat}: below threshold'

# ============================================================
# HELPERS
# ============================================================

def load_json(path):
    if os.path.exists(path):
        try: return json.loads(open(path, 'r', encoding='utf-8').read())
        except: pass
    return {'entries': [], 'stats': {'scanned': 0, 'kept': 0, 'rejected': 0, 'last_scan': None}}

def save_json(path, data):
    data['entries'] = data['entries'][-300:]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def h(text): return hashlib.md5(text[:200].encode()).hexdigest()

def load_seen():
    p = os.path.join(DATA_DIR, 'seen_hashes.json')
    if os.path.exists(p):
        try: return set(json.loads(open(p).read()))
        except: pass
    return set()

def save_seen(seen):
    with open(os.path.join(DATA_DIR, 'seen_hashes.json'), 'w') as f:
        json.dump(list(seen)[-8000:], f)

def add_finding(seen, log, source, title, text, url, track):
    hh = h(title + text)
    if hh in seen: return 0
    seen.add(hh)
    log['stats']['scanned'] += 1
    status, reason = classify_with_haiku(title, text, track)
    log['entries'].append({
        'source': source, 'title': title[:200], 'text': text[:300],
        'url': url, 'time': datetime.utcnow().isoformat(),
        'status': status, 'reason': reason, 'track': track
    })
    if status == 'keep':
        log['stats']['kept'] += 1
        return 1
    log['stats']['rejected'] += 1
    return 0

# ============================================================
# PLATFORM SCRAPERS
# ============================================================

def scrape_reddit(subs, terms_unused, seen, log, track):
    count = 0
    for sub in subs:
        try:
            r = requests.get(f'https://www.reddit.com/r/{sub}/new.json?limit=25', headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            for post in r.json().get('data', {}).get('children', []):
                p = post.get('data', {})
                count += add_finding(seen, log, f'Reddit r/{sub}', p.get('title',''), p.get('selftext','')[:500], f"https://reddit.com{p.get('permalink','')}", track)
            time.sleep(2)
        except: pass
    return count

def scrape_youtube(terms, seen, log, track):
    count = 0
    for term in terms[:4]:
        try:
            r = requests.get(f'https://www.youtube.com/results?search_query={quote_plus(term)}&sp=CAI', headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            for title in re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', r.text)[:8]:
                count += add_finding(seen, log, 'YouTube', title, f'Search: {term}', '', track)
            time.sleep(2)
        except: pass
    return count

def scrape_google(queries, seen, log, track):
    count = 0
    for q in queries[:3]:
        try:
            r = requests.get(f'https://www.google.com/search?q={quote_plus(q)}&tbs=qdr:w', headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for res in soup.select('h3')[:8]:
                title = res.get_text()
                if title: count += add_finding(seen, log, 'Google', title, f'Search: {q[:50]}', '', track)
            time.sleep(3)
        except: pass
    return count

def scrape_platform_google(platform, queries, seen, log, track):
    count = 0
    for q in queries[:2]:
        try:
            r = requests.get(f'https://www.google.com/search?q={quote_plus(q)}&tbs=qdr:m', headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for res in soup.select('h3')[:6]:
                title = res.get_text()
                if title: count += add_finding(seen, log, platform, title, f'Search: {q[:50]}', '', track)
            time.sleep(3)
        except: pass
    return count

# ============================================================
# MAIN
# ============================================================

def run():
    print(f'=== Geuphoria Research Scraper v3 ===')
    print(f'Time: {datetime.utcnow().isoformat()}')
    print(f'AI: {"Haiku API" if API_KEY else "Local classifier (no API key)"}')

    seen = load_seen()

    # ---- TRACK 1: NICHE RESEARCH ----
    print('\n--- TRACK 1: NICHE (online fitness coach pain points & goals) ---')
    niche = load_json(NICHE_LOG)
    total_n = 0

    total_n += scrape_reddit(['personaltraining','fitnessbusiness','onlinepersonaltraining','personaltrainers','Entrepreneur','smallbusiness'], [], seen, niche, 'niche')
    total_n += scrape_youtube(['online fitness coach struggling','fitness coach getting clients','online coaching business tips','fitness coach burnout','online trainer marketing'], seen, niche, 'niche')
    total_n += scrape_google(['"online fitness coach" problems OR struggling OR burnout','online fitness coach client acquisition 2026','personal trainer business challenges'], seen, niche, 'niche')
    total_n += scrape_platform_google('LinkedIn',   ['online fitness coach site:linkedin.com','personal trainer business advice site:linkedin.com'], seen, niche, 'niche')
    total_n += scrape_platform_google('Quora',      ['online fitness coach site:quora.com','personal trainer business site:quora.com'], seen, niche, 'niche')
    total_n += scrape_platform_google('Medium',     ['online fitness coaching site:medium.com','fitness coach business tips site:medium.com'], seen, niche, 'niche')
    total_n += scrape_platform_google('Twitter/X',  ['online fitness coach site:twitter.com OR site:x.com','fitness coach clients site:twitter.com'], seen, niche, 'niche')
    total_n += scrape_platform_google('Facebook',   ['online fitness coach group site:facebook.com','fitness coaching business site:facebook.com'], seen, niche, 'niche')
    total_n += scrape_platform_google('Skool',      ['online fitness coach site:skool.com','fitness coaching community site:skool.com'], seen, niche, 'niche')
    total_n += scrape_platform_google('Instagram',  ['online fitness coach site:instagram.com','fitness coach tips site:instagram.com'], seen, niche, 'niche')

    niche['stats']['last_scan'] = datetime.utcnow().isoformat()
    niche['stats']['platforms'] = ['Reddit','YouTube','Google','LinkedIn','Quora','Medium','Twitter/X','Facebook','Skool','Instagram']
    save_json(NICHE_LOG, niche)
    print(f'Niche: {total_n} new kept | Total: {niche["stats"]["kept"]} kept, {niche["stats"]["rejected"]} rejected')

    # ---- TRACK 2: COMPETITOR RESEARCH ----
    print('\n--- TRACK 2: COMPETITOR (fitness coach business mentors) ---')
    comp = load_json(COMP_LOG)
    total_c = 0

    total_c += scrape_youtube([
        'Vince Del Monte fitness coach',
        'Bedros Keuilian online fitness',
        'Charlie Johnson fitness business',
        'Brian Mark fitness coaching',
        'fitness coach mentor program',
        'online fitness coach business mentor',
    ], seen, comp, 'competitor')
    total_c += scrape_google([
        '"fitness coach" mentor program 2026',
        '"Vince Del Monte" OR "Bedros Keuilian" OR "Brian Mark" fitness coach',
        'online fitness coach business coaching program review',
    ], seen, comp, 'competitor')
    total_c += scrape_reddit(['fitnessbusiness','personaltraining','onlinepersonaltraining'], [], seen, comp, 'competitor')
    total_c += scrape_platform_google('LinkedIn',  ['fitness business mentor site:linkedin.com','online fitness coach program site:linkedin.com'], seen, comp, 'competitor')
    total_c += scrape_platform_google('Twitter/X', ['"Vince Del Monte" site:twitter.com','fitness coach mentor site:x.com'], seen, comp, 'competitor')
    total_c += scrape_platform_google('Quora',     ['fitness coaching business mentor site:quora.com','online coaching program review site:quora.com'], seen, comp, 'competitor')
    total_c += scrape_platform_google('Medium',    ['fitness business coaching site:medium.com','online coach scaling site:medium.com'], seen, comp, 'competitor')
    total_c += scrape_platform_google('Facebook',  ['fitness coach mentor group site:facebook.com','online fitness coaching community site:facebook.com'], seen, comp, 'competitor')
    total_c += scrape_platform_google('Instagram', ['"charliejohnsonfitness" OR "therealbrianmark" OR "vincedelmonte" site:instagram.com','fitness coach mentor site:instagram.com'], seen, comp, 'competitor')
    total_c += scrape_platform_google('Skool',     ['fitness coaching mentor site:skool.com','online fitness coach community site:skool.com'], seen, comp, 'competitor')

    comp['stats']['last_scan'] = datetime.utcnow().isoformat()
    comp['stats']['platforms'] = ['YouTube','Google','Reddit','LinkedIn','Twitter/X','Quora','Medium','Facebook','Instagram','Skool']
    save_json(COMP_LOG, comp)
    print(f'Competitor: {total_c} new kept | Total: {comp["stats"]["kept"]} kept, {comp["stats"]["rejected"]} rejected')

    # ---- TRACK 3: BUSINESS RESEARCH ----
    print('\n--- TRACK 3: BUSINESS (Hormozi, Morgan, Martell, Ovens, Dalen + biz/AI news) ---')
    busi = load_json(BUSI_LOG)
    total_b = 0

    total_b += scrape_youtube([
        'Alex Hormozi',
        'Charlie Morgan business',
        'Dan Martell',
        'Sam Ovens',
        'Daniel Dalen',
        'business growth tips 2026',
        'AI tools for business 2026',
    ], seen, busi, 'business')
    total_b += scrape_google([
        'business news today 2026',
        'AI tools entrepreneurs 2026',
        'entrepreneur growth strategies 2026',
    ], seen, busi, 'business')
    total_b += scrape_reddit(['Entrepreneur','startups','marketing','artificial','MachineLearning','smallbusiness'], [], seen, busi, 'business')
    total_b += scrape_platform_google('LinkedIn',  ['Alex Hormozi site:linkedin.com','entrepreneur business growth site:linkedin.com'], seen, busi, 'business')
    total_b += scrape_platform_google('Twitter/X', ['Alex Hormozi site:twitter.com','Dan Martell site:x.com'], seen, busi, 'business')
    total_b += scrape_platform_google('Quora',     ['business growth strategies site:quora.com','entrepreneur advice site:quora.com'], seen, busi, 'business')
    total_b += scrape_platform_google('Medium',    ['business growth site:medium.com','entrepreneurship lessons site:medium.com'], seen, busi, 'business')
    total_b += scrape_platform_google('YouTube',   ['"Alex Hormozi" site:youtube.com','"Charlie Morgan" business site:youtube.com'], seen, busi, 'business')
    total_b += scrape_platform_google('Instagram', ['Alex Hormozi site:instagram.com','business tips entrepreneur site:instagram.com'], seen, busi, 'business')
    total_b += scrape_platform_google('Twitter/X', ['Charlie Morgan site:twitter.com','Sam Ovens site:x.com'], seen, busi, 'business')

    busi['stats']['last_scan'] = datetime.utcnow().isoformat()
    busi['stats']['platforms'] = ['YouTube','Google','Reddit','LinkedIn','Twitter/X','Quora','Medium','Instagram']
    save_json(BUSI_LOG, busi)
    print(f'Business: {total_b} new kept | Total: {busi["stats"]["kept"]} kept, {busi["stats"]["rejected"]} rejected')

    # ---- SAVE COMBINED ----
    kept = load_json(KEPT_FILE)
    all_kept  = [e for e in niche.get('entries', []) if e.get('status') == 'keep']
    all_kept += [e for e in comp.get('entries',  []) if e.get('status') == 'keep']
    all_kept += [e for e in busi.get('entries',  []) if e.get('status') == 'keep']
    kept['entries'] = all_kept[-500:]
    kept['stats'] = {
        'niche_kept':      niche['stats']['kept'],
        'niche_rejected':  niche['stats']['rejected'],
        'niche_scanned':   niche['stats']['scanned'],
        'comp_kept':       comp['stats']['kept'],
        'comp_rejected':   comp['stats']['rejected'],
        'comp_scanned':    comp['stats']['scanned'],
        'busi_kept':       busi['stats']['kept'],
        'busi_rejected':   busi['stats']['rejected'],
        'busi_scanned':    busi['stats']['scanned'],
        'last_scan':       datetime.utcnow().isoformat(),
        'total_kept':      niche['stats']['kept'] + comp['stats']['kept'] + busi['stats']['kept'],
        'total_rejected':  niche['stats']['rejected'] + comp['stats']['rejected'] + busi['stats']['rejected'],
        'ai_model':        'claude-haiku-4-5' if API_KEY else 'local-classifier',
        'niche_platforms': niche['stats'].get('platforms', []),
        'comp_platforms':  comp['stats'].get('platforms', []),
        'busi_platforms':  busi['stats'].get('platforms', []),
    }
    save_json(KEPT_FILE, kept)
    save_seen(seen)
    print(f'\n=== Done. Total kept: {kept["stats"]["total_kept"]} | AI: {"Haiku" if API_KEY else "Local"} ===')

if __name__ == '__main__':
    run()
