"""Run quota maintenance once from an external scheduler."""

import logging

from sqlalchemy import text

from database import SessionLocal
from services.user_quota import run_daily_maintenance

LOCK_NAME = "yunyao:daily-maintenance"


def main() -> int:
    db = SessionLocal()
    locked = False
    try:
        if db.bind.dialect.name == "mysql":
            locked = bool(db.execute(
                text("SELECT GET_LOCK(:name, 0)"),
                {"name": LOCK_NAME},
            ).scalar())
            if not locked:
                logging.info("maintenance skipped: lock is held by another instance")
                return 0
        downgraded, refreshed = run_daily_maintenance(db)
        logging.info("maintenance complete: downgraded=%s refreshed=%s", downgraded, refreshed)
        return 0
    finally:
        if locked:
            db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
