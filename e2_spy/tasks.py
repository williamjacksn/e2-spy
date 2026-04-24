import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from e2_spy import config, paperless
from e2_spy.db import AppDatabase

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def paperless_parts_sync() -> None:
    log.info("Syncing data from Paperless Parts...")
    db = AppDatabase(str(config.APP_DB_PATH))
    c = paperless.get_client(db.paperless_parts_api_key)
    for q in paperless.get_quotes(c, use_cache=False):
        qd = db.paperless_parts_quote_details_get(q["quote"], q["revision"])
        if qd is None:
            qd = paperless.get_quote_details(c, q["quote"], q["revision"])
            db.paperless_parts_quote_details_insert(qd)
        else:
            qd = json.loads(qd["payload"])
        db.paperless_parts_quote_items_reset(q["quote"], q["revision"])
        for item in qd["quote_items"]:
            for component in item["components"]:
                db.paperless_parts_quote_items_insert(
                    {
                        "part_name": component["part_name"],
                        "part_number": component["part_number"],
                        "part_revision": component["revision"],
                        "quote_number": q["quote"],
                        "quote_sent_date": qd["sent_date"],
                        "revision": q["revision"],
                    }
                )
    log.info("Done syncing data from Paperless Parts")
