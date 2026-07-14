"""Remove payment fields and superseded material tables.

Revision ID: 0002_remove_legacy_features
Revises: 0001_initial_schema
"""

from alembic import op
from sqlalchemy import inspect, text


revision = "0002_remove_legacy_features"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

REMOVED_TABLES = (
    "wallet_transactions", "wallet_recharge_orders", "payments",
    "purchased_recipes", "purchases", "glazy_materials", "ceramic_materials",
)
REMOVED_COLUMNS = {
    "users": ("balance",),
    "recipes": ("price", "reward", "sold_count"),
    "reviews": ("purchase_id",),
    "user_levels": ("max_paid_recipes",),
    "user_usage_quotas": ("paid_recipe_remaining",),
}


def upgrade() -> None:
    conn = op.get_bind()
    quote = conn.dialect.identifier_preparer.quote
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    if "recipes" in tables:
        conn.execute(text("UPDATE recipes SET visibility='private' WHERE visibility='paid'"))
    if "materials" in tables:
        conn.execute(text("UPDATE materials SET source='overseas' WHERE source='glazy'"))
    if "app_settings" in tables:
        conn.execute(text("DELETE FROM app_settings WHERE `key`='paid_enabled'"))

    for table in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table):
            name = foreign_key.get("name")
            referred_table = foreign_key.get("referred_table")
            columns = set(foreign_key.get("constrained_columns") or [])
            if name and (referred_table in REMOVED_TABLES or columns.intersection(REMOVED_COLUMNS.get(table, ()))):
                conn.execute(text(f"ALTER TABLE {quote(table)} DROP FOREIGN KEY {quote(name)}"))

    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    for table, columns in REMOVED_COLUMNS.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column in existing:
                conn.execute(text(f"ALTER TABLE {quote(table)} DROP COLUMN {quote(column)}"))

    for table in REMOVED_TABLES:
        if table in tables:
            conn.execute(text(f"DROP TABLE {quote(table)}"))


def downgrade() -> None:
    # Removed payment data cannot be recreated safely.
    pass
