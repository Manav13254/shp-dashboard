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
