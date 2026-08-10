import threading

from flask import Blueprint, jsonify, render_template, current_app

from .models import Stock, RefreshLog
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
