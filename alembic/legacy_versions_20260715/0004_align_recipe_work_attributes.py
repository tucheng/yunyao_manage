"""Align recipe and work attribute columns.

Revision ID: 0004_align_attributes
Revises: 0003_remove_wechat_identity
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "0004_align_attributes"
down_revision = "0003_remove_wechat_identity"
branch_labels = None
depends_on = None


def _columns(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    work_columns = _columns(conn, "works")
    if "category" not in work_columns:
        op.add_column("works", sa.Column("category", sa.String(30), nullable=True, server_default=""))
    if "atmosphere" not in work_columns:
        op.add_column("works", sa.Column("atmosphere", sa.String(20), nullable=True, server_default=""))

    for table in ("recipes", "works"):
        columns = _columns(conn, table)
        if "kiln_type_other" in columns and "kiln_type" in columns:
            conn.execute(text(
                f"UPDATE {table} SET kiln_type = kiln_type_other "
                "WHERE COALESCE(kiln_type_other, '') <> ''"
            ))

    for table, removed_columns in {
        "recipes": ("kiln_type_other", "contact", "turnaround", "color"),
        "works": ("kiln_type_other",),
    }.items():
        columns = _columns(conn, table)
        for column in removed_columns:
            if column in columns:
                op.drop_column(table, column)


def downgrade() -> None:
    conn = op.get_bind()

    recipe_columns = _columns(conn, "recipes")
    for column in (
        sa.Column("kiln_type_other", sa.String(50), nullable=True, server_default=""),
        sa.Column("contact", sa.String(200), nullable=True, server_default=""),
        sa.Column("turnaround", sa.String(50), nullable=True, server_default=""),
        sa.Column("color", sa.String(50), nullable=True, server_default=""),
    ):
        if column.name not in recipe_columns:
            op.add_column("recipes", column)

    work_columns = _columns(conn, "works")
    if "kiln_type_other" not in work_columns:
        op.add_column("works", sa.Column("kiln_type_other", sa.String(50), nullable=True, server_default=""))
    for column in ("atmosphere", "category"):
        if column in _columns(conn, "works"):
            op.drop_column("works", column)
