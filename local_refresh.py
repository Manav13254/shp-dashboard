"""
Run the NSE scraper from a machine NSE doesn't block (your local machine),
writing results straight into the same database your deployed dashboard reads.

WHY THIS FILE EXISTS
---------------------
NSE puts most cloud/hosting IP ranges (AWS, GCP, Azure, Render, Railway,
Heroku, etc.) behind a bot-block that returns 403 on every request to
www.nseindia.com, no matter what headers/cookies you send. It does NOT
block ordinary home/ISP IPs. So: the dashboard stays hosted, but the actual
scraping runs from here, against the SAME remote database.

SETUP (one-time)
-----------------
1. Get your deployed database's public connection string. On most hosts
   (Render, Railway, Supabase, etc.) this is in your dashboard under the
   Postgres instance -> "External"/"Public" connection string. It looks like:
       postgresql://user:password@host.region.provider.com:5432/dbname

2. Set it as an environment variable before running this script. Easiest
   way: create a file named `.env.local` (same folder as this script,
   already in .gitignore) with one line:
       DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname

   Note the `+psycopg2` after `postgresql` — SQLAlchemy needs that.

3. Install the one extra dependency this needs (already in requirements.txt
   as a comment — uncomment it or just pip install it directly):
       pip install psycopg2-binary

USAGE
-----
    python local_refresh.py            # incremental refresh (fast, only changed filings)
    python local_refresh.py --bootstrap  # first-time full symbol list + refresh

SCHEDULING IT DAILY
--------------------
macOS/Linux (cron) - run `crontab -e` and add a line like:
    0 21 * * * cd /path/to/shp-dashboard && /path/to/venv/bin/python local_refresh.py >> refresh.log 2>&1

Windows (Task Scheduler):
    Create a daily task that runs:
        python.exe C:\\path\\to\\shp-dashboard\\local_refresh.py
    with "Start in" set to the shp-dashboard folder.
"""

import os
import sys
import logging

# Load DATABASE_URL from .env.local if present, without requiring
# python-dotenv as a hard dependency.
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

if not os.environ.get("DATABASE_URL"):
    print(
        "ERROR: DATABASE_URL is not set.\n"
        "Set it in your environment, or create a .env.local file next to this "
        "script with a line like:\n"
        "  DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname\n"
        "(See the top of local_refresh.py for details.)"
    )
    sys.exit(1)

# This machine IS allowed to scrape.
os.environ["ENABLE_SCRAPER"] = "true"

logging.basicConfig(level=logging.INFO)

from app import create_app  # noqa: E402
from app.scraper import run_refresh, bootstrap_all_stocks  # noqa: E402

app = create_app()

if __name__ == "__main__":
    if "--bootstrap" in sys.argv:
        print("Running full bootstrap (symbol list + first refresh)...")
        bootstrap_all_stocks(app)
    else:
        print("Running incremental refresh against remote database...")
        run_refresh(app)
    print("Done.")
