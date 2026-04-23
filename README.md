# Job Monitor

An automated tool that checks multiple job boards for software engineering roles matching your qualifications and sends notifications to your email and phone whenever a new match is posted.

## Features

- **Multiple sources**: Fetches jobs from Greenhouse, Lever, and RSS feeds (RemoteOK, WeWorkRemotely)
- **Smart filtering**: Matches jobs by required keywords, blocked keywords, location, and max years of experience
- **Deduplication**: Uses a local SQLite database so you're only notified about genuinely new postings
- **Notifications**: Sends a consolidated email via Gmail and a push notification via Pushover
- **Free to run**: No paid APIs required (Pushover is a one-time $5 if you want phone alerts)

## Tech Stack

- Python 3.9+
- `requests` — HTTP client for API calls
- `feedparser` — RSS feed parsing
- `sqlite3` — built-in, for deduplication
- `smtplib` — built-in, for email
- `python-dotenv` — for managing secrets

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd job-monitor
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up credentials

Copy the example env file and fill in your real values:

```bash
cp .env.example .env
```

Then edit `.env`:

```
EMAIL_FROM=youremail@gmail.com
EMAIL_APP_PASSWORD=your-16-char-app-password
EMAIL_TO=youremail@gmail.com
PUSHOVER_USER_KEY=your-pushover-user-key
PUSHOVER_APP_TOKEN=your-pushover-app-token
```

**Getting a Gmail App Password:**

1. Enable 2-Step Verification on your Google account
2. Visit [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Generate a new app password and paste it into `.env` (remove spaces)

**Getting Pushover keys:**

1. Install the Pushover app on your phone
2. Log in at [pushover.net](https://pushover.net) and copy your User Key
3. Create a new Application to get an API Token

## Configuration

Open `job-monitor.py` and adjust these settings at the top:

```python
KEYWORDS_REQUIRED = ["typescript", "react", "javascript"]   # job must match at least one
KEYWORDS_BLOCKED  = ["senior", "staff", "principal", "manager"]  # skip these (checked in title only)
LOCATIONS_OK      = ["remote", "new york", "nyc"]
MAX_YEARS_REQUIRED = 4   # skip jobs requiring more than this many years
```

### Companies to monitor

Add or remove company slugs in `GREENHOUSE_COMPANIES` and `LEVER_COMPANIES`. To verify a company uses Greenhouse, visit:

```
https://boards-api.greenhouse.io/v1/boards/COMPANY-SLUG/jobs
```

If you see JSON with a `jobs` array, the slug works.

## Running

### Manually

```bash
python3 job-monitor.py
```

On the first run, every matching job will be treated as new. If that's too many notifications, comment out `send_push(new_matches)` for the first run to silently populate the database.

### On a schedule

**Option 1: cron (macOS/Linux)** — runs every 30 minutes:

```bash
crontab -e
```

Add:

```
*/30 * * * * cd /path/to/job-monitor && ./venv/bin/python job-monitor.py >> log.txt 2>&1
```

**Option 2: GitHub Actions** — runs in the cloud, no local machine required. See `.github/workflows/check.yml` (create one if needed; add your `.env` values as repo secrets).

## Project Structure

```
job-monitor/
├── .env                    # your secrets (never commit)
├── .env.example            # template for secrets
├── .gitignore
├── job-monitor.py          # main script
├── jobs_seen.db            # SQLite dedup store (auto-created)
├── requirements.txt
└── README.md
```

## How It Works

1. **Fetch**: Each run, the script queries every configured Greenhouse, Lever, and RSS source
2. **Dedupe**: Each job has a stable ID; if it's already in `jobs_seen.db`, it's skipped
3. **Filter**: Jobs must match your keyword, location, and experience filters
4. **Notify**: New matches are sent as a single email and a Pushover notification
5. **Record**: All seen jobs (matched or not) are saved to prevent future re-notification

## Troubleshooting

- **`KeyError: 'EMAIL_FROM'`** — your `.env` file is missing or `load_dotenv()` isn't being called
- **`SMTPAuthenticationError`** — your Gmail app password is wrong; regenerate it
- **`0 new matches`** — your filters are too strict, or dedupe already caught these jobs. Delete `jobs_seen.db` and adjust keywords
- **Lots of `Greenhouse X failed` errors** — the company slug is wrong or they no longer use Greenhouse; remove them from the list
- **Pushover not arriving** — verify the app is logged in on your phone and system notifications are enabled

## Ideas for Future Improvements

- LLM-based matching: score each job against your resume using the Claude or OpenAI API
- Add more sources: Ashby, Workday, SmartRecruiters, LinkedIn RSS from saved searches
- Salary extraction from descriptions
- Weekly digest mode as an alternative to instant alerts
- Simple Streamlit dashboard to review jobs and mark them "applied"

## Legal Note

This tool uses **public APIs** (Greenhouse and Lever provide open job board APIs) and **RSS feeds**. It does not scrape sites that prohibit automated access. Do not use this tool to scrape LinkedIn, Indeed, or other sites whose Terms of Service prohibit automated access.

## License

Personal use. Adapt freely.
