import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .scraper import run_refresh

logger = logging.getLogger(__name__)

_scheduler = None


def init_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)

    _scheduler.add_job(
        func=lambda: run_refresh(app),
        trigger=CronTrigger(
            hour=app.config["REFRESH_HOUR"], minute=app.config["REFRESH_MINUTE"]
        ),
        id="daily_shp_refresh",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started - daily refresh at %02d:%02d",
        app.config["REFRESH_HOUR"],
        app.config["REFRESH_MINUTE"],
    )
    return _scheduler
