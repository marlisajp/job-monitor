import requests
import feedparser
import sqlite3
import smtplib
import re
import os
from email.mime.text import MIMEText
from datetime import datetime
from hashlib import sha256
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()

# ---------- CONFIG ----------
KEYWORDS_REQUIRED = ["typescript", "javascript", "react", "frontend", "backend", "full stack", "software engineer", "full stack developer", "full stack software engineer", "product engineer"]  
KEYWORDS_BLOCKED  = ["senior", "principal", "manager", "staff", "sr.", "director", "lead", "head"] 
LOCATIONS_OK      = ["remote", "new york", "nyc", "ny"]
MAX_YEARS_REQUIRED         = 4     

GREENHOUSE_COMPANIES = ["spacex", "databricks", "stripe", "cloudflare", "anthropic", "mongodb", "datadog", "samsara", "oscar", "airbnb", "brex", "gitlab", "elastic", "pinterest", "figma", "affirm", "robinhood", "reddit", "asana", "instacart", "coinbase", "dropbox", "duolingo", "discord", "gusto", "chime", "vercel", "faire", "mercury", "twitch", "checkr", "carta", "fastly", "newrelic", "airtable", "pagerduty", "mixpanel", "launchdarkly", "thumbtack", "amplitude", "squarespace", "nextdoor", "alloy", "pendo", "circleci", "consensys", "modernhealth", "clever", "medium", "kickstarter", "harrys", "mammothbrands"]

LEVER_COMPANIES      = ["netflix", "ramp"]
RSS_FEEDS = [
    "https://remoteok.com/remote-dev-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
]

DB_PATH = "jobs_seen.db"

# ---------- DEDUP STORE ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS seen
                    (id TEXT PRIMARY KEY, seen_at TEXT)""")
    conn.commit()
    return conn

def is_new(conn, job_id):
    cur = conn.execute("SELECT 1 FROM seen WHERE id=?", (job_id,))
    return cur.fetchone() is None

def mark_seen(conn, job_id):
    conn.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)",
                 (job_id, datetime.utcnow().isoformat()))
    conn.commit()

MAX_AGE_MINUTES = 70

def is_recent(job):
    """Return True if the job was posted within MAX_AGE_MINUTES."""
    if not job.get("updated_at"):
        return False  # no timestamp → skip to be safe
    try:
        posted = datetime.fromisoformat(job["updated_at"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - posted
        return age < timedelta(minutes=MAX_AGE_MINUTES)
    except Exception as e:
        print(f"Could not parse timestamp {job['updated_at']}: {e}")
        return False

# ---------- FETCHERS ----------
def fetch_greenhouse(company):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    try:
        r = requests.get(url, timeout=10)
        for j in r.json().get("jobs", []):
            yield {
                "id": f"gh-{company}-{j['id']}",
                "title": j["title"],
                "company": company,
                "location": j.get("location", {}).get("name", ""),
                "url": j["absolute_url"],
                "description": j.get("content", ""),
                "updated_at": j.get("updated_at"),  # ISO format string
            }
    except Exception as e:
        print(f"Greenhouse {company} failed: {e}")

def fetch_lever(company):
    url = f"https://api.lever.co/v0/postings/{company}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if not isinstance(data, list):
            print(f"Lever {company}: unexpected response format")
            return
        for j in data:
            created_ms = j.get("createdAt")
            updated_iso = None
            if created_ms:
                updated_iso = datetime.fromtimestamp(
                    created_ms / 1000, tz=timezone.utc
                ).isoformat()
            yield {
                "id": f"lever-{company}-{j['id']}",
                "title": j["text"],
                "company": company,
                "location": j.get("categories", {}).get("location", ""),
                "url": j["hostedUrl"],
                "description": j.get("descriptionPlain", ""),
                "updated_at": updated_iso,
            }
    except Exception as e:
        print(f"Lever {company} failed: {e}")

def fetch_rss(url):
    feed = feedparser.parse(url)
    for entry in feed.entries:
        updated_iso = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            updated_iso = datetime(
                *entry.published_parsed[:6], tzinfo=timezone.utc
            ).isoformat()
        yield {
            "id": f"rss-{sha256(entry.link.encode()).hexdigest()[:16]}",
            "title": entry.title,
            "company": entry.get("author", "unknown"),
            "location": "",
            "url": entry.link,
            "description": entry.get("summary", ""),
            "updated_at": updated_iso,
        }

# ---------- FILTER ----------
def matches(job):
    title = job["title"].lower()
    full_text = f"{job['title']} {job['description']} {job['location']}".lower()

    # Required keywords: check anywhere
    if KEYWORDS_REQUIRED and not any(k in full_text for k in KEYWORDS_REQUIRED):
        return False

    # Blocked keywords: only check the TITLE (not description)
    if any(b in title for b in KEYWORDS_BLOCKED):
        return False

    # Location: check anywhere
    if LOCATIONS_OK and not any(loc in full_text for loc in LOCATIONS_OK):
        return False

    if MAX_YEARS_REQUIRED:
        m = re.search(r"(\d+)\+?\s*years", full_text)
        if m and int(m.group(1)) > MAX_YEARS_REQUIRED:
            return False
    return True

# ---------- NOTIFIER ----------
def send_email(jobs):
    if not jobs:
        return
    body = "\n\n".join(
        f"{j['title']} @ {j['company']}\n{j['location']}\n{j['url']}"
        for j in jobs
    )
    msg = MIMEText(body)
    msg["Subject"] = f"🚨 {len(jobs)} new job(s) matched"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"]   = os.environ["EMAIL_TO"]

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(os.environ["EMAIL_FROM"], os.environ["EMAIL_APP_PASSWORD"])
        s.send_message(msg)

def send_push(jobs):
    if not jobs:
        return

    lines = []
    for j in jobs[:5]:
        lines.append(
            f'<a href="{j["url"]}">{j["title"]}</a> @ {j["company"]} '
            f'<i>({j["location"] or "no location"})</i>'
        )

    message = "<br>".join(lines)
    if len(jobs) > 5:
        message += f"<br><br>+{len(jobs) - 5} more — check email"

    requests.post("https://api.pushover.net/1/messages.json", data={
        "token": os.environ["PUSHOVER_APP_TOKEN"],
        "user": os.environ["PUSHOVER_USER_KEY"],
        "title": f"🚨 {len(jobs)} new job match(es)",
        "message": message,
        "html": 1,  # <-- this enables HTML parsing
    })

# ---------- MAIN ----------
def run():
    new_matches = []

    sources = (
        [fetch_greenhouse(c) for c in GREENHOUSE_COMPANIES] +
        [fetch_lever(c)      for c in LEVER_COMPANIES] +
        [fetch_rss(u)        for u in RSS_FEEDS]
    )

    for source in sources:
        for job in source:
            if is_recent(job) and matches(job):
                new_matches.append(job)

    print(f"Found {len(new_matches)} new matches in the last {MAX_AGE_MINUTES} minutes")
    if new_matches:
        send_email(new_matches)
        send_push(new_matches)

if __name__ == "__main__":
    run()