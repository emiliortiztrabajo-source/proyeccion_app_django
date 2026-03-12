from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import os
import logging

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)


def _run_download_and_ingest():
    try:
        repo = os.path.dirname(os.path.dirname(__file__))
        # download to dated file and then ingest
        dated_path = os.path.join(repo, "data", f"cafci_planilla_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.xlsx")
        logger.info("Scheduler: downloading planilla to %s", dated_path)
        call_command("download_cafci_planilla", path=dated_path)
        # copy to current path
        current = os.getenv("CAFCI_LOCAL_PLANILLA_PATH") or os.path.join(repo, "data", "cafci_planilla.xlsx")
        try:
            from shutil import copyfile

            copyfile(dated_path, current)
        except Exception as e:
            logger.exception("Scheduler: error copying to current file: %s", e)
        # ingest into DB
        logger.info("Scheduler: ingesting planilla %s", dated_path)
        call_command("ingest_cafci_planilla", path=dated_path)
    except Exception:
        logger.exception("Scheduler job failed")


def start_scheduler():
    # Only start scheduler when explicitly enabled via env var
    enabled = os.getenv("CAFCI_SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes")
    if not enabled:
        logger.info("CAFCI scheduler disabled (set CAFCI_SCHEDULER_ENABLED=1 to enable)")
        return None

    scheduler = BackgroundScheduler()
    # Daily at 03:30 server time (adjust as needed)
    trigger = CronTrigger(hour=3, minute=30)
    scheduler.add_job(_run_download_and_ingest, trigger, id="cafci_daily_download", replace_existing=True)
    scheduler.start()
    logger.info("CAFCI scheduler started: daily job scheduled at 03:30")
    return scheduler
