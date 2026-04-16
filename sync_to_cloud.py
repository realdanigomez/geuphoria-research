"""
Push scraper results to Railway PostgreSQL.
Run after each scraper scan in GitHub Actions.
"""
import os, json, hashlib
import psycopg2

DB_URL = os.environ.get('DATABASE_URL', '')
if not DB_URL:
    print('No DATABASE_URL set, skipping cloud sync')
    exit(0)

conn = psycopg2.connect(DB_URL)
conn.autocommit = True
cur = conn.cursor()

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def sync_track(filename, track):
    """Sync a scraper JSON file to the cloud DB."""
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        print(f'  {filename} not found, skipping')
        return 0

    data = json.loads(open(filepath, 'r', encoding='utf-8').read())
    entries = data.get('entries', [])
    stats = data.get('stats', {})
    added = 0

    for e in entries:
        # Use hash of source+title+text for dedup
        key = f"{e.get('source','')}{e.get('title','')}{e.get('text','')}"
        h = hashlib.md5(key.encode()).hexdigest()

        # Check if already exists
        cur.execute("SELECT id FROM scraper_entries WHERE track=%s AND source=%s AND title=%s LIMIT 1",
                    (track, e.get('source', ''), e.get('title', '')))
        if cur.fetchone():
            continue

        cur.execute(
            """INSERT INTO scraper_entries (track, source, title, body, url, status, reason, scraped_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (track, e.get('source', ''), e.get('title', ''), e.get('text', ''),
             e.get('url', ''), e.get('status', 'keep'), e.get('reason', ''),
             e.get('time'))
        )
        added += 1

    # Update stats
    if stats:
        cur.execute(
            """INSERT INTO scraper_stats (track, stats, updated_at)
               VALUES (%s, %s, NOW())
               ON CONFLICT (track) DO UPDATE SET stats=EXCLUDED.stats, updated_at=NOW()""",
            (track, json.dumps(stats))
        )

    return added


# Sync all tracks
total = 0
for fname, track in [('niche_research.json', 'niche'), ('competitor_research.json', 'competitor'), ('business_research.json', 'business'), ('kept_findings.json', 'combined')]:
    n = sync_track(fname, track)
    total += n
    print(f'  {track}: {n} new entries')

print(f'Cloud sync complete: {total} new entries pushed')
cur.close()
conn.close()
