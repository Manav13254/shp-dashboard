from app import create_app
from app.scheduler import init_scheduler

app = create_app()

# Only run the in-app daily scraper on hosts where ENABLE_SCRAPER=true.
# On the deployed web host this is normally off (NSE 403-blocks most cloud
# IPs) — run local_refresh.py from a non-blocked machine instead, on a cron
# job, to do the actual scraping against the same remote database.
if app.config.get("ENABLE_SCRAPER"):
    init_scheduler(app)

if __name__ == "__main__":
    # host=0.0.0.0 so it's reachable if you deploy this on a server/VM
    app.run(host="0.0.0.0", port=5000, debug=False)
