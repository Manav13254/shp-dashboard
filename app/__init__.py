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

    db.init_app(app)

    # Enable SQLite WAL mode & 10s busy timeout for concurrent read/write support
    with app.app_context():
        engine = db.engine
        if engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                conn.exec_driver_sql("PRAGMA busy_timeout=10000;")
        db.create_all()

        # Clean up any orphaned 'running' logs from previous server restarts
        from .models import RefreshLog
        from datetime import datetime
        try:
            running_logs = RefreshLog.query.filter_by(status="running").all()
            for l in running_logs:
                l.status = "done"
                l.finished_at = l.finished_at or datetime.utcnow()
            if running_logs:
                db.session.commit()
        except Exception:
            pass

    from .routes import bp

    app.register_blueprint(bp)

    return app
