"""
Run this ONCE before first deploying/using the dashboard:

    python bootstrap.py

It fetches the full NSE equity symbol list and populates the DB with each
stock's latest 2 filings (Latest + Prev Qtr), so the dashboard has
Change % populated immediately instead of waiting for two 9PM cycles.

Safe to re-run - stocks already in DB are skipped for the symbol-list step,
and refresh_stock() only re-parses XBRLs when a genuinely new filing exists.
"""

from app import create_app
from app.scraper import bootstrap_all_stocks

if __name__ == "__main__":
    app = create_app()
    print("Starting bootstrap - this will take a while for ~2000 stocks...")
    bootstrap_all_stocks(app)
    print("Bootstrap complete.")
