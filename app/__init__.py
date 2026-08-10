import logging
import os

from flask import Flask

from config import Config
from .models import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.config["NSE_DOWNLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["BSE_DOWNLOAD_FOLDER"], exist_ok=True)

    logging.basicConfig(level=logging.INFO)

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if type(dbapi_connection).__module__ == "sqlite3":
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
            try:
                cursor.execute("PRAGMA busy_timeout=10000;")
            except Exception:
                pass
            cursor.close()

    db.init_app(app)

    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        # Clean up any orphaned 'running' logs from previous server restarts
        from .models import RefreshLog, Stock
        from .scraper import bootstrap_all_stocks
        from datetime import datetime
        import threading

        try:
            running_logs = RefreshLog.query.filter_by(status="running").all()
            for l in running_logs:
                l.status = "done"
                l.finished_at = l.finished_at or datetime.utcnow()
            if running_logs:
                db.session.commit()
        except Exception:
            pass

        # If DB has 0 stocks (fresh container deploy), trigger background bootstrap.
        # Only do this when ENABLE_SCRAPER=true — on the deployed host this is
        # normally OFF because NSE 403-blocks most cloud IPs. Symbols alone are
        # cheap (bundled CSV fallback), but the shareholding refresh that follows
        # bootstrap is the expensive part we want to run from local_refresh.py
        # instead. If you want the deployed host to also attempt scraping,
        # set ENABLE_SCRAPER=true in its environment.
        try:
            if app.config.get("ENABLE_SCRAPER") and Stock.query.count() == 0:
                logging.info("Fresh database detected (0 stocks). Triggering background bootstrap...")
                threading.Thread(target=bootstrap_all_stocks, args=(app,), daemon=True).start()
            elif Stock.query.count() == 0:
                logging.info(
                    "Fresh database detected (0 stocks), but ENABLE_SCRAPER is off on this host. "
                    "Run local_refresh.py from a machine NSE doesn't block to populate data."
                )
        except Exception:
            pass

    from .routes import bp

    app.register_blueprint(bp)

    return app
