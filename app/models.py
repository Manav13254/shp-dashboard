from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Stock(db.Model):
    __tablename__ = "stocks"
    __table_args__ = (db.UniqueConstraint("symbol", "exchange", name="_symbol_exchange_uc"),)

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(32), nullable=False, index=True)
    company_name = db.Column(db.String(255))
    exchange = db.Column(db.String(4), default="NSE")  # "NSE" or "BSE"
    scrip_code = db.Column(db.String(16))  # BSE scrip code, if exchange == "BSE"

    # Cached, so we don't parse XBRL twice for the same filing
    last_submission_date = db.Column(db.String(20))  # e.g. "16-JUL-2026"
    prev_submission_date = db.Column(db.String(20))

    # Latest quarter values (as fractions, e.g. 0.0716 == 7.16%)
    promoter_pct = db.Column(db.Float)
    fii_pct = db.Column(db.Float)
    dii_pct = db.Column(db.Float)
    retail_latest_pct = db.Column(db.Float)
    retail_prev_pct = db.Column(db.Float)

    last_checked_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500))

    @property
    def retail_change_pct(self):
        if self.retail_latest_pct is None or self.retail_prev_pct is None:
            return None
        return self.retail_latest_pct - self.retail_prev_pct

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "exchange": self.exchange,
            "retail_latest_pct": round(self.retail_latest_pct * 100, 2)
            if self.retail_latest_pct is not None
            else None,
            "retail_prev_pct": round(self.retail_prev_pct * 100, 2)
            if self.retail_prev_pct is not None
            else None,
            "retail_change_pct": round(self.retail_change_pct * 100, 2)
            if self.retail_change_pct is not None
            else None,
            "promoter_pct": round(self.promoter_pct * 100, 2)
            if self.promoter_pct is not None
            else None,
            "fii_pct": round(self.fii_pct * 100, 2) if self.fii_pct is not None else None,
            "dii_pct": round(self.dii_pct * 100, 2) if self.dii_pct is not None else None,
            "last_submission_date": self.last_submission_date,
            "last_checked_at": self.last_checked_at.isoformat()
            if self.last_checked_at
            else None,
        }


class RefreshLog(db.Model):
    """One row per refresh run, for visibility into scraper health."""

    __tablename__ = "refresh_logs"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
    stocks_checked = db.Column(db.Integer, default=0)
    stocks_updated = db.Column(db.Integer, default=0)
    stocks_failed = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="running")  # running | done | failed
