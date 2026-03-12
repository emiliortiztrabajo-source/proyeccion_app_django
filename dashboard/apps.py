from django.apps import AppConfig
import logging


logger = logging.getLogger(__name__)


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'

    def ready(self):
        # Start internal scheduler to download CAFCI planilla daily if enabled
        try:
            from .scheduler import start_scheduler

            scheduler = start_scheduler()
            if scheduler:
                logger.info("Dashboard: scheduler started")
        except Exception:
            logger.exception("Error starting CAFCI scheduler")
