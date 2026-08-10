"""
Run the NSE scraper from a machine NSE doesn't block (your local machine),
then push the results to your deployed dashboard over HTTPS.

WHY THIS FILE EXISTS
---------------------
NSE puts most cloud/hosting IP ranges (AWS, GCP, Azure, Render, Railway,
Heroku, etc.) behind a bot-block that returns 403 on every request to
www.nseindia.com, no matter what headers/cookies you send. It does NOT
block ordinary home/ISP IPs. So: the dashboard stays hosted, but the actual
scraping runs from here (using a local SQLite file), and results are then
POSTed to your deployed app's /api/sync endpoint, which writes them into
its own database.

SETUP (one-time)
-----------------
1. On your Render web service, add an environment variable:
       SYNC_SECRET = <any random string, e.g. generate one with:
                       python -c "import secrets; print(secrets.token_urlsafe(32))">
   Redeploy after adding it.

2. In this project folder on your local machine, create a file named
   `.env.local` (already in .gitignore) with:
       DASHBOARD_URL=https://shp-dashboard-1.onrender.com
       SYNC_SECRET=<the exact same random string you set on Render>

3. pip install -r requirements.txt

USAGE
-----
    python local_refresh.py              # incremental refresh (fast, only changed filings)
    python local_refresh.py --bootstrap  # first-time: full symbol list + full scrape

SCHEDULING IT DAILY
--------------------
macOS/Linux (cron) - run `crontab -e` and add:
    0 21 * * * cd /path/to/shp-dashboard && /path/to/venv/bin/python local_refresh.py >> refresh.log 2>&1

Windows (Task Scheduler):
    Create a daily task running:
        python.exe C:\\path\\to\\shp-dashboard\\local_refresh.py
    with "Start in" set to the shp-dashboard folder.
"""

import os
import sys
import logging

import requests

# --- Load .env.local (no python-dotenv dependency needed) -----------------
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
SYNC_SECRET = os.environ.get("SYNC_SECRET", "")

if not DASHBOARD_URL or not SYNC_SECRET:
    print(
        "ERROR: DASHBOARD_URL and/or SYNC_SECRET not set.\n"
        "Create a .env.local file next to this script with:\n"
        "  DASHBOARD_URL=https://your-app.onrender.com\n"
        "  SYNC_SECRET=<same secret you set in Render's env vars>\n"
        "(See the top of local_refresh.py for full setup steps.)"
    )
    sys.exit(1)

# This machine scrapes into its OWN local sqlite db (default config) — never
# touches the deployed app directly. ENABLE_SCRAPER only matters for the
# in-app scheduler/bootstrap thread, which local runs don't use anyway, but
# set it for clarity/consistency.
os.environ["ENABLE_SCRAPER"] = "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local_refresh")

from app import create_app  # noqa: E402
from app.scraper import run_refresh, bootstrap_all_stocks  # noqa: E402
from app.models import Stock, RefreshLog  # noqa: E402

app = create_app()


def push_to_dashboard():
    """Read all locally-scraped stock rows and POST them to /api/sync."""
    with app.app_context():
        stocks = Stock.query.all()
        stocks_payload = [
            {
                "symbol": s.symbol,
                "exchange": s.exchange,
                "company_name": s.company_name,
                "scrip_code": s.scrip_code,
                "last_submission_date": s.last_submission_date,
                "prev_submission_date": s.prev_submission_date,
                "promoter_pct": s.promoter_pct,
                "fii_pct": s.fii_pct,
                "dii_pct": s.dii_pct,
                "retail_latest_pct": s.retail_latest_pct,
                "retail_prev_pct": s.retail_prev_pct,
                "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
                "last_error": s.last_error,
            }
            for s in stocks
        ]

        last_log = RefreshLog.query.order_by(RefreshLog.id.desc()).first()
        log_payload = None
        if last_log:
            log_payload = {
                "stocks_checked": last_log.stocks_checked,
                "stocks_updated": last_log.stocks_updated,
                "stocks_failed": last_log.stocks_failed,
            }

    if not stocks_payload:
        print("No stocks to sync yet (nothing scraped locally). Skipping push.")
        return

    print(f"Pushing {len(stocks_payload)} stock rows to {DASHBOARD_URL}/api/sync ...")
    # Send in batches so the request body doesn't get unreasonably large.
    batch_size = 500
    for i in range(0, len(stocks_payload), batch_size):
        batch = stocks_payload[i:i + batch_size]
        resp = requests.post(
            f"{DASHBOARD_URL}/api/sync",
            json={
                "secret": SYNC_SECRET,
                "stocks": batch,
                # Only attach the refresh_log summary on the last batch.
                "refresh_log": log_payload if (i + batch_size) >= len(stocks_payload) else None,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"ERROR: sync failed (status {resp.status_code}): {resp.text}")
            sys.exit(1)
        print(f"  batch {i // batch_size + 1}: {resp.json()}")

    print("Sync complete.")


if __name__ == "__main__":
    if "--bootstrap" in sys.argv:
        print("Running full bootstrap locally (symbol list + first scrape)...")
        bootstrap_all_stocks(app)
    else:
        print("Running incremental refresh locally...")
        run_refresh(app)

    push_to_dashboard()
    print("Done.")
