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
KEYWORDS_REQUIRED = ["typescript", "javascript", "react", "frontend", "backend", "full stack", "software engineer", "full stack developer", "full stack software engineer", "product engineer", "entry", "software engineer I", "software engineer II", "software engineer 2", "software engineer 1", "senior software engineer", "senior engineer" ]  
KEYWORDS_BLOCKED  = ["principal", "manager", "staff", "director", "lead", "head", "C++", "iOS"] 
LOCATIONS_OK      = ["remote", "new york", "nyc", "ny"]
MAX_YEARS_REQUIRED         = 4;    

GREENHOUSE_COMPANIES = [
    # your existing list (removed thumbtack and amplitude, which return 404)
    "spacex", "databricks", "stripe", "cloudflare", "anthropic", "mongodb", "datadog", "samsara", "oscar", "airbnb",
    "brex", "gitlab", "elastic", "pinterest", "figma", "affirm", "robinhood", "reddit", "asana", "instacart",
    "coinbase", "dropbox", "duolingo", "discord", "gusto", "chime", "vercel", "faire", "mercury", "twitch",
    "checkr", "carta", "fastly", "newrelic", "airtable", "pagerduty", "mixpanel", "launchdarkly", "squarespace", "nextdoor",
    "alloy", "pendo", "circleci", "consensys", "modernhealth", "clever", "medium", "kickstarter", "harrys", "mammothbrands",

    # big tech / consumer
    "doordashusa", "lyft", "roblox", "tripadvisor", "hubspotjobs", "twilio", "okta", "zscaler", "toast", "block",
    "epicgames", "riotgames", "scopely", "peloton", "seatgeek", "stockx", "oura", "intercom", "smartsheet", "zoominfo",
    "appian", "lucidsoftware", "wrike", "coursera", "calendly", "yext", "braze", "klaviyo", "attentive", "postscript",
    "yotpo", "hellofresh", "thrivemarket", "misfitsmarket", "weee", "renttherunway", "sweetgreen",

    # AI / ML / infra
    "xai", "scaleai", "togetherai", "inflectionai", "stabilityai", "coreweave", "snorkelai", "labelbox", "dataiku", "c3iot",
    "typeface", "descript", "grafanalabs", "cribl", "honeycomb", "sumologic", "fivetran", "sigmacomputing", "starburst", "dremio",
    "singlestore", "cockroachlabs", "yugabyte", "planetscale", "neo4j", "algolia", "contentful", "storyblok", "netlify", "buildkite",
    "jfrog", "tailscale", "bitwarden", "backblaze", "wasabi", "purestorage", "rubrik", "druva", "tanium", "wizinc",
    "abnormalsecurity", "sendbird", "bandwidth", "vonage", "dialpad",

    # hardware / robotics / autonomy / aerospace
    "andurilindustries", "waymo", "nuro", "kodiak", "lucidmotors", "rocketlab", "astranis", "planetlabs", "verkada", "axon",
    "figureai", "apptronik", "agilityrobotics", "flexport", "project44",

    # fintech / crypto
    "sofi", "upstart", "sezzle", "blend", "betterment", "stashinvest", "step", "current", "monzo", "n26",
    "adyen", "payoneer", "billcom", "lithic", "highnote", "treasuryprime", "alpaca", "drivewealth", "tastytrade", "public",
    "gemini", "ripple", "fireblocks", "bitgo",

    # quant / trading
    "janestreet", "jumptrading", "imc", "towerresearchcapital", "point72", "schonfeld", "worldquant", "akunacapital", "flowtraders", "chicagotrading",
    "virtu", "pdtpartners", "vaticlabs", "aqr", "mangroup",

    # health / HR / other SaaS
    "zocdoc", "flatironhealth", "komodohealth", "doximity", "talkspace", "swordhealth", "healthie", "garnerhealth", "justworks", "lattice",
    "cultureamp", "greenhouse", "tripactions", "relativity",
]

LEVER_COMPANIES = [
    "palantir", "spotify", "zoox", "veeva", "sonarsource", "coupa", "jumpcloud", "sysdig", "filevine", "olo",
    "wealthfront", "crypto", "binance", "anchorage", "offchainlabs", "safe", "1inch", "zerion", "immutable", "greenlight",
    "ro", "rover", "outreach", "gopuff", "alltrails", "zilliz", "truv", "secureframe", "twingate", "bazaarvoice",
    "brilliant", "educative", "emburse", "pattern", "cin7", "elroyair", "merlinlabs", "tala", "rigetti", "atomcomputing",
    "lucidworks", "hive", "zeta", "nium", "deputy", "theathletic", "traackr", "wattpad",
]
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

MAX_AGE_MINUTES = 170
# MAX_AGE_MINUTES = 1440

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
    conn = init_db()
    new_matches = []

    sources = (
        [fetch_greenhouse(c) for c in GREENHOUSE_COMPANIES] +
        [fetch_lever(c)      for c in LEVER_COMPANIES] +
        [fetch_rss(u)        for u in RSS_FEEDS]
    )

    for source in sources:
        for job in source:
            if is_new(conn, job["id"]) and is_recent(job) and matches(job):
                new_matches.append(job)
            mark_seen(conn, job["id"])

    print(f"Found {len(new_matches)} new matches in the last {MAX_AGE_MINUTES} minutes")
    if new_matches:
        send_email(new_matches)
        send_push(new_matches)

if __name__ == "__main__":
    run()