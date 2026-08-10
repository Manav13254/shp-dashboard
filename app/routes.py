import hmac
import threading
from datetime import datetime

from flask import Blueprint, jsonify, render_template, current_app, request

from .models import db, Stock, RefreshLog
from .scraper import run_refresh, bootstrap_all_stocks

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    return render_template("dashboard.html")


@bp.route("/api/stocks")
def api_stocks():
    """
    Returns only stocks where retail holding % has DECREASED
    (retail_change_pct < 0), sorted ascending - biggest retail exits first.
    Stocks with no change data yet, or a zero/positive change, are excluded.
    """
    stocks = Stock.query.all()

    negative_only = [
        s for s in stocks if s.retail_change_pct is not None and s.retail_change_pct < 0
    ]

    stocks_sorted = sorted(negative_only, key=lambda s: s.retail_change_pct)
    return jsonify([s.to_dict() for s in stocks_sorted])


@bp.route("/api/status")
def api_status():
    last_log = RefreshLog.query.order_by(RefreshLog.id.desc()).first()
    total_stocks = getattr(current_app, "_cached_total_stocks", None)
    if total_stocks is None or total_stocks == 0:
        total_stocks = Stock.query.count()
        current_app._cached_total_stocks = total_stocks
    return jsonify(
        {
            "total_stocks": total_stocks,
            "last_refresh": {
                "started_at": (last_log.started_at.isoformat() + "Z") if last_log and last_log.started_at else None,
                "finished_at": (last_log.finished_at.isoformat() + "Z") if last_log and last_log.finished_at else None,
                "checked": last_log.stocks_checked if last_log else 0,
                "updated": last_log.stocks_updated if last_log else 0,
                "failed": last_log.stocks_failed if last_log else 0,
                "status": last_log.status if last_log else "never_run",
            }
            if last_log
            else None,
        }
    )


@bp.route("/api/refresh", methods=["POST"])
def api_trigger_refresh():
    """Manually trigger an incremental refresh in the background (admin use)."""
    app = current_app._get_current_object()
    if not app.config.get("ENABLE_SCRAPER"):
        return jsonify({
            "status": "disabled",
            "message": "ENABLE_SCRAPER is off on this host. NSE blocks most cloud "
                       "IPs with 403 - run local_refresh.py from a non-blocked "
                       "machine instead."
        }), 403
    threading.Thread(target=run_refresh, args=(app,), daemon=True).start()
    return jsonify({"status": "started"})


@bp.route("/api/bootstrap", methods=["POST"])
def api_trigger_bootstrap():
    """
    Manually trigger the one-time bootstrap: fetch full NSE symbol list +
    populate latest-2-filings for every stock. Runs in background since it
    can take a long time for ~2000 stocks.
    """
    app = current_app._get_current_object()
    if not app.config.get("ENABLE_SCRAPER"):
        return jsonify({
            "status": "disabled",
            "message": "ENABLE_SCRAPER is off on this host. NSE blocks most cloud "
                       "IPs with 403 - run local_refresh.py from a non-blocked "
                       "machine instead."
        }), 403
    threading.Thread(target=bootstrap_all_stocks, args=(app,), daemon=True).start()
    return jsonify({"status": "bootstrap_started"})


@bp.route("/api/sync", methods=["POST"])
def api_sync():
    """
    Receives scraped stock data from local_refresh.py (run on a machine NSE
    doesn't block) and upserts it into THIS host's database. Requires a
    shared secret so randoms on the internet can't overwrite your data.

    Expected JSON body:
        {
          "secret": "...",
          "stocks": [ { "symbol": "...", "exchange": "NSE", ... }, ... ],
          "refresh_log": { "stocks_checked": n, "stocks_updated": n,
                            "stocks_failed": n, "started_at": "...",
                            "finished_at": "..." }   # optional
        }
    """
    app = current_app._get_current_object()
    configured_secret = app.config.get("SYNC_SECRET")
    if not configured_secret:
        return jsonify({
            "status": "disabled",
            "message": "SYNC_SECRET is not set on this host's environment variables. "
                       "Set it (any random string) to enable /api/sync."
        }), 403

    payload = request.get_json(silent=True) or {}
    provided_secret = payload.get("secret") or request.headers.get("X-Sync-Secret", "")
    if not hmac.compare_digest(str(provided_secret), str(configured_secret)):
        return jsonify({"status": "unauthorized"}), 401

    stocks_payload = payload.get("stocks", [])
    if not isinstance(stocks_payload, list):
        return jsonify({"status": "error", "message": "'stocks' must be a list"}), 400

    upserted = 0
    for row in stocks_payload:
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        exchange = (row.get("exchange") or "NSE").strip().upper()

        stock = Stock.query.filter_by(symbol=symbol, exchange=exchange).first()
        if stock is None:
            stock = Stock(symbol=symbol, exchange=exchange)
            db.session.add(stock)

        for field in (
            "company_name", "scrip_code", "last_submission_date",
            "prev_submission_date", "promoter_pct", "fii_pct", "dii_pct",
            "retail_latest_pct", "retail_prev_pct", "last_error",
        ):
            if field in row:
                setattr(stock, field, row[field])

        if row.get("last_checked_at"):
            try:
                stock.last_checked_at = datetime.fromisoformat(row["last_checked_at"])
            except (TypeError, ValueError):
                pass
        else:
            stock.last_checked_at = datetime.utcnow()

        upserted += 1

    log_payload = payload.get("refresh_log")
    if isinstance(log_payload, dict):
        log = RefreshLog(
            status="done",
            stocks_checked=log_payload.get("stocks_checked", upserted),
            stocks_updated=log_payload.get("stocks_updated", upserted),
            stocks_failed=log_payload.get("stocks_failed", 0),
            finished_at=datetime.utcnow(),
        )
        db.session.add(log)

    db.session.commit()
    return jsonify({"status": "synced", "upserted": upserted})
