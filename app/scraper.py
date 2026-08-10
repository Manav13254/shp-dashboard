import logging
import time
import threading
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from nse import NSE

from .models import db, Stock, RefreshLog
from .xbrl_parser import parse_xbrl

logger = logging.getLogger(__name__)


# Patch NSE._setCookies to be fault-tolerant against 403 Forbidden on cloud IPs
def _safe_set_cookies(self):
    try:
        return self._original_set_cookies()
    except Exception as e:
        logger.warning("NSE cookie fetch bypassed (403 on cloud IP): %s", e)
        return {}

if not hasattr(NSE, "_original_set_cookies"):
    NSE._original_set_cookies = NSE._setCookies
    NSE._setCookies = _safe_set_cookies


def get_all_equity_symbols(nse_download_folder):
    """
    Fetch the full list of NSE-listed equity symbols dynamically.
    Uses NSE's official EQUITY_L.csv master list via the `nse` library.
    """
    with NSE(nse_download_folder) as nse:
        nse._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        resp = nse._req(
            "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
        )
        text = resp.text
        lines = text.strip().split("\n")
        header = lines[0].split(",")
        symbol_idx = header.index("SYMBOL")
        name_idx = header.index("NAME OF COMPANY")

        symbols = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(symbol_idx, name_idx):
                continue
            symbols.append(
                {"symbol": parts[symbol_idx].strip(), "name": parts[name_idx].strip()}
            )
        return symbols


def _fetch_and_parse_filing(session, filing):
    """
    Download one NSE filing's XBRL attachment and parse it.
    Returns parsed dict or None.
    """
    xbrl_url = filing.get("xbrl")
    if not xbrl_url:
        return None
    try:
        resp = session._req(xbrl_url)
        content = resp.content
        parsed = parse_xbrl(content)
        parsed["submission_date"] = filing.get("submissionDate")
        return parsed
    except Exception as e:
        logger.warning("Failed to fetch/parse XBRL %s: %s", xbrl_url, e)
        return None


