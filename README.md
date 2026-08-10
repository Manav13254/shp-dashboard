# Shareholding Pattern Dashboard

Tracks Retail (≤₹2L) / Promoter / FII / DII shareholding % across all NSE
equity stocks, diffed quarter-over-quarter, sorted by biggest retail-holding
decrease first.

## Setup

```bash
pip install -r requirements.txt
```

## First-time run (bootstrap)

Populates every NSE stock with its latest 2 quarterly filings so the
dashboard has Change % from day one. This can take a while (~2000 stocks,
2 XBRL downloads each, rate-limited).

```bash
python bootstrap.py
```

## Run the app

```bash
python run.py
```

Then open http://localhost:5000

This starts the Flask server AND the background scheduler, which will
automatically re-check every stock daily at 9 PM (configurable in
`config.py` via `REFRESH_HOUR` / `REFRESH_MINUTE`). Each check compares the
latest filing's submission date against what's stored — if unchanged,
nothing is re-downloaded; if a new filing appeared, it's parsed and the
dashboard updates.

## How it works

1. `app/scraper.py` uses the `nse` PyPI package to talk to NSE (handles
   session/cookies automatically) and fetch each stock's list of quarterly
   shareholding filings (`nse.shareholding(symbol)`).
2. For the latest 1-2 filings, it downloads the linked XBRL file and parses
   it (`app/xbrl_parser.py`) to pull out Promoter / FII / DII / Retail %
   using the standard `in-bse-shp` XBRL taxonomy context IDs.
3. Results are stored in SQLite via SQLAlchemy (`app/models.py`) -
   swappable for Postgres by changing `DATABASE_URL` in `config.py`.
4. `app/routes.py` serves the dashboard + a JSON API the frontend polls.
5. `app/scheduler.py` (APScheduler) runs the daily 9PM incremental refresh
   inside the same process - no external cron needed.

## Notes

- The `nse` library writes cookie files to `NSE_DOWNLOAD_FOLDER`
  (`config.py`) - don't delete this between runs or every request will
  re-authenticate from scratch.
- `SCRAPE_CONCURRENCY` / `REQUEST_DELAY` in `config.py` control how gently
  we hit NSE. Increase delay if you start seeing failures/blocks.
- Manual triggers available at `POST /api/refresh` (incremental) and
  `POST /api/bootstrap` (full re-fetch of symbol list + all filings).
