"""Remove the retired payment and legacy material schemas.

This migration is intentionally opt-in. Run without arguments to print the
plan, then run with ``--apply`` after taking a database backup.
"""

import argparse
import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine


REMOVED_TABLES = (
    "wallet_transactions",
    "wallet_recharge_orders",
    "payments",
    "purchased_recipes",
    "purchases",
    "glazy_materials",
    "ceramic_materials",
)

REMOVED_COLUMNS = {
    "users": ("balance",),
    "recipes": ("price", "reward", "sold_count"),
    "reviews": ("purchase_id",),
    "user_levels": ("max_paid_recipes",),
    "user_usage_quotas": ("paid_recipe_remaining",),
}


def _drop_foreign_keys(conn, inspector, quote) -> None:
    removed_tables = set(REMOVED_TABLES)
    for table in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table):
            name = foreign_key.get("name")
            referred_table = foreign_key.get("referred_table")
            columns = set(foreign_key.get("constrained_columns") or [])
            removed_columns = set(REMOVED_COLUMNS.get(table, ()))
            if not name:
                continue
            if referred_table in removed_tables or columns.intersection(removed_columns):
                conn.execute(text(
                    f"ALTER TABLE {quote(table)} DROP FOREIGN KEY {quote(name)}"
                ))


def apply_migration() -> None:
    if engine.dialect.name not in ("mysql", "mariadb"):
        raise RuntimeError("This cleanup migration currently supports MySQL/MariaDB only")

    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())

        if "recipes" in tables:
            conn.execute(text(
                "UPDATE recipes SET visibility='private' WHERE visibility='paid'"
            ))
        if "materials" in tables:
            conn.execute(text(
                "UPDATE materials SET source='overseas' WHERE source='glazy'"
            ))
        if "app_settings" in tables:
            conn.execute(text(
                "DELETE FROM app_settings WHERE `key`='paid_enabled'"
            ))

        _drop_foreign_keys(conn, inspector, quote)

        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        for table, columns in REMOVED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for column in columns:
                if column in existing:
                    conn.execute(text(
                        f"ALTER TABLE {quote(table)} DROP COLUMN {quote(column)}"
                    ))

        for table in REMOVED_TABLES:
            if table in tables:
                conn.execute(text(f"DROP TABLE {quote(table)}"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the destructive migration after a verified database backup",
    )
    args = parser.parse_args()

    print("Tables to remove:", ", ".join(REMOVED_TABLES))
    for table, columns in REMOVED_COLUMNS.items():
        print(f"Columns to remove from {table}: {', '.join(columns)}")
    print("Legacy paid recipe visibility will be changed to private.")

    if not args.apply:
        print("Dry run only. Re-run with --apply after backing up the database.")
        return

    apply_migration()
    print("Legacy feature cleanup completed.")


if __name__ == "__main__":
    main()
