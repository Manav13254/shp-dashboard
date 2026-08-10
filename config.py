import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Postgres connection string. Set DATABASE_URL in your environment, e.g.:
    #   postgresql+psycopg2://user:password@localhost:5432/shp_dashboard
    # Falls back to a local default for convenience during development.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        # SQLite default — works locally with zero setup.
        # For production, set DATABASE_URL=postgresql+psycopg2://user:pass@host/dbname
        "sqlite:///" + os.path.join(BASE_DIR, "shp_dashboard.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 30,
        "max_overflow": 50,
        "pool_pre_ping": True,  # avoids stale-connection errors after idle periods
        "pool_recycle": 280,
    }

    # Folder where nse/bse libs store cookies + we store downloaded XBRL files
    NSE_DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "nse_downloads")
    BSE_DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "bse_downloads")

    # Daily refresh time (24h, local server time)
    REFRESH_HOUR = 21  # 9 PM
    REFRESH_MINUTE = 0

    # How many worker threads to use when fetching stocks
    SCRAPE_CONCURRENCY = 15

    # Delay (seconds) between requests per worker, to avoid rate limiting/bans
    REQUEST_DELAY = 0.5

    # Whether THIS process is allowed to scrape NSE itself (bootstrap thread +
    # daily APScheduler job). Leave this OFF on the deployed web host, since
    # NSE blocks most cloud/datacenter IPs with a 403 regardless of headers.
    # Turn it ON only on the machine you actually want scraping from
    # (e.g. your local machine, via local_refresh.py, or set
    # ENABLE_SCRAPER=true in env if you deploy somewhere NSE doesn't block).
    ENABLE_SCRAPER = os.environ.get("ENABLE_SCRAPER", "false").lower() == "true"

    # Shared secret required to POST scraped data to /api/sync. Set this in
    # your Render web service's environment variables, and use the SAME
    # value in .env.local on your local machine. If unset, /api/sync is
    # disabled entirely (safer default than leaving it open).
    SYNC_SECRET = os.environ.get("SYNC_SECRET")
