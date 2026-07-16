"""Remove the unused WeChat identity column.

Revision ID: 0003_remove_wechat_identity
Revises: 0002_remove_legacy_features
"""

from alembic import op
from sqlalchemy import inspect


revision = "0003_remove_wechat_identity"
down_revision = "0002_remove_legacy_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "openid" not in columns:
        return
    for index in inspector.get_indexes("users"):
        if "openid" in (index.get("column_names") or []) and index.get("name"):
            op.drop_index(index["name"], table_name="users")
    op.drop_column("users", "openid")


def downgrade() -> None:
    # WeChat identities are intentionally retired and are not recreated.
    pass
