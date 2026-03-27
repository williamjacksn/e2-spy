import logging

from apscheduler.schedulers.background import BackgroundScheduler

from e2_spy import config, paperless
from e2_spy.db import AppDatabase

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def paperless_parts_sync() -> None:
    log.info("Syncing data from Paperless Parts...")
    db = AppDatabase(config.APP_DB_PATH)
    c = paperless.get_client(db.paperless_parts_api_key)
    for q in paperless.get_quotes(c):
        if db.paperless_parts_quote_details_get(q["quote"], q["revision"]) is None:
            qd = paperless.get_quote_details(c, q["quote"], q["revision"])
            db.paperless_parts_quote_details_insert(qd)
    log.info("Done syncing data from Paperless Parts")