def normalize_date(d_str):
    """Normalize any NSE date string into standard DD-MM-YYYY format."""
    if not d_str:
        return None
    d_str = str(d_str).strip()
    if not d_str:
        return None

    # Already DD-MM-YYYY
    if re.match(r"^\d{2}-\d{2}-\d{4}$", d_str):
        return d_str

    # 1. ISO format: 2026-07-16T19:24:00 or 2026-07-16
    if re.match(r"^\d{4}-\d{2}-\d{2}", d_str):
        try:
            return datetime.strptime(d_str[:10], "%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError:
            pass

    # 2. NSE format: 20-OCT-2025 or 21-JUL-2026
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(d_str, fmt).strftime("%d-%m-%Y")
        except ValueError:
            pass

    return d_str


def refresh_stock(nse_session, stock, request_delay=0.1, db_lock=None):
    """
    Fetch the filings list for an NSE `stock`,
    take the latest 2, parse both, and update the Stock row in place.
    Returns True if changed, False if nothing changed. Thread-safe when db_lock is passed.
    """
    try:
        filings = nse_session.shareholding(stock.symbol)
    except Exception as e:
        logger.warning("filings fetch failed for %s: %s", stock.symbol, e)
        if db_lock:
            with db_lock:
                stock.last_error = str(e)[:500]
                stock.last_checked_at = datetime.utcnow()
                db.session.commit()
        return False

    if not filings:
        if db_lock:
            with db_lock:
                stock.last_checked_at = datetime.utcnow()
                db.session.commit()
        return False

    latest_filing = filings[0]
    latest_submission_date = normalize_date(latest_filing.get("submissionDate"))

    if stock.last_submission_date == latest_submission_date:
        if db_lock:
            with db_lock:
                stock.last_checked_at = datetime.utcnow()
                db.session.commit()
        return False

    latest_parsed = _fetch_and_parse_filing(nse_session, latest_filing)
    if request_delay > 0:
        time.sleep(request_delay)

    prev_parsed = None
    prev_submission_date = None
    if len(filings) > 1:
        prev_filing = filings[1]
        prev_submission_date = normalize_date(prev_filing.get("submissionDate"))
        prev_parsed = _fetch_and_parse_filing(nse_session, prev_filing)
        if request_delay > 0:
            time.sleep(request_delay)

    if latest_parsed is None:
        return False

    def _update():
        stock.company_name = (
            latest_filing.get("company_name") or latest_filing.get("name") or stock.company_name
        )
        stock.last_submission_date = latest_submission_date
        stock.prev_submission_date = prev_submission_date

        stock.promoter_pct = latest_parsed.get("promoter_pct")
        stock.fii_pct = latest_parsed.get("fii_pct")
        stock.dii_pct = latest_parsed.get("dii_pct")
        stock.retail_latest_pct = latest_parsed.get("retail_pct")
        stock.retail_prev_pct = (
            prev_parsed.get("retail_pct") if prev_parsed else stock.retail_prev_pct
        )

        stock.last_checked_at = datetime.utcnow()
        stock.last_error = None
        if not db_lock:
            db.session.commit()

    _update()
    return True


def run_refresh(app, symbols=None, concurrency=None, request_delay=None):
    """
    Parallel multi-threaded refresh for all NSE stocks.
    Uses ThreadPoolExecutor to achieve high throughput across NSE filings.
    """
    concurrency = concurrency or app.config.get("SCRAPE_CONCURRENCY", 10)
    request_delay = request_delay if request_delay is not None else 0.05

    with app.app_context():
        log = RefreshLog(status="running")
        db.session.add(log)
        db.session.commit()
        log_id = log.id

        query = Stock.query
        if symbols is not None:
            query = query.filter(Stock.symbol.in_(symbols))
        stocks = query.all()
        total_count = len(stocks)

        logger.info("Starting refresh for %d NSE stocks with %d parallel workers", total_count, concurrency)

        checked = 0
        updated = 0
        failed = 0
        db_lock = threading.Lock()

        def process_single_stock(stock_id):
            nonlocal checked, updated, failed
            with app.app_context():
                stock_item = db.session.get(Stock, stock_id)
                if not stock_item:
                    return False
                try:
                    changed = refresh_stock(
                        nse_session, stock_item, request_delay=request_delay, db_lock=db_lock
                    )
                    with db_lock:
                        checked += 1
                        if changed:
                            updated += 1
                        # Batch commit every 50 stocks to minimize SQLite lock contention
                        if checked % 50 == 0 or checked == total_count or changed:
                            db.session.commit()
                            cur_log = db.session.get(RefreshLog, log_id)
                            if cur_log:
                                cur_log.stocks_checked = checked
                                cur_log.stocks_updated = updated
                                cur_log.stocks_failed = failed
                                db.session.commit()
                    return changed
                except Exception:
                    logger.exception("Unexpected error refreshing stock ID %s", stock_id)
                    with db_lock:
                        checked += 1
                        failed += 1
                        if checked % 50 == 0 or checked == total_count:
                            db.session.commit()
                    return False

        with NSE(app.config["NSE_DOWNLOAD_FOLDER"]) as nse_session:
            nse_session._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            })
            stock_ids = [s.id for s in stocks]
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(process_single_stock, sid) for sid in stock_ids]
                for _ in as_completed(futures):
                    pass

        # Final log update
        with db_lock:
            cur_log = db.session.get(RefreshLog, log_id)
            if cur_log:
                cur_log.finished_at = datetime.utcnow()
                cur_log.stocks_checked = checked
                cur_log.stocks_updated = updated
                cur_log.stocks_failed = failed
                cur_log.status = "done"
                db.session.commit()

        logger.info(
            "Refresh done: checked=%d updated=%d failed=%d", checked, updated, failed
        )


def bootstrap_all_stocks(app):
    """
    First-time setup: fetch full NSE equity symbol list.
    """
    with app.app_context():
        existing_symbols = set(
            s.symbol.upper() for s in db.session.query(Stock.symbol).all()
        )

        nse_symbols = get_all_equity_symbols(app.config["NSE_DOWNLOAD_FOLDER"])
        logger.info("Fetched %d NSE equity symbols", len(nse_symbols))

        new_nse_stocks = []
        for row in nse_symbols:
            sym = row["symbol"].strip().upper()
            if sym not in existing_symbols:
                new_nse_stocks.append(
                    Stock(symbol=sym, company_name=row["name"], exchange="NSE")
                )
                existing_symbols.add(sym)

        if new_nse_stocks:
            db.session.add_all(new_nse_stocks)
            db.session.commit()

    # Run multi-threaded parallel refresh across all NSE stocks
    run_refresh(app)
